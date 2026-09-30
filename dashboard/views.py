from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import render
from django.utils import timezone

from django.http import HttpResponse
from openpyxl import Workbook

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser , IsAuthenticated ,AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from books.models import *
from books.serializers import *
from accounts.models import UserProfile

from .serializers import *
from django.core.mail import send_mail
from django.conf import settings

from books.serializers import * 
from rest_framework.pagination import PageNumberPagination
from django.core.mail import EmailMultiAlternatives

User = get_user_model() 

class DashboardBookPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 10

class BookAdminView( viewsets.ModelViewSet ) : 
    queryset = Book.objects.all() 
    serializer_class = BookSerializers 
    permission_classes = [IsAdminUser] # just admin 
    pagination_class = DashboardBookPagination

    
    def get_queryset ( self ) :
        queryset = Book.objects.all().order_by("is_archived","-count_borrowed")
        author = self.request.query_params.get('author') 
        category = self.request.query_params.get('category') 

        if author : 
            queryset = queryset.filter( author__name__icontains = author ) 
        if category : 
            queryset = queryset.filter( category__name__icontains = category ) 
        
        return queryset

    @action(detail=False, methods=["get"], permission_classes=[IsAdminUser], url_path="export")
    def export(self, request):
        queryset = self.filter_queryset(self.get_queryset())

        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Books"

        worksheet.append([
            "ID",
            "Title",
            "Author",
            "Category",
            "Total Copies",
            "Available Copies",
            "Borrow Count",
            "Available",
            "Archived",
            "Pages",
            "Publication Year",
            "ISBN",
            "Position",
            "Created At",
        ])

        for book in queryset.select_related("author", "category"):
            worksheet.append([
                book.id,
                book.title,
                book.author.name if book.author else "",
                book.category.name if book.category else "",
                book.total_copies,
                book.available_copies,
                book.count_borrowed,
                "Yes" if book.is_avaiable else "No",
                "Yes" if book.is_archived else "No",
                book.pages,
                book.publication_year or "",
                book.isbn or "",
                book.possition or "",
                book.created_at.strftime("%Y-%m-%d %H:%M") if book.created_at else "",
            ])

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = 'attachment; filename="dashboard_books.xlsx"'
        workbook.save(response)
        return response

    # archif 
    def destroy( self , request , *args , **kwargs ) : 
        book = self.get_object() 
        book.is_archived = True 
        book.is_avaiable = False 
        book.save() 
        return Response( { "Message" : "تمت الأرشفة بنجاح" } , status = status.HTTP_200_OK )
    
    @action( detail = True , methods = ['post'] , permission_classes = [IsAdminUser] ) 
    def restore( self , request , pk = None ) : 
        book = self.get_object() 

        if not book.is_archived :
            return Response({ "ERROR" : "الكتاب ليس مؤرشف "} , status = status.HTTP_400_BAD_REQUEST )
        
        book.is_archived = False 
        book.save() 
        return Response({"MESSAGE" : "تمت الغاء الارشفة بنجاح"} , status = status.HTTP_200_OK ) 
    
    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def summaries(self, request, pk=None):
     book = self.get_object()
     queryset = BookSummary.objects.filter(book=book).order_by("-created_at")
     serializer = BookSummarySerializer(queryset, many=True)
     return Response(serializer.data, status=status.HTTP_200_OK)
    
    @action(
    detail=True,
    methods=["delete"],
    permission_classes=[IsAdminUser],
    url_path=r"summaries/(?P<summary_id>[^/.]+)",
    )
    def delete_summary(self, request, pk=None, summary_id=None):
     book = self.get_object()
     summary = BookSummary.objects.filter(id=summary_id, book=book).first()

     if not summary:
        return Response({"error": "لا يوجد تلخيص لهذا الكتاب "}, status=status.HTTP_404_NOT_FOUND)

     summary.delete()
     return Response({"message": "تم حذف التلخيص بنجاح"}, status=status.HTTP_200_OK)
"""
###BookAdminView

### GET /dashboard/books/

**Description**  
Returns a list of all books (both archived and active) for administrative purposes. Results are ordered by archive status and popularity.

**Permissions**  
- `IsAdminUser` – only admin users can access this endpoint.

**Ordering**  
- First by `is_archived` (non-archived books first).
- Then by `-count_borrowed` (most borrowed books first).

**Query Parameters**
- `author` *(optional, string)*  
  Filters books by author name (case-insensitive, partial match).  
  Example: `?author=Naguib`
- `category` *(optional, string)*  
  Filters books by category name (case-insensitive, partial match).  
  Example: `?category=Novel`

**Response (200 OK)**  
Returns a list of `BookSerializers` objects.

"""

class UserAdminView( viewsets.ReadOnlyModelViewSet ) :
     serializer_class = UserAdminSeri 
     permission_classes = [IsAdminUser] 
     queryset = User.objects.all()
     
     def get_queryset(self) :
         queryset = User.objects.annotate(
             borrowed_books_count = Count('borrower_book' , filter = Q( borrower_book__is_returned = False ))
         )

         name = self.request.query_params.get("name")
         if name :
             queryset = queryset.filter(
                 Q(username__icontains=name)
                 | Q(first_name__icontains=name)
                 | Q(last_name__icontains=name)
             )

         return queryset

     def _set_borrowing_block(self, user, blocked):
         profile, _ = UserProfile.objects.get_or_create(user=user)
         profile.borrowing_blocked = blocked
         profile.save(update_fields=["borrowing_blocked"])
         return profile

     @action(
         detail=True,
         methods=["post"],
         permission_classes=[IsAdminUser],
         url_path=r"block[_-]borrowing",
     )
     def block_borrowing(self, request, pk=None):
         user = self.get_object()
         self._set_borrowing_block(user, True)
         return Response(
             {
                "message": "تم حجب المستخدم عن الاستعارة بنجاح",
                "user_id": user.id,
                "borrowing_blocked": True,
                "available_books": -1,
             },
             status=status.HTTP_200_OK,
         )

     @action(
         detail=True,
         methods=["post"],
         permission_classes=[IsAdminUser],
         url_path=r"unblock[_-]borrowing",
     )
     def unblock_borrowing(self, request, pk=None):
         from books.views import get_user_tier

         user = self.get_object()
         self._set_borrowing_block(user, False)
         tier, max_allowed = get_user_tier(user)
         active_count = BorrowedBook.objects.filter(borrower=user, is_returned=False).count()
         return Response(
             {
                 "message": "تم فك حجب الاستعارة عن المستخدم بنجاح",
                 "user_id": user.id,
                 "borrowing_blocked": False,
                "tier": tier,
                "max_allowed": max_allowed,
                "active_borrows": active_count,
                "available_books": 1,
            },
             status=status.HTTP_200_OK,
         )
     
"""
### UserAdminView
### GET /admin/users/

**Description**  
Returns a read-only list of all users in the system, annotated with the number of books each 
user is currently borrowing (i.e., not yet returned).

**Permissions**  
- `IsAdminUser` – only admin users are allowed to access this endpoint.

**Behavior**  
Each user object is annotated with:
- `borrowed_books_count`: the number of `BorrowedBook` records linked to this user where `is_returned = False`.

This is implemented using:
- `annotate(borrowed_books_count=Count('borrower_book', filter=Q(borrower_book__is_returned=False)))`

**Response (200 OK)**  
Returns a list of `UserAdminSeri` objects. A typical response item may look like:
"""

class BorrowedBookAdminViewSet( viewsets.ModelViewSet ) :
    serializer_class = BarrowBookSerilaizers
    permission_classes = [IsAdminUser] 
    queryset = BorrowedBook.objects.all() 

    def get_queryset( self ) :
        queryset = BorrowedBook.objects.filter( is_returned = False )
        username = self.request.query_params.get("username")
        book_name = self.request.query_params.get("book_name")

        if username:
         queryset = queryset.filter(
            Q(borrower__username__icontains=username)
            | Q(borrower__first_name__icontains=username)
            | Q(borrower__last_name__icontains=username)
        )

        if book_name:
         queryset = queryset.filter(book__title__icontains=book_name)

        return queryset
    
    @action( detail = True , methods = ['post'] , permission_classes = [IsAdminUser] ) 
    def approve_return( self , request , pk = None ) : 
        borrow = self.get_object() 
        if not borrow.return_request : 
            return Response({"Erroe" : "المستخدم لم يقدم طلب استرجاع"} , status = status.HTTP_400_BAD_REQUEST )
        borrow.book.return_copy() 
        borrow.is_returned = True 
        borrow.return_date = borrow.return_request_date 
        borrow.save() 
        return Response({"MESSAGE" : "تمت استعادة الكتاب بنجاح"} , status = status.HTTP_200_OK )
    
    @action( detail = True , methods = ['post'] , permission_classes = [IsAdminUser] ) 
    def return_book( self , request , pk = None ) : 
        with transaction.atomic():
            borrow = BorrowedBook.objects.select_for_update().filter( id = pk ).first()

            if not borrow :
                return Response({"ERROR" : "سجل الاستعارة غير موجود"} , status = status.HTTP_404_NOT_FOUND )

            if borrow.is_returned :
                return Response({"MESSAGE" : "تمت استعادة هذا الكتاب سابقا"} , status = status.HTTP_400_BAD_REQUEST )

            borrow.book.return_copy()
            borrow.is_returned = True
            borrow.return_date = timezone.localdate()
            borrow.save(update_fields = ['is_returned','return_date'])

        return Response({"MESSAGE" : "تمت استعادة الكتاب بنجاح"} , status = status.HTTP_200_OK )
    
    @action( detail = True , methods = ['post'] , permission_classes = [IsAdminUser] ) 
    def approve_extension( self , request , pk = None ) : 
        with transaction.atomic():
            borrow = BorrowedBook.objects.select_for_update().filter( id = pk , is_returned = False ).first()

            if not borrow :
                return Response({"ERROR" : "سجل الاستعارة غير موجود"} , status = status.HTTP_404_NOT_FOUND )

            if not borrow.extension_request :
                return Response({"ERROR" : "المستخدم لم يقدم طلب تمديد"} , status = status.HTTP_400_BAD_REQUEST )

            if borrow.is_extended :
                return Response({"ERROR" : "تم تمديد مدة هذه الاستعارة سابقا"} , status = status.HTTP_400_BAD_REQUEST )

            borrow.due_date = (borrow.due_date or timezone.localdate()) + timedelta(days = 10)
            borrow.extension_request = False
            borrow.is_extended = True
            borrow.save(update_fields = ['due_date','extension_request','is_extended'])

        return Response({"MESSAGE" : "تم تمديد مدة الاستعارة بنجاح"} , status = status.HTTP_200_OK )
    
    @action( detail = True , methods = ['post'] , permission_classes = [IsAdminUser] ) 
    def reject_extension( self , request , pk = None ) : 
        borrow = self.get_object()

        if not borrow.extension_request :
            return Response({"ERROR" : "المستخدم لم يقدم طلب تمديد"} , status = status.HTTP_400_BAD_REQUEST )

        borrow.extension_request = False
        borrow.extension_request_date = None
        borrow.save(update_fields = ['extension_request','extension_request_date'])

        return Response({"MESSAGE" : "تم رفض طلب تمديد الإعارة"} , status = status.HTTP_200_OK )
"""
### BorrowedBookAdminViewSet
### GET /dashboard/borrowed-books/

**Description**  
Returns a list of all *active* borrowed-book records (i.e., borrowings that have not yet been marked as returned).

**Permissions**  
- `IsAdminUser` – only admin users can access this endpoint.

**Behavior**  
The queryset is restricted to:
- `BorrowedBook.objects.filter(is_returned=False)`

So only currently borrowed (open) records are included.

**Response (200 OK)**  
Returns a list of `BarrowBookSerilaizers` objects.

"""


class BookReservationAdminViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = BookReservationSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = BookReservation.objects.select_related("user", "book").order_by("reserved_at")
        username = self.request.query_params.get("username")
        book_name = self.request.query_params.get("book_name")

        if username:
            queryset = queryset.filter(
                Q(user__username__icontains=username)
                | Q(user__first_name__icontains=username)
                | Q(user__last_name__icontains=username)
            )

        if book_name:
            queryset = queryset.filter(book__title__icontains=book_name)

        return queryset


class DashboardStatsView ( APIView ) :
    permission_classes = [IsAdminUser] 

    def get( self , request ) : 
        total_users = User.objects.count() 
        total_books = Book.objects.count() 
        today = timezone.localdate()
        start = today - timedelta(days = 6 )  
        borrowed_books = BorrowedBook.objects.filter( is_returned = False ).count()
        pending_returns = BorrowedBook.objects.filter( is_returned = False , return_request = True ).count()
        archived_books = Book.objects.filter( is_archived = True ).count() 
        available_books = Book.objects.filter( is_avaiable = True ).count() 
        category_stats = (
           Category.objects.annotate(
               books_count = Count('category')
           )
           .values('id','name','books_count')
        )
        history = (
            BorrowedBook.objects.filter( borrow_date__range = ( start , today ) ) 
            .values("borrow_date") 
            .annotate( count = Count("id")) 
        )

        counts_map = {row["borrow_date"]: row["count"] for row in history }
        borrowed_last_7_days = [
            {
              "date": (start + timedelta(days=i)).strftime("%Y %m %d"),  
              "count": counts_map.get(start + timedelta(days=i), 0),
            }
            for i in range(7)
        ]

        data = {
             "total_users" : total_users , 
             "total_books" : total_books , 
             "borrowed_books" : borrowed_books , 
             "available_books" : available_books , 
             "pending_returns" : pending_returns , 
             "archived_books" : archived_books ,
             'category_stats' : category_stats ,
             'borrowed_last_7_days' : borrowed_last_7_days ,
            
        }
        return Response( data , status = status.HTTP_200_OK ) 


"""
### DashboardStatsView
### GET /dashboard/stats/

**Description**  
Provides a summary of key statistics for the admin dashboard, including counts of users, books, borrowing activity, category breakdown, and borrow history for the last 7 days.

**Permissions**  
- `IsAdminUser` – only admin users can access this endpoint.

**Response (200 OK)**  

"""

class CategoryAdminView( viewsets.ModelViewSet ) : 
    queryset = Category.objects.all() 
    serializer_class = CategorySerializers 
    permission_classes = [IsAdminUser] 
    
    def get_queryset ( self ) :
        queryset = Category.objects.all()
        category = self.request.query_params.get("category")
        if category:
         queryset = queryset.filter(
            Q(name__icontains=category)
        )
        return queryset 

"""

### CategoryAdminView
### PUT /dashboard/categories/{id}/
### PATCH /dashboard/categories/{id}/

**Description**  
Updates an existing category (full update with PUT, partial update with PATCH).

**Permissions**  
- `IsAdminUser`

---

### DELETE /dashboard/categories/{id}/

**Description**  
Deletes a category.

**Permissions**  
- `IsAdminUser`

**Response (204 No Content)**  
Category successfully deleted.

"""

class AuthorAdminView( viewsets.ModelViewSet ) : 
    queryset = Author.objects.all() 
    serializer_class = AuthorSerializers 
    permission_classes = [ IsAdminUser ] 
    def get_queryset ( self ) :
        queryset = Author.objects.all()
        author = self.request.query_params.get("author")
        if author:
         queryset = queryset.filter(
            Q(name__icontains=author)
        )
        return queryset 


"""
### AuthorAdminView

Admin CRUD API for managing authors.

"""

class LibraryActivityAdminViewSet(viewsets.ModelViewSet) : 
    serializer_class = LibraryActivitySerializer
    permission_classes = [IsAdminUser]
    queryset = LibraryActivity.objects.all().order_by("-created_at")
    
    @action(detail=True,methods=["post"],permission_classes=[IsAdminUser]) 
    def deactivate(self, request, pk=None) :
        activity = self.get_object() 
        activity.is_active = False
        activity.save(update_fields=["is_active", "updated_at"])
        return Response({"message": "تم إيقاف التسجيل على النشاط"}, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def activate(self, request, pk=None):
        activity = self.get_object()
        activity.is_active = True
        activity.save(update_fields=["is_active", "updated_at"])
        return Response({"message": "تم تفعيل التسجيل على النشاط"}, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def hide(self, request, pk=None):
        activity = self.get_object()
        activity.is_visible = False
        activity.save(update_fields=["is_visible", "updated_at"])
        return Response({"message": "تم إخفاء النشاط عن واجهة المستخدم"}, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def show(self, request, pk=None):
        activity = self.get_object()
        activity.is_visible = True
        activity.save(update_fields=["is_visible", "updated_at"])
        return Response({"message": "تم إظهار النشاط للمستخدم"}, status=status.HTTP_200_OK)
    
    
    @action(detail=True, methods=["get"], permission_classes=[IsAdminUser])
    def participants(self, request, pk=None):
     activity = self.get_object()
     users = User.objects.filter(activity_registrations__activity=activity).distinct()
     serializer = ActivityParticipantSerializer(users, many=True)
     return Response(serializer.data, status=status.HTTP_200_OK)


class QuoteAdminViewSet(viewsets.ModelViewSet):
    serializer_class = QuoteAdminSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = Quote.objects.select_related("user", "approved_by").prefetch_related("likes__user").annotate(
            likes_count=Count("likes", distinct=True)
        ).order_by("-created_at")

        status_value = self.request.query_params.get("status")
        name = self.request.query_params.get("name")

        if status_value:
            queryset = queryset.filter(status=status_value)
        if name :
            queryset = queryset.filter(
                Q(content__icontains=name)
                | Q(user__username__icontains=name)
                | Q(user__first_name__icontains=name)
                | Q(user__last_name__icontains=name)
            )

        return queryset

    def _send_quote_status_email(self, quote, is_approved):
        if not quote.user.email:
            return

        if is_approved:
            subject = "تهانينا! تم قبول خاطرتك"
            message = (
                f"مرحباً {quote.writer_full_name}،\n\n"
                "تهانينا! تمت الموافقة على خاطرتك ونشرها بنجاح.\n"
                "نتمنى لك المزيد من الإبداع.\n\n"
                "فريق المكتبة"
            )
        else:
            subject = "نعتذر، تم رفض خاطرتك"
            message = (
                f"مرحباً {quote.writer_full_name}،\n\n"
                "نعتذر، تم رفض خاطرتك بعد المراجعة.\n"
                "يمكنك تعديلها وإرسال خاطرة جديدة في أي وقت.\n\n"
                "فريق المكتبة"
            )

        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[quote.user.email],
            fail_silently=True,
        )
    
    def destroy(self, request, *args, **kwargs):
        quote = self.get_object()
        self.perform_destroy(quote)
        return Response({"message": "تم حذف هذه الخاطرة بنجاح."}, status=status.HTTP_200_OK)
    
    def _validate_quote_is_pending(self, quote):
        if quote.status != Quote.Status.PENDING:
            return Response(
                {
                    "message": "لا يمكن تعديل حالة الخاطرة بعد حسمها (مقبولة أو مرفوضة).",
                    "current_status": quote.status,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return None

    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def approve(self, request, pk=None):
        quote = self.get_object()
        validation_response = self._validate_quote_is_pending(quote)
        if validation_response:
            return validation_response

        quote.status = Quote.Status.APPROVED
        quote.approved_at = timezone.now()
        quote.approved_by = request.user
        quote.save(update_fields=["status", "approved_at", "approved_by", "updated_at"])
        self._send_quote_status_email(quote, is_approved=True)
        return Response({"message": "تمت الموافقة على الخاطرة بنجاح."}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def reject(self, request, pk=None):
        quote = self.get_object()
        validation_response = self._validate_quote_is_pending(quote)
        if validation_response:
            return validation_response

        quote.status = Quote.Status.REJECTED
        quote.approved_at = None
        quote.approved_by = None
        quote.save(update_fields=["status", "approved_at", "approved_by", "updated_at"])
        self._send_quote_status_email(quote, is_approved=False)
        return Response({"message": "تم رفض الخاطرة."}, status=status.HTTP_200_OK)
    
