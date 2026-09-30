from django.contrib import admin
from .models import *

# Register your models here.

admin.site.register( Book ) 
admin.site.register( Author ) 
admin.site.register( Category ) 
admin.site.register( BorrowedBook ) 
admin.site.register( Favorite_Book ) 
admin.site.register( BookRating ) 
admin.site.register( BookSummary ) 
admin.site.register( Quote ) 
admin.site.register( QuoteLike ) 


@admin.register(BookReservation)
class BookReservationAdmin(admin.ModelAdmin):
    list_display = ("user", "book", "reserved_at", "queue_position")
    list_filter = ("reserved_at",)
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "book__title",
    )
    readonly_fields = ("reserved_at",)

    def queue_position(self, obj):
        return BookReservation.objects.filter(
            book=obj.book,
            reserved_at__lte=obj.reserved_at,
        ).count()


