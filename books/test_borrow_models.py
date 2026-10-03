from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from accounts.models import CustomUser, Governorate, Library
from books.models import Book, Borrow, BorrowRequest


PASSWORD = "StrongPass123!"


class BorrowModelsTestMixin:
    def setUp(self):
        governorate = Governorate.objects.create(name="Governorate A")
        library = Library.objects.create(name="Library A", governorate=governorate)
        self.reader = CustomUser.objects.create_user(
            username="reader",
            email="reader@example.com",
            password=PASSWORD,
            role=CustomUser.Role.READER,
            governorate=governorate,
        )
        self.other_reader = CustomUser.objects.create_user(
            username="other_reader",
            email="other_reader@example.com",
            password=PASSWORD,
            role=CustomUser.Role.READER,
            governorate=governorate,
        )
        self.librarian = CustomUser.objects.create_user(
            username="librarian",
            email="librarian@example.com",
            password=PASSWORD,
            role=CustomUser.Role.LIBRARIAN,
            library=library,
        )
        self.book = Book.objects.create(
            title="Book", description="desc", library=library, total_copies=3
        )
        self.other_book = Book.objects.create(
            title="Other Book", description="desc", library=library, total_copies=3
        )

    def assert_integrity_error(self, create):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                create()


class BorrowRequestModelTests(BorrowModelsTestMixin, TestCase):
    def create_request(self, **extra):
        values = {"reader": self.reader, "book": self.book}
        values.update(extra)
        return BorrowRequest.objects.create(**values)

    def test_defaults(self):
        request = self.create_request()

        self.assertEqual(request.status, BorrowRequest.Status.PENDING)
        self.assertIsNotNone(request.created_at)
        self.assertIsNone(request.decided_at)
        self.assertIsNone(request.decided_by)
        self.assertEqual(request.rejection_reason, "")

    def test_decided_history_is_allowed_for_same_reader_and_book(self):
        self.create_request(status=BorrowRequest.Status.APPROVED, decided_by=self.librarian)
        self.create_request(status=BorrowRequest.Status.REJECTED, decided_by=self.librarian)
        self.create_request(status=BorrowRequest.Status.REJECTED, decided_by=self.librarian)
        self.create_request()

        self.assertEqual(
            BorrowRequest.objects.filter(reader=self.reader, book=self.book).count(), 4
        )

    def test_second_pending_request_for_same_reader_and_book_is_rejected_by_db(self):
        self.create_request()

        self.assert_integrity_error(self.create_request)
        self.assertEqual(BorrowRequest.objects.count(), 1)

    def test_pending_requests_for_other_reader_or_book_are_allowed(self):
        self.create_request()
        self.create_request(reader=self.other_reader)
        self.create_request(book=self.other_book)

        self.assertEqual(BorrowRequest.objects.filter(status="PENDING").count(), 3)

    def test_pending_can_be_reopened_after_the_previous_one_is_decided(self):
        first = self.create_request()
        first.status = BorrowRequest.Status.REJECTED
        first.save(update_fields=["status"])

        self.create_request()

        self.assertEqual(BorrowRequest.objects.filter(status="PENDING").count(), 1)

    def test_reader_and_book_with_requests_cannot_be_deleted(self):
        self.create_request(decided_by=self.librarian)

        for instance in (self.reader, self.book, self.librarian):
            with self.subTest(instance=str(instance)):
                with self.assertRaises(ProtectedError):
                    instance.delete()


class BorrowModelTests(BorrowModelsTestMixin, TestCase):
    def create_borrow(self, **extra):
        values = {"reader": self.reader, "book": self.book, "created_by": self.librarian}
        values.update(extra)
        return Borrow.objects.create(**values)

    def test_defaults_and_direct_borrow_without_request(self):
        borrow = self.create_borrow()

        self.assertEqual(borrow.status, Borrow.Status.ACTIVE)
        self.assertIsNone(borrow.request)
        self.assertIsNotNone(borrow.borrowed_at)
        self.assertIsNone(borrow.returned_at)
        self.assertIsNone(borrow.returned_by)

    def test_returned_history_is_allowed_for_same_reader_and_book(self):
        for _ in range(3):
            self.create_borrow(status=Borrow.Status.RETURNED, returned_by=self.librarian)
        self.create_borrow()

        self.assertEqual(Borrow.objects.filter(reader=self.reader, book=self.book).count(), 4)

    def test_second_active_borrow_for_same_reader_and_book_is_rejected_by_db(self):
        self.create_borrow()

        self.assert_integrity_error(self.create_borrow)
        self.assertEqual(Borrow.objects.count(), 1)

    def test_active_borrows_for_other_reader_or_book_are_allowed(self):
        self.create_borrow()
        self.create_borrow(reader=self.other_reader)
        self.create_borrow(book=self.other_book)

        self.assertEqual(Borrow.objects.filter(status="ACTIVE").count(), 3)

    def test_request_links_to_one_borrow_only(self):
        request = BorrowRequest.objects.create(
            reader=self.reader,
            book=self.book,
            status=BorrowRequest.Status.APPROVED,
            decided_by=self.librarian,
        )
        borrow = self.create_borrow(request=request)

        self.assertEqual(request.borrow, borrow)
        self.assert_integrity_error(
            lambda: self.create_borrow(request=request, status=Borrow.Status.RETURNED)
        )

    def test_many_direct_borrows_may_have_no_request(self):
        self.create_borrow(status=Borrow.Status.RETURNED)
        self.create_borrow()
        self.create_borrow(reader=self.other_reader)

        self.assertEqual(Borrow.objects.filter(request__isnull=True).count(), 3)

    def test_linked_request_and_users_cannot_be_deleted(self):
        request = BorrowRequest.objects.create(
            reader=self.reader, book=self.book, status=BorrowRequest.Status.APPROVED
        )
        self.create_borrow(request=request, returned_by=self.librarian)

        for instance in (request, self.reader, self.librarian, self.book):
            with self.subTest(instance=str(instance)):
                with self.assertRaises(ProtectedError):
                    instance.delete()
