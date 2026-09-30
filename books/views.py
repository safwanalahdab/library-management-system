from django.http import HttpResponse
from django.shortcuts import render

from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.db.models import Avg, Count, Q
from .models import *
from .serializers import *
from dashboard.serializers import * 
from rest_framework.pagination import PageNumberPagination
from recommendations.constants import DEFAULT_TOP_K, MAX_TOP_K
from recommendations.service import BookRecommendationService



class DashboardBookPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 10

 
def get_user_tier( user ) :
    from accounts.models import UserProfile

    profile, _ = UserProfile.objects.get_or_create(user=user)
    if profile.borrowing_blocked:
       return "blocked" , -1

    read_books_count = (
        BorrowedBook.objects.filter(borrower=user, is_returned=True)
        .values("book_id")
        .distinct()
        .count()
    )
    summaries_count = (
        BookSummary.objects.filter(user=user)
        .values("book_id")
        .distinct()
        .count()
    )

    if read_books_count >= 10 and summaries_count >= 10 : 
       return "gold" , 3 
    elif read_books_count >= 5 and summaries_count >= 5 : 
       return "silver" , 2  
    else : 
       return "black" , 1 
    

class BookViewSet( viewsets.ReadOnlyModelViewSet ) :
    
    queryset = Book.objects.all()
    serializer_class = BookSerializers
    permission_classes = [ AllowAny ]
    pagination_class = DashboardBookPagination

    def get_queryset( self ) :
      queryset = Book.objects.filter( is_archived = False ) 
      author = self.request.query_params.get('author') 
      category = self.request.query_params.get('category') 

      if author   :
         queryset = queryset.filter( author__name__icontains = author ) 
      if category : 
         queryset = queryset.filter( category__name__icontains = category ) 

      return queryset 
      
      
    @action( detail = True , methods = ['post'] , permission_classes = [IsAuthenticated] ) 
    def borrow( self , request , pk = None ) : 
         book = self.get_object() 
         user = request.user 

         if BorrowedBook.objects.filter( borrower = user , is_returned = False , book = book ).count() > 0 :
            return Response( { "error" : "انت مستعير هذه النسخة حاليا" } , status = status.HTTP_400_BAD_REQUEST )

         tier, max_allowed = get_user_tier(user)
         active_count = BorrowedBook.objects.filter(borrower=user, is_returned=False).count() 
         
         if active_count >= max_allowed : 
            return Response(
            {
            "error" : "لقد وصلت الى الحد الاقصى المسموح للاستعارة",
            "tier": tier,
            "max_allowed": max_allowed,
            "active_borrows": active_count ,
            }
               , status = status.HTTP_400_BAD_REQUEST
            )

         if not book.borrow_book() :
            return Response({"error" : "الكتاب غير متاح حاليا"} , status = status.HTTP_400_BAD_REQUEST )
         
         BorrowedBook.objects.create( book = book , borrower = user ) 
         return Response({"success" : "تمت الاستعارة بنجاح"} , status = status.HTTP_201_CREATED ) 
      
    @action( detail = True , methods = ['post'] , permission_classes = [IsAuthenticated] ) 
    def like( self , request , pk = None ) : 
       book = self.get_object() 
       user = request.user 
       fav , created = Favorite_Book.objects.get_or_create( user = user , book = book )

       if not created :
          return Response({"message" : "الكتاب موجود بالفعل ضمن المفضلة"} , status = status.HTTP_400_BAD_REQUEST )

       return Response({"Message" : "تمت اضافة الكتاب الى المفضلة"} , status = status.HTTP_200_OK ) 


    @action( detail = True , methods = ['post'] , permission_classes = [IsAuthenticated] ) 
    def unlike( self , request , pk = None ) : 
       book = self.get_object() 
       user = request.user 
       created = Favorite_Book.objects.filter( user = user , book = book ).first() 

       if not created  :
          return Response({ "MESSAGE" : "انت لست معجب بالكتاب اصلا"} , status = status.HTTP_400_BAD_REQUEST )

       created.delete() 
       return Response({"MESSAGE" : "لقد قمت بالغاء الاعجاب على هذا الكتاب" } , status = status.HTTP_200_OK )    
    
    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def summarize(self, request, pk=None):
     book = self.get_object()
     serializer = BookSummarySerializer(data=request.data)
     serializer.is_valid(raise_exception=True)
     serializer.save(book=book, user=request.user)
     return Response(serializer.data, status=status.HTTP_201_CREATED) 
    
    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def summaries(self, request, pk=None):
     book = self.get_object()
     queryset = BookSummary.objects.filter(book=book).order_by("-created_at")
     serializer = BookSummarySerializer(queryset, many=True)
     return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def rate(self, request, pk=None):
     book = self.get_object()
     current_rating = BookRating.objects.filter(book=book, user=request.user).first()
     serializer = BookRatingSerializer(current_rating, data=request.data)
     serializer.is_valid(raise_exception=True)
     rating = serializer.save(book=book, user=request.user)
     stats = book.ratings.aggregate(
        average_rating=Avg("rating"),
        rating_count=Count("id"),
     )
     average_rating = stats["average_rating"]

     return Response(
        {
            "message": "تم حفظ تقييم الكتاب بنجاح",
            "rating": BookRatingSerializer(rating).data,
            "average_rating": round(average_rating, 1) if average_rating is not None else None,
            "rating_count": stats["rating_count"],
            "user_rating": rating.rating,
        },
        status=status.HTTP_200_OK,
     )

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def reserve(self, request, pk=None):
     book = self.get_object()

     if book.available_copies != 0:
        return Response(
           {"message": "لا يمكن حجز الكتاب لأنه متاح حالياً للاستعارة"},
           status=status.HTTP_400_BAD_REQUEST,
        )

     if BookReservation.objects.filter(user=request.user, book=book).exists():
        return Response(
           {"message": "لديك حجز سابق لهذا الكتاب"},
           status=status.HTTP_400_BAD_REQUEST,
        )

     reservation = BookReservation.objects.create(user=request.user, book=book)
     serializer = BookReservationSerializer(reservation, context={"request": request})
     return Response(
        {
           "message": "تم حجز الكتاب بنجاح",
           "reservation": serializer.data,
        },
        status=status.HTTP_201_CREATED,
     )
    
"""        
### BookViewSet

Public read-only API for browsing books.

- **List books**
  - `GET /api/books/`
  - Returns all non-archived books.
  - Optional query params:
    - `author`: substring match on author name
    - `category`: substring match on category name

- **Retrieve a book**
  - `GET /api/books/{id}/`

- **Borrow a book**
  - `POST /api/books/{id}/borrow/`
  - Auth required.
  - Fails if:
    - user already has an active borrow for this book, or
    - no available copies remain.

- **Add to favorites**
  - `POST /api/books/{id}/like/`
  - Auth required.
  - Fails if the book is already in the user's favorites.

- **Remove from favorites**
  - `POST /api/books/{id}/unlike/`
  - Auth required.
  - Fails if the book is not in the user's favorites.

"""


class CategoryViewSet ( viewsets.ReadOnlyModelViewSet ) : 
   queryset = Category.objects.all() 
   serializer_class = CategorySerializers
   parser_classes = [ AllowAny ] 

"""
    ### CategoryViewSet
    Public read-only API for listing and retrieving book categories.

    Endpoints (assuming router prefix 'category'):
      GET /api/category/        -> list all categories
      GET /api/category/{id}/   -> retrieve a single category

    Permissions:
      - All endpoints are public (no authentication required).

"""      

class ActivityViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = LibraryActivitySerializer 
    permission_classes = [AllowAny]

    def get_queryset(self):
        return LibraryActivity.objects.filter(is_visible=True).order_by("-created_at")
    
    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def register(self, request, pk=None):
        activity = self.get_object()

        if not activity.is_active:
            return Response(
                {"error": "تم إغلاق التسجيل لهذا النشاط"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        _, created = ActivityRegistration.objects.get_or_create(
            activity=activity,
            user=request.user,
        )
        if not created:
            return Response(
                {"error": "أنت مسجل مسبقاً في هذا النشاط"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {"message": "تم التسجيل بالنشاط بنجاح"},
            status=status.HTTP_201_CREATED,
        )
    
    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def unregister(self, request, pk=None):
        activity = self.get_object()
        registration = ActivityRegistration.objects.filter(
            activity=activity,
            user=request.user,
        ).first()
        if not registration:
            return Response(
                {"error": "أنت غير مسجل في هذا النشاط"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        registration.delete()
        return Response({"message": "تم إلغاء التسجيل بنجاح"}, status=status.HTTP_200_OK)

class QuoteViewSet(viewsets.ModelViewSet):
    permission_classes = [AllowAny]
    serializer_class = QuoteSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = (
            Quote.objects.select_related("user")
            .prefetch_related("likes__user")
            .annotate(likes_count=Count("likes", distinct=True))
            .order_by("-created_at")
        )

        if self.action in ["list", "retrieve", "create", "like", "unlike", "likes_info"]:
            queryset = queryset.filter(status=Quote.Status.APPROVED)
            name = self.request.query_params.get("name")
            if name:
                queryset = queryset.filter(
                    Q(content__icontains=name)
                    | Q(user__username__icontains=name)
                    | Q(user__first_name__icontains=name)
                    | Q(user__last_name__icontains=name)
                )
            return queryset

        return queryset.none()

    def get_permissions(self):
        if self.action in ["create", "like", "unlike"]:
            return [IsAuthenticated()]
        return [AllowAny()]

    def perform_create(self, serializer):
        serializer.save(
            user=self.request.user,
            status=Quote.Status.PENDING,
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            {
                "message": "تم إرسال الخاطرة للمراجعة وبانتظار موافقة الإدارة.",
                "data": serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def like(self, request, pk=None):
        quote = self.get_object()
        already_liked = QuoteLike.objects.filter(user=request.user, quote=quote).exists()

        if already_liked:
            return Response(
                {
                    "message": "أنت معجب بهذه الخاطرة بالفعل.",
                    "liked": True,
                    "likes_count": quote.likes.count(),
                },
                status=status.HTTP_200_OK,
            )

        QuoteLike.objects.create(user=request.user, quote=quote)
        return Response(
            {
                "message": "تم تسجيل الإعجاب بالخاطرة.",
                "liked": True,
                "likes_count": quote.likes.count(),
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def unlike(self, request, pk=None):
        quote = self.get_object()
        like_obj = QuoteLike.objects.filter(user=request.user, quote=quote).first()

        if not like_obj:
            return Response(
                {
                    "message": "لا يوجد إعجاب مسبق لإزالته.",
                    "liked": False,
                    "likes_count": quote.likes.count(),
                },
                status=status.HTTP_200_OK,
            )

        like_obj.delete()

        return Response(
            {
                "message": "تمت إزالة الإعجاب من الخاطرة.",
                "liked": False,
                "likes_count": quote.likes.count(),
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def likes_info(self, request, pk=None):
        quote = self.get_object()
        liked_by_full_names = [
            like.user.get_full_name().strip() or like.user.username
            for like in quote.likes.select_related("user").all()
        ]
        return Response(
            {
                "quote_id": quote.id,
                "likes_count": quote.likes.count(),
                "liked_by_full_names": liked_by_full_names,
            },
            status=status.HTTP_200_OK,
        )


class MyRecommendationsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        limit_raw = request.query_params.get("limit", DEFAULT_TOP_K)
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            return Response(
                {"error": "limit must be a valid integer"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        limit = max(1, min(limit, MAX_TOP_K))

        available_only = request.query_params.get("available_only", "false").lower()
        available_only = available_only in ("true", "1", "yes")

        service = BookRecommendationService()
        payload = service.recommend_for_user(
            user_id=request.user.id,
            top_k=limit,
            available_only=available_only,
        )

        serializer = BookSerializers(
            payload.books,
            many=True,
            context={"request": request},
        )
        return Response(
            {
                "source": payload.source,
                "count": len(serializer.data),
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )
