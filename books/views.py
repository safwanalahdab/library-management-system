from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from .models import Book, BorrowedBook, Category
from .serializers import BookSerializers, CategorySerializers



class DashboardBookPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 10


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

         if user.borrowing_blocked :
            return Response( { "error" : "الاستعارة محظورة على هذا الحساب" } , status = status.HTTP_400_BAD_REQUEST )

         if BorrowedBook.objects.filter( borrower = user , is_returned = False , book = book ).exists() :
            return Response( { "error" : "انت مستعير هذه النسخة حاليا" } , status = status.HTTP_400_BAD_REQUEST )

         if not book.borrow_book() :
            return Response({"error" : "الكتاب غير متاح حاليا"} , status = status.HTTP_400_BAD_REQUEST )

         BorrowedBook.objects.create( book = book , borrower = user )
         return Response({"success" : "تمت الاستعارة بنجاح"} , status = status.HTTP_201_CREATED )

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
    - borrowing is blocked for the user, or
    - user already has an active borrow for this book, or
    - no available copies remain.

"""


class CategoryViewSet ( viewsets.ReadOnlyModelViewSet ) :
   queryset = Category.objects.all()
   serializer_class = CategorySerializers
   permission_classes = [ AllowAny ]

"""
    ### CategoryViewSet
    Public read-only API for listing and retrieving book categories.

    Endpoints (assuming router prefix 'category'):
      GET /api/category/        -> list all categories
      GET /api/category/{id}/   -> retrieve a single category

    Permissions:
      - All endpoints are public (no authentication required).

"""
