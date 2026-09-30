from rest_framework import serializers
from django.contrib.auth.models import User 
from books.serializers import BookSerializers 
from django.contrib.auth import authenticate, get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.validators import UniqueValidator 
from django.contrib.auth.password_validation import validate_password 
from books.models import Favorite_Book  
from .models import * 
from dashboard.models import * 

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
            raise serializers.ValidationError({"error": "اسم المستخدم/الإيميل غير موجود"})

        auth_user = authenticate(username=user.username, password=password)
        if not auth_user:
            raise serializers.ValidationError({"error": "اسم المستخدم أو كلمة المرور غير صحيحة"})

        attrs["user"] = auth_user
        return attrs

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


class ResetPasswordSerilaizer( serializers.Serializer ) :
    old_password = serializers.CharField( required = True )
    new_password = serializers.CharField( write_only = True , required = True  , validators = [ validate_password ] )
    confirm_password = serializers.CharField(  write_only = True , required = True ) 
    
    def validate( self , attrs ) : 
        user = self.context['request'].user 
        if not user.check_password( attrs['old_password'] ) : 
            raise serializers.ValidationError( { "error" : "كلمة المرور القديمة خاطئة"} )   
        if attrs['new_password'] != attrs['confirm_password'] : 
            raise serializers.ValidationError({"error" : "كلمة المرور غير متطابقة"}) 
        return attrs 
    
    def save( self , **kwargs ) :
        user = self.context['request'].user 
        user.set_password( self.validated_data['new_password'] ) 
        user.save()
        return user 

class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model  = UserProfile
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
    profile = UserProfileSerializer()
    activities = UserActivitySerializer(many=True, read_only=True, source="registered_activities")
    available_books = serializers.IntegerField( read_only = True )
    borrowing_blocked = serializers.BooleanField(source="profile.borrowing_blocked", read_only=True)


    class Meta : 
        model = User 
        fields = [ "username" , "email" , "first_name" , "last_name" , 
        "borrowed_books_count" ,"overdue_books_count","favorites_count","available_books"
        ,"borrowing_blocked","date_joined" ,"profile","tier","activities"] 
        read_only_fields = ['date_joined'] 
       
    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', {})

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if profile_data:
            profile = instance.profile
            for attr, value in profile_data.items():
                setattr(profile, attr, value)
            profile.save()

        return instance
    
class FavoriteBookSerializer ( serializers.ModelSerializer ) :
    book = BookSerializers( read_only = True ) 

    class Meta : 
        model = Favorite_Book 
        fields = ['id','book','created_at'] 
                 
