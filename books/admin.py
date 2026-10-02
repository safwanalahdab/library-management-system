from django.contrib import admin
from .models import Author, Book, BorrowedBook, Category

# Register your models here.

admin.site.register( Book )
admin.site.register( Author )
admin.site.register( Category )
admin.site.register( BorrowedBook )
