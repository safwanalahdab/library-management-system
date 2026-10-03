"""Transactional business logic for the new borrowing system.

Views call these functions; they never touch Borrow/BorrowRequest state or book
quantities directly. Every function re-reads and locks the rows it depends on,
so it is safe to call with stale instances.

Errors are DRF exceptions so the shared exception handler renders them:
- PermissionDenied: the actor's role may not perform the operation.
- NotFound: the target is outside the actor's scope (it behaves as missing).
- ValidationError: the operation is not valid for the current state.

Locking order is always Book, then BorrowRequest/Borrow, then the reader row.
Every operation on a book serializes on that book's row, so checks such as
"no pending request" and "no active borrow" cannot race each other.
"""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from accounts.models import CustomUser
from accounts.scopes import (
    books_accessible_to,
    books_manageable_by,
    get_effective_governorate_id,
    has_active_user_scope,
    is_authenticated_user,
    is_superuser,
)

from .models import Book, Borrow, BorrowRequest


User = get_user_model()

OPERATOR_ROLES = frozenset(
    {
        CustomUser.Role.MINISTRY_ADMIN,
        CustomUser.Role.GOVERNORATE_ADMIN,
        CustomUser.Role.LIBRARIAN,
    }
)

BOOK_NOT_FOUND = "الكتاب غير موجود أو خارج نطاقك."
READER_NOT_FOUND = "القارئ غير موجود أو خارج نطاقك."
REQUEST_NOT_FOUND = "طلب الاستعارة غير موجود أو خارج نطاقك."
BORROW_NOT_FOUND = "سجل الاستعارة غير موجود أو خارج نطاقك."
DUPLICATE_PENDING = "يوجد طلب استعارة قيد المراجعة لهذا الكتاب بالفعل."
DUPLICATE_ACTIVE = "القارئ مستعير لهذا الكتاب حالياً."
CONCURRENT_CONFLICT = "تعارضت العملية مع عملية أخرى على نفس الكتاب؛ يرجى إعادة المحاولة."


# Actor checks


def _require_operator(actor):
    """Superusers and ministry/governorate admins and librarians may operate."""
    if not is_authenticated_user(actor) or not actor.is_active:
        raise PermissionDenied("لا تملك الصلاحية لتنفيذ هذه العملية.")
    if is_superuser(actor) or actor.role in OPERATOR_ROLES:
        return
    raise PermissionDenied("لا تملك الصلاحية لتنفيذ هذه العملية.")


def _lock_book_in_scope(actor, book_id):
    book = (
        books_manageable_by(actor)
        .select_for_update(of=("self",))
        .filter(pk=book_id)
        .first()
    )
    if book is None:
        raise NotFound(BOOK_NOT_FOUND)
    # Library and governorate are read after the lock for fresh is_active values.
    return Book.objects.select_related("library__governorate").get(pk=book.pk)


def _reader_in_actor_scope(actor, reader):
    if is_superuser(actor) or actor.role == CustomUser.Role.MINISTRY_ADMIN:
        return True
    governorate_id = get_effective_governorate_id(actor)
    return governorate_id is not None and reader.governorate_id == governorate_id


# Eligibility checks shared by request creation, approval and direct borrow


def _lock_reader(reader_id):
    reader = (
        User.objects.select_for_update(of=("self",))
        .select_related("governorate")
        .filter(pk=reader_id)
        .first()
    )
    if reader is None:
        raise NotFound(READER_NOT_FOUND)
    return reader


def _validate_reader_can_borrow(reader):
    if reader.is_superuser or reader.role != CustomUser.Role.READER:
        raise ValidationError({"reader": "المستخدم المحدد ليس قارئاً."})
    if not reader.is_active:
        raise ValidationError({"reader": "حساب القارئ غير مفعّل."})
    if reader.borrowing_blocked:
        raise ValidationError({"reader": "الاستعارة محظورة على هذا القارئ."})
    if not has_active_user_scope(reader):
        raise ValidationError({"reader": "محافظة القارئ غير مفعّلة أو غير محددة."})


def _validate_book_can_be_borrowed(book):
    if book.is_archived:
        raise ValidationError({"book": "الكتاب مؤرشف."})
    if not book.library.is_active:
        raise ValidationError({"book": "مكتبة الكتاب غير مفعّلة."})
    if not book.library.governorate.is_active:
        raise ValidationError({"book": "محافظة مكتبة الكتاب غير مفعّلة."})


def _validate_same_governorate(reader, book):
    # Applies to every actor, including superusers and ministry admins.
    if reader.governorate_id != book.library.governorate_id:
        raise ValidationError({"book": "الكتاب لا يتبع لمحافظة القارئ."})


def _validate_no_active_borrow(reader, book):
    if Borrow.objects.filter(
        reader=reader, book=book, status=Borrow.Status.ACTIVE
    ).exists():
        raise ValidationError({"book": DUPLICATE_ACTIVE})


def _validate_copy_available(book):
    if book.available_copies <= 0:
        raise ValidationError({"book": "لا توجد نسخة متاحة من هذا الكتاب حالياً."})


# Quantity changes. Book.save() would recompute available_copies from the
# stored values and undo the change, so these save with skip_recalc.


def _take_copy(book):
    book.available_copies -= 1
    book.is_avaiable = book.available_copies > 0
    book.count_borrowed += 1
    book.save(
        skip_recalc=True,
        update_fields=["available_copies", "is_avaiable", "count_borrowed"],
    )


def _give_back_copy(book):
    if book.available_copies >= book.total_copies:
        # Inconsistent stored quantities are reported, never silently fixed.
        raise ValidationError(
            {"book": "لا يمكن تسجيل الإرجاع لأن عدد النسخ المتاحة يساوي عدد النسخ الكلي."}
        )
    book.available_copies += 1
    book.is_avaiable = book.available_copies > 0
    book.save(skip_recalc=True, update_fields=["available_copies", "is_avaiable"])


# Operations


def create_borrow_request(*, reader, book):
    """A reader requests a book for themselves; copies need not be available."""
    if not is_authenticated_user(reader) or is_superuser(reader) or reader.role != CustomUser.Role.READER:
        raise PermissionDenied("طلب الاستعارة متاح للقرّاء فقط.")

    try:
        with transaction.atomic():
            # Lock the book row first, like every other borrowing operation.
            locked_book = Book.objects.select_for_update().filter(pk=book.pk).first()
            if locked_book is None:
                raise NotFound(BOOK_NOT_FOUND)
            reader = _lock_reader(reader.pk)
            _validate_reader_can_borrow(reader)
            # The reader's read scope already excludes archived books, inactive
            # libraries/governorates and other governorates.
            if not books_accessible_to(reader).filter(pk=locked_book.pk).exists():
                raise NotFound(BOOK_NOT_FOUND)
            # Defensive: re-checked explicitly in case the read scope changes.
            locked_book = Book.objects.select_related("library__governorate").get(pk=locked_book.pk)
            _validate_book_can_be_borrowed(locked_book)
            _validate_same_governorate(reader, locked_book)

            if BorrowRequest.objects.filter(
                reader=reader, book=locked_book, status=BorrowRequest.Status.PENDING
            ).exists():
                raise ValidationError({"book": DUPLICATE_PENDING})
            _validate_no_active_borrow(reader, locked_book)

            return BorrowRequest.objects.create(reader=reader, book=locked_book)
    except IntegrityError:
        # The pending-request constraint caught a concurrent duplicate.
        raise ValidationError({"book": DUPLICATE_PENDING})


def approve_borrow_request(*, actor, borrow_request):
    """Approve a pending request: take one copy and open an active borrow."""
    _require_operator(actor)
    book_id = (
        BorrowRequest.objects.filter(pk=borrow_request.pk)
        .values_list("book_id", flat=True)
        .first()
    )
    if book_id is None:
        raise NotFound(REQUEST_NOT_FOUND)

    try:
        with transaction.atomic():
            book = _lock_book_in_scope_or_request_not_found(actor, book_id)
            request = BorrowRequest.objects.select_for_update().get(pk=borrow_request.pk)
            if request.status != BorrowRequest.Status.PENDING:
                raise ValidationError({"status": "لا يمكن الموافقة إلا على طلب قيد المراجعة."})
            if Borrow.objects.filter(request=request).exists():
                raise ValidationError({"status": "تم إنشاء استعارة لهذا الطلب سابقاً."})

            reader = _lock_reader(request.reader_id)
            _validate_reader_can_borrow(reader)
            _validate_book_can_be_borrowed(book)
            _validate_same_governorate(reader, book)
            _validate_no_active_borrow(reader, book)
            _validate_copy_available(book)

            _take_copy(book)
            borrow = Borrow.objects.create(
                reader=reader, book=book, request=request, created_by=actor
            )
            request.status = BorrowRequest.Status.APPROVED
            request.decided_by = actor
            request.decided_at = timezone.now()
            request.rejection_reason = ""
            request.save(
                update_fields=["status", "decided_by", "decided_at", "rejection_reason"]
            )
            return borrow
    except IntegrityError:
        # A uniqueness constraint (active borrow or request link) caught a race.
        raise ValidationError({"book": CONCURRENT_CONFLICT})


def reject_borrow_request(*, actor, borrow_request, reason=""):
    """Reject a pending request. Quantities, blocking and copies are irrelevant."""
    _require_operator(actor)
    book_id = (
        BorrowRequest.objects.filter(pk=borrow_request.pk)
        .values_list("book_id", flat=True)
        .first()
    )
    if book_id is None:
        raise NotFound(REQUEST_NOT_FOUND)

    with transaction.atomic():
        _lock_book_in_scope_or_request_not_found(actor, book_id)
        request = BorrowRequest.objects.select_for_update().get(pk=borrow_request.pk)
        if request.status != BorrowRequest.Status.PENDING:
            raise ValidationError({"status": "لا يمكن رفض إلا طلب قيد المراجعة."})

        request.status = BorrowRequest.Status.REJECTED
        request.decided_by = actor
        request.decided_at = timezone.now()
        request.rejection_reason = (reason or "").strip()
        request.save(
            update_fields=["status", "decided_by", "decided_at", "rejection_reason"]
        )
        return request


def direct_borrow(*, actor, reader, book):
    """Hand a book to a reader without a request (e.g. the reader is at the desk)."""
    _require_operator(actor)

    try:
        with transaction.atomic():
            book = _lock_book_in_scope(actor, book.pk)
            reader = _lock_reader(reader.pk)
            if not _reader_in_actor_scope(actor, reader):
                raise NotFound(READER_NOT_FOUND)
            _validate_reader_can_borrow(reader)
            _validate_book_can_be_borrowed(book)
            _validate_same_governorate(reader, book)
            _validate_no_active_borrow(reader, book)
            # A pending request is decided explicitly, never closed implicitly here.
            if BorrowRequest.objects.filter(
                reader=reader, book=book, status=BorrowRequest.Status.PENDING
            ).exists():
                raise ValidationError(
                    {"book": "لدى القارئ طلب قيد المراجعة لهذا الكتاب؛ يجب البت فيه أولاً."}
                )
            _validate_copy_available(book)

            _take_copy(book)
            return Borrow.objects.create(reader=reader, book=book, created_by=actor)
    except IntegrityError:
        # A uniqueness constraint (active borrow or request link) caught a race.
        raise ValidationError({"book": CONCURRENT_CONFLICT})


def return_borrow(*, actor, borrow):
    """Record the return of an active borrow and give the copy back once."""
    _require_operator(actor)
    book_id = (
        Borrow.objects.filter(pk=borrow.pk).values_list("book_id", flat=True).first()
    )
    if book_id is None:
        raise NotFound(BORROW_NOT_FOUND)

    with transaction.atomic():
        book = (
            books_manageable_by(actor)
            .select_for_update(of=("self",))
            .filter(pk=book_id)
            .first()
        )
        if book is None:
            raise NotFound(BORROW_NOT_FOUND)
        borrow = Borrow.objects.select_for_update().get(pk=borrow.pk)
        if borrow.status != Borrow.Status.ACTIVE:
            raise ValidationError({"status": "تم تسجيل إرجاع هذه الاستعارة سابقاً."})

        _give_back_copy(book)
        borrow.status = Borrow.Status.RETURNED
        borrow.returned_at = timezone.now()
        borrow.returned_by = actor
        borrow.save(update_fields=["status", "returned_at", "returned_by"])
        return borrow


def _lock_book_in_scope_or_request_not_found(actor, book_id):
    try:
        return _lock_book_in_scope(actor, book_id)
    except NotFound:
        raise NotFound(REQUEST_NOT_FOUND)
