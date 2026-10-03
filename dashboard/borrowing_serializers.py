"""Serializers for the borrow request and borrow APIs.

Read serializers are output-only. Input serializers validate request shape
only: they accept IDs, reject every other key, and leave lookups, scope and
business rules to the views and books.borrowing_services.
"""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from books.models import Borrow, BorrowRequest
from books.serializers import RejectUnexpectedInputMixin

from .query_params import MAX_FILTER_ID


def _id_field(label):
    message = f"يجب أن يكون معرّف {label} رقماً صحيحاً موجباً."
    return serializers.IntegerField(
        min_value=1,
        max_value=MAX_FILTER_ID,
        error_messages={
            "required": f"يجب تحديد {label}.",
            "null": f"يجب تحديد {label}.",
            "invalid": message,
            "min_value": message,
            "max_value": message,
            "max_string_length": message,
        },
    )


class _BorrowingReadFields(serializers.Serializer):
    """Reader, book and organization fields shared by both read serializers."""

    reader_username = serializers.CharField(source="reader.username", read_only=True)
    reader_first_name = serializers.CharField(source="reader.first_name", read_only=True)
    reader_last_name = serializers.CharField(source="reader.last_name", read_only=True)
    book_title = serializers.CharField(source="book.title", read_only=True)
    library = serializers.IntegerField(source="book.library_id", read_only=True)
    library_name = serializers.CharField(source="book.library.name", read_only=True)
    governorate = serializers.IntegerField(source="book.library.governorate_id", read_only=True)
    governorate_name = serializers.CharField(
        source="book.library.governorate.name", read_only=True
    )


READ_IDENTITY_FIELDS = [
    "id",
    "reader",
    "reader_username",
    "reader_first_name",
    "reader_last_name",
    "book",
    "book_title",
    "library",
    "library_name",
    "governorate",
    "governorate_name",
]


class BorrowRequestReadSerializer(_BorrowingReadFields, serializers.ModelSerializer):
    decided_by_username = serializers.CharField(
        source="decided_by.username", read_only=True, allow_null=True
    )

    class Meta:
        model = BorrowRequest
        fields = READ_IDENTITY_FIELDS + [
            "status",
            "created_at",
            "decided_at",
            "decided_by",
            "decided_by_username",
            "rejection_reason",
        ]
        read_only_fields = fields


class BorrowReadSerializer(_BorrowingReadFields, serializers.ModelSerializer):
    created_by_username = serializers.CharField(
        source="created_by.username", read_only=True, allow_null=True
    )
    returned_by_username = serializers.CharField(
        source="returned_by.username", read_only=True, allow_null=True
    )
    source = serializers.SerializerMethodField()

    class Meta:
        model = Borrow
        fields = READ_IDENTITY_FIELDS + [
            "request",
            "source",
            "status",
            "borrowed_at",
            "returned_at",
            "created_by",
            "created_by_username",
            "returned_by",
            "returned_by_username",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.ChoiceField(choices=["REQUEST", "DIRECT"]))
    def get_source(self, obj):
        """Derived only: REQUEST when created by approving a request, else DIRECT."""
        return "REQUEST" if obj.request_id else "DIRECT"


class BorrowRequestRejectSerializer(RejectUnexpectedInputMixin, serializers.Serializer):
    writable_input_fields = frozenset({"reason"})
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
        error_messages={
            "null": "يجب أن يكون سبب الرفض نصاً.",
            "invalid": "يجب أن يكون سبب الرفض نصاً.",
        },
    )


class DirectBorrowCreateSerializer(RejectUnexpectedInputMixin, serializers.Serializer):
    """POST /dashboard/borrows/. The staff member is always request.user."""

    writable_input_fields = frozenset({"reader_id", "book_id"})
    reader_id = _id_field("القارئ")
    book_id = _id_field("الكتاب")


class EmptyBodySerializer(RejectUnexpectedInputMixin, serializers.Serializer):
    """Reader request creation, approve and return take no input; any key is rejected."""

    writable_input_fields = frozenset()


class BorrowRequestApprovalSerializer(serializers.Serializer):
    """Response data of approve: the decided request and the borrow it opened."""

    request = BorrowRequestReadSerializer()
    borrow = BorrowReadSerializer()
