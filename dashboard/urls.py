from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *
 
router = DefaultRouter() 
router.register(r'books', BookAdminView, basename='admin-books')
router.register(r'users', UserAdminView , basename='admin-users')
router.register(r'borrow', BorrowedBookAdminViewSet , basename='borrow-users')
router.register(r'reservations', BookReservationAdminViewSet , basename='admin-reservations')
router.register(r'category', CategoryAdminView , basename='category-users')
router.register(r'author', AuthorAdminView , basename='AuthorAdminView-users')
router.register(r'libraryactivity', LibraryActivityAdminViewSet , basename='LibraryActivityAdmin')
router.register(r"quotes", QuoteAdminViewSet, basename="admin-quotes")


urlpatterns = [
    path('', include(router.urls) ) ,
    path('stats/' , DashboardStatsView.as_view() , name = "DashboardStatsView" ) ,
]
