"""Borrow request and borrow APIs.

Views only validate request shape, look up targets and call
books.borrowing_services, which owns every state change, quantity update and
business rule. Querysets are scoped per role before filters, ordering and
pagination, so out-of-scope records behave as missing (404).

Only list, retrieve and the named POST actions exist: there is no PUT, PATCH
or DELETE on these resources, and no POST on the borrow request collection.
Readers create requests through POST /dashboard/books/{id}/borrow-requests/.
"""

from django.contrib.auth import get_user_model
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from rest_framework import generics, mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from accounts.permissions import IsLibrarian, IsReader, IsReaderRole
from accounts.scopes import books_accessible_to, borrowing_records_visible_to
from accounts.views import LibraryPagination
from Bookshelf.api_responses import ArabicApiResponseMixin
from Bookshelf.openapi import error_response, success_envelope
from books import borrowing_services as services
from books.borrowing_services import BOOK_NOT_FOUND, READER_NOT_FOUND
from books.models import Book, Borrow, BorrowRequest

from .borrowing_serializers import (
    BorrowReadSerializer,
    BorrowRequestApprovalSerializer,
    BorrowRequestReadSerializer,
    BorrowRequestRejectSerializer,
    DirectBorrowCreateSerializer,
    EmptyBodySerializer,
)
from .query_params import parse_id_param


User = get_user_model()

BORROW_REQUEST_RELATED = ("reader", "book__library__governorate", "decided_by")
BORROW_RELATED = (
    "reader",
    "book__library__governorate",
    "created_by",
    "returned_by",
    "request",
)

# Direct borrow body fields. A referenced reader/book that is missing or
# outside the actor's scope is a validation error on the field with one shared
# message, so its existence never leaks. Service errors keyed by the resource
# ("reader"/"book") are reported under the matching input field.
DIRECT_BORROW_FIELDS = {"reader": "reader_id", "book": "book_id"}
REFERENCED_TARGET_FIELDS = {BOOK_NOT_FOUND: "book_id", READER_NOT_FOUND: "reader_id"}

ID_FILTERS = (
    ("reader", "reader_id", "يجب أن يكون معرّف القارئ رقماً صحيحاً موجباً."),
    ("book", "book_id", "يجب أن يكون معرّف الكتاب رقماً صحيحاً موجباً."),
    ("library", "book__library_id", "يجب أن يكون معرّف المكتبة رقماً صحيحاً موجباً."),
    ("governorate", "book__library__governorate_id", "يجب أن يكون معرّف المحافظة رقماً صحيحاً موجباً."),
)

COMMON_ERRORS = {
    401: error_response("AUTHENTICATION_REQUIRED أو INVALID_TOKEN."),
    429: error_response("THROTTLED."),
}

SCOPE_RULES = (
    "النطاق: SUPERUSER وMINISTRY_ADMIN كل النظام؛ GOVERNORATE_ADMIN كتب محافظته؛ "
    "LIBRARIAN كتب مكتبته؛ READER سجلاته فقط. السجل خارج النطاق يُعاد كـNOT_FOUND."
)


def _filter_parameters(status_values):
    return [
        OpenApiParameter(
            name="status", type=str, required=False, enum=status_values, description="الحالة."
        ),
        OpenApiParameter(name="reader", type=int, required=False, description="معرّف القارئ."),
        OpenApiParameter(name="book", type=int, required=False, description="معرّف الكتاب."),
        OpenApiParameter(name="library", type=int, required=False, description="معرّف المكتبة."),
        OpenApiParameter(
            name="governorate", type=int, required=False, description="معرّف المحافظة."
        ),
        OpenApiParameter(name="page", type=int, required=False),
        OpenApiParameter(name="page_size", type=int, required=False, description="بحد أقصى 100."),
    ]


def _page_schema(name, serializer):
    return inline_serializer(
        name=name,
        fields={
            "count": serializers.IntegerField(),
            "next": serializers.URLField(allow_null=True),
            "previous": serializers.URLField(allow_null=True),
            "results": serializer(many=True),
        },
    )


class BorrowingViewSetMixin(ArabicApiResponseMixin):
    """Shared scope, filters, ordering and method restrictions."""

    pagination_class = LibraryPagination
    # No PUT/PATCH/DELETE on borrowing records.
    http_method_names = ["get", "post", "head", "options"]
    read_actions = frozenset({"list", "retrieve"})
    model = None
    read_serializer_class = None
    select_related_fields = ()
    ordering = ()

    def get_permissions(self):
        method = getattr(self.request, "method", "") or ""
        if method and (method.lower() not in self.http_method_names or self.action is None):
            # Methods without an action on this route (PUT/PATCH/DELETE, or POST
            # on the request collection) never reach a handler; skipping the
            # permission check lets DRF answer 405 instead of 403.
            return []
        if self.action in self.read_actions:
            return [IsReader()]
        return [IsLibrarian()]

    def get_queryset(self):
        queryset = borrowing_records_visible_to(
            self.request.user,
            self.model.objects.select_related(*self.select_related_fields),
        )
        if self.action == "list":
            queryset = self._apply_list_filters(queryset)
        return queryset.order_by(*self.ordering)

    def _apply_list_filters(self, queryset):
        """List filters run on the scoped queryset, so they can only narrow it."""
        params = self.request.query_params
        status_value = params.get("status")
        if status_value not in (None, ""):
            status_value = status_value.strip().upper()
            if status_value not in self.model.Status.values:
                allowed = "، ".join(self.model.Status.values)
                raise ValidationError({"status": f"القيم المسموحة: {allowed}."})
            queryset = queryset.filter(status=status_value)
        for param, lookup, message in ID_FILTERS:
            object_id = parse_id_param(params, param, message)
            if object_id is not None:
                queryset = queryset.filter(**{lookup: object_id})
        return queryset

    def _validated(self, serializer_class):
        serializer = serializer_class(data=self.request.data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def _read(self, instance):
        """Serialize a record re-read with the list relations loaded."""
        fresh = self.model.objects.select_related(*self.select_related_fields).get(
            pk=instance.pk
        )
        return self.read_serializer_class(fresh).data


def _lookup_or_field_error(queryset, pk, field, message):
    instance = queryset.filter(pk=pk).first()
    if instance is None:
        raise ValidationError({field: message})
    return instance


def _as_direct_borrow_error(exc):
    """Report a service error on the direct borrow input fields."""
    if isinstance(exc, NotFound):
        field = REFERENCED_TARGET_FIELDS.get(str(exc.detail))
        return ValidationError({field: str(exc.detail)}) if field else exc
    if isinstance(exc.detail, dict):
        return ValidationError(
            {DIRECT_BORROW_FIELDS.get(key, key): value for key, value in exc.detail.items()}
        )
    return exc


class BookBorrowRequestCreateView(ArabicApiResponseMixin, generics.GenericAPIView):
    """POST /dashboard/books/{id}/borrow-requests/: a reader requests a book.

    Kept outside BookAdminView so book management permissions never apply here.
    """

    permission_classes = [IsReaderRole]
    # Used for the {id} path parameter in the schema; lookups use the reader scope.
    queryset = Book.objects.all()
    serializer_class = EmptyBodySerializer
    success_response_messages = {
        "post": ("BORROW_REQUEST_CREATED", "تم إرسال طلب الاستعارة بنجاح."),
    }

    @extend_schema(
        tags=["Book Management"],
        operation_id="books_borrow_request_create",
        summary="تقديم طلب استعارة لكتاب (للقارئ)",
        description=(
            "متاح لـREADER فقط؛ القارئ هو دائماً المستخدم الحالي والكتاب من المسار، ولا يقبل body "
            "(أي حقل يُرفض بـVALIDATION_ERROR). بقية الأدوار 403. الكتاب غير الموجود أو غير الظاهر "
            "للقارئ (مؤرشف، مكتبة أو محافظة غير مفعّلة، محافظة أخرى) يُعاد كـNOT_FOUND. يُسمح بالطلب "
            "حتى لو لم تتوفر نسخة. يُرفض إذا كان القارئ محظوراً من الاستعارة أو لديه طلب قيد المراجعة "
            "أو استعارة نشطة لنفس الكتاب."
        ),
        request=None,
        responses={
            201: success_envelope(
                "BookBorrowRequestCreateSuccessEnvelope",
                BorrowRequestReadSerializer(),
                ["BORROW_REQUEST_CREATED"],
            ),
            400: error_response("VALIDATION_ERROR، مثل body غير فارغ أو قارئ محظور أو طلب مكرر."),
            403: error_response("PERMISSION_DENIED لغير القارئ."),
            404: error_response("NOT_FOUND للكتاب غير الموجود أو خارج نطاق القارئ."),
            **COMMON_ERRORS,
        },
    )
    def post(self, request, pk):
        serializer = EmptyBodySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        book = books_accessible_to(request.user).filter(pk=pk).first()
        if book is None:
            raise NotFound(BOOK_NOT_FOUND)
        borrow_request = services.create_borrow_request(reader=request.user, book=book)
        fresh = BorrowRequest.objects.select_related(*BORROW_REQUEST_RELATED).get(
            pk=borrow_request.pk
        )
        return Response(
            BorrowRequestReadSerializer(fresh).data, status=status.HTTP_201_CREATED
        )


@extend_schema_view(
    list=extend_schema(
        tags=["Borrow Requests"],
        operation_id="borrow_requests_list",
        summary="قائمة طلبات الاستعارة ضمن النطاق",
        description=(
            f"متاح لجميع الأدوار. {SCOPE_RULES} يُطبَّق النطاق أولاً ثم الفلاتر ثم الترتيب "
            "(الأحدث أولاً) ثم pagination؛ الفلاتر تضيّق ولا توسّع. القيمة غير الصالحة تُرفض بـVALIDATION_ERROR."
        ),
        parameters=_filter_parameters(BorrowRequest.Status.values),
        responses={
            200: success_envelope(
                "BorrowRequestListSuccessEnvelope",
                _page_schema("BorrowRequestPage", BorrowRequestReadSerializer),
                ["BORROW_REQUESTS_RETRIEVED"],
            ),
            400: error_response("VALIDATION_ERROR عند قيمة فلتر غير صالحة."),
            403: error_response("PERMISSION_DENIED لمستخدم بلا دور صالح."),
            **COMMON_ERRORS,
        },
    ),
    retrieve=extend_schema(
        tags=["Borrow Requests"],
        operation_id="borrow_requests_retrieve",
        summary="جلب طلب استعارة",
        description=f"متاح لجميع الأدوار. {SCOPE_RULES}",
        responses={
            200: success_envelope(
                "BorrowRequestRetrieveSuccessEnvelope",
                BorrowRequestReadSerializer(),
                ["BORROW_REQUEST_RETRIEVED"],
            ),
            404: error_response("NOT_FOUND، ويشمل الطلب خارج النطاق."),
            **COMMON_ERRORS,
        },
    ),
)
class BorrowRequestViewSet(
    BorrowingViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    model = BorrowRequest
    read_serializer_class = BorrowRequestReadSerializer
    select_related_fields = BORROW_REQUEST_RELATED
    ordering = ("-created_at", "-pk")
    success_response_messages = {
        "list": ("BORROW_REQUESTS_RETRIEVED", "تم جلب طلبات الاستعارة بنجاح."),
        "retrieve": ("BORROW_REQUEST_RETRIEVED", "تم جلب طلب الاستعارة بنجاح."),
        "approve": ("BORROW_REQUEST_APPROVED", "تمت الموافقة على طلب الاستعارة بنجاح."),
        "reject": ("BORROW_REQUEST_REJECTED", "تم رفض طلب الاستعارة."),
    }

    def get_serializer_class(self):
        return {
            "approve": EmptyBodySerializer,
            "reject": BorrowRequestRejectSerializer,
        }.get(self.action, BorrowRequestReadSerializer)

    @extend_schema(
        tags=["Borrow Requests"],
        operation_id="borrow_requests_approve",
        summary="الموافقة على طلب استعارة",
        description=(
            f"متاح لـSUPERUSER وMINISTRY_ADMIN وGOVERNORATE_ADMIN وLIBRARIAN؛ READER ممنوع. {SCOPE_RULES} "
            "لا يقبل body. يشترط أن يكون الطلب قيد المراجعة، والقارئ مفعّلاً وغير محظور، والكتاب غير مؤرشف "
            "في مكتبة ومحافظة مفعّلتين وبنفس محافظة القارئ، ووجود نسخة متاحة. ينقص available_copies "
            "ويزيد count_borrowed وينشئ استعارة ACTIVE في عملية واحدة."
        ),
        request=None,
        responses={
            200: success_envelope(
                "BorrowRequestApproveSuccessEnvelope",
                BorrowRequestApprovalSerializer(),
                ["BORROW_REQUEST_APPROVED"],
            ),
            400: error_response("VALIDATION_ERROR، ويبقى الطلب قيد المراجعة دون أي تغيير."),
            403: error_response("PERMISSION_DENIED للقارئ."),
            404: error_response("NOT_FOUND، ويشمل الطلب خارج النطاق."),
            **COMMON_ERRORS,
        },
    )
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        self._validated(EmptyBodySerializer)
        borrow = services.approve_borrow_request(
            actor=request.user, borrow_request=self.get_object()
        )
        return Response(
            {
                "request": self._read(borrow.request),
                "borrow": BorrowReadSerializer(
                    Borrow.objects.select_related(*BORROW_RELATED).get(pk=borrow.pk)
                ).data,
            }
        )

    @extend_schema(
        tags=["Borrow Requests"],
        operation_id="borrow_requests_reject",
        summary="رفض طلب استعارة",
        description=(
            f"متاح لـSUPERUSER وMINISTRY_ADMIN وGOVERNORATE_ADMIN وLIBRARIAN؛ READER ممنوع. {SCOPE_RULES} "
            "الحقل الوحيد المسموح: reason (اختياري، تُحذف المسافات حوله). لا يغيّر الكميات ولا ينشئ استعارة."
        ),
        request=BorrowRequestRejectSerializer,
        responses={
            200: success_envelope(
                "BorrowRequestRejectSuccessEnvelope",
                BorrowRequestReadSerializer(),
                ["BORROW_REQUEST_REJECTED"],
            ),
            400: error_response("VALIDATION_ERROR، مثل طلب غير قيد المراجعة."),
            403: error_response("PERMISSION_DENIED للقارئ."),
            404: error_response("NOT_FOUND، ويشمل الطلب خارج النطاق."),
            **COMMON_ERRORS,
        },
    )
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        data = self._validated(BorrowRequestRejectSerializer)
        borrow_request = services.reject_borrow_request(
            actor=request.user, borrow_request=self.get_object(), reason=data["reason"]
        )
        return Response(self._read(borrow_request))


@extend_schema_view(
    list=extend_schema(
        tags=["Borrows"],
        operation_id="borrows_list",
        summary="قائمة الاستعارات ضمن النطاق",
        description=(
            f"متاح لجميع الأدوار. {SCOPE_RULES} يُطبَّق النطاق أولاً ثم الفلاتر ثم الترتيب "
            "(الأحدث أولاً) ثم pagination. source مشتق: REQUEST أو DIRECT."
        ),
        parameters=_filter_parameters(Borrow.Status.values),
        responses={
            200: success_envelope(
                "BorrowListSuccessEnvelope",
                _page_schema("BorrowPage", BorrowReadSerializer),
                ["BORROWS_RETRIEVED"],
            ),
            400: error_response("VALIDATION_ERROR عند قيمة فلتر غير صالحة."),
            403: error_response("PERMISSION_DENIED لمستخدم بلا دور صالح."),
            **COMMON_ERRORS,
        },
    ),
    retrieve=extend_schema(
        tags=["Borrows"],
        operation_id="borrows_retrieve",
        summary="جلب استعارة",
        description=f"متاح لجميع الأدوار. {SCOPE_RULES}",
        responses={
            200: success_envelope(
                "BorrowRetrieveSuccessEnvelope", BorrowReadSerializer(), ["BORROW_RETRIEVED"]
            ),
            404: error_response("NOT_FOUND، ويشمل الاستعارة خارج النطاق."),
            **COMMON_ERRORS,
        },
    ),
    create=extend_schema(
        tags=["Borrows"],
        operation_id="borrows_direct_create",
        summary="استعارة مباشرة دون طلب",
        description=(
            f"متاح لـSUPERUSER وMINISTRY_ADMIN وGOVERNORATE_ADMIN وLIBRARIAN؛ READER ممنوع. {SCOPE_RULES} "
            "الحقول المسموحة: reader_id وbook_id. يشترط قارئاً مفعّلاً وغير محظور، وكتاباً غير مؤرشف في مكتبة "
            "ومحافظة مفعّلتين وبنفس محافظة القارئ (حتى للوزارة)، ونسخة متاحة، وعدم وجود استعارة نشطة "
            "أو طلب قيد المراجعة لنفس القارئ والكتاب. القارئ أو الكتاب غير الموجود أو خارج النطاق "
            "يُرفض برسالة واحدة على الحقل. أخطاء التحقق تُعاد على reader_id أو book_id."
        ),
        request=DirectBorrowCreateSerializer,
        responses={
            201: success_envelope(
                "BorrowCreateSuccessEnvelope", BorrowReadSerializer(), ["BORROW_CREATED"]
            ),
            400: error_response("VALIDATION_ERROR مع أخطاء reader_id أو book_id."),
            403: error_response("PERMISSION_DENIED للقارئ."),
            **COMMON_ERRORS,
        },
    ),
)
class BorrowViewSet(
    BorrowingViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    model = Borrow
    read_serializer_class = BorrowReadSerializer
    select_related_fields = BORROW_RELATED
    ordering = ("-borrowed_at", "-pk")
    success_response_messages = {
        "list": ("BORROWS_RETRIEVED", "تم جلب الاستعارات بنجاح."),
        "retrieve": ("BORROW_RETRIEVED", "تم جلب بيانات الاستعارة بنجاح."),
        "create": ("BORROW_CREATED", "تم تسجيل الاستعارة بنجاح."),
        "return_borrow": ("BORROW_RETURNED", "تم تسجيل إعادة الكتاب بنجاح."),
    }

    def get_serializer_class(self):
        return {
            "create": DirectBorrowCreateSerializer,
            "return_borrow": EmptyBodySerializer,
        }.get(self.action, BorrowReadSerializer)

    def create(self, request, *args, **kwargs):
        data = self._validated(DirectBorrowCreateSerializer)
        reader = _lookup_or_field_error(
            User.objects.all(), data["reader_id"], "reader_id", READER_NOT_FOUND
        )
        book = _lookup_or_field_error(Book.objects.all(), data["book_id"], "book_id", BOOK_NOT_FOUND)
        try:
            borrow = services.direct_borrow(actor=request.user, reader=reader, book=book)
        except (NotFound, ValidationError) as exc:
            raise _as_direct_borrow_error(exc)
        return Response(self._read(borrow), status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["Borrows"],
        operation_id="borrows_return",
        summary="تسجيل إعادة كتاب",
        description=(
            f"متاح لـSUPERUSER وMINISTRY_ADMIN وGOVERNORATE_ADMIN وLIBRARIAN؛ READER ممنوع. {SCOPE_RULES} "
            "لا يقبل body. يعيد النسخة مرة واحدة فقط ويرفض الإرجاع المكرر؛ لا يغيّر count_borrowed."
        ),
        request=None,
        responses={
            200: success_envelope(
                "BorrowReturnSuccessEnvelope", BorrowReadSerializer(), ["BORROW_RETURNED"]
            ),
            400: error_response("VALIDATION_ERROR، مثل إرجاع مكرر."),
            403: error_response("PERMISSION_DENIED للقارئ."),
            404: error_response("NOT_FOUND، ويشمل الاستعارة خارج النطاق."),
            **COMMON_ERRORS,
        },
    )
    @action(detail=True, methods=["post"], url_path="return", url_name="return")
    def return_borrow(self, request, pk=None):
        self._validated(EmptyBodySerializer)
        borrow = services.return_borrow(actor=request.user, borrow=self.get_object())
        return Response(self._read(borrow))
