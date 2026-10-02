from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .forms import CustomUserCreationForm
from .models import CustomUser, Governorate, Library


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm

    fieldsets = UserAdmin.fieldsets + (
        (
            "Organization and profile",
            {
                "fields": (
                    "role",
                    "governorate",
                    "library",
                    "address",
                    "phone",
                    "gender",
                    "age",
                    "borrowing_blocked",
                )
            },
        ),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "Organization and profile",
            {"fields": ("role", "governorate", "library")},
        ),
    )
    list_display = ("username", "email", "role", "is_staff", "is_active")
    list_filter = UserAdmin.list_filter + ("role", "governorate", "library")


admin.site.register(Governorate)
admin.site.register(Library)
