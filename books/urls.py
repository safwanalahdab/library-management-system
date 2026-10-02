from django.urls import path , include
from rest_framework.routers import DefaultRouter
from .views import BookViewSet, CategoryViewSet


router = DefaultRouter()
router.register('books', BookViewSet , basename = 'books' )
router.register('category', CategoryViewSet , basename = 'category' )


urlpatterns = [
       path('api/', include( router.urls ) ) ,
]
