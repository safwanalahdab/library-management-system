from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from django.http import HttpResponse
from openpyxl import Workbook

from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)

from Bookshelf.api_responses import ArabicApiResponseMixin
from Bookshelf.openapi import (
    BorrowingBlockedDataSchemaSerializer,
    BorrowingUnblockedDataSchemaSerializer,
    error_response,
    success_envelope,
)
from books.models import Book, BorrowedBook, Category, Author
from books.serializers import (
    AuthorSerializers,
    BarrowBookSerilaizers,
    BookSerializers,
    CategorySerializers,
)
from accounts.permissions import (
    CanAccessUser,
    CanResetUserPassword,
    IsGovernorateAdmin,
    IsLibrarian,
)
from accounts.scopes import (
    can_manage_user_status,
    has_active_user_scope,
    readers_searchable_by,
    users_accessible_to,
)
from accounts.serializers import AdminPasswordResetSerializer

from .serializers import (
    ReaderSearchResultSerializer,
    UserAdminCreateSerializer,
    UserAdminSeri,
)
from rest_framework.pagination import PageNumberPagination

User = get_user_model() 

class ReaderSearchPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50


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

@extend_schema_view(
     list=extend_schema(
         tags=["User Management"],
         operation_id="users_list",
         summary="قائمة المستخدمين ضمن نطاق مقدم الطلب",
         description=(
             "متاح لـGOVERNORATE_ADMIN فأعلى. SUPERUSER لجميع المستخدمين، MINISTRY_ADMIN لمستخدمي النظام، "
             "GOVERNORATE_ADMIN ضمن محافظته (القراء حسب محافظتهم المباشرة والأمناء حسب محافظة مكتبتهم). "
             "LIBRARIAN وREADER ممنوعان؛ يستخدم LIBRARIAN مسار reader-search."
         ),
         parameters=[
             OpenApiParameter(
                 name="name",
                 type=str,
                 required=False,
                 description="بحث جزئي في username أو الاسم الأول أو الأخير.",
             )
         ],
         responses={
             200: success_envelope(
                 "UserListSuccessEnvelope", UserAdminSeri(many=True), ["USERS_RETRIEVED"]
             ),
             401: error_response("AUTHENTICATION_REQUIRED أو INVALID_TOKEN."),
             403: error_response("PERMISSION_DENIED."),
             429: error_response("THROTTLED."),
         },
     ),
     retrieve=extend_schema(
         tags=["User Management"],
         operation_id="users_retrieve",
         summary="جلب مستخدم ضمن النطاق",
         description=(
             "متاح لـGOVERNORATE_ADMIN فأعلى. الهدف خارج scoped queryset يعاد كـNOT_FOUND دون كشف وجوده."
         ),
         responses={
             200: success_envelope(
                 "UserRetrieveSuccessEnvelope", UserAdminSeri(), ["USER_RETRIEVED"]
             ),
             401: error_response("AUTHENTICATION_REQUIRED أو INVALID_TOKEN."),
             403: error_response("PERMISSION_DENIED."),
             404: error_response("NOT_FOUND، ويشمل الهدف خارج النطاق."),
             429: error_response("THROTTLED."),
         },
     ),
     create=extend_schema(
         tags=["User Management"],
         operation_id="users_create",
         summary="إنشاء مستخدم",
         description=(
             "الأدوار المسموحة: SUPERUSER ينشئ جميع Business roles؛ MINISTRY_ADMIN ينشئ "
             "GOVERNORATE_ADMIN/LIBRARIAN/READER؛ GOVERNORATE_ADMIN ينشئ LIBRARIAN/READER "
             "ضمن محافظته؛ LIBRARIAN ينشئ READER فقط؛ READER ممنوع. "
             "GOVERNORATE_ADMIN يحتاج governorate، وLIBRARIAN يحتاج library دون governorate. "
             "READER يرتبط بمحافظة دون مكتبة: الوزارة تحدد governorate، بينما تُعين محافظة "
             "GOVERNORATE_ADMIN أو محافظة مكتبة LIBRARIAN server-side، وإرسال محافظة مختلفة يُرفض. "
             "is_staff وis_superuser وgroups وuser_permissions ليست مدخلات مسموحة."
         ),
         request=UserAdminCreateSerializer,
         responses={
             201: success_envelope(
                 "UserCreateSuccessEnvelope",
                 UserAdminCreateSerializer(),
                 ["USER_CREATED"],
             ),
             400: error_response("VALIDATION_ERROR مع أخطاء role أو governorate أو library أو password أو username."),
             401: error_response("AUTHENTICATION_REQUIRED أو INVALID_TOKEN."),
             403: error_response("PERMISSION_DENIED."),
             429: error_response("THROTTLED."),
         },
     ),
)
class UserAdminView(
     ArabicApiResponseMixin,
     mixins.CreateModelMixin,
     mixins.ListModelMixin,
     mixins.RetrieveModelMixin,
     viewsets.GenericViewSet,
) :
     serializer_class = UserAdminSeri 
     permission_classes = [IsLibrarian, CanAccessUser]
     queryset = User.objects.all()
     success_response_messages = {
         "list": ("USERS_RETRIEVED", "تم جلب قائمة المستخدمين بنجاح."),
         "retrieve": ("USER_RETRIEVED", "تم جلب بيانات المستخدم بنجاح."),
         "create": ("USER_CREATED", "تم إنشاء المستخدم بنجاح."),
         "reader_search": ("READERS_RETRIEVED", "تم جلب نتائج البحث عن القراء بنجاح."),
     }
     # General user listing, details and account status stay with governorate
     # admins and above; librarians create readers and use reader_search only.
     governorate_admin_actions = frozenset({"list", "retrieve", "deactivate", "reactivate"})
     reader_search_min_length = 2

     def get_permissions(self):
         if self.action in self.governorate_admin_actions:
             return [IsGovernorateAdmin(), CanAccessUser()]
         return super().get_permissions()

     def get_serializer_class(self):
         if self.action == "create":
             return UserAdminCreateSerializer
         return UserAdminSeri
     
     def get_queryset(self) :
         queryset = users_accessible_to(self.request.user).annotate(
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

     @extend_schema(
         tags=["User Management"],
         operation_id="users_reader_search",
         summary="البحث عن قارئ لاختياره في الاستعارة",
         description=(
             "متاح لـLIBRARIAN فأعلى. LIBRARIAN يبحث ضمن محافظة مكتبته، GOVERNORATE_ADMIN ضمن محافظته، "
             "وMINISTRY_ADMIN في جميع المحافظات. القراء الفعّالون فقط. عبارة البحث `q` إلزامية "
             "(حرفان على الأقل) وتطابق username أو الاسم الأول أو الأخير جزئياً، أو البريد أو الهاتف تطابقاً تاماً. "
             "النتائج مرتبة حسب username وتُعاد على صفحات."
         ),
         parameters=[
             OpenApiParameter(name="q", type=str, required=True, description="عبارة البحث."),
             OpenApiParameter(name="page", type=int, required=False),
             OpenApiParameter(name="page_size", type=int, required=False, description="بحد أقصى 50."),
         ],
         responses={
             200: success_envelope(
                 "ReaderSearchSuccessEnvelope",
                 inline_serializer(
                     name="ReaderSearchPage",
                     fields={
                         "count": serializers.IntegerField(),
                         "next": serializers.URLField(allow_null=True),
                         "previous": serializers.URLField(allow_null=True),
                         "results": ReaderSearchResultSerializer(many=True),
                     },
                 ),
                 ["READERS_RETRIEVED"],
             ),
             400: error_response("VALIDATION_ERROR عند غياب عبارة البحث أو قصرها."),
             401: error_response("AUTHENTICATION_REQUIRED أو INVALID_TOKEN."),
             403: error_response("PERMISSION_DENIED."),
             429: error_response("THROTTLED."),
         },
     )
     @action(
         detail=False,
         methods=["get"],
         permission_classes=[IsLibrarian],
         url_path="reader-search",
     )
     def reader_search(self, request):
         term = (request.query_params.get("q") or "").strip()
         if len(term) < self.reader_search_min_length:
             raise ValidationError(
                 {"q": f"عبارة البحث مطلوبة ويجب ألا تقل عن {self.reader_search_min_length} أحرف."}
             )

         queryset = (
             readers_searchable_by(request.user)
             .filter(
                 Q(username__icontains=term)
                 | Q(first_name__icontains=term)
                 | Q(last_name__icontains=term)
                 | Q(email__iexact=term)
                 | Q(phone=term)
             )
             .select_related("governorate")
             .order_by("username", "id")
         )

         paginator = ReaderSearchPagination()
         page = paginator.paginate_queryset(queryset, request, view=self)
         serializer = ReaderSearchResultSerializer(page, many=True)
         return paginator.get_paginated_response(serializer.data)

     def _set_borrowing_block(self, user, blocked):
         user.borrowing_blocked = blocked
         user.save(update_fields=["borrowing_blocked"])
         return user

     def _set_active_status(self, request, user, active):
         if not can_manage_user_status(request.user, user):
             raise PermissionDenied("لا تملك صلاحية إدارة هذا المستخدم.")
         if active and not has_active_user_scope(user):
             raise ValidationError(
                 {"detail": "لا يمكن إعادة تفعيل المستخدم لأن نطاقه التنظيمي غير فعال."}
             )
         changed = user.is_active != active
         if changed:
             user.is_active = active
             user.save(update_fields=["is_active"])
         return changed

     @extend_schema(
         tags=["User Management"],
         operation_id="user_deactivate",
         summary="تعطيل حساب مستخدم",
         description="لا يحذف الحساب. يخضع للصلاحيات والنطاق الحاليين.",
         request=None,
         responses={
             200: success_envelope(
                 "UserDeactivateSuccessEnvelope",
                 serializers.JSONField(allow_null=True),
                 ["USER_DEACTIVATED", "USER_ALREADY_INACTIVE"],
             ),
             400: error_response("VALIDATION_ERROR للحالات business-invalid."),
             401: error_response("AUTHENTICATION_REQUIRED أو INVALID_TOKEN."),
             403: error_response("PERMISSION_DENIED."),
             404: error_response("NOT_FOUND للهدف خارج النطاق."),
             429: error_response("THROTTLED."),
         },
     )
     @action(detail=True, methods=["post"], url_path="deactivate")
     def deactivate(self, request, pk=None):
         user = self.get_object()
         changed = self._set_active_status(request, user, False)
         return self.success_response(
             data=None,
             code="USER_DEACTIVATED" if changed else "USER_ALREADY_INACTIVE",
             message="تم تعطيل حساب المستخدم بنجاح." if changed else "الحساب معطل بالفعل.",
         )

     @extend_schema(
         tags=["User Management"],
         operation_id="user_reactivate",
         summary="إعادة تفعيل حساب مستخدم",
         description="لا ينشئ حسابًا جديدًا، ويتحقق من بقاء النطاق التنظيمي فعالًا.",
         request=None,
         responses={
             200: success_envelope(
                 "UserReactivateSuccessEnvelope",
                 serializers.JSONField(allow_null=True),
                 ["USER_REACTIVATED", "USER_ALREADY_ACTIVE"],
             ),
             400: error_response("VALIDATION_ERROR، بما فيه النطاق التنظيمي غير الفعال."),
             401: error_response("AUTHENTICATION_REQUIRED أو INVALID_TOKEN."),
             403: error_response("PERMISSION_DENIED."),
             404: error_response("NOT_FOUND للهدف خارج النطاق."),
             429: error_response("THROTTLED."),
         },
     )
     @action(detail=True, methods=["post"], url_path="reactivate")
     def reactivate(self, request, pk=None):
         user = self.get_object()
         changed = self._set_active_status(request, user, True)
         return self.success_response(
             data=None,
             code="USER_REACTIVATED" if changed else "USER_ALREADY_ACTIVE",
             message="تم تفعيل حساب المستخدم بنجاح." if changed else "الحساب فعال بالفعل.",
         )

     @extend_schema(
         tags=["User Management"],
         operation_id="user_block_borrowing",
         summary="حظر الاستعارة لمستخدم",
         description=(
             "المسار الفعلي يقبل `block_borrowing` و`block-borrowing` بسبب url_path الحالي."
         ),
         request=None,
         responses={
             200: success_envelope(
                 "UserBorrowingBlockedSuccessEnvelope",
                 BorrowingBlockedDataSchemaSerializer(),
                 ["USER_BORROWING_BLOCKED"],
             ),
             401: error_response("AUTHENTICATION_REQUIRED أو INVALID_TOKEN."),
             403: error_response("PERMISSION_DENIED."),
             404: error_response("NOT_FOUND للهدف خارج النطاق."),
             429: error_response("THROTTLED."),
         },
     )
     @action(
         detail=True,
         methods=["post"],
         permission_classes=[IsLibrarian, CanAccessUser],
         url_path=r"block[_-]borrowing",
     )
     def block_borrowing(self, request, pk=None):
         user = self.get_object()
         self._set_borrowing_block(user, True)
         return self.success_response(
             data={
                "user_id": user.id,
                "borrowing_blocked": True,
             },
             code="USER_BORROWING_BLOCKED",
             message="تم حظر الاستعارة للمستخدم بنجاح.",
         )

     @extend_schema(
         tags=["User Management"],
         operation_id="user_unblock_borrowing",
         summary="إلغاء حظر الاستعارة لمستخدم",
         description=(
             "المسار الفعلي يقبل `unblock_borrowing` و`unblock-borrowing` بسبب url_path الحالي."
         ),
         request=None,
         responses={
             200: success_envelope(
                 "UserBorrowingUnblockedSuccessEnvelope",
                 BorrowingUnblockedDataSchemaSerializer(),
                 ["USER_BORROWING_UNBLOCKED"],
             ),
             401: error_response("AUTHENTICATION_REQUIRED أو INVALID_TOKEN."),
             403: error_response("PERMISSION_DENIED."),
             404: error_response("NOT_FOUND للهدف خارج النطاق."),
             429: error_response("THROTTLED."),
         },
     )
     @action(
         detail=True,
         methods=["post"],
         permission_classes=[IsLibrarian, CanAccessUser],
         url_path=r"unblock[_-]borrowing",
     )
     def unblock_borrowing(self, request, pk=None):
         user = self.get_object()
         self._set_borrowing_block(user, False)
         return self.success_response(
             data={
                 "user_id": user.id,
                 "borrowing_blocked": False,
             },
             code="USER_BORROWING_UNBLOCKED",
             message="تم إلغاء حظر الاستعارة للمستخدم بنجاح.",
         )

     @extend_schema(
         tags=["User Management"],
         operation_id="user_reset_password",
         summary="إعادة تعيين كلمة مرور مستخدم",
         description="الصلاحية تعتمد على الدور والنطاق، ولا يسمح بإعادة تعيين كلمة مرور الذات حسب السياسة الحالية.",
         request=AdminPasswordResetSerializer,
         responses={
             200: success_envelope(
                 "UserPasswordResetSuccessEnvelope",
                 serializers.JSONField(allow_null=True),
                 ["USER_PASSWORD_RESET"],
             ),
             400: error_response("VALIDATION_ERROR لتطابق أو قوة كلمة المرور."),
             401: error_response("AUTHENTICATION_REQUIRED أو INVALID_TOKEN."),
             403: error_response("PERMISSION_DENIED."),
             404: error_response("NOT_FOUND للهدف خارج النطاق."),
             429: error_response("THROTTLED."),
         },
     )
     @action(
         detail=True,
         methods=["post"],
         permission_classes=[CanResetUserPassword],
         url_path="reset-password",
     )
     def reset_password(self, request, pk=None):
         user = self.get_object()
         self.check_object_permissions(request, user)
         serializer = AdminPasswordResetSerializer(
             data=request.data,
             context={"user": user},
         )
         serializer.is_valid(raise_exception=True)
         serializer.save()
         return self.success_response(
             data=None,
             code="USER_PASSWORD_RESET",
             message="تم إعادة تعيين كلمة المرور بنجاح.",
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
