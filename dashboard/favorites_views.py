"""Reader-only endpoints for managing and listing favorite books."""

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import generics, serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination

from accounts.permissions import IsReaderRole
from accounts.scopes import books_accessible_to
from Bookshelf.api_responses import ArabicApiResponseMixin
from Bookshelf.openapi import error_response, success_envelope
from books.models import Book, FavoriteBook
from books.serializers import BookReadSerializer

from .borrowing_serializers import EmptyBodySerializer


BOOK_NOT_FOUND = "الكتاب غير موجود."


class FavoriteBookPagination(PageNumberPagination):
    """Keep favorite-book pages aligned with the dashboard book list."""

    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 10


FAVORITE_BOOK_PAGE_SCHEMA = inline_serializer(
    name="FavoriteBookPage",
    fields={
        "count": serializers.IntegerField(),
        "next": serializers.URLField(allow_null=True),
        "previous": serializers.URLField(allow_null=True),
        "results": BookReadSerializer(many=True),
    },
)

COMMON_ERRORS = {
    401: error_response("AUTHENTICATION_REQUIRED أو INVALID_TOKEN."),
    403: error_response("PERMISSION_DENIED لغير القارئ."),
    429: error_response("THROTTLED."),
}


class BookFavoriteView(ArabicApiResponseMixin, generics.GenericAPIView):
    """Add or remove the current reader's favorite relation for a URL book."""

    permission_classes = [IsReaderRole]
    serializer_class = EmptyBodySerializer
    queryset = Book.objects.all()

    @extend_schema(
        tags=["Favorites"],
        operation_id="favorite_create",
        summary="إضافة كتاب إلى المفضلة",
        description=(
            "متاح للقارئ فقط. المستخدم من request.user والكتاب من المسار. "
            "لا يقبل body، والكتاب غير الظاهر للقارئ يعامل كغير موجود. "
            "الإضافة المكررة idempotent ولا تنشئ سجلاً ثانياً."
        ),
        request=None,
        responses={
            201: success_envelope(
                "FavoriteCreateSuccessEnvelope", BookReadSerializer(), ["FAVORITE_CREATED"]
            ),
            200: success_envelope(
                "FavoriteAlreadyExistsSuccessEnvelope",
                BookReadSerializer(),
                ["FAVORITE_ALREADY_EXISTS"],
            ),
            400: error_response("VALIDATION_ERROR عند إرسال body غير فارغ."),
            404: error_response("NOT_FOUND للكتاب غير الموجود أو خارج نطاق القارئ."),
            **COMMON_ERRORS,
        },
    )
    def post(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        book = (
            books_accessible_to(request.user)
            .select_related("author", "category", "library__governorate")
            .filter(pk=pk)
            .first()
        )
        if book is None:
            raise NotFound(BOOK_NOT_FOUND)

        _, created = FavoriteBook.objects.get_or_create(user=request.user, book=book)
        data = BookReadSerializer(book, context={"request": request}).data
        if created:
            return self.success_response(
                data,
                "FAVORITE_CREATED",
                "تمت إضافة الكتاب إلى المفضلة بنجاح.",
                status.HTTP_201_CREATED,
            )
        return self.success_response(
            data,
            "FAVORITE_ALREADY_EXISTS",
            "الكتاب موجود في المفضلة بالفعل.",
        )

    @extend_schema(
        tags=["Favorites"],
        operation_id="favorite_delete",
        summary="إزالة كتاب من المفضلة",
        description=(
            "متاح للقارئ فقط ولا يعتمد على نطاق الكتب. يمكن حذف سجل قديم لكتاب "
            "مؤرشف أو خارج النطاق، ولا تكشف النتيجة هل معرف الكتاب موجود."
        ),
        request=None,
        responses={
            200: success_envelope(
                "FavoriteDeleteSuccessEnvelope",
                serializers.JSONField(allow_null=True),
                ["FAVORITE_REMOVED", "FAVORITE_ALREADY_ABSENT"],
            ),
            400: error_response("VALIDATION_ERROR عند إرسال body غير فارغ."),
            **COMMON_ERRORS,
        },
    )
    def delete(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        deleted, _ = FavoriteBook.objects.filter(user=request.user, book_id=pk).delete()
        if deleted:
            return self.success_response(
                None,
                "FAVORITE_REMOVED",
                "تمت إزالة الكتاب من المفضلة بنجاح.",
            )
        return self.success_response(
            None,
            "FAVORITE_ALREADY_ABSENT",
            "الكتاب غير موجود في المفضلة.",
        )


class FavoriteBookListView(ArabicApiResponseMixin, generics.ListAPIView):
    """List accessible books favorited by the current reader."""

    permission_classes = [IsReaderRole]
    serializer_class = BookReadSerializer
    pagination_class = FavoriteBookPagination
    success_response_messages = {
        "get": ("FAVORITES_RETRIEVED", "تم جلب الكتب المفضلة بنجاح."),
    }

    def get_queryset(self):
        return (
            books_accessible_to(self.request.user)
            .filter(favorites__user=self.request.user)
            .select_related("author", "category", "library__governorate")
            .order_by("-favorites__created_at", "-favorites__pk")
        )

    @extend_schema(
        tags=["Favorites"],
        operation_id="favorites_list",
        summary="قائمة الكتب المفضلة",
        description=(
            "يعيد للقارئ كتبه المفضلة الظاهرة ضمن نطاقه الحالي، مرتبة بحسب أحدث "
            "إضافة. تبقى علاقة المفضلة محفوظة عند أرشفة الكتاب أو خروجه من النطاق."
        ),
        responses={
            200: success_envelope(
                "FavoriteListSuccessEnvelope",
                FAVORITE_BOOK_PAGE_SCHEMA,
                ["FAVORITES_RETRIEVED"],
            ),
            **COMMON_ERRORS,
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
