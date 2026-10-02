from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone

from rest_framework import generics, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_view,
)

from Bookshelf.api_responses import (
    ArabicApiResponseMixin,
    RefreshTokenMissing,
    get_user_role_meta,
)
from Bookshelf.openapi import (
    AccessTokenDataSchemaSerializer,
    LoginDataSchemaSerializer,
    ProfileUpdateSchemaSerializer,
    error_response,
    success_envelope,
)
from books.models import BorrowedBook
from books.serializers import BarrowBookSerilaizers
from .models import Governorate
from .serializers import (
    CurrentUserSerializer,
    GovernorateOptionSerializer,
    LoginSerializer,
    ProfileSerializer,
    RegisteredUserSerializer,
    RegisterSerializer,
    ResetPasswordSerilaizer,
)

User = get_user_model()


def _set_refresh_cookie(response, refresh_token):
    response.set_cookie(
        key=settings.JWT_REFRESH_COOKIE_NAME,
        value=str(refresh_token),
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        httponly=True,
        secure=settings.JWT_REFRESH_COOKIE_SECURE,
        samesite=settings.JWT_REFRESH_COOKIE_SAMESITE,
        path=settings.JWT_REFRESH_COOKIE_PATH,
    )


def _delete_refresh_cookie(response):
    response.delete_cookie(
        key=settings.JWT_REFRESH_COOKIE_NAME,
        path=settings.JWT_REFRESH_COOKIE_PATH,
        samesite=settings.JWT_REFRESH_COOKIE_SAMESITE,
    )


@extend_schema_view(
    post=extend_schema(
        tags=["Authentication"],
        operation_id="auth_register",
        summary="تسجيل حساب قارئ جديد",
        description=(
            "ينشئ حساب READER دائماً ضمن محافظة فعالة يختارها المستخدم، دون مكتبة. "
            "لا يقبل role أو library أو أي حقول إدارية مثل is_staff وis_superuser "
            "وgroups وuser_permissions. لا يسجّل الدخول تلقائياً."
        ),
        auth=[],
        request=RegisterSerializer,
        responses={
            201: success_envelope(
                "RegisterSuccessEnvelope", RegisteredUserSerializer(), ["ACCOUNT_REGISTERED"]
            ),
            400: error_response("VALIDATION_ERROR مع تفاصيل الحقول."),
            429: error_response("THROTTLED."),
        },
    )
)
class RegisterView(ArabicApiResponseMixin, generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = RegisterSerializer
    success_response_messages = {
        "post": ("ACCOUNT_REGISTERED", "تم إنشاء الحساب بنجاح."),
    }

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            RegisteredUserSerializer(user).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    get=extend_schema(
        tags=["Authentication"],
        operation_id="governorates_active_list",
        summary="قائمة المحافظات الفعالة",
        description="قائمة عامة بالمحافظات الفعالة (المعرّف والاسم فقط) لاستخدامها في التسجيل.",
        auth=[],
        responses={
            200: success_envelope(
                "GovernorateListSuccessEnvelope",
                GovernorateOptionSerializer(many=True),
                ["GOVERNORATES_RETRIEVED"],
            ),
            429: error_response("THROTTLED."),
        },
    )
)
class GovernorateListView(ArabicApiResponseMixin, generics.ListAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = GovernorateOptionSerializer
    pagination_class = None
    queryset = Governorate.objects.filter(is_active=True).order_by("name", "id")
    success_response_messages = {
        "get": ("GOVERNORATES_RETRIEVED", "تم جلب المحافظات بنجاح."),
    }


@extend_schema_view(
    post=extend_schema(
        tags=["Authentication"],
        operation_id="auth_login",
        summary="تسجيل الدخول",
        description=(
            "يعيد access token في JSON، بينما يُرسل refresh token كـHttpOnly Cookie "
            "باسم `refresh_token` ولا يظهر في جسم الاستجابة."
        ),
        auth=[],
        request=LoginSerializer,
        responses={
            200: success_envelope(
                "LoginSuccessEnvelope", LoginDataSchemaSerializer(), ["LOGIN_SUCCESS"]
            ),
            400: error_response("INVALID_CREDENTIALS أو VALIDATION_ERROR."),
            429: error_response("THROTTLED."),
        },
    )
)
class LoginView(ArabicApiResponseMixin, APIView):
    permission_classes = [AllowAny]
    success_response_messages = {
        "post": ("LOGIN_SUCCESS", "تم تسجيل الدخول بنجاح."),
    }

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        refresh = RefreshToken.for_user(user)

        data = {
            "access": str(refresh.access_token),
            "user": {
                "id": user.id,
                "username": user.username,
                "role": get_user_role_meta(user),
                "governorate": user.governorate_id,
                "library": user.library_id,
            },
        }
        response = Response(data, status=status.HTTP_200_OK)
        response._requester_user = user
        _set_refresh_cookie(response, refresh)
        return response


@extend_schema_view(
    post=extend_schema(
        tags=["Authentication"],
        operation_id="auth_refresh",
        summary="تجديد access token",
        description=(
            "لا يستقبل body. يقرأ refresh token حصريًا من HttpOnly Cookie باسم "
            "`refresh_token`. قد لا تتمكن Swagger UI من إنشاء هذه الكوكي يدويًا؛ "
            "عادةً تُحفظ تلقائيًا من استجابة login عند استخدام نفس الأصل."
        ),
        auth=[],
        request=None,
        parameters=[
            OpenApiParameter(
                name="refresh_token",
                type=str,
                location=OpenApiParameter.COOKIE,
                required=True,
                description="HttpOnly refresh cookie المنشأة عند تسجيل الدخول.",
            )
        ],
        responses={
            200: success_envelope(
                "TokenRefreshSuccessEnvelope",
                AccessTokenDataSchemaSerializer(),
                ["TOKEN_REFRESHED"],
            ),
            401: error_response(
                "AUTHENTICATION_REQUIRED أو INVALID_TOKEN أو AUTHENTICATION_FAILED."
            ),
            429: error_response("THROTTLED."),
        },
    )
)
class RefreshView(ArabicApiResponseMixin, APIView):
    permission_classes = [AllowAny]
    success_response_messages = {
        "post": ("TOKEN_REFRESHED", "تم تجديد رمز الدخول بنجاح."),
    }

    def post(self, request):
        refresh_token = request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME)
        if not refresh_token:
            raise RefreshTokenMissing()

        try:
            token = RefreshToken(refresh_token)
            user_id = token[settings.SIMPLE_JWT.get("USER_ID_CLAIM", "user_id")]
        except (TokenError, KeyError):
            raise InvalidToken("Invalid refresh token.")

        user = get_user_model().objects.filter(pk=user_id).first()
        if user is None or not user.is_active:
            raise AuthenticationFailed()

        serializer = TokenRefreshSerializer(data={"refresh": refresh_token})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError:
            raise InvalidToken("Invalid refresh token.")

        response = Response(
            {"access": serializer.validated_data["access"]},
            status=status.HTTP_200_OK,
        )
        response._requester_user = user
        rotated_refresh = serializer.validated_data.get("refresh")
        if rotated_refresh:
            _set_refresh_cookie(response, rotated_refresh)
        return response


@extend_schema_view(
    post=extend_schema(
        tags=["Authentication"],
        operation_id="auth_logout",
        summary="تسجيل الخروج",
        description=(
            "يتطلب Bearer access token ويقرأ `refresh_token` من HttpOnly Cookie. "
            "يبطل refresh token عبر blacklist؛ ولا يبطل access token الحالي فورًا. "
            "غياب refresh cookie يبقى نجاحًا idempotent حسب السلوك الحالي."
        ),
        request=None,
        parameters=[
            OpenApiParameter(
                name="refresh_token",
                type=str,
                location=OpenApiParameter.COOKIE,
                required=False,
                description="HttpOnly refresh cookie المنشأة عند تسجيل الدخول.",
            )
        ],
        responses={
            200: success_envelope(
                "LogoutSuccessEnvelope",
                serializers.JSONField(allow_null=True),
                ["LOGOUT_SUCCESS"],
            ),
            401: error_response("AUTHENTICATION_REQUIRED أو AUTHENTICATION_FAILED أو INVALID_TOKEN."),
            429: error_response("THROTTLED."),
        },
    )
)
class LogoutView(ArabicApiResponseMixin, APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    success_response_messages = {
        "post": ("LOGOUT_SUCCESS", "تم تسجيل الخروج بنجاح."),
    }

    def post(self, request):
        refresh_token = request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME)
        if not refresh_token:
            response = Response(
                None,
                status=status.HTTP_200_OK,
            )
            _delete_refresh_cookie(response)
            return response

        try:
            token = RefreshToken(refresh_token)
            refresh_user_id = token[settings.SIMPLE_JWT.get("USER_ID_CLAIM", "user_id")]
        except (TokenError, KeyError):
            raise InvalidToken("Invalid refresh token.")

        if str(refresh_user_id) != str(request.user.pk):
            raise AuthenticationFailed(
                "Refresh token does not belong to the authenticated user."
            )

        token.blacklist()

        response = Response(
            None,
            status=status.HTTP_200_OK,
        )
        _delete_refresh_cookie(response)
        return response


@extend_schema_view(
    get=extend_schema(
        tags=["Profile"],
        operation_id="auth_me",
        summary="بيانات المستخدم الحالي",
        responses={
            200: success_envelope(
                "CurrentUserSuccessEnvelope",
                CurrentUserSerializer(),
                ["CURRENT_USER_RETRIEVED"],
            ),
            401: error_response("AUTHENTICATION_REQUIRED أو INVALID_TOKEN."),
            429: error_response("THROTTLED."),
        },
    )
)
class MeView(ArabicApiResponseMixin, APIView):
    permission_classes = [IsAuthenticated]
    success_response_messages = {
        "get": ("CURRENT_USER_RETRIEVED", "تم جلب بيانات المستخدم بنجاح."),
    }

    def get(self, request):
        serializer = CurrentUserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema_view(
    post=extend_schema(
        tags=["Profile"],
        operation_id="profile_change_password",
        summary="تغيير كلمة المرور",
        description=(
            "يتحقق من كلمة المرور الحالية، وتطابق كلمتي المرور الجديدتين، "
            "ومدققات قوة كلمة المرور. أخطاء هذه الحالات تبقى VALIDATION_ERROR بأسماء الحقول."
        ),
        request=ResetPasswordSerilaizer,
        responses={
            200: success_envelope(
                "PasswordChangedSuccessEnvelope",
                serializers.JSONField(allow_null=True),
                ["PASSWORD_CHANGED"],
            ),
            400: error_response("VALIDATION_ERROR مع تفاصيل الحقول."),
            401: error_response("AUTHENTICATION_REQUIRED أو INVALID_TOKEN."),
            429: error_response("THROTTLED."),
        },
    )
)
class ResetPasswordView(ArabicApiResponseMixin, APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    success_response_messages = {
        "post": ("PASSWORD_CHANGED", "تم تغيير كلمة المرور بنجاح."),
    }

    def post(self, request):
        serilizaer = ResetPasswordSerilaizer(
            data=request.data, context={"request": request}
        )
        serilizaer.is_valid(raise_exception=True)
        serilizaer.save()
        return Response(None, status=status.HTTP_200_OK)


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


@extend_schema_view(
    get=extend_schema(
        tags=["Profile"],
        operation_id="profile_get",
        summary="جلب الملف الشخصي",
        responses={
            200: success_envelope(
                "ProfileSuccessEnvelope", ProfileSerializer(), ["PROFILE_RETRIEVED"]
            ),
            401: error_response("AUTHENTICATION_REQUIRED أو INVALID_TOKEN."),
            429: error_response("THROTTLED."),
        },
    ),
    put=extend_schema(
        tags=["Profile"],
        operation_id="profile_replace",
        summary="تحديث الملف الشخصي بالكامل",
        description=(
            "الحقول القابلة للتعديل موضحة في request schema. إرسال role أو is_active أو is_staff "
            "أو is_superuser أو groups أو user_permissions أو password يُرفض بـVALIDATION_ERROR، "
            "وكذلك governorate أو library بقيمة تختلف عن القيمة الحالية. borrowing_blocked للقراءة فقط."
        ),
        request=ProfileUpdateSchemaSerializer,
        responses={
            200: success_envelope(
                "ProfileUpdateSuccessEnvelope", ProfileSerializer(), ["PROFILE_UPDATED"]
            ),
            400: error_response("VALIDATION_ERROR."),
            401: error_response("AUTHENTICATION_REQUIRED أو INVALID_TOKEN."),
            429: error_response("THROTTLED."),
        },
    ),
    patch=extend_schema(
        tags=["Profile"],
        operation_id="profile_update",
        summary="تحديث جزئي للملف الشخصي",
        description=(
            "يسمح فقط بـemail وfirst_name وlast_name وحقول profile: address وphone وgender وage. "
            "إرسال حقول الدور أو الصلاحيات أو كلمة المرور، أو تغيير governorate أو library، "
            "يُرفض بـVALIDATION_ERROR."
        ),
        request=ProfileUpdateSchemaSerializer,
        responses={
            200: success_envelope(
                "ProfilePatchSuccessEnvelope", ProfileSerializer(), ["PROFILE_UPDATED"]
            ),
            400: error_response("VALIDATION_ERROR."),
            401: error_response("AUTHENTICATION_REQUIRED أو INVALID_TOKEN."),
            429: error_response("THROTTLED."),
        },
    ),
)
class ProfileView(ArabicApiResponseMixin, generics.RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]
    success_response_messages = {
        "get": ("PROFILE_RETRIEVED", "تم جلب الملف الشخصي بنجاح."),
        "put": ("PROFILE_UPDATED", "تم تحديث معلومات الحساب بنجاح."),
        "patch": ("PROFILE_UPDATED", "تم تحديث معلومات الحساب بنجاح."),
    }

    def get_object(self):

        today = timezone.now().date()
        return User.objects.annotate(
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
        ).get(id=self.request.user.id)


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
"""


class BorrwoedProfileView(viewsets.ModelViewSet):
    queryset = BorrowedBook.objects.all()
    serializer_class = BarrowBookSerilaizers
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        querset = BorrowedBook.objects.filter(borrower=user, is_returned=False)
        return querset

    @action(detail=True, methods=["post"])
    def return_book(self, request, pk=None):
        book = self.get_object()
        if book.return_request == True:
            return Response(
                {"Message": "لقد قمت بتقديم طلب استعادة بالفعل سابقا"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        book.return_request = True
        book.return_request_date = timezone.now()
        book.save()
        return Response(
            {"Message": "لقد قمت بتقديم طلب استعادة بنجاح"}, status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["post"])
    def extension_book(self, request, pk=None):
        book = BorrowedBook.objects.filter(
            id=pk, borrower=request.user, is_returned=False
        ).first()

        if not book:
            return Response(
                {"ERROR": "سجل الاستعارة غير موجود"}, status=status.HTTP_404_NOT_FOUND
            )

        if book.extension_request == True:
            return Response(
                {"Message": "لقد قمت بتقديم طلب تمديد بالفعل سابقا"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if book.is_extended == True:
            return Response(
                {"Message": "تم تمديد مدة هذه الاستعارة سابقا"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        book.extension_request = True
        book.extension_request_date = timezone.localdate()
        book.save(update_fields=["extension_request", "extension_request_date"])

        return Response(
            {"Message": "لقد قمت بتقديم طلب تمديد الإعارة بنجاح"},
            status=status.HTTP_200_OK,
        )


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


class RecoveredbooksProfileView(viewsets.ModelViewSet):
    queryset = BorrowedBook.objects.all()
    serializer_class = BarrowBookSerilaizers
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = BorrowedBook.objects.filter(borrower=user, is_returned=True)
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
