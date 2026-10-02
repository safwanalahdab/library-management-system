from django.urls import path , include
from . import views 
from .views import * 
from rest_framework.routers import DefaultRouter 

router = DefaultRouter() 
router.register('profileborrwoed', BorrwoedProfileView , basename = 'BorrwoedProfileView' )
router.register('Recoveredbooks', RecoveredbooksProfileView , basename = 'RecoveredbooksProfileView' )
router.register('FavoriteBooksProfileView', FavoriteBooksProfileView , basename = FavoriteBooksProfileView )

urlpatterns = [
      path('register' , RegisterView.as_view() , name = "register" ) ,
      path('login' , LoginView.as_view() , name = "login" ) ,
      path('refresh' , RefreshView.as_view() , name = "refresh" ) ,
      path('logout' , LogoutView.as_view() , name = "logout" ) ,
      path('me' , MeView.as_view() , name = "me" ) ,
      path('change_password' , ResetPasswordView.as_view() , name = "change_password" ) ,
      path('profile' , ProfileView.as_view() , name = "profile" ) ,
      path('', include( router.urls ) ) ,
]

