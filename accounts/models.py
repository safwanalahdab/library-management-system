from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class Governorate(models.Model):
    name = models.CharField(max_length=150)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Library(models.Model):
    name = models.CharField(max_length=150)
    governorate = models.ForeignKey(
        Governorate,
        on_delete=models.PROTECT,
        related_name="libraries",
    )
    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class CustomUser(AbstractUser):
    class Role(models.TextChoices):
        MINISTRY_ADMIN = "MINISTRY_ADMIN", "Ministry admin"
        GOVERNORATE_ADMIN = "GOVERNORATE_ADMIN", "Governorate admin"
        LIBRARIAN = "LIBRARIAN", "Librarian"
        READER = "READER", "Reader"

    role = models.CharField(max_length=30, choices=Role.choices)
    governorate = models.ForeignKey(
        Governorate,
        on_delete=models.PROTECT,
        related_name="administrators",
        null=True,
        blank=True,
    )
    library = models.ForeignKey(
        Library,
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
    )
    address = models.CharField(max_length=255, null=True, blank=True)
    phone = models.CharField(max_length=30, null=True, blank=True)
    gender = models.CharField(
        max_length=10,
        choices=[("male", "ذكر"), ("female", "أنثى")],
        null=True,
        blank=True,
    )
    age = models.PositiveBigIntegerField(null=True, blank=True)
    borrowing_blocked = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(is_superuser=True)
                    | models.Q(role="MINISTRY_ADMIN", governorate__isnull=True, library__isnull=True)
                    | models.Q(role="GOVERNORATE_ADMIN", governorate__isnull=False, library__isnull=True)
                    | models.Q(role="LIBRARIAN", governorate__isnull=True, library__isnull=False)
                    | models.Q(role="READER", governorate__isnull=True, library__isnull=False)
                ),
                name="accounts_user_role_scope_valid",
            )
        ]

    @property
    def effective_governorate(self):
        if self.governorate_id:
            return self.governorate
        if self.library_id:
            return self.library.governorate
        return None

    def clean(self):
        super().clean()

        if self.is_superuser:
            return

        if self.role == self.Role.MINISTRY_ADMIN:
            valid = self.governorate_id is None and self.library_id is None
        elif self.role == self.Role.GOVERNORATE_ADMIN:
            valid = self.governorate_id is not None and self.library_id is None
        elif self.role in {self.Role.LIBRARIAN, self.Role.READER}:
            valid = self.governorate_id is None and self.library_id is not None
        else:
            valid = False

        if not valid:
            raise ValidationError(
                {"role": "The selected role does not match the required governorate and library scope."}
            )
