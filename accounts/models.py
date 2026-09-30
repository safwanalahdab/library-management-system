from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User 

# Create your models here.

class UserProfile (models.Model) :
   GENDER_CHOICES = [
        ('male', 'ذكر'),
        ('fmale', 'أنثى'),
    
    ]
   
   user = models.OneToOneField(User,on_delete=models.CASCADE,related_name='profile')
   address = models.CharField(null=True,blank=True)
   phone = models.CharField(null=True,blank=True) 
   gender  = models.CharField(choices=GENDER_CHOICES, blank=True, null=True)
   age = models.PositiveBigIntegerField(blank=True,null=True) 
   borrowing_blocked = models.BooleanField(default=False)

   @receiver(post_save, sender=User)
   def create_user_profile(sender, instance, created, **kwargs):
    if created :
        UserProfile.objects.get_or_create(user=instance)

   
   
