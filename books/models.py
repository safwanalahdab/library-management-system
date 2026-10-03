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
