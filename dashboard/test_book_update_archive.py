from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import CustomUser, Governorate, Library
from books.models import Author, Book, Category


PASSWORD = "StrongPass123!"
BOOKS_URL = "/dashboard/books/"


class BookManagementTestMixin:
    """Governorate A: libraries A1, A2 and an inactive one. Governorate B: library B."""

    def setUp(self):
        self.gov_a = Governorate.objects.create(name="Governorate A")
        self.gov_b = Governorate.objects.create(name="Governorate B")
        self.library_a1 = Library.objects.create(name="Library A1", governorate=self.gov_a)
        self.library_a2 = Library.objects.create(name="Library A2", governorate=self.gov_a)
        self.library_a_closed = Library.objects.create(
            name="Library A Closed", governorate=self.gov_a, is_active=False
        )
        self.library_b = Library.objects.create(name="Library B", governorate=self.gov_b)

        self.superuser = CustomUser.objects.create_superuser(
            username="root", email="root@example.com", password=PASSWORD
        )
        self.ministry = self.create_user("ministry", CustomUser.Role.MINISTRY_ADMIN)
        self.gov_admin_a = self.create_user(
            "gov_admin_a", CustomUser.Role.GOVERNORATE_ADMIN, governorate=self.gov_a
        )
        self.librarian_a1 = self.create_user(
            "librarian_a1", CustomUser.Role.LIBRARIAN, library=self.library_a1
        )
        self.reader_a = self.create_user("reader_a", CustomUser.Role.READER, governorate=self.gov_a)

        self.author = Author.objects.create(name="Author One")
        self.other_author = Author.objects.create(name="Author Two")
        self.category = Category.objects.create(name="Category One")
        self.other_category = Category.objects.create(name="Category Two")

        self.book_a1 = self.create_book("Book A1", self.library_a1)
        self.book_a2 = self.create_book("Book A2", self.library_a2)
        self.book_a_closed = self.create_book("Book A Closed", self.library_a_closed)
        self.book_b = self.create_book("Book B", self.library_b)

    def create_user(self, username, role, **extra):
        return CustomUser.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password=PASSWORD,
            role=role,
            **extra,
        )

    def create_book(self, title, library, **extra):
        extra.setdefault("author", self.author)
        extra.setdefault("category", self.category)
        return Book.objects.create(title=title, description="desc", library=library, **extra)

    def set_copies(self, book, total, available, count_borrowed=0, is_archived=None):
        """Store quantities directly, as an active borrowing would leave them."""
        values = {
            "total_copies": total,
            "available_copies": available,
            "is_avaiable": available > 0,
            "count_borrowed": count_borrowed,
        }
        if is_archived is not None:
            values["is_archived"] = is_archived
        Book.objects.filter(pk=book.pk).update(**values)
        book.refresh_from_db()
        return book

    def snapshot(self, book):
        book.refresh_from_db()
        return (
            book.title,
            book.library_id,
            book.total_copies,
            book.available_copies,
            book.is_avaiable,
            book.count_borrowed,
            book.is_archived,
        )

    def url(self, book, suffix=""):
        return f"{BOOKS_URL}{book.id}/{suffix}"

    def patch(self, user, book, data, format="json"):
        self.client.force_authenticate(user=user)
        return self.client.patch(self.url(book), data, format=format)

    def archive(self, user, book):
        self.client.force_authenticate(user=user)
        return self.client.delete(self.url(book))

    def restore(self, user, book):
        self.client.force_authenticate(user=user)
        return self.client.post(self.url(book, "restore/"))

    def assert_success(self, response, code):
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["code"], code)
        return response.data["data"]

    def assert_validation_error(self, response, field):
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "VALIDATION_ERROR")
        self.assertIn(field, response.data["errors"])

    def assert_not_found(self, response, book):
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["code"], "NOT_FOUND")
        self.assertNotIn(book.title, str(response.data))


class BookUpdatePermissionTests(BookManagementTestMixin, APITestCase):
    def test_ministry_and_superuser_update_books_in_any_governorate(self):
        for user in (self.ministry, self.superuser):
            for book in (self.book_a1, self.book_b):
                with self.subTest(user=user.username, book=book.title):
                    title = f"{user.username} {book.id}"
                    response = self.patch(user, book, {"title": title})

                    self.assert_success(response, "BOOK_UPDATED")
                    book.refresh_from_db()
                    self.assertEqual(book.title, title)

    def test_governorate_admin_updates_books_of_own_governorate(self):
        for book in (self.book_a1, self.book_a2, self.book_a_closed):
            with self.subTest(book=book.title):
                response = self.patch(self.gov_admin_a, book, {"title": "Updated"})

                self.assert_success(response, "BOOK_UPDATED")
                book.refresh_from_db()
                self.assertEqual(book.title, "Updated")

    def test_governorate_admin_gets_not_found_for_other_governorate(self):
        before = self.snapshot(self.book_b)

        response = self.patch(self.gov_admin_a, self.book_b, {"title": "Hijack"})

        self.assert_not_found(response, self.book_b)
        self.assertEqual(self.snapshot(self.book_b), before)

    def test_librarian_updates_own_library_books_including_archived(self):
        self.set_copies(self.book_a1, 1, 1, is_archived=True)

        response = self.patch(self.librarian_a1, self.book_a1, {"title": "Updated"})

        self.assert_success(response, "BOOK_UPDATED")
        self.book_a1.refresh_from_db()
        self.assertEqual(self.book_a1.title, "Updated")
        self.assertTrue(self.book_a1.is_archived)

    def test_librarian_gets_not_found_outside_own_library(self):
        for book in (self.book_a2, self.book_a_closed, self.book_b):
            with self.subTest(book=book.title):
                before = self.snapshot(book)
                response = self.patch(self.librarian_a1, book, {"title": "Hijack"})

                self.assert_not_found(response, book)
                self.assertEqual(self.snapshot(book), before)

    def test_reader_is_forbidden(self):
        before = self.snapshot(self.book_a1)

        response = self.patch(self.reader_a, self.book_a1, {"title": "Hijack"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["code"], "PERMISSION_DENIED")
        self.assertEqual(self.snapshot(self.book_a1), before)

    def test_anonymous_is_unauthorized(self):
        response = self.client.patch(self.url(self.book_a1), {"title": "Hijack"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.book_a1.refresh_from_db()
        self.assertEqual(self.book_a1.title, "Book A1")


class BookUpdateInputTests(BookManagementTestMixin, APITestCase):
    def test_organization_fields_are_rejected_and_library_never_changes(self):
        forbidden = {
            "library": self.library_b.id,
            "library_name": "Library B",
            "governorate": self.gov_b.id,
            "governorate_name": "Governorate B",
        }
        for field, value in forbidden.items():
            with self.subTest(field=field):
                response = self.patch(self.ministry, self.book_a1, {field: value, "title": "X"})
                self.assert_validation_error(response, field)

        # Even resending the current library is not accepted: library is fixed.
        response = self.patch(self.ministry, self.book_a1, {"library": self.library_a1.id})
        self.assert_validation_error(response, "library")

        self.book_a1.refresh_from_db()
        self.assertEqual(self.book_a1.library_id, self.library_a1.id)
        self.assertEqual(self.book_a1.title, "Book A1")

    def test_server_managed_and_unknown_fields_are_rejected(self):
        self.set_copies(self.book_a1, 5, 3, count_borrowed=4)
        before = self.snapshot(self.book_a1)
        forbidden = {
            "available_copies": 99,
            "is_avaiable": False,
            "count_borrowed": 0,
            "is_archived": True,
            "id": 999,
            "created_at": "2020-01-01T00:00:00Z",
            "unknown_field": "x",
        }
        for field, value in forbidden.items():
            with self.subTest(field=field):
                response = self.patch(self.ministry, self.book_a1, {field: value})
                self.assert_validation_error(response, field)

        self.assertEqual(self.snapshot(self.book_a1), before)

    def test_book_detail_fields_are_saved(self):
        data = {
            "title": "New Title",
            "description": "New description",
            "author_id": self.other_author.id,
            "category_id": self.other_category.id,
            "pages": 321,
            "isbn": "9781234567897",
            "possition": "B-12",
            "publication_year": 2001,
        }

        response = self.patch(self.librarian_a1, self.book_a1, data)

        payload = self.assert_success(response, "BOOK_UPDATED")
        self.book_a1.refresh_from_db()
        self.assertEqual(self.book_a1.title, "New Title")
        self.assertEqual(self.book_a1.description, "New description")
        self.assertEqual(self.book_a1.author_id, self.other_author.id)
        self.assertEqual(self.book_a1.category_id, self.other_category.id)
        self.assertEqual(self.book_a1.pages, 321)
        self.assertEqual(self.book_a1.isbn, "9781234567897")
        self.assertEqual(self.book_a1.possition, "B-12")
        self.assertEqual(self.book_a1.publication_year, 2001)
        self.assertEqual(payload["author"], {"id": self.other_author.id, "name": "Author Two"})
        self.assertEqual(payload["category"], {"id": self.other_category.id, "name": "Category Two"})

    def test_response_keeps_organization_fields(self):
        response = self.patch(self.gov_admin_a, self.book_a2, {"title": "Updated"})

        payload = self.assert_success(response, "BOOK_UPDATED")
        self.assertEqual(payload["id"], self.book_a2.id)
        self.assertEqual(payload["title"], "Updated")
        self.assertEqual(payload["library"], self.library_a2.id)
        self.assertEqual(payload["library_name"], "Library A2")
        self.assertEqual(payload["governorate"], self.gov_a.id)
        self.assertEqual(payload["governorate_name"], "Governorate A")
        for field in ("total_copies", "available_copies", "is_avaiable", "is_archived"):
            self.assertIn(field, payload)

    def test_multipart_patch_is_supported(self):
        response = self.patch(
            self.librarian_a1,
            self.book_a1,
            {"title": "Multipart Title", "total_copies": "4"},
            format="multipart",
        )

        self.assert_success(response, "BOOK_UPDATED")
        self.book_a1.refresh_from_db()
        self.assertEqual((self.book_a1.title, self.book_a1.total_copies), ("Multipart Title", 4))

    def test_invalid_detail_values_are_rejected_without_changes(self):
        before = self.snapshot(self.book_a1)
        invalid = [
            ("title", {"title": "x" * 101}),
            ("description", {"description": ""}),
            ("author_id", {"author_id": 999999}),
        ]
        for field, data in invalid:
            with self.subTest(field=field):
                response = self.patch(self.ministry, self.book_a1, data)
                self.assert_validation_error(response, field)

        self.assertEqual(self.snapshot(self.book_a1), before)


class BookUpdateCopiesTests(BookManagementTestMixin, APITestCase):
    """Book A1 starts with 5 copies, 2 of them borrowed (3 available)."""

    def setUp(self):
        super().setUp()
        self.set_copies(self.book_a1, 5, 3, count_borrowed=6)

    def assert_copies(self, response, total, available, is_available):
        payload = self.assert_success(response, "BOOK_UPDATED")
        self.assertEqual(
            (payload["total_copies"], payload["available_copies"], payload["is_avaiable"]),
            (total, available, is_available),
        )
        self.book_a1.refresh_from_db()
        self.assertEqual(
            (
                self.book_a1.total_copies,
                self.book_a1.available_copies,
                self.book_a1.is_avaiable,
            ),
            (total, available, is_available),
        )
        self.assertEqual(self.book_a1.count_borrowed, 6)

    def test_increasing_total_adds_available_copies(self):
        response = self.patch(self.librarian_a1, self.book_a1, {"total_copies": 8})

        self.assert_copies(response, total=8, available=6, is_available=True)

    def test_decreasing_total_keeps_borrowed_copies(self):
        response = self.patch(self.librarian_a1, self.book_a1, {"total_copies": 4})

        self.assert_copies(response, total=4, available=2, is_available=True)

    def test_decreasing_total_to_borrowed_count_makes_book_unavailable(self):
        response = self.patch(self.librarian_a1, self.book_a1, {"total_copies": 2})

        self.assert_copies(response, total=2, available=0, is_available=False)

    def test_unavailable_book_becomes_available_when_copies_are_added(self):
        self.set_copies(self.book_a1, 2, 0, count_borrowed=6)

        response = self.patch(self.librarian_a1, self.book_a1, {"total_copies": 3})

        self.assert_copies(response, total=3, available=1, is_available=True)

    def test_total_below_borrowed_copies_is_rejected_without_partial_update(self):
        before = self.snapshot(self.book_a1)

        response = self.patch(
            self.librarian_a1, self.book_a1, {"total_copies": 1, "title": "Should Not Save"}
        )

        self.assert_validation_error(response, "total_copies")
        self.assertEqual(self.snapshot(self.book_a1), before)

    def test_negative_and_invalid_totals_are_rejected(self):
        before = self.snapshot(self.book_a1)
        for value in (-1, None, "abc", 1.5):
            with self.subTest(value=value):
                response = self.patch(self.librarian_a1, self.book_a1, {"total_copies": value})
                self.assert_validation_error(response, "total_copies")

        self.assertEqual(self.snapshot(self.book_a1), before)

    def test_zero_total_is_allowed_without_borrowed_copies(self):
        self.set_copies(self.book_a1, 3, 3, count_borrowed=6)

        response = self.patch(self.librarian_a1, self.book_a1, {"total_copies": 0})

        self.assert_copies(response, total=0, available=0, is_available=False)

    def test_patch_without_total_keeps_quantities(self):
        response = self.patch(self.librarian_a1, self.book_a1, {"title": "Renamed"})

        self.assert_copies(response, total=5, available=3, is_available=True)


class BookPutTests(BookManagementTestMixin, APITestCase):
    def test_put_is_not_allowed_and_changes_nothing(self):
        before = self.snapshot(self.book_a1)
        data = {
            "title": "Put Title",
            "description": "desc",
            "author_id": self.author.id,
            "total_copies": 9,
        }
        for user in (self.superuser, self.ministry, self.gov_admin_a, self.librarian_a1):
            with self.subTest(user=user.username):
                self.client.force_authenticate(user=user)
                response = self.client.put(self.url(self.book_a1), data, format="json")

                self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
                self.assertEqual(response.data["code"], "METHOD_NOT_ALLOWED")

        self.assertEqual(self.snapshot(self.book_a1), before)


class BookArchiveTests(BookManagementTestMixin, APITestCase):
    def assert_archived_only(self, response, book, before):
        payload = self.assert_success(response, "BOOK_ARCHIVED")
        self.assertTrue(payload["is_archived"])
        self.assertEqual(payload["library"], book.library_id)
        self.assertTrue(Book.objects.filter(pk=book.pk).exists())
        after = self.snapshot(book)
        self.assertTrue(after[-1])
        self.assertEqual(after[:-1], before[:-1])

    def test_ministry_archives_any_book_without_touching_quantities(self):
        for book in (self.book_a1, self.book_b):
            with self.subTest(book=book.title):
                self.set_copies(book, 5, 3, count_borrowed=7)
                before = self.snapshot(book)

                response = self.archive(self.ministry, book)

                self.assert_archived_only(response, book, before)
                self.assertTrue(book.is_avaiable)

    def test_unavailable_book_stays_unavailable_when_archived(self):
        self.set_copies(self.book_a1, 0, 0)
        before = self.snapshot(self.book_a1)

        response = self.archive(self.librarian_a1, self.book_a1)

        self.assert_archived_only(response, self.book_a1, before)
        self.assertFalse(self.book_a1.is_avaiable)

    def test_governorate_admin_archives_within_own_governorate_only(self):
        for book in (self.book_a2, self.book_a_closed):
            with self.subTest(book=book.title):
                before = self.snapshot(book)
                self.assert_archived_only(self.archive(self.gov_admin_a, book), book, before)

        before = self.snapshot(self.book_b)
        self.assert_not_found(self.archive(self.gov_admin_a, self.book_b), self.book_b)
        self.assertEqual(self.snapshot(self.book_b), before)

    def test_librarian_archives_own_library_only(self):
        before = self.snapshot(self.book_a1)
        self.assert_archived_only(
            self.archive(self.librarian_a1, self.book_a1), self.book_a1, before
        )

        for book in (self.book_a2, self.book_b):
            with self.subTest(book=book.title):
                before = self.snapshot(book)
                self.assert_not_found(self.archive(self.librarian_a1, book), book)
                self.assertEqual(self.snapshot(book), before)

    def test_reader_and_anonymous_cannot_archive(self):
        before = self.snapshot(self.book_a1)

        response = self.archive(self.reader_a, self.book_a1)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=None)
        response = self.client.delete(self.url(self.book_a1))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        self.assertEqual(self.snapshot(self.book_a1), before)

    def test_archiving_an_archived_book_is_rejected(self):
        self.set_copies(self.book_a1, 5, 3, count_borrowed=2, is_archived=True)
        before = self.snapshot(self.book_a1)

        response = self.archive(self.librarian_a1, self.book_a1)

        self.assert_validation_error(response, "is_archived")
        self.assertEqual(self.snapshot(self.book_a1), before)


class BookRestoreTests(BookManagementTestMixin, APITestCase):
    def assert_restored_only(self, response, book, before):
        payload = self.assert_success(response, "BOOK_RESTORED")
        self.assertFalse(payload["is_archived"])
        after = self.snapshot(book)
        self.assertFalse(after[-1])
        self.assertEqual(after[:-1], before[:-1])

    def test_restore_within_scope_keeps_quantities(self):
        cases = (
            (self.ministry, self.book_b),
            (self.gov_admin_a, self.book_a_closed),
            (self.librarian_a1, self.book_a1),
        )
        for user, book in cases:
            with self.subTest(user=user.username, book=book.title):
                self.set_copies(book, 5, 3, count_borrowed=7, is_archived=True)
                before = self.snapshot(book)

                self.assert_restored_only(self.restore(user, book), book, before)

    def test_restore_does_not_make_unavailable_book_available(self):
        self.set_copies(self.book_a1, 5, 0, count_borrowed=5, is_archived=True)
        before = self.snapshot(self.book_a1)

        response = self.restore(self.librarian_a1, self.book_a1)

        self.assert_restored_only(response, self.book_a1, before)
        self.assertEqual(self.book_a1.available_copies, 0)
        self.assertFalse(self.book_a1.is_avaiable)

    def test_zero_copy_book_stays_unavailable_after_archive_and_restore(self):
        self.client.force_authenticate(user=self.librarian_a1)
        created = self.client.post(
            BOOKS_URL,
            {"title": "Zero", "description": "desc", "total_copies": 0},
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        book = Book.objects.get(pk=created.data["data"]["id"])
        self.assertEqual((book.available_copies, book.is_avaiable), (0, False))

        self.assert_success(self.archive(self.librarian_a1, book), "BOOK_ARCHIVED")
        payload = self.assert_success(self.restore(self.librarian_a1, book), "BOOK_RESTORED")

        book.refresh_from_db()
        self.assertFalse(book.is_archived)
        self.assertEqual((book.total_copies, book.available_copies), (0, 0))
        self.assertFalse(book.is_avaiable)
        self.assertEqual((payload["available_copies"], payload["is_avaiable"]), (0, False))

    def test_out_of_scope_restore_is_not_found(self):
        cases = (
            (self.gov_admin_a, self.book_b),
            (self.librarian_a1, self.book_a2),
            (self.librarian_a1, self.book_b),
        )
        for user, book in cases:
            with self.subTest(user=user.username, book=book.title):
                self.set_copies(book, 1, 1, is_archived=True)
                before = self.snapshot(book)

                self.assert_not_found(self.restore(user, book), book)
                self.assertEqual(self.snapshot(book), before)

    def test_reader_cannot_restore(self):
        self.set_copies(self.book_a1, 1, 1, is_archived=True)

        response = self.restore(self.reader_a, self.book_a1)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.book_a1.refresh_from_db()
        self.assertTrue(self.book_a1.is_archived)

    def test_restoring_a_non_archived_book_is_rejected(self):
        before = self.snapshot(self.book_a1)

        response = self.restore(self.librarian_a1, self.book_a1)

        self.assert_validation_error(response, "is_archived")
        self.assertEqual(self.snapshot(self.book_a1), before)
