from rest_framework import serializers
from drf_spectacular.utils import OpenApiResponse, inline_serializer


DOCUMENTED_API_METHODS = {
    ("accounts.views", "LoginView"): {"POST"},
    ("accounts.views", "RefreshView"): {"POST"},
    ("accounts.views", "LogoutView"): {"POST"},
    ("accounts.views", "MeView"): {"GET"},
    ("accounts.views", "ProfileView"): {"GET", "PUT", "PATCH"},
    ("accounts.views", "ResetPasswordView"): {"POST"},
    ("accounts.views", "RegisterView"): {"POST"},
    ("accounts.views", "GovernorateListView"): {"GET"},
}

DOCUMENTED_USER_ACTIONS = {
    "list",
    "retrieve",
    "create",
    "reader_search",
    "reset_password",
    "deactivate",
    "reactivate",
    "block_borrowing",
    "unblock_borrowing",
}


def keep_documented_endpoints(endpoints):
    """Limit OpenAPI output without changing the runtime URL configuration."""
    documented = []
    for path, path_regex, method, callback in endpoints:
        view_class = getattr(callback, "cls", None)
        if view_class is None:
            continue

        view_key = (view_class.__module__, view_class.__name__)
        method_upper = method.upper()
        if method_upper in DOCUMENTED_API_METHODS.get(view_key, set()):
            documented.append((path, path_regex, method, callback))
            continue

        if view_key == ("dashboard.views", "UserAdminView"):
            action = getattr(callback, "actions", {}).get(method_upper.lower())
            if action in DOCUMENTED_USER_ACTIONS:
                documented.append((path, path_regex, method, callback))

    return documented


class RequesterRoleSchemaSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()


class ResponseMetaSchemaSerializer(serializers.Serializer):
    requester_role = RequesterRoleSchemaSerializer(allow_null=True)
    retry_after = serializers.IntegerField(required=False)


class ErrorEnvelopeSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=False)
    code = serializers.ChoiceField(
        choices=[
            "INVALID_CREDENTIALS",
            "VALIDATION_ERROR",
            "AUTHENTICATION_REQUIRED",
            "AUTHENTICATION_FAILED",
            "INVALID_TOKEN",
            "PERMISSION_DENIED",
            "NOT_FOUND",
            "METHOD_NOT_ALLOWED",
            "THROTTLED",
        ]
    )
    message = serializers.CharField()
    data = serializers.JSONField(allow_null=True, default=None)
    errors = serializers.JSONField(allow_null=True)
    meta = ResponseMetaSchemaSerializer()


class GovernorateSummarySchemaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class LoginUserSchemaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    role = RequesterRoleSchemaSerializer()
    governorate = serializers.IntegerField(allow_null=True)
    library = serializers.IntegerField(allow_null=True)


class LoginDataSchemaSerializer(serializers.Serializer):
    access = serializers.CharField()
    user = LoginUserSchemaSerializer()


class AccessTokenDataSchemaSerializer(serializers.Serializer):
    access = serializers.CharField()


class BorrowingBlockedDataSchemaSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    borrowing_blocked = serializers.BooleanField()


class BorrowingUnblockedDataSchemaSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    borrowing_blocked = serializers.BooleanField()


class ProfileUpdateSchemaSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    profile = inline_serializer(
        name="ProfileWritableFields",
        required=False,
        fields={
            "address": serializers.CharField(required=False, allow_blank=True),
            "phone": serializers.CharField(required=False, allow_blank=True),
            "gender": serializers.CharField(required=False, allow_blank=True),
            "age": serializers.IntegerField(required=False, allow_null=True),
        },
    )


def success_envelope(name, data_field, codes):
    return inline_serializer(
        name=name,
        fields={
            "success": serializers.BooleanField(default=True),
            "code": serializers.ChoiceField(choices=codes),
            "message": serializers.CharField(),
            "data": data_field,
            "meta": ResponseMetaSchemaSerializer(),
        },
    )


def error_response(description):
    return OpenApiResponse(response=ErrorEnvelopeSerializer, description=description)
