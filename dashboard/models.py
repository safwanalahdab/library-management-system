from django.db import models
from django.conf import settings

# Create your models here.

class LibraryActivity(models.Model):
    activity_name = models.CharField(max_length=120)
    title = models.CharField(max_length=200)
    image = models.ImageField(upload_to="activities/", null=True, blank=True)
    description = models.TextField()
    is_active = models.BooleanField(default=True)
    is_visible = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    @property
    def participants_count(self):
        return self.activity_registrations.count()


class ActivityRegistration(models.Model):
    activity = models.ForeignKey(
        LibraryActivity,
        on_delete=models.CASCADE,
        related_name="activity_registrations",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="activity_registrations",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["activity", "user"],
                name="unique_activity_registration",
            )
        ]

    def __str__(self):
        return f"{self.user} -> {self.activity}"
    
