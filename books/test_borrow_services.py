from unittest import mock

from django.db import IntegrityError
from django.test import TestCase
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from accounts.models import CustomUser, Governorate, Library
from books.borrowing_services import (
    approve_borrow_request,
    create_borrow_request,
    direct_borrow,
    reject_borrow_request,
    return_borrow,
)
from books.models import Book, Borrow, BorrowRequest


PASSWORD = "StrongPass123!"


class BorrowServiceTestMixin:
    """Governorate A: libraries A1 and A2. Governorate B: library B."""

    def setUp(self):
        self.gov_a = Governorate.objects.create(name="Governorate A")
        self.gov_b = Governorate.objects.create(name="Governorate B")
        self.library_a1 = Library.objects.create(name="Library A1", governorate=self.gov_a)
        self.library_a2 = Library.objects.create(name="Library A2", governorate=self.gov_a)
        self.library_b = Library.objects.create(name="Library B", governorate=self.gov_b)

        self.superuser = CustomUser.objects.create_superuser(
            username="root", email="root@example.com", password=PASSWORD
        )
        self.ministry = self.create_user("ministry", CustomUser.Role.MINISTRY_ADMIN)
        self.gov_admin_a = self.create_user(
            "gov_admin_a", CustomUser.Role.GOVERNORATE_ADMIN, governorate=self.gov_a
        )
        self.gov_admin_b = self.create_user(
            "gov_admin_b", CustomUser.Role.GOVERNORATE_ADMIN, governorate=self.gov_b
        )
        self.librarian_a1 = self.create_user(
            "librarian_a1", CustomUser.Role.LIBRARIAN, library=self.library_a1
        )
        self.librarian_a2 = self.create_user(
            "librarian_a2", CustomUser.Role.LIBRARIAN, library=self.library_a2
        )
        self.reader = self.create_user("reader_a", CustomUser.Role.READER, governorate=self.gov_a)
        self.other_reader = self.create_user(
            "reader_a2", CustomUser.Role.READER, governorate=self.gov_a
        )
        self.reader_b = self.create_user("reader_b", CustomUser.Role.READER, governorate=self.gov_b)

        self.book = self.create_book("Book A1", self.library_a1, 3)
        self.empty_book = self.create_book("Empty A1", self.library_a1, 0)
        self.book_a2 = self.create_book("Book A2", self.library_a2, 2)
        self.book_b = self.create_book("Book B", self.library_b, 2)

    def create_user(self, username, role, **extra):
        return CustomUser.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password=PASSWORD,
            role=role,
            **extra,
        )

    def create_book(self, title, library, copies, **extra):
        return Book.objects.create(
            title=title, description="desc", library=library, total_copies=copies, **extra
        )

    def quantities(self, book):
        book.refresh_from_db()
        return (book.total_copies, book.available_copies, book.is_avaiable, book.count_borrowed)

    def set_quantities(self, book, total, available, count_borrowed=0):
        Book.objects.filter(pk=book.pk).update(
            total_copies=total,
            available_copies=available,
            is_avaiable=available > 0,
            count_borrowed=count_borrowed,
        )
        book.refresh_from_db()

    def pending_request(self, reader=None, book=None):
        return BorrowRequest.objects.create(reader=reader or self.reader, book=book or self.book)

    def save_field(self, instance, **values):
        for field, value in values.items():
            setattr(instance, field, value)
        instance.save(update_fields=list(values))


class CreateBorrowRequestTests(BorrowServiceTestMixin, TestCase):
    def test_reader_creates_pending_request(self):
        request = create_borrow_request(reader=self.reader, book=self.book)

        self.assertEqual(request.status, BorrowRequest.Status.PENDING)
        self.assertEqual((request.reader_id, request.book_id), (self.reader.id, self.book.id))
        self.assertIsNone(request.decided_by)
        self.assertEqual(self.quantities(self.book), (3, 3, True, 0))

    def test_no_available_copies_does_not_block_request(self):
        request = create_borrow_request(reader=self.reader, book=self.empty_book)

        self.assertEqual(request.status, BorrowRequest.Status.PENDING)

    def test_blocked_reader_is_rejected(self):
        self.save_field(self.reader, borrowing_blocked=True)

        with self.assertRaises(ValidationError):
            create_borrow_request(reader=self.reader, book=self.book)
        self.assertFalse(BorrowRequest.objects.exists())

    def test_inactive_reader_is_rejected(self):
        self.save_field(self.reader, is_active=False)

        with self.assertRaises(ValidationError):
            create_borrow_request(reader=self.reader, book=self.book)

    def test_archived_book_is_outside_reader_scope(self):
        self.save_field(self.book, is_archived=True)

        with self.assertRaises(NotFound):
            create_borrow_request(reader=self.reader, book=self.book)

    def test_inactive_library_is_outside_reader_scope(self):
        self.save_field(self.library_a1, is_active=False)

        with self.assertRaises(NotFound):
            create_borrow_request(reader=self.reader, book=self.book)

    def test_inactive_governorate_is_rejected(self):
        self.save_field(self.gov_a, is_active=False)

        with self.assertRaises(ValidationError):
            create_borrow_request(reader=self.reader, book=self.book)

    def test_book_of_other_governorate_is_outside_reader_scope(self):
        with self.assertRaises(NotFound):
            create_borrow_request(reader=self.reader, book=self.book_b)

    def test_duplicate_pending_request_is_a_business_error(self):
        create_borrow_request(reader=self.reader, book=self.book)

        with self.assertRaises(ValidationError) as raised:
            create_borrow_request(reader=self.reader, book=self.book)
        self.assertIn("book", raised.exception.detail)
        self.assertEqual(BorrowRequest.objects.count(), 1)

    def test_database_race_on_duplicate_pending_becomes_validation_error(self):
        with mock.patch.object(
            BorrowRequest.objects, "create", side_effect=IntegrityError("duplicate")
        ):
            with self.assertRaises(ValidationError):
                create_borrow_request(reader=self.reader, book=self.book)

    def test_active_borrow_for_same_book_blocks_request(self):
        Borrow.objects.create(reader=self.reader, book=self.book, created_by=self.librarian_a1)

        with self.assertRaises(ValidationError):
            create_borrow_request(reader=self.reader, book=self.book)
        self.assertFalse(BorrowRequest.objects.exists())

    def test_non_reader_cannot_create_request(self):
        for user in (self.librarian_a1, self.ministry, self.superuser):
            with self.subTest(user=user.username):
                with self.assertRaises(PermissionDenied):
                    create_borrow_request(reader=user, book=self.book)


class ApproveBorrowRequestTests(BorrowServiceTestMixin, TestCase):
    def assert_not_approved(self, request, book, before, error=ValidationError, actor=None):
        with self.assertRaises(error):
            approve_borrow_request(actor=actor or self.librarian_a1, borrow_request=request)
        request.refresh_from_db()
        self.assertEqual(request.status, BorrowRequest.Status.PENDING)
        self.assertIsNone(request.decided_by)
        self.assertFalse(Borrow.objects.filter(request=request).exists())
        self.assertEqual(self.quantities(book), before)

    def test_approval_opens_active_borrow_and_takes_a_copy(self):
        request = self.pending_request()

        borrow = approve_borrow_request(actor=self.librarian_a1, borrow_request=request)

        self.assertEqual(borrow.status, Borrow.Status.ACTIVE)
        self.assertEqual(
            (borrow.reader_id, borrow.book_id, borrow.request_id, borrow.created_by_id),
            (self.reader.id, self.book.id, request.id, self.librarian_a1.id),
        )
        request.refresh_from_db()
        self.assertEqual(request.status, BorrowRequest.Status.APPROVED)
        self.assertEqual(request.decided_by, self.librarian_a1)
        self.assertIsNotNone(request.decided_at)
        self.assertEqual(request.rejection_reason, "")
        self.assertEqual(self.quantities(self.book), (3, 2, True, 1))

    def test_approving_last_copy_makes_book_unavailable(self):
        self.set_quantities(self.book, 3, 1, count_borrowed=4)
        request = self.pending_request()

        approve_borrow_request(actor=self.librarian_a1, borrow_request=request)

        self.assertEqual(self.quantities(self.book), (3, 0, False, 5))

    def test_no_copies_keeps_request_pending(self):
        request = self.pending_request(book=self.empty_book)

        self.assert_not_approved(request, self.empty_book, (0, 0, False, 0))

    def test_reader_blocked_after_request_is_rejected(self):
        request = self.pending_request()
        self.save_field(self.reader, borrowing_blocked=True)

        self.assert_not_approved(request, self.book, (3, 3, True, 0))

    def test_inactive_reader_is_rejected(self):
        request = self.pending_request()
        self.save_field(self.reader, is_active=False)

        self.assert_not_approved(request, self.book, (3, 3, True, 0))

    def test_inactive_library_or_governorate_is_rejected(self):
        for instance in (self.library_a1, self.gov_a):
            with self.subTest(instance=instance.name):
                request = self.pending_request()
                self.save_field(instance, is_active=False)

                self.assert_not_approved(request, self.book, (3, 3, True, 0))

                self.save_field(instance, is_active=True)
                request.delete()

    def test_archived_book_is_rejected(self):
        request = self.pending_request()
        self.save_field(self.book, is_archived=True)

        self.assert_not_approved(request, self.book, (3, 3, True, 0))

    def test_decided_request_cannot_be_approved(self):
        for status in (BorrowRequest.Status.APPROVED, BorrowRequest.Status.REJECTED):
            with self.subTest(status=status):
                request = BorrowRequest.objects.create(
                    reader=self.reader, book=self.book, status=status
                )
                with self.assertRaises(ValidationError):
                    approve_borrow_request(actor=self.librarian_a1, borrow_request=request)
                self.assertFalse(Borrow.objects.filter(request=request).exists())
        self.assertEqual(self.quantities(self.book), (3, 3, True, 0))

    def test_second_approval_of_same_request_is_rejected(self):
        request = self.pending_request()
        approve_borrow_request(actor=self.librarian_a1, borrow_request=request)

        with self.assertRaises(ValidationError):
            approve_borrow_request(actor=self.librarian_a1, borrow_request=request)
        self.assertEqual(Borrow.objects.count(), 1)
        self.assertEqual(self.quantities(self.book), (3, 2, True, 1))

    def test_existing_active_borrow_blocks_approval(self):
        Borrow.objects.create(reader=self.reader, book=self.book, created_by=self.librarian_a1)
        request = self.pending_request()

        self.assert_not_approved(request, self.book, (3, 3, True, 0))

    def test_out_of_scope_actors_get_not_found(self):
        request = self.pending_request()
        for actor in (self.librarian_a2, self.gov_admin_b):
            with self.subTest(actor=actor.username):
                self.assert_not_approved(
                    request, self.book, (3, 3, True, 0), error=NotFound, actor=actor
                )

    def test_reader_cannot_approve(self):
        request = self.pending_request()

        self.assert_not_approved(
            request, self.book, (3, 3, True, 0), error=PermissionDenied, actor=self.reader
        )

    def test_operators_approve_within_scope(self):
        self.set_quantities(self.book, 5, 5)
        actors = (self.librarian_a1, self.gov_admin_a, self.ministry, self.superuser)
        for index, actor in enumerate(actors):
            with self.subTest(actor=actor.username):
                reader = self.create_user(
                    f"approve_reader_{index}", CustomUser.Role.READER, governorate=self.gov_a
                )
                request = self.pending_request(reader=reader)

                borrow = approve_borrow_request(actor=actor, borrow_request=request)

                self.assertEqual(borrow.created_by, actor)
                request.refresh_from_db()
                self.assertEqual(request.decided_by, actor)
        self.assertEqual(self.quantities(self.book), (5, 1, True, 4))

    def test_failure_after_taking_copy_rolls_everything_back(self):
        request = self.pending_request()

        with mock.patch.object(Borrow.objects, "create", side_effect=IntegrityError("race")):
            with self.assertRaises(ValidationError):
                approve_borrow_request(actor=self.librarian_a1, borrow_request=request)

        request.refresh_from_db()
        self.assertEqual(request.status, BorrowRequest.Status.PENDING)
        self.assertEqual(self.quantities(self.book), (3, 3, True, 0))
        self.assertFalse(Borrow.objects.exists())


class RejectBorrowRequestTests(BorrowServiceTestMixin, TestCase):
    def test_pending_request_is_rejected_with_trimmed_reason(self):
        request = self.pending_request()

        rejected = reject_borrow_request(
            actor=self.librarian_a1, borrow_request=request, reason="  لا توجد نسخ  "
        )

        self.assertEqual(rejected.status, BorrowRequest.Status.REJECTED)
        self.assertEqual(rejected.decided_by, self.librarian_a1)
        self.assertIsNotNone(rejected.decided_at)
        self.assertEqual(rejected.rejection_reason, "لا توجد نسخ")
        self.assertFalse(Borrow.objects.exists())
        self.assertEqual(self.quantities(self.book), (3, 3, True, 0))

    def test_reason_is_optional(self):
        rejected = reject_borrow_request(
            actor=self.gov_admin_a, borrow_request=self.pending_request()
        )

        self.assertEqual(rejected.rejection_reason, "")

    def test_reject_ignores_blocking_and_missing_copies(self):
        request = self.pending_request(book=self.empty_book)
        self.save_field(self.reader, borrowing_blocked=True)

        rejected = reject_borrow_request(actor=self.librarian_a1, borrow_request=request)

        self.assertEqual(rejected.status, BorrowRequest.Status.REJECTED)

    def test_decided_request_cannot_be_rejected(self):
        for status in (BorrowRequest.Status.APPROVED, BorrowRequest.Status.REJECTED):
            with self.subTest(status=status):
                request = BorrowRequest.objects.create(
                    reader=self.reader, book=self.book, status=status
                )
                with self.assertRaises(ValidationError):
                    reject_borrow_request(actor=self.librarian_a1, borrow_request=request)
                request.refresh_from_db()
                self.assertEqual(request.status, status)

    def test_out_of_scope_actor_and_reader_are_refused(self):
        request = self.pending_request()

        with self.assertRaises(NotFound):
            reject_borrow_request(actor=self.librarian_a2, borrow_request=request)
        with self.assertRaises(NotFound):
            reject_borrow_request(actor=self.gov_admin_b, borrow_request=request)
        with self.assertRaises(PermissionDenied):
            reject_borrow_request(actor=self.reader, borrow_request=request)

        request.refresh_from_db()
        self.assertEqual(request.status, BorrowRequest.Status.PENDING)


class DirectBorrowTests(BorrowServiceTestMixin, TestCase):
    def assert_refused(self, actor, reader, book, error=ValidationError):
        before = self.quantities(book)
        with self.assertRaises(error):
            direct_borrow(actor=actor, reader=reader, book=book)
        self.assertFalse(Borrow.objects.filter(reader=reader, book=book).exists())
        self.assertEqual(self.quantities(book), before)

    def test_operators_borrow_directly_within_scope(self):
        cases = (
            (self.librarian_a1, self.reader, self.book),
            (self.gov_admin_a, self.other_reader, self.book),
            (self.ministry, self.reader_b, self.book_b),
            (self.superuser, self.reader, self.book_a2),
        )
        for actor, reader, book in cases:
            with self.subTest(actor=actor.username):
                borrow = direct_borrow(actor=actor, reader=reader, book=book)

                self.assertEqual(borrow.status, Borrow.Status.ACTIVE)
                self.assertIsNone(borrow.request)
                self.assertEqual(borrow.created_by, actor)
                self.assertEqual((borrow.reader_id, borrow.book_id), (reader.id, book.id))

        self.assertFalse(BorrowRequest.objects.exists())

    def test_direct_borrow_takes_a_copy(self):
        direct_borrow(actor=self.librarian_a1, reader=self.reader, book=self.book)

        self.assertEqual(self.quantities(self.book), (3, 2, True, 1))

    def test_blocked_reader_is_refused(self):
        self.save_field(self.reader, borrowing_blocked=True)

        self.assert_refused(self.librarian_a1, self.reader, self.book)

    def test_inactive_reader_is_refused(self):
        self.save_field(self.reader, is_active=False)

        self.assert_refused(self.librarian_a1, self.reader, self.book)

    def test_non_reader_borrower_is_refused(self):
        self.assert_refused(self.ministry, self.librarian_a1, self.book)

    def test_archived_book_is_refused(self):
        self.save_field(self.book, is_archived=True)

        self.assert_refused(self.librarian_a1, self.reader, self.book)

    def test_inactive_library_or_governorate_is_refused(self):
        for instance in (self.library_a1, self.gov_a):
            with self.subTest(instance=instance.name):
                self.save_field(instance, is_active=False)
                self.assert_refused(self.ministry, self.reader, self.book)
                self.save_field(instance, is_active=True)

    def test_no_copies_is_refused(self):
        self.assert_refused(self.librarian_a1, self.reader, self.empty_book)

    def test_governorate_mismatch_is_refused_even_for_ministry_and_superuser(self):
        for actor in (self.ministry, self.superuser):
            with self.subTest(actor=actor.username):
                self.assert_refused(actor, self.reader, self.book_b)

    def test_librarian_cannot_use_other_library_book(self):
        self.assert_refused(self.librarian_a1, self.reader, self.book_a2, error=NotFound)
        self.assert_refused(self.librarian_a1, self.reader_b, self.book_b, error=NotFound)

    def test_librarian_cannot_serve_reader_of_other_governorate(self):
        self.assert_refused(self.librarian_a1, self.reader_b, self.book, error=NotFound)

    def test_governorate_admin_cannot_leave_own_governorate(self):
        self.assert_refused(self.gov_admin_a, self.reader_b, self.book_b, error=NotFound)
        self.assert_refused(self.gov_admin_a, self.reader_b, self.book, error=NotFound)

    def test_reader_cannot_borrow_directly(self):
        self.assert_refused(self.reader, self.reader, self.book, error=PermissionDenied)

    def test_existing_active_borrow_is_refused(self):
        direct_borrow(actor=self.librarian_a1, reader=self.reader, book=self.book)

        self.assert_refused_after_first(self.reader, self.book)

    def assert_refused_after_first(self, reader, book):
        before = self.quantities(book)
        with self.assertRaises(ValidationError):
            direct_borrow(actor=self.librarian_a1, reader=reader, book=book)
        self.assertEqual(Borrow.objects.filter(reader=reader, book=book).count(), 1)
        self.assertEqual(self.quantities(book), before)

    def test_pending_request_blocks_direct_borrow_and_stays_pending(self):
        request = self.pending_request()

        self.assert_refused(self.librarian_a1, self.reader, self.book)
        request.refresh_from_db()
        self.assertEqual(request.status, BorrowRequest.Status.PENDING)

    def test_last_copy_cannot_be_borrowed_twice(self):
        self.set_quantities(self.book, 1, 1)
        direct_borrow(actor=self.librarian_a1, reader=self.reader, book=self.book)

        self.assert_refused(self.librarian_a1, self.other_reader, self.book)
        self.assertEqual(self.quantities(self.book), (1, 0, False, 1))

    def test_last_copy_taken_directly_blocks_approval(self):
        self.set_quantities(self.book, 1, 1)
        request = self.pending_request(reader=self.other_reader)
        direct_borrow(actor=self.librarian_a1, reader=self.reader, book=self.book)

        with self.assertRaises(ValidationError):
            approve_borrow_request(actor=self.librarian_a1, borrow_request=request)
        request.refresh_from_db()
        self.assertEqual(request.status, BorrowRequest.Status.PENDING)
        self.assertEqual(self.quantities(self.book), (1, 0, False, 1))


class ReturnBorrowTests(BorrowServiceTestMixin, TestCase):
    def active_borrow(self, reader=None, book=None):
        return direct_borrow(
            actor=self.superuser, reader=reader or self.reader, book=book or self.book
        )

    def test_return_closes_borrow_and_gives_copy_back(self):
        borrow = self.active_borrow()

        returned = return_borrow(actor=self.librarian_a1, borrow=borrow)

        self.assertEqual(returned.status, Borrow.Status.RETURNED)
        self.assertIsNotNone(returned.returned_at)
        self.assertEqual(returned.returned_by, self.librarian_a1)
        self.assertEqual(self.quantities(self.book), (3, 3, True, 1))

    def test_returning_last_copy_makes_book_available_again(self):
        self.set_quantities(self.book, 1, 1)
        borrow = self.active_borrow()
        self.assertEqual(self.quantities(self.book), (1, 0, False, 1))

        return_borrow(actor=self.librarian_a1, borrow=borrow)

        self.assertEqual(self.quantities(self.book), (1, 1, True, 1))

    def test_double_return_is_refused_and_copy_given_back_once(self):
        borrow = self.active_borrow()
        return_borrow(actor=self.librarian_a1, borrow=borrow)

        with self.assertRaises(ValidationError):
            return_borrow(actor=self.librarian_a1, borrow=borrow)
        self.assertEqual(self.quantities(self.book), (3, 3, True, 1))

    def test_return_is_allowed_for_blocked_reader(self):
        borrow = self.active_borrow()
        self.save_field(self.reader, borrowing_blocked=True)

        returned = return_borrow(actor=self.librarian_a1, borrow=borrow)

        self.assertEqual(returned.status, Borrow.Status.RETURNED)

    def test_operators_return_within_scope(self):
        cases = (
            (self.librarian_a1, self.reader, self.book),
            (self.gov_admin_a, self.other_reader, self.book_a2),
            (self.ministry, self.reader_b, self.book_b),
            (self.superuser, self.other_reader, self.book),
        )
        for actor, reader, book in cases:
            with self.subTest(actor=actor.username):
                borrow = self.active_borrow(reader=reader, book=book)

                returned = return_borrow(actor=actor, borrow=borrow)

                self.assertEqual(returned.returned_by, actor)

    def test_out_of_scope_actors_get_not_found(self):
        borrow = self.active_borrow()
        for actor in (self.librarian_a2, self.gov_admin_b):
            with self.subTest(actor=actor.username):
                with self.assertRaises(NotFound):
                    return_borrow(actor=actor, borrow=borrow)

        with self.assertRaises(PermissionDenied):
            return_borrow(actor=self.reader, borrow=borrow)
        borrow.refresh_from_db()
        self.assertEqual(borrow.status, Borrow.Status.ACTIVE)
        self.assertEqual(self.quantities(self.book), (3, 2, True, 1))

    def test_inconsistent_quantities_are_reported_not_fixed(self):
        borrow = self.active_borrow()
        self.set_quantities(self.book, 3, 3, count_borrowed=1)

        with self.assertRaises(ValidationError):
            return_borrow(actor=self.librarian_a1, borrow=borrow)

        borrow.refresh_from_db()
        self.assertEqual(borrow.status, Borrow.Status.ACTIVE)
        self.assertEqual(self.quantities(self.book), (3, 3, True, 1))

    def test_failure_after_giving_copy_back_rolls_everything_back(self):
        borrow = self.active_borrow()

        with mock.patch.object(Borrow, "save", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                return_borrow(actor=self.librarian_a1, borrow=borrow)

        borrow.refresh_from_db()
        self.assertEqual(borrow.status, Borrow.Status.ACTIVE)
        self.assertEqual(self.quantities(self.book), (3, 2, True, 1))
