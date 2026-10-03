from django.urls import path , include
from .views import (
    BorrwoedProfileView,
    GovernorateListView,
    LibraryViewSet,
    LoginView,
    LogoutView,
    MeView,
    ProfileView,
    RecoveredbooksProfileView,
    RefreshView,
    RegisterView,
    ResetPasswordView,
)
from rest_framework.routers import DefaultRouter 

router = DefaultRouter() 
router.register('profileborrwoed', BorrwoedProfileView , basename = 'BorrwoedProfileView' )
router.register('Recoveredbooks', RecoveredbooksProfileView , basename = 'RecoveredbooksProfileView' )
router.register('libraries', LibraryViewSet , basename = 'libraries' )

urlpatterns = [
      path('register' , RegisterView.as_view() , name = "register" ) ,
      path('governorates' , GovernorateListView.as_view() , name = "governorates" ) ,
      path('login' , LoginView.as_view() , name = "login" ) ,
      path('refresh' , RefreshView.as_view() , name = "refresh" ) ,
      path('logout' , LogoutView.as_view() , name = "logout" ) ,
      path('me' , MeView.as_view() , name = "me" ) ,
      path('change_password' , ResetPasswordView.as_view() , name = "change_password" ) ,
      path('profile' , ProfileView.as_view() , name = "profile" ) ,
      path('', include( router.urls ) ) ,
]

