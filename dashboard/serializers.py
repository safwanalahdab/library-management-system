from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from accounts.serializers import UserDetailsSerializer
from accounts.models import CustomUser
from accounts.scopes import get_effective_governorate, is_active_governorate, is_superuser
from Bookshelf.api_responses import get_user_role_meta
from Bookshelf.openapi import GovernorateSummarySchemaSerializer, RequesterRoleSchemaSerializer
from drf_spectacular.utils import extend_schema_field

User = get_user_model() 


class UserAdminSeri( serializers.ModelSerializer ) :
    borrowed_books_count = serializers.IntegerField(read_only=True)
    profile = UserDetailsSerializer(source="*", read_only=True)
    borrowing_blocked = serializers.BooleanField(read_only=True)
    role = serializers.SerializerMethodField()

    @extend_schema_field(RequesterRoleSchemaSerializer)
    def get_role(self, obj):
        return get_user_role_meta(obj)

    class Meta : 
        model = User 
        fields = ['id','username','email','first_name','last_name','borrowed_books_count'
        ,'borrowing_blocked','profile','role','date_joined']
        read_only_fields = ['borrowed_books_count', 'role']


class UserAdminCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True)
    governorate = serializers.PrimaryKeyRelatedField(
        queryset=CustomUser._meta.get_field("governorate").remote_field.model.objects.all(),
        required=False,
        allow_null=True,
    )
    library = serializers.PrimaryKeyRelatedField(
        queryset=CustomUser._meta.get_field("library").remote_field.model.objects.select_related(
            "governorate"
        ),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "password",
            "first_name",
            "last_name",
            "email",
            "role",
            "governorate",
            "library",
            "is_active",
            "date_joined",
        ]
        read_only_fields = ["id", "is_active", "date_joined"]

    def validate(self, attrs):
        allowed_input_fields = {
            "username",
            "password",
            "first_name",
            "last_name",
            "email",
            "role",
            "governorate",
            "library",
        }
        unexpected_fields = set(self.initial_data) - allowed_input_fields
        if unexpected_fields:
            raise serializers.ValidationError(
                {field: "هذا الحقل غير مسموح به." for field in unexpected_fields}
            )

        request = self.context.get("request")
        actor = getattr(request, "user", None)
        role = attrs.get("role")
        governorate = attrs.get("governorate")
        library = attrs.get("library")

        if is_superuser(actor):
            allowed_roles = set(CustomUser.Role.values)
        elif actor.role == CustomUser.Role.MINISTRY_ADMIN:
            allowed_roles = {
                CustomUser.Role.GOVERNORATE_ADMIN,
                CustomUser.Role.LIBRARIAN,
                CustomUser.Role.READER,
            }
        elif actor.role == CustomUser.Role.GOVERNORATE_ADMIN:
            allowed_roles = {
                CustomUser.Role.LIBRARIAN,
                CustomUser.Role.READER,
            }
        elif actor.role == CustomUser.Role.LIBRARIAN:
            allowed_roles = {CustomUser.Role.READER}
        else:
            allowed_roles = set()

        if role not in allowed_roles:
            raise serializers.ValidationError(
                {"role": "لا تملك صلاحية إنشاء مستخدم بهذا الدور."}
            )

        if role == CustomUser.Role.MINISTRY_ADMIN:
            if governorate is not None or library is not None:
                raise serializers.ValidationError(
                    {"role": "مسؤول الوزارة لا يرتبط بمحافظة أو مكتبة."}
                )
            attrs["governorate"] = None
            attrs["library"] = None

        elif role == CustomUser.Role.GOVERNORATE_ADMIN:
            if governorate is None:
                raise serializers.ValidationError(
                    {"governorate": "يجب تحديد محافظة فعالة."}
                )
            if not is_active_governorate(governorate):
                raise serializers.ValidationError(
                    {"governorate": "لا يمكن إنشاء مستخدم ضمن محافظة غير فعالة."}
                )
            if library is not None:
                raise serializers.ValidationError(
                    {"library": "مسؤول المحافظة لا يرتبط بمكتبة."}
                )
            attrs["library"] = None

        elif role == CustomUser.Role.LIBRARIAN:
            if library is None:
                raise serializers.ValidationError(
                    {"library": "يجب تحديد مكتبة فعالة ضمن محافظة فعالة."}
                )
            if not library.is_active:
                raise serializers.ValidationError(
                    {"library": "لا يمكن إنشاء مستخدم ضمن مكتبة غير فعالة."}
                )
            if not library.governorate.is_active:
                raise serializers.ValidationError(
                    {"library": "لا يمكن إنشاء مستخدم ضمن محافظة غير فعالة."}
                )
            if (
                actor.role == CustomUser.Role.GOVERNORATE_ADMIN
                and not is_superuser(actor)
                and library.governorate_id != actor.governorate_id
            ):
                raise serializers.ValidationError(
                    {"library": "المكتبة المحددة لا تتبع لمحافظتك."}
                )
            if governorate is not None:
                raise serializers.ValidationError(
                    {"governorate": "أمين المكتبة يرتبط بالمكتبة فقط، ومحافظته تُعرف منها."}
                )
            attrs["governorate"] = None

        elif role == CustomUser.Role.READER:
            if library is not None:
                raise serializers.ValidationError(
                    {"library": "القارئ لا يرتبط بمكتبة."}
                )

            if not is_superuser(actor) and actor.role in {
                CustomUser.Role.GOVERNORATE_ADMIN,
                CustomUser.Role.LIBRARIAN,
            }:
                actor_governorate = get_effective_governorate(actor)
                if governorate is not None and (
                    actor_governorate is None or governorate.pk != actor_governorate.pk
                ):
                    raise serializers.ValidationError(
                        {"governorate": "لا يمكنك إنشاء قارئ خارج محافظتك."}
                    )
                governorate = actor_governorate

            if governorate is None:
                raise serializers.ValidationError(
                    {"governorate": "يجب تحديد محافظة فعالة للقارئ."}
                )
            if not is_active_governorate(governorate):
                raise serializers.ValidationError(
                    {"governorate": "لا يمكن إنشاء قارئ ضمن محافظة غير فعالة."}
                )
            attrs["governorate"] = governorate
            attrs["library"] = None

        password = attrs.get("password")
        candidate = User(**{key: value for key, value in attrs.items() if key != "password"})
        validate_password(password, user=candidate)
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["role"] = get_user_role_meta(instance)
        return representation


class ReaderSearchResultSerializer(serializers.ModelSerializer):
    """Minimal reader identity used when selecting a borrower."""

    full_name = serializers.SerializerMethodField()
    governorate = serializers.SerializerMethodField()

    def get_full_name(self, obj):
        return obj.get_full_name().strip() or obj.username

    @extend_schema_field(GovernorateSummarySchemaSerializer)
    def get_governorate(self, obj):
        return {"id": obj.governorate_id, "name": obj.governorate.name}

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "full_name", "governorate"]
        read_only_fields = fields
