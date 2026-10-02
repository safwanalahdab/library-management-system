from django.contrib.auth.forms import AdminUserCreationForm

from .models import CustomUser


class CustomUserCreationForm(AdminUserCreationForm):
    class Meta(AdminUserCreationForm.Meta):
        model = CustomUser
        fields = ("username", "role", "governorate", "library")
