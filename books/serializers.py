"""
serializers to convert from frontend to JSON 

"""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers 
from accounts.scopes import is_active_library, is_superuser, libraries_accessible_to
from accounts.models import CustomUser
from .models import Author, Book, BorrowedBook, Category

def catalog_name_field(required_message):
    """Required, non-blank name; surrounding whitespace is trimmed before saving."""
    return serializers.CharField(
        max_length=100,
        trim_whitespace=True,
        error_messages={
            "required": required_message,
            "null": required_message,
            "blank": required_message,
            "invalid": required_message,
            "max_length": "يجب ألا يتجاوز الاسم 100 حرف.",
        },
    )


class AuthorSerializers ( serializers.ModelSerializer ) :
    name = catalog_name_field("يجب إدخال اسم المؤلف.")

    class Meta :
        model = Author
        fields = "__all__"

class CategorySerializers (serializers.ModelSerializer ) :
    name = catalog_name_field("يجب إدخال اسم التصنيف.")

    class Meta :
        model = Category
        fields = "__all__"

class BookSerializers ( serializers.ModelSerializer ) :
    author = AuthorSerializers( read_only = True ) 
    category = CategorySerializers( read_only = True , allow_null=True ) 
    image = serializers.ImageField( use_url = True , allow_null = True , required=False) 
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

    class Meta : 
        model = Book 
        fields = ['id','title','author','author_id',
        'image','category','category_id','description','possition','total_copies','available_copies','count_borrowed','is_avaiable','is_archived','pages','publication_year' , 'isbn' ]  
        read_only_fields = ["id"] 


class RejectUnexpectedInputMixin:
    """Reject unknown and response-only keys instead of silently dropping them."""

    writable_input_fields = frozenset()

    def to_internal_value(self, data):
        if hasattr(data, "keys"):
            unexpected = set(data.keys()) - self.writable_input_fields
            if unexpected:
                raise serializers.ValidationError(
                    {field: "هذا الحقل غير مسموح به." for field in sorted(unexpected)}
                )
        return super().to_internal_value(data)


BOOK_DETAIL_INPUT_FIELDS = frozenset(
    {
        "title",
        "description",
        "image",
        "author_id",
        "category_id",
        "possition",
        "total_copies",
        "pages",
        "publication_year",
        "isbn",
    }
)

TOTAL_COPIES_ERROR_MESSAGES = {
    "required": "يجب تحديد عدد النسخ الكلي.",
    "null": "يجب تحديد عدد النسخ الكلي.",
    "invalid": "يجب أن يكون عدد النسخ الكلي رقماً صحيحاً.",
    "min_value": "لا يمكن أن يكون عدد النسخ الكلي سالباً.",
}


class BookReadSerializer(BookSerializers):
    """Read-only serializer for GET /dashboard/books/ and /dashboard/books/{id}/.

    Adds the book's organizational placement. Never used for input; PATCH uses
    BookUpdateSerializer, which keeps `library` read-only.
    """

    library = serializers.PrimaryKeyRelatedField(read_only=True)
    library_name = serializers.CharField(source="library.name", read_only=True)
    governorate = serializers.IntegerField(source="library.governorate_id", read_only=True)
    governorate_name = serializers.CharField(source="library.governorate.name", read_only=True)

    class Meta(BookSerializers.Meta):
        fields = BookSerializers.Meta.fields + [
            "library",
            "library_name",
            "governorate",
            "governorate_name",
        ]


class BarrowBookSerilaizers ( serializers.ModelSerializer ) :
     book = BookSerializers( read_only = True ) 
     borrower = serializers.StringRelatedField( read_only = True )

     late_day = serializers.SerializerMethodField()

     class Meta : 
         model = BorrowedBook 
         fields = ['id','book','borrower','borrow_date','return_request','return_date','is_returned','notes','due_date','late_day','return_request_date','extension_request','extension_request_date','is_extended']
    
     def get_late_day(self, obj):
        return obj.late_day


class ScopedLibraryField(serializers.PrimaryKeyRelatedField):
    """Library choices limited to the requester's scope.

    Out-of-scope and missing IDs share one error, so the response never
    reveals whether a library outside the requester's scope exists.
    """

    default_error_messages = {
        "null": "يجب تحديد مكتبة الكتاب.",
        "does_not_exist": "المكتبة المحددة غير موجودة أو خارج نطاقك.",
        "incorrect_type": "يجب أن يكون معرّف المكتبة رقماً صحيحاً.",
    }

    def get_queryset(self):
        request = self.context.get("request")
        return libraries_accessible_to(getattr(request, "user", None)).select_related(
            "governorate"
        )


class BookCreateSerializer(RejectUnexpectedInputMixin, BookSerializers):
    """Create-only serializer for POST /dashboard/books/.

    Kept separate from BookSerializers so list, retrieve and update responses
    stay unchanged and `library` cannot be changed on existing books.
    """

    library = ScopedLibraryField(required=False)
    library_name = serializers.CharField(source="library.name", read_only=True)
    governorate = serializers.IntegerField(source="library.governorate_id", read_only=True)
    governorate_name = serializers.CharField(source="library.governorate.name", read_only=True)
    # The client sends total_copies; 0 is allowed. available_copies and
    # is_avaiable are read-only and derived from it in Book.save() on create.
    total_copies = serializers.IntegerField(
        min_value=0,
        max_value=2147483647,
        error_messages=TOTAL_COPIES_ERROR_MESSAGES,
    )

    writable_input_fields = BOOK_DETAIL_INPUT_FIELDS | {"library"}

    class Meta(BookSerializers.Meta):
        fields = BookSerializers.Meta.fields + [
            "library",
            "library_name",
            "governorate",
            "governorate_name",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "available_copies",
            "count_borrowed",
            "is_avaiable",
            "is_archived",
            "created_at",
        ]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context.get("request")
        actor = getattr(request, "user", None)

        library = attrs.get("library")
        if library is None:
            if not is_superuser(actor) and actor.role == CustomUser.Role.LIBRARIAN:
                library = actor.library
            else:
                raise serializers.ValidationError({"library": "يجب تحديد مكتبة الكتاب."})

        if not is_active_library(library):
            raise serializers.ValidationError(
                {"library": "لا يمكن إضافة كتب إلى مكتبة غير مفعّلة أو تابعة لمحافظة غير مفعّلة."}
            )

        attrs["library"] = library
        return attrs


class BookUpdateSerializer(RejectUnexpectedInputMixin, BookReadSerializer):
    """PATCH-only serializer for /dashboard/books/{id}/.

    Book details are editable; `library` is fixed after creation, and
    available_copies, is_avaiable, count_borrowed and is_archived stay
    server-managed. The response keeps the read contract, including the
    organizational fields.
    """

    total_copies = serializers.IntegerField(
        min_value=0,
        max_value=2147483647,
        error_messages=TOTAL_COPIES_ERROR_MESSAGES,
    )

    writable_input_fields = BOOK_DETAIL_INPUT_FIELDS

    class Meta(BookReadSerializer.Meta):
        read_only_fields = [
            "id",
            "available_copies",
            "count_borrowed",
            "is_avaiable",
            "is_archived",
        ]

    def update(self, instance, validated_data):
        # Lock the row so the borrowed-copies check in Book.save() and the
        # write see the same available_copies, and apply the change to the
        # fresh row so concurrent borrow counters are not overwritten.
        with transaction.atomic():
            locked = Book.objects.select_for_update().get(pk=instance.pk)
            try:
                return super().update(locked, validated_data)
            except DjangoValidationError as exc:
                raise serializers.ValidationError({"total_copies": exc.messages})
