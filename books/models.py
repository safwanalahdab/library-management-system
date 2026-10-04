from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from django.core.exceptions import ValidationError

# Create your models here.

class Author ( models.Model ) :
    name = models.CharField( max_length = 100 ) 
    
    def __str__( self ) :
        return self.name 
    
class Category ( models.Model ) :
    name = models.CharField( max_length = 100 ) 
    
    def __str__( self ) :
      return self.name


class Book ( models.Model ) : 
    title = models.CharField( max_length = 100 ) 
    description = models.TextField()
    image = models.ImageField( upload_to = 'books/' , null = True , blank = True )
    author = models.ForeignKey( Author , on_delete = models.SET_NULL , related_name = 'author' , null = True ) 
    category = models.ForeignKey( Category , on_delete = models.SET_NULL , related_name = 'category' , null = True ) 
    total_copies = models.PositiveIntegerField( default = 1 ) 
    available_copies = models.PositiveIntegerField( default = 1 ) 
    count_borrowed = models.PositiveBigIntegerField( default = 0 ) #Number of times the book was borrowed 
    created_at = models.DateTimeField( auto_now_add = True )
    is_avaiable = models.BooleanField( default = True ) 
    possition = models.CharField( max_length = 10 , null = True ) 
    is_archived = models.BooleanField( default = False ) 
    pages = models.IntegerField( default = 0 )
    publication_year = models.IntegerField( null = True  ) 
    isbn = models.CharField( null = True , max_length = 15 )
    # Each book record belongs to one library; its governorate comes from library.governorate.
    library = models.ForeignKey(
        "accounts.Library",
        on_delete=models.PROTECT,
        related_name="books",
    )

    def save(self, *args, **kwargs):
     
     skip_recalc = kwargs.pop("skip_recalc", False)
    # إذا الكتاب جديد (ما له PK لسا)
     if self.pk is None:
        self.available_copies = self.total_copies
        self.is_avaiable = self.available_copies > 0
        return super().save(*args, **kwargs)
     
     if skip_recalc:
       return super().save(*args, **kwargs)
    
     old = Book.objects.only("total_copies","available_copies").get( pk = self.pk ) 
     old_total = old.total_copies 
     old_available_copies = old.available_copies 
     
     borrowed_now  = max( (old_total - old_available_copies) , 0 )  

     if self.total_copies < borrowed_now : 
        raise ValidationError("لا يمكنك التعديل لانه عدد النسخ المستعارة حاليا اكبر من عدد النسخ الكلي")
     
     self.available_copies = self.total_copies - borrowed_now
     self.is_avaiable = self.available_copies > 0 

     return super().save(*args, **kwargs)    
    """
    this function to boorow 
    """
    def borrow_book( self ) :
        if self.available_copies == 0 :
            return False 
        self.available_copies -= 1 
        self.is_avaiable = self.available_copies > 0 
        self.count_borrowed += 1 
        self.save(skip_recalc=True, update_fields=['available_copies', 'is_avaiable', 'count_borrowed'])

        return True 
    
    """
    this function to return coppy 
    """

    def return_copy( self ) :
        self.available_copies += 1 
        self.is_avaiable = True 
        self.save(skip_recalc=True, update_fields=['available_copies', 'is_avaiable']) 

    def __str__( self ) : 
        return self.title 
    
class FavoriteBook(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="favorite_books",
    )
    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name="favorites",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "book"],
                name="books_favoritebook_unique_user_book",
            ),
        ]

    def __str__(self):
        return f"{self.user_id} → {self.book_id}"


class BorrowedBook ( models.Model ) :
     book = models.ForeignKey( Book , on_delete = models.CASCADE , related_name = "borrowed_book" ) 
     borrower = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete = models.CASCADE , related_name = "borrower_book") 
     borrow_date = models.DateField( auto_now_add = True ) 
     return_date = models.DateField( blank = True , null = True )
     is_returned = models.BooleanField( default = False ) 
     notes = models.TextField( blank = True , null = True , default = "" )  
     return_request = models.BooleanField( default = False ) 
     return_request_date =  models.DateField( blank = True , null = True )
     extension_request = models.BooleanField( default = False )
     extension_request_date = models.DateField( blank = True , null = True )
     is_extended = models.BooleanField( default = False )
     due_date = models.DateField( null = True , blank = True ) 
    # late_day = models.IntegerField( default = 0 ) 
     def __str__( self ) : 
         return self.book.title 
     
     def save( self, *args , **kwargs ) : 
        
        if not self.borrow_date:
            self.borrow_date = timezone.now().date()
        if not self.due_date :
            self.due_date = self.borrow_date + timedelta( days = 10 )   
        super().save(*args, **kwargs) 
        
     @property
     def late_day( self ) : 
       date = self.due_date or self.borrow_date + timedelta( days = 10 ) 
       today = timezone.now().date()
       if today <= date : 
          return 0 
       else : 
          return ( ( today - date ).days ) 
       
    #Returns the number of days this borrowing is late.


# New borrowing system. It lives beside the legacy BorrowedBook until data is
# migrated. Workflow, quantities and permissions belong to a service layer;
# these models only store state and enforce uniqueness at the database level.
#
# History is kept: users and books are deactivated/archived instead of deleted,
# so every relation uses PROTECT and a delete that would erase history fails.


class BorrowRequest(models.Model):
    """A reader's request to borrow a book; library/governorate come from book."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "قيد المراجعة"
        APPROVED = "APPROVED", "مقبول"
        REJECTED = "REJECTED", "مرفوض"

    reader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="borrow_requests",
    )
    book = models.ForeignKey(
        Book,
        on_delete=models.PROTECT,
        related_name="borrow_requests",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="decided_borrow_requests",
    )
    rejection_reason = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["reader", "book"],
                condition=models.Q(status="PENDING"),
                name="books_borrowrequest_one_pending_per_reader_book",
            ),
        ]

    def __str__(self):
        return f"{self.reader_id} → {self.book_id} ({self.status})"


class Borrow(models.Model):
    """A book actually handed to a reader, from an approved request or directly."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "نشطة"
        RETURNED = "RETURNED", "مُرجعة"

    reader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="borrows",
    )
    book = models.ForeignKey(
        Book,
        on_delete=models.PROTECT,
        related_name="borrows",
    )
    # Null for a direct borrow. One-to-one so a request yields at most one borrow.
    request = models.OneToOneField(
        BorrowRequest,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="borrow",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    borrowed_at = models.DateTimeField(auto_now_add=True)
    returned_at = models.DateTimeField(null=True, blank=True)
    # The service layer always sets the staff member; null is kept only for
    # borrows migrated later from BorrowedBook, which never recorded one.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="created_borrows",
    )
    returned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="returned_borrows",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["reader", "book"],
                condition=models.Q(status="ACTIVE"),
                name="books_borrow_one_active_per_reader_book",
            ),
        ]

    def __str__(self):
        return f"{self.reader_id} → {self.book_id} ({self.status})"
