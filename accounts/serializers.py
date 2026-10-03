from rest_framework import serializers
from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.auth.password_validation import validate_password 
from django.db import IntegrityError, transaction
from .models import Governorate, Library
from .scopes import is_superuser
from drf_spectacular.utils import extend_schema_field
from Bookshelf.api_responses import InvalidCredentials, get_user_role_meta
from Bookshelf.openapi import RequesterRoleSchemaSerializer

User = get_user_model()


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()  # username OR email
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        identifier = attrs.get("identifier", "").strip()
        password = attrs.get("password")

        user = None
        if "@" in identifier:
            user = User.objects.filter(email__iexact=identifier).first()
        else:
            user = User.objects.filter(username__iexact=identifier).first()

        if not user:
            raise InvalidCredentials()

        auth_user = authenticate(username=user.username, password=password)
        if not auth_user:
            raise InvalidCredentials()

        attrs["user"] = auth_user
        return attrs


class CurrentUserSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    @extend_schema_field(RequesterRoleSchemaSerializer)
    def get_role(self, obj):
        return get_user_role_meta(obj)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "governorate",
            "library",
        ]
        read_only_fields = fields

class GovernorateOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Governorate
        fields = ["id", "name"]
        read_only_fields = fields


class RegisterSerializer(serializers.ModelSerializer):
    """Public self-registration. Always creates an unscoped-library READER."""

    allowed_input_fields = frozenset(
        {"username", "password", "password2", "email", "first_name", "last_name", "governorate"}
    )

    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, required=True)
    password2 = serializers.CharField(write_only=True, required=True)
    governorate = serializers.PrimaryKeyRelatedField(
        queryset=Governorate.objects.all(),
        error_messages={
            "required": "يجب اختيار محافظة.",
            "null": "يجب اختيار محافظة.",
            "does_not_exist": "المحافظة المحددة غير موجودة.",
            "incorrect_type": "معرّف المحافظة غير صالح.",
        },
    )

    class Meta:
        model = User
        fields = [
            "username",
            "password",
            "password2",
            "email",
            "first_name",
            "last_name",
            "governorate",
        ]
        extra_kwargs = {
            # Uniqueness is checked case-insensitively in validate_username.
            "username": {
                "required": True,
                "allow_blank": False,
                "validators": [User.username_validator],
            },
            "first_name": {"required": True, "allow_blank": False},
            "last_name": {"required": True, "allow_blank": False},
        }

    def validate(self, attrs):
        unexpected_fields = set(self.initial_data) - self.allowed_input_fields
        if unexpected_fields:
            raise serializers.ValidationError(
                {field: "هذا الحقل غير مسموح به." for field in sorted(unexpected_fields)}
            )

        if attrs["password"] != attrs["password2"]:
            raise serializers.ValidationError(
                {"password2": "كلمة السر غير متطابقة"}
            )

        candidate = User(
            username=attrs["username"],
            email=attrs["email"],
            first_name=attrs.get("first_name", ""),
            last_name=attrs.get("last_name", ""),
        )
        try:
            validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs

    def validate_username(self, value):
        value = value.strip().lower()
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("اسم المستخدم مستخدم مسبقاً.")
        return value

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("البريد الإلكتروني مستخدم مسبقاً.")
        return value

    def validate_governorate(self, value):
        if not value.is_active:
            raise serializers.ValidationError("لا يمكن التسجيل ضمن محافظة غير فعالة.")
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        validated_data.pop("password2")
        user = User(
            **validated_data,
            role=User.Role.READER,
            library=None,
        )
        user.set_password(password)
        try:
            with transaction.atomic():
                user.save()
        except IntegrityError:
            raise serializers.ValidationError(
                {"username": "تعذر إنشاء الحساب لأن بياناته مستخدمة مسبقاً."}
            )
        return user


class RegisteredUserSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    @extend_schema_field(RequesterRoleSchemaSerializer)
    def get_role(self, obj):
        return get_user_role_meta(obj)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "governorate",
            "library",
        ]
        read_only_fields = fields


class ResetPasswordSerilaizer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, required=True)
    new_password = serializers.CharField(write_only=True, required=True)
    new_password_confirm = serializers.CharField(write_only=True, required=True)
    
    def validate( self , attrs ) : 
        user = self.context['request'].user 
        if not user.check_password(attrs["current_password"]):
            raise serializers.ValidationError(
                {"current_password": "كلمة المرور الحالية غير صحيحة."}
            )
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError(
                {"new_password_confirm": "كلمتا المرور الجديدتان غير متطابقتين."}
            )
        validate_password(attrs["new_password"], user=user)
        return attrs
    
    def save( self , **kwargs ) :
        user = self.context['request'].user 
        user.set_password( self.validated_data['new_password'] ) 
        user.save()
        return user 


class AdminPasswordResetSerializer(serializers.Serializer):
    new_password = serializers.CharField(write_only=True, required=True)
    new_password_confirm = serializers.CharField(write_only=True, required=True)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError(
                {"new_password_confirm": "كلمتا المرور الجديدتان غير متطابقتين."}
            )
        validate_password(attrs["new_password"], user=self.context["user"])
        return attrs

    def save(self, **kwargs):
        user = self.context["user"]
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user

class UserDetailsSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['address', 'phone', 'gender', 'age', 'borrowing_blocked']
        read_only_fields = ['borrowing_blocked']

class ProfileSerializer( serializers.ModelSerializer ) : 
    borrowed_books_count =  serializers.IntegerField( read_only = True )
    overdue_books_count = serializers.IntegerField( read_only = True )
    profile = UserDetailsSerializer(source="*", required=False)
    borrowing_blocked = serializers.BooleanField(read_only=True)
    governorate = serializers.PrimaryKeyRelatedField(read_only=True)
    library = serializers.PrimaryKeyRelatedField(read_only=True)

    # Account, role and scope fields are managed by administrators only.
    protected_fields = frozenset(
        {
            "role",
            "governorate",
            "library",
            "is_staff",
            "is_superuser",
            "is_active",
            "groups",
            "user_permissions",
            "password",
            "last_login",
        }
    )
    # Scope fields are returned by GET, so echoing the current value back is accepted.
    echo_allowed_fields = frozenset({"governorate", "library"})

    class Meta : 
        model = User 
        fields = [ "username" , "email" , "first_name" , "last_name" , 
        "borrowed_books_count" ,"overdue_books_count"
        ,"borrowing_blocked","date_joined" ,"governorate","library","profile"] 
        read_only_fields = [
            "username",
            "borrowed_books_count",
            "overdue_books_count",
            "borrowing_blocked",
            "date_joined",
            "governorate",
            "library",
        ]

    def validate(self, attrs):
        rejected = {}
        for field in self.protected_fields & set(self.initial_data):
            if field in self.echo_allowed_fields and self.instance is not None:
                current = getattr(self.instance, f"{field}_id")
                if self.initial_data[field] in (current, None if current is None else str(current)):
                    continue
            rejected[field] = "لا يمكن تعديل هذا الحقل من الملف الشخصي."
        if rejected:
            raise serializers.ValidationError(rejected)
        return attrs
       
    def update(self, instance, validated_data):
        profile_fields = {"address", "phone", "gender", "age"}
        profile_data = {
            field: validated_data.pop(field)
            for field in profile_fields
            if field in validated_data
        }

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if profile_data:
            for attr, value in profile_data.items():
                setattr(instance, attr, value)
            instance.save(update_fields=profile_data.keys())

        return instance


class LibrarySerializer(serializers.ModelSerializer):
    """Library details. Scope and role checks for the target object live in the view."""

    governorate = serializers.PrimaryKeyRelatedField(
        queryset=Governorate.objects.all(),
        required=False,
    )
    governorate_name = serializers.CharField(source="governorate.name", read_only=True)

    writable_input_fields = frozenset({"name", "address", "phone", "email", "governorate"})

    class Meta:
        model = Library
        fields = [
            "id",
            "name",
            "governorate",
            "governorate_name",
            "address",
            "phone",
            "email",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_active", "created_at", "updated_at"]

    def to_internal_value(self, data):
        # Reject unexpected keys up front instead of silently dropping them.
        if hasattr(data, "keys"):
            errors = {}
            for field in data.keys():
                if field == "is_active":
                    errors[field] = "تُغيَّر حالة المكتبة عبر عمليتي التفعيل وإلغاء التفعيل فقط."
                elif field not in self.writable_input_fields:
                    errors[field] = "هذا الحقل غير مسموح به."
            if errors:
                raise serializers.ValidationError(errors)
        return super().to_internal_value(data)

    def _get_actor(self):
        request = self.context.get("request")
        return getattr(request, "user", None)

    def validate_governorate(self, value):
        if self.instance is not None:
            if value.pk != self.instance.governorate_id:
                raise serializers.ValidationError("لا يمكن تغيير محافظة المكتبة بعد إنشائها.")
            return value

        actor = self._get_actor()
        if (
            not is_superuser(actor)
            and actor.role == User.Role.GOVERNORATE_ADMIN
            and value.pk != actor.governorate_id
        ):
            raise serializers.ValidationError("لا يمكنك إنشاء مكتبة خارج محافظتك.")
        return value

    def validate(self, attrs):
        if self.instance is not None:
            # The governorate is fixed after creation; an identical value is a no-op.
            attrs.pop("governorate", None)
            return attrs

        actor = self._get_actor()
        if not is_superuser(actor) and actor.role == User.Role.GOVERNORATE_ADMIN:
            attrs["governorate"] = actor.governorate

        governorate = attrs.get("governorate")
        if governorate is None:
            raise serializers.ValidationError({"governorate": "يجب تحديد محافظة المكتبة."})
        if not governorate.is_active:
            raise serializers.ValidationError(
                {"governorate": "لا يمكن إنشاء مكتبة ضمن محافظة غير فعالة."}
            )
        return attrs
