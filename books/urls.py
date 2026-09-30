from django.urls import path , include 
from rest_framework.routers import DefaultRouter 
from .views import * 
from . import views


router = DefaultRouter() 
router.register('books', BookViewSet , basename = 'books' ) 
router.register('category', CategoryViewSet , basename = 'category' ) 
router.register('activity' , ActivityViewSet , basename = "activity")
router.register("quotes", QuoteViewSet, basename="quotes")


urlpatterns = [
       path('api/', include( router.urls ) ) ,
       path('api/recommendations/me/', MyRecommendationsView.as_view(), name='my_recommendations'),
]

