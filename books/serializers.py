"""
serializers to convert from frontend to JSON 

"""
from rest_framework import serializers 
from django.contrib.auth import get_user_model 
from django.db.models import Avg
from .models import *

user = get_user_model() 

class AuthorSerializers ( serializers.ModelSerializer ) :

    class Meta : 
        model = Author
        fields = "__all__" 

class CategorySerializers (serializers.ModelSerializer ) : 

    class Meta : 
        model = Category 
        fields = "__all__" 

class BookSerializers ( serializers.ModelSerializer ) :
    author = AuthorSerializers( read_only = True ) 
    category = CategorySerializers( read_only = True , allow_null=True ) 
    image = serializers.ImageField( use_url = True , allow_null = True , required=False) 
    is_like = serializers.SerializerMethodField()
    available_books = serializers.SerializerMethodField()
    average_rating = serializers.SerializerMethodField()
    rating_count = serializers.SerializerMethodField()
    #user_rating = serializers.SerializerMethodField()
    author_id = serializers.PrimaryKeyRelatedField(
        source='author',              # يربطه بحقل author في الموديل
        queryset=Author.objects.all(),
        write_only=True,
        required=False,
    )
    category_id = serializers.PrimaryKeyRelatedField(
        source='category',            # يربطه بحقل category في الموديل
        queryset=Category.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )

    def get_is_like(self,obj) :
        request = self.context.get("request")
        if not request or not request.user.is_authenticated :
            return False 
        return Favorite_Book.objects.filter(
            book=obj,
            user=request.user,
        ).exists()

    def get_available_books(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return 0

        if not hasattr(self, "_available_books_for_user"):
            self._available_books_for_user = self._calculate_available_books(request.user)

        return self._available_books_for_user

    def _calculate_available_books(self, user):
        if user.borrowing_blocked:
            return -1

        read_books_count = (
            BorrowedBook.objects.filter(borrower=user, is_returned=True)
            .values("book_id")
            .distinct()
            .count()
        )
        summaries_count = (
            BookSummary.objects.filter(user=user)
            .values("book_id")
            .distinct()
            .count()
        )

        if read_books_count >= 10 and summaries_count >= 10:
            max_allowed = 3
        elif read_books_count >= 5 and summaries_count >= 5:
            max_allowed = 2
        else:
            max_allowed = 1

        active_count = BorrowedBook.objects.filter(
            borrower=user,
            is_returned=False,
        ).count()

        return max(max_allowed - active_count, 0)

    def get_average_rating(self, obj):
        average = obj.ratings.aggregate(average=Avg("rating"))["average"]
        if average is None:
            return None
        return round(average, 1)

    def get_rating_count(self, obj):
        return obj.ratings.count()

    """
    def get_user_rating(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return None

        rating = BookRating.objects.filter(book=obj, user=request.user).first()
        if not rating:
            return None
        return rating.rating
     """

    class Meta : 
        model = Book 
        fields = ['id','title','author','author_id',
        'image','category','is_like','available_books','average_rating','rating_count','category_id','description','possition','total_copies','available_copies','count_borrowed','is_avaiable','is_archived','pages','publication_year' , 'isbn' ]  
        read_only_fields = ["id"] 


class BookRatingSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    book = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = BookRating
        fields = ["id", "user", "book", "rating", "created_at", "updated_at"]
        read_only_fields = ["id", "user", "book", "created_at", "updated_at"]

    def validate_rating(self, value):
        if value < 1 or value > 5:
            raise serializers.ValidationError("rating must be an integer between 1 and 5.")
        return value


class BookReservationSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    book = serializers.PrimaryKeyRelatedField(read_only=True)
    book_title = serializers.CharField(source="book.title", read_only=True)
    queue_position = serializers.SerializerMethodField()

    class Meta:
        model = BookReservation
        fields = [
            "id",
            "user",
            "username",
            "book",
            "book_title",
            "reserved_at",
            "queue_position",
        ]
        read_only_fields = [
            "id",
            "user",
            "username",
            "book",
            "book_title",
            "reserved_at",
            "queue_position",
        ]

    def get_queue_position(self, obj):
        return BookReservation.objects.filter(
            book=obj.book,
            reserved_at__lte=obj.reserved_at,
        ).count()

class BarrowBookSerilaizers ( serializers.ModelSerializer ) : 
     book = BookSerializers( read_only = True ) 
     borrower = serializers.StringRelatedField( read_only = True )

     late_day = serializers.SerializerMethodField()

     class Meta : 
         model = BorrowedBook 
         fields = ['id','book','borrower','borrow_date','return_request','return_date','is_returned','notes','due_date','late_day','return_request_date','extension_request','extension_request_date','is_extended']
    
     def get_late_day(self, obj):
        return obj.late_day 

class BookSummarySerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    book = serializers.PrimaryKeyRelatedField(read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)

    class Meta:
        model = BookSummary
        fields = [
            "id",
            "book",
            "user",
            "username",
            "first_name",
            "last_name",
            "summary",
            "created_at",
            "updated_at",
        ]
        
        read_only_fields = [
            "id",
            "book",
            "user",
            "username",
            "first_name",
            "last_name",
            "created_at",
            "updated_at",
        ]

class QuoteSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)
    writer_full_name = serializers.ReadOnlyField()
    likes_count = serializers.IntegerField(read_only=True)
    is_liked = serializers.SerializerMethodField()
    liked_by_full_names = serializers.SerializerMethodField()
    
    def get_liked_by_full_names(self, obj):
        return [
            like.user.get_full_name().strip() or like.user.username
            for like in obj.likes.select_related("user").all()
        ]
    
    def get_is_liked(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        return obj.likes.filter(user=request.user).exists()
    
    class Meta:
        model = Quote
        fields = [
            "id",
            "user",
            "username",
            "first_name",
            "last_name",
            "writer_full_name",
            "content",
            "status",
            "likes_count",
            "liked_by_full_names",
            "is_liked",
            "approved_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "username",
            "first_name",
            "last_name",
            "writer_full_name",
            "status",
            "likes_count",
            "liked_by_full_names",
            "approved_at",
            "created_at",
            "updated_at",
        ]


class QuoteAdminSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)
    writer_full_name = serializers.ReadOnlyField()
    likes_count = serializers.IntegerField(read_only=True)
    liked_by_full_names = serializers.SerializerMethodField()
    approved_by_username = serializers.CharField(source="approved_by.username", read_only=True)
  
    def get_liked_by_full_names(self, obj):
        return [
            like.user.get_full_name().strip() or like.user.username
            for like in obj.likes.select_related("user").all()
        ]
    
    class Meta:
        model = Quote
        fields = [
            "id",
            "user",
            "username",
            "first_name",
            "last_name",
            "writer_full_name",
            "content",
            "status",
            "likes_count",
            "liked_by_full_names",
            "approved_at",
            "approved_by",
            "approved_by_username",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "username",
            "first_name",
            "last_name",
            "writer_full_name",
            "likes_count",
            "liked_by_full_names",
            "approved_at",
            "approved_by",
            "approved_by_username",
            "created_at",
            "updated_at",
        ]
