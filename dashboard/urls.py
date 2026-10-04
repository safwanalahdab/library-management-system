from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .borrowing_views import BookBorrowRequestCreateView, BorrowRequestViewSet, BorrowViewSet
from .favorites_views import BookFavoriteView, FavoriteBookListView
from .views import (
    AuthorAdminView,
    BookAdminView,
    BorrowedBookAdminViewSet,
    CategoryAdminView,
    DashboardStatsView,
    UserAdminView,
)
 
router = DefaultRouter() 
router.register(r'books', BookAdminView, basename='admin-books')
router.register(r'users', UserAdminView , basename='admin-users')
router.register(r'borrow', BorrowedBookAdminViewSet , basename='borrow-users')
router.register(r'category', CategoryAdminView , basename='category-users')
router.register(r'author', AuthorAdminView , basename='AuthorAdminView-users')
# New borrowing system; the legacy 'borrow' route above stays until it is retired.
router.register(r'borrow-requests', BorrowRequestViewSet, basename='borrow-requests')
router.register(r'borrows', BorrowViewSet, basename='borrows')


urlpatterns = [
    # Reader borrow requests are created from the book; listed under borrow-requests/.
    path('books/<int:pk>/borrow-requests/', BookBorrowRequestCreateView.as_view(), name='book-borrow-requests'),
    path('books/<int:pk>/favorite/', BookFavoriteView.as_view(), name='book-favorite'),
    path('favorites/', FavoriteBookListView.as_view(), name='favorites'),
    path('', include(router.urls) ) ,
    path('stats/' , DashboardStatsView.as_view() , name = "DashboardStatsView" ) ,
]
