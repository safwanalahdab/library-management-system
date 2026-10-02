from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    MethodNotAllowed,
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    Throttled,
    ValidationError,
)
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import InvalidToken


class InvalidCredentials(APIException):
    status_code = 400
    default_detail = "اسم المستخدم أو كلمة المرور غير صحيحة."
    default_code = "invalid_credentials"


class RefreshTokenMissing(NotAuthenticated):
    default_detail = "رمز التجديد غير موجود. يرجى تسجيل الدخول."
    default_code = "authentication_required"


DEFAULT_SUCCESS_MESSAGES = {
    "list": ("RECORDS_RETRIEVED", "تم جلب البيانات بنجاح."),
    "retrieve": ("RECORD_RETRIEVED", "تم جلب البيانات المطلوبة بنجاح."),
    "create": ("RECORD_CREATED", "تمت إضافة البيانات بنجاح."),
    "update": ("RECORD_UPDATED", "تم تحديث البيانات بنجاح."),
    "partial_update": ("RECORD_UPDATED", "تم تحديث البيانات بنجاح."),
    "destroy": ("RECORD_DELETED", "تم حذف البيانات بنجاح."),
}


def get_user_role_meta(user):
    if not user:
        return None

    if getattr(user, "is_superuser", False):
        role = "SUPERUSER"
    else:
        role = getattr(user, "role", None)

    role_labels = {
        "SUPERUSER": "مدير النظام",
        "MINISTRY_ADMIN": "مسؤول الوزارة",
        "GOVERNORATE_ADMIN": "مسؤول المحافظة",
        "LIBRARIAN": "أمين مكتبة",
        "READER": "قارئ",
    }
    if role not in role_labels:
        return None

    return {"code": role, "label": role_labels[role]}


def get_requester_role(user):
    if not user or not getattr(user, "is_authenticated", False):
        return None
    return get_user_role_meta(user)


ERROR_SPECS = {
    "INVALID_CREDENTIALS": "اسم المستخدم أو كلمة المرور غير صحيحة.",
    "VALIDATION_ERROR": "بيانات الطلب غير صالحة.",
    "AUTHENTICATION_REQUIRED": "يجب تسجيل الدخول للوصول إلى هذا المورد.",
    "AUTHENTICATION_FAILED": "تعذر التحقق من بيانات المصادقة.",
    "PERMISSION_DENIED": "لا تملك الصلاحية لتنفيذ هذه العملية.",
    "NOT_FOUND": "المورد المطلوب غير موجود.",
    "METHOD_NOT_ALLOWED": "طريقة الطلب غير مسموحة لهذا المسار.",
    "THROTTLED": "تم تجاوز عدد المحاولات المسموح بها. حاول لاحقًا.",
    "INVALID_TOKEN": "رمز الدخول غير صالح أو منتهي الصلاحية.",
}


def _get_error_code(exc, status_code):
    if isinstance(exc, InvalidCredentials):
        return "INVALID_CREDENTIALS"
    if isinstance(exc, InvalidToken):
        return "INVALID_TOKEN"
    if isinstance(exc, NotAuthenticated):
        return "AUTHENTICATION_REQUIRED"
    if isinstance(exc, AuthenticationFailed):
        return "AUTHENTICATION_FAILED"
    if isinstance(exc, ValidationError):
        return "VALIDATION_ERROR"
    if isinstance(exc, PermissionDenied):
        return "PERMISSION_DENIED"
    if isinstance(exc, NotFound):
        return "NOT_FOUND"
    if isinstance(exc, MethodNotAllowed):
        return "METHOD_NOT_ALLOWED"
    if isinstance(exc, Throttled):
        return "THROTTLED"

    return {
        400: "VALIDATION_ERROR",
        401: "AUTHENTICATION_FAILED",
        403: "PERMISSION_DENIED",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        429: "THROTTLED",
    }.get(status_code, "VALIDATION_ERROR")


def _get_error_message(exc, code):
    if isinstance(exc, RefreshTokenMissing):
        return RefreshTokenMissing.default_detail
    return ERROR_SPECS[code]


def _get_error_details(exc, error_data):
    if isinstance(exc, ValidationError) and not isinstance(exc, InvalidCredentials):
        return error_data
    return None


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None

    code = _get_error_code(exc, response.status_code)
    request = context.get("request")
    requester_role = get_requester_role(getattr(request, "user", None))
    response.data = {
        "success": False,
        "code": code,
        "message": _get_error_message(exc, code),
        "data": None,
        "errors": _get_error_details(exc, response.data),
        "meta": {"requester_role": requester_role},
    }
    if isinstance(exc, Throttled) and exc.wait is not None:
        response.data["meta"]["retry_after"] = exc.wait
    return response


class ArabicApiResponseMixin:
    """Apply the shared success envelope to selected DRF views only."""

    success_response_messages = {}

    def success_response(self, data, code, message, status_code=200, requester_user=None):
        response = Response(data, status=status_code)
        response._success_code = code
        response._success_message = message
        if requester_user is not None:
            response._requester_user = requester_user
        return response

    def _get_success_spec(self, response):
        response_code = getattr(response, "_success_code", None)
        response_message = getattr(response, "_success_message", None)
        if response_code and response_message:
            return response_code, response_message

        action = getattr(self, "action", None)
        request_method = getattr(getattr(self, "request", None), "method", "").lower()
        messages = self.success_response_messages
        return (
            messages.get(action)
            or messages.get(request_method)
            or DEFAULT_SUCCESS_MESSAGES.get(action)
        )

    def _get_response_requester_user(self, response):
        explicit_user = getattr(response, "_requester_user", None)
        if explicit_user is not None:
            return explicit_user
        request = getattr(self, "request", None)
        return getattr(request, "user", None)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if not isinstance(response, Response) or not 200 <= response.status_code < 300:
            return response

        requester_role = get_requester_role(
            self._get_response_requester_user(response)
        )
        if isinstance(response.data, dict) and "success" in response.data:
            meta = response.data.get("meta")
            if not isinstance(meta, dict):
                meta = {}
                response.data["meta"] = meta
            meta.setdefault("requester_role", requester_role)
            return response

        success_spec = self._get_success_spec(response)
        if success_spec is None:
            return response

        code, message = success_spec
        response.data = {
            "success": True,
            "code": code,
            "message": message,
            "data": response.data,
            "meta": {"requester_role": requester_role},
        }
        return response
