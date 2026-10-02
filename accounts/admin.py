from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .forms import CustomUserCreationForm
from .models import CustomUser, Governorate, Library


ROLE_SCOPE_HELP = (
    "MINISTRY_ADMIN: no governorate or library. "
    "GOVERNORATE_ADMIN: governorate only. "
    "LIBRARIAN: library only (governorate comes from the library). "
    "READER: governorate only, no library."
)


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm

    fieldsets = UserAdmin.fieldsets + (
        (
            "Organization and profile",
            {
                "description": ROLE_SCOPE_HELP,
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
            {"description": ROLE_SCOPE_HELP, "fields": ("role", "governorate", "library")},
        ),
    )
    list_display = ("username", "email", "role", "governorate", "library", "is_staff", "is_active")
    list_select_related = ("governorate", "library")
    list_filter = UserAdmin.list_filter + ("role", "governorate", "library")


admin.site.register(Governorate)
admin.site.register(Library)
