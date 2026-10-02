from rest_framework import serializers
from books.serializers import BookSerializers 
from django.contrib.auth import authenticate, get_user_model
from rest_framework.validators import UniqueValidator 
from django.contrib.auth.password_validation import validate_password 
from books.models import Favorite_Book  
from .models import * 
from dashboard.models import * 
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

class RegisterSerializer( serializers.ModelSerializer ) : 
    
    email = serializers.EmailField( required = True , validators = [ UniqueValidator( queryset = User.objects.all() )] ) 
    password = serializers.CharField( write_only = True , required = True , validators = [ validate_password ] ) 
    password2 = serializers.CharField( write_only = True , required = True ) 

    class Meta : 
        model = User 
        fields = ['username' , 'password' , 'password2' , 'email' , 'first_name' , 'last_name' ]
        extra_kwargs = {
            'username' : {'required' : True ,
                          'allow_blank': False, } , 
            'first_name' : { 'required' : True , 
                            'allow_blank': False, } , 
            'last_name' : { 'required' : True , 
                           'allow_blank': False, } ,
        } 

    def validate( self , attrs ) :
        if "username" in attrs and attrs["username"]:
         attrs["username"] = attrs["username"].strip().lower()

        if "email" in attrs and attrs["email"]:
            attrs["email"] = attrs["email"].strip().lower()

        if attrs['password'] != attrs['password2'] : 
            raise serializers.ValidationError( {"password" : "كلمة السر غير متطابقة"} ) 
        return attrs 
    
    def create( self , validated_data ) :

        user = User.objects.create( 
            username = validated_data['username'] , 
            email = validated_data['email'] ,
            first_name = validated_data.get('first_name','' ) ,
            last_name = validated_data.get('last_name' , '' ) ,
        )

        user.set_password(validated_data['password'])
        user.save() 

        return user 


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

class UserActivitySerializer(serializers.ModelSerializer):
    activity_id = serializers.IntegerField(source="activity.id", read_only=True)
    activity_name = serializers.CharField(source="activity.activity_name", read_only=True)
    title = serializers.CharField(source="activity.title", read_only=True)
    description = serializers.CharField(source="activity.description", read_only=True)
    image = serializers.ImageField(source="activity.image", read_only=True)
    is_active = serializers.BooleanField(source="activity.is_active", read_only=True)
    is_visible = serializers.BooleanField(source="activity.is_visible", read_only=True)
    registered_at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = ActivityRegistration
        fields = [
            "id",
            "activity_id",
            "activity_name",
            "title",
            "description",
            "image",
            "is_active",
            "is_visible",
            "registered_at",
        ]

class ProfileSerializer( serializers.ModelSerializer ) : 
    borrowed_books_count =  serializers.IntegerField( read_only = True )
    overdue_books_count = serializers.IntegerField( read_only = True )
    favorites_count = serializers.IntegerField( read_only = True )
    tier = serializers.CharField(read_only=True)
    profile = UserDetailsSerializer(source="*", required=False)
    activities = UserActivitySerializer(many=True, read_only=True, source="registered_activities")
    available_books = serializers.IntegerField( read_only = True )
    borrowing_blocked = serializers.BooleanField(read_only=True)


    class Meta : 
        model = User 
        fields = [ "username" , "email" , "first_name" , "last_name" , 
        "borrowed_books_count" ,"overdue_books_count","favorites_count","available_books"
        ,"borrowing_blocked","date_joined" ,"profile","tier","activities"] 
        read_only_fields = [
            "username",
            "borrowed_books_count",
            "overdue_books_count",
            "favorites_count",
            "available_books",
            "borrowing_blocked",
            "date_joined",
            "tier",
            "activities",
        ]
       
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
    
class FavoriteBookSerializer ( serializers.ModelSerializer ) :
    book = BookSerializers( read_only = True ) 

    class Meta : 
        model = Favorite_Book 
        fields = ['id','book','created_at'] 
                 
