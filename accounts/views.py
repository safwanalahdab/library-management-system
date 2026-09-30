from django.contrib.auth import login
from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from rest_framework import generics, status, viewsets
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import obtain_auth_token, ObtainAuthToken
from rest_framework.decorators import (
    action,
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from books.models import BorrowedBook
from books.serializers import BarrowBookSerilaizers
from .serializers import *
from books.views import get_user_tier 

class RegisterView ( generics.CreateAPIView ) : 
    queryset = User.objects.all() 
    permission_classes = [ AllowAny ] 
    serializer_class = RegisterSerializer 

    def create( self , request , *args, **kwargs ) : 
        serilizer = self.get_serializer( data = request.data )
        serilizer.is_valid( raise_exception = True ) 

        user = serilizer.save() 

        token , created = Token.objects.get_or_create( user = user )

        login( request , user ) 

        data = {
            "message" : "تم انشاء المستخدم بنجاح " ,
            "user" : {
            "username" : user.username , 
            "email" : user.email , 
            "first_name" : user.first_name , 
            "last_name" : user.last_name ,
            }
            ,
            "token" : token.key 
        }

        return Response( data , status = status.HTTP_201_CREATED )

""" 
### RegisterView

Public API for user registration with automatic token creation and login.

- **Register a new user**
  - `POST /api/register/`
  - Public endpoint (`AllowAny`).
  - Uses `RegisterSerializer` to validate and create the user.
  - On success:
    - Creates or retrieves an auth `Token` for the new user.
    - Logs the user in using Django's `login(request, user)`.
    - Returns:
      - Success message (Arabic).
      - Basic user info: `username`, `email`, `first_name`, `last_name`.
      - Authentication `token` to be used for subsequent authenticated requests. 

class LoginView ( ObtainAuthToken ) :
    permission_classes = [ AllowAny ] 
    authentication_classes = [ TokenAuthentication ] 

    def post( self, request, *args, **kwargs ) : 
         response =  super().post(request, *args, **kwargs) 
         if 'token' in response.data : 
          token = Token.objects.get( key = response.data['token'] )  
          data = {
            "message" : "تم تسجيل الدخول بنجاح " , 
            "status" : {
                "token" : token.key , 
                "user_id" : token.user.id ,
                "user_name" : token.user.username , 
            }
          }  
          return Response( data ) 
         
         return Response(
                {"error": "اسم المستخدم أو كلمة المرور غير صحيحة"},
                status= status.HTTP_400_BAD_REQUEST 
            )
"""

class LoginView(APIView):
    permission_classes = [AllowAny]


    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        token, _ = Token.objects.get_or_create(user=user)

        data = {
            "message": "تم تسجيل الدخول بنجاح",
            "status": {
                "token": token.key,
                "user_id": user.id,
                "user_name": user.username,
            },
        }
        return Response(data, status=status.HTTP_200_OK)


class LogoutView( APIView ) : 

    def post( self , request ) : 
        request.user.auth_token.delete() 
        return Response({"message" : "تم تسجيل الخروج بنجاح "} , status = status.HTTP_200_OK  )
     
"""
### LogoutView

Authenticated API for logging out a user by deleting their auth token.

- **Logout**
  - `POST /api/logout/`
  - Auth required (user must be logged in with a valid token).
  - Behavior:
    - Deletes the current user's `auth_token` (`request.user.auth_token.delete()`).
    - Effectively invalidates the token so it can no longer be used.
  - Response:
    - `{"message": "تم تسجيل الخروج بنجاح "}`
    - HTTP status `200 OK`.

"""

class ResetPasswordView( APIView ) :
    
    def post( self , request ) : 
        serilizaer = ResetPasswordSerilaizer( data = request.data , context =  { "request" : request } )
        serilizaer.is_valid( raise_exception = True ) 
        serilizaer.save() 
        return Response({"message" : "تم تغيير كلمة المرور بنجاح"} , status = status.HTTP_200_OK )  

"""
### ResetPasswordView

Authenticated API for changing the current user's password.

- **Reset password**
  - `POST /api/reset-password/`
  - Auth required (user must be logged in).
  - Request body:
    - Handled by `ResetPasswordSerilaizer` (validates old password, new password, etc.).
  - Behavior:
    - Initializes `ResetPasswordSerilaizer` with `request.data` and `context={"request": request}`.
    - Validates input (`is_valid(raise_exception=True)`).
    - Calls `serializer.save()` to perform the password change.
  - Response:
    - `{"message": "تم تغيير كلمة المرور بنجاح"}`
    - HTTP status `200 OK`.
"""

class ProfileView( generics.RetrieveUpdateAPIView ) :
    serializer_class = ProfileSerializer

    def _get_user_activities(self, user):
     return (
        ActivityRegistration.objects.select_related("activity")
        .filter(user=user, activity__is_visible=True)
        .order_by("-created_at")
    )

    def get_object( self ) :

        today = timezone.now().date()
        user = (
         User.objects.annotate(
            borrowed_books_count=Count(
                "borrower_book",
                filter=Q(borrower_book__is_returned=False),
                distinct=True,
            ),
            overdue_books_count=Count(
                "borrower_book",
                filter=Q(
                    borrower_book__is_returned=False,
                    borrower_book__due_date__lt=today,
                ),
                distinct=True,
            ),
            favorites_count=Count(
                "user_fav",
                filter=Q(user_fav__book__is_archived=False),
                distinct=True,
            ),
        )
        .get(id=self.request.user.id)
    )
        user.tier,mx = get_user_tier(user)
        user.registered_activities = self._get_user_activities(user)
        user.available_books = mx if mx < 0 else max(mx - user.borrowed_books_count, 0)
        return user

"""
### ProfileView

Authenticated API for retrieving and updating the current user's profile with extra stats.

- **Get current user's profile**
  - `GET /api/profile/`
  - Auth required (uses `request.user`).
  - Behavior:
    - Fetches the currently authenticated user and annotates them with:
      - `borrowed_books_count`  
        - Count of active borrow records:
        - `borrower_book__is_returned = False`
      - `overdue_books_count`  
        - Count of active overdue borrow records:
        - `borrower_book__is_returned = False`
        - `borrower_book__due_date__lt = today`
      - `favorites_count`  
        - Count of favorite books that are not archived:
        - `user_fav__book__is_archived = False`
    - Returns the annotated user object serialized via `ProfileSerializer`.

- **Update current user's profile**
  - `PUT /api/profile/`
  - `PATCH /api/profile/`
  - Auth required.
  - Behavior:
    - Updates the current user's profile fields as defined in `ProfileSerializer`.
    - Still returns the profile including:
      - `borrowed_books_count`
      - `overdue_books_count`
      - `favorites_count`
"""

class BorrwoedProfileView( viewsets.ModelViewSet ) :
    queryset = BorrowedBook.objects.all() 
    serializer_class = BarrowBookSerilaizers 
    
    def get_queryset( self ) :
        user = self.request.user 
        querset = BorrowedBook.objects.filter( borrower = user , is_returned = False )
        return querset 
    
    @action( detail = True , methods = ['post'] ) 
    def return_book( self , request , pk = None ) : 
        book = self.get_object() 
        if book.return_request == True : 
            return Response({"Message" : "لقد قمت بتقديم طلب استعادة بالفعل سابقا"},status = status.HTTP_400_BAD_REQUEST)
        book.return_request = True
        book.return_request_date = timezone.now() 
        book.save() 
        return Response({"Message" : "لقد قمت بتقديم طلب استعادة بنجاح"} , status = status.HTTP_200_OK ) 
    
    @action( detail = True , methods = ['post'] ) 
    def extension_book( self , request , pk = None ) : 
        book = BorrowedBook.objects.filter( id = pk , borrower = request.user , is_returned = False ).first()

        if not book :
            return Response({"ERROR" : "سجل الاستعارة غير موجود"} , status = status.HTTP_404_NOT_FOUND )

        if book.extension_request == True :
            return Response({"Message" : "لقد قمت بتقديم طلب تمديد بالفعل سابقا"} , status = status.HTTP_400_BAD_REQUEST )

        if book.is_extended == True :
            return Response({"Message" : "تم تمديد مدة هذه الاستعارة سابقا"} , status = status.HTTP_400_BAD_REQUEST )

        book.extension_request = True
        book.extension_request_date = timezone.localdate()
        book.save(update_fields = ['extension_request','extension_request_date'])
        
        return Response({"Message" : "لقد قمت بتقديم طلب تمديد الإعارة بنجاح"} , status = status.HTTP_200_OK )
"""
### BorrwoedProfileView

Authenticated API for users to view and manage their own active borrowed books.

- **List active borrowed books**
  - `GET /api/borrows/`
  - Auth required.
  - Returns all `BorrowedBook` records where:
    - `borrower = request.user`
    - `is_returned = False`
  - Uses `BarrowBookSerilaizers` for serialization.

- **Retrieve a single borrowed book**
  - `GET /api/borrows/{id}/`
  - Auth required.
  - Returns details of a single active borrow record that belongs to the current user.

- **Request to return a borrowed book**
  - `POST /api/borrows/{id}/return_book/`
  - Auth required.
  - Behavior:
    - Loads the borrow record for the current user by `{id}`.
    - If `return_request` is already `True`:
      - Fails with:
        - `{"Message": "لقد قمت بتقديم طلب استعادة بالفعل سابقا"}`
        - HTTP `400 Bad Request`
    - Otherwise:
      - Sets `return_request = True`
      - Sets `return_request_date = timezone.now()`
      - Saves the record.
      - Returns:
        - `{"Message": "لقد قمت بتقديم طلب استعادة بنجاح"}`
        - HTTP `200 OK`

"""

class RecoveredbooksProfileView( viewsets.ModelViewSet ) : 
    queryset = BorrowedBook.objects.all() 
    serializer_class = BarrowBookSerilaizers 
    def get_queryset( self ) :
        user = self.request.user 
        queryset = BorrowedBook.objects.filter(borrower = user , is_returned = True ) 
        return queryset 

"""
### RecoveredbooksProfileView

Authenticated API for users to view their previously returned (recovered) books.

- **List returned books**
  - `GET /api/recovered-borrows/`
  - Auth required.
  - Returns all `BorrowedBook` records where:
    - `borrower = request.user`
    - `is_returned = True`
  - Uses `BarrowBookSerilaizers` for serialization.
  - Useful for showing the user's borrow history of books they already returned.

- **Retrieve a single returned book record**
  - `GET /api/recovered-borrows/{id}/`
  - Auth required.
  - Returns details of a single returned borrow record that belongs to the current user.

"""


class FavoriteBooksProfileView( viewsets.ReadOnlyModelViewSet ) :
    serializer_class = FavoriteBookSerializer 
    queryset = Favorite_Book.objects.all()
    
    def get_queryset( self ) :
        user = self.request.user 
        return(
             Favorite_Book.objects.filter( user = user , book__is_archived = False )
           #  .select_related( "book" , "book__author" , "book__category") 
            # .order_by("-created_at") 
        )
    
"""
### FavoriteBooksProfileView

Authenticated read-only API for users to browse their favorite (liked) books.

- **List favorite books**
  - `GET /api/favorites/`
  - Auth required.
  - Returns all `Favorite_Book` records where:
    - `user = request.user`
    - related book is not archived (`book__is_archived = False`)
  - Uses `FavoriteBookSerializer` for serialization.
  - Optimized with:
    - `.select_related("book", "book__author", "book__category")`
    - `.order_by("-created_at")` (newest favorites first)

- **Retrieve a single favorite entry**
  - `GET /api/favorites/{id}/`
  - Auth required.
  - Returns details of a single favorite record that belongs to the current user, including the related book, author, and category data.

"""

class VerifyTokenAndRoleView( APIView ) :
    authentication_classes = [TokenAuthentication] 
    permission_classes = [IsAuthenticated]     

    def get( self , request ) :
        user = request.user 
        is_admin = user.is_staff or user.is_superuser 

        Json = {
            "valid" : True , 
            "role" : "admin" if is_admin else "user" , 
            "is_admin": is_admin ,
        }

        return Response( Json , status = status.HTTP_200_OK )
    
"""
### VerifyTokenAndRoleView

Authenticated utility API for checking if a token is valid and determining the user's role.

- **Verify token and get role**
  - `GET /api/auth/verify-token/`
  - Auth required (Token authentication).
  - Behavior:
    - Uses `TokenAuthentication` and `IsAuthenticated` to ensure:
      - The provided token is valid.
      - A logged-in user is attached to the request.
    - Determines if the user is an admin:
      - `is_admin = user.is_staff or user.is_superuser`
    - Returns a JSON object with:
      - `valid`: always `True` if the request reaches this view (token is valid).
      - `role`: `"admin"` if user is staff or superuser, otherwise `"user"`.
      - `is_admin`: boolean flag indicating admin status.
"""
