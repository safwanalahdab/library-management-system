from rest_framework import serializers
from django.contrib.auth import get_user_model
from accounts.serializers import ProfileSerializer , UserProfileSerializer
from .models import * 

User = get_user_model() 


class UserAdminSeri( serializers.ModelSerializer ) :
    borrowed_books_count = serializers.IntegerField(read_only=True)
    profile = UserProfileSerializer()
    borrowing_blocked = serializers.BooleanField(source="profile.borrowing_blocked", read_only=True)

    class Meta : 
        model = User 
        fields = ['id','username','email','first_name','last_name','borrowed_books_count'
        ,'borrowing_blocked','profile','date_joined']
        read_only_fields = ['borrowed_books_count']
        

class ActivityParticipantSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name"]


class LibraryActivitySerializer(serializers.ModelSerializer):
    image = serializers.ImageField(use_url=True, allow_null=True, required=False)
    participants_count = serializers.IntegerField(read_only=True)
    is_registered = serializers.SerializerMethodField()
    
    def get_is_registered(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False

        return ActivityRegistration.objects.filter(
            activity=obj,
            user=request.user,
        ).exists()
    
    class Meta:
        model = LibraryActivity
        fields = [
            "id",
            "activity_name",
            "title",
            "image",
            "description",
            "is_active",
            "is_visible",
            "participants_count",
            "is_registered",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "participants_count", "created_at", "updated_at"]


class ActivityParticipantsListSerializer(serializers.ModelSerializer):
    user = ActivityParticipantSerializer(read_only=True)

    class Meta:
        model = ActivityRegistration
        fields = ["id", "user", "created_at"]

