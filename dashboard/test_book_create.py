import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import CustomUser, Governorate, Library
from books.models import Author, Book, Category


PASSWORD = "StrongPass123!"
BOOKS_URL = "/dashboard/books/"


class BookCreateTestMixin:
    """Two governorates; governorate A has two libraries, governorate B has one."""

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
        self.librarian_a1 = self.create_user(
            "librarian_a1", CustomUser.Role.LIBRARIAN, library=self.library_a1
        )
        self.reader_a = self.create_user("reader_a", CustomUser.Role.READER, governorate=self.gov_a)

        self.author = Author.objects.create(name="Author One")
        self.category = Category.objects.create(name="Category One")

    def create_user(self, username, role, **extra):
        return CustomUser.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password=PASSWORD,
            role=role,
            **extra,
        )

    def payload(self, **extra):
        data = {
            "title": "New Book",
            "description": "desc",
            "author_id": self.author.id,
            "category_id": self.category.id,
            "total_copies": 3,
        }
        data.update(extra)
        return data

    def post_book(self, user, data, format="json"):
        self.client.force_authenticate(user=user)
        return self.client.post(BOOKS_URL, data, format=format)

    def assert_rejected_on_library(self, response):
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["code"], "VALIDATION_ERROR")
        self.assertIn("library", response.data["errors"])


class MinistryBookCreateTests(BookCreateTestMixin, APITestCase):
    def test_creates_books_in_libraries_of_two_governorates(self):
        for library in (self.library_a1, self.library_b):
            with self.subTest(library=library.name):
                response = self.post_book(self.ministry, self.payload(library=library.id))

                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                book = Book.objects.get(pk=response.data["data"]["id"])
                self.assertEqual(book.library_id, library.id)

    def test_superuser_chooses_library(self):
        response = self.post_book(self.superuser, self.payload(library=self.library_b.id))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["library"], self.library_b.id)

    def test_library_is_required(self):
        response = self.post_book(self.ministry, self.payload())

        self.assert_rejected_on_library(response)
        self.assertFalse(Book.objects.exists())

    def test_null_and_missing_ids_are_rejected(self):
        for value in (None, 999999, "abc"):
            with self.subTest(value=value):
                response = self.post_book(self.ministry, self.payload(library=value))
                self.assert_rejected_on_library(response)

        self.assertFalse(Book.objects.exists())

    def test_inactive_library_or_governorate_is_rejected(self):
        inactive_library = Library.objects.create(
            name="Closed Library", governorate=self.gov_a, is_active=False
        )
        inactive_governorate = Governorate.objects.create(name="Closed Gov", is_active=False)
        library_in_inactive_gov = Library.objects.create(
            name="Library In Closed Gov", governorate=inactive_governorate
        )

        for library in (inactive_library, library_in_inactive_gov):
            with self.subTest(library=library.name):
                response = self.post_book(self.ministry, self.payload(library=library.id))
                self.assert_rejected_on_library(response)

        self.assertFalse(Book.objects.exists())


class GovernorateAdminBookCreateTests(BookCreateTestMixin, APITestCase):
    def test_creates_in_any_library_of_own_governorate(self):
        for library in (self.library_a1, self.library_a2):
            with self.subTest(library=library.name):
                response = self.post_book(self.gov_admin_a, self.payload(library=library.id))

                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                self.assertEqual(response.data["data"]["governorate"], self.gov_a.id)

    def test_library_is_required(self):
        response = self.post_book(self.gov_admin_a, self.payload())

        self.assert_rejected_on_library(response)

    def test_other_governorate_library_is_rejected_without_details(self):
        response = self.post_book(self.gov_admin_a, self.payload(library=self.library_b.id))

        self.assert_rejected_on_library(response)
        self.assertNotIn(self.library_b.name, str(response.data))
        self.assertNotIn(self.gov_b.name, str(response.data))
        self.assertFalse(Book.objects.exists())

    def test_out_of_scope_and_missing_ids_share_the_same_error(self):
        out_of_scope = self.post_book(self.gov_admin_a, self.payload(library=self.library_b.id))
        missing = self.post_book(self.gov_admin_a, self.payload(library=999999))

        self.assertEqual(out_of_scope.data["errors"], missing.data["errors"])


class LibrarianBookCreateTests(BookCreateTestMixin, APITestCase):
    def test_library_defaults_to_own_library(self):
        response = self.post_book(self.librarian_a1, self.payload())

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        book = Book.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(book.library_id, self.library_a1.id)

    def test_sending_own_library_is_accepted(self):
        response = self.post_book(self.librarian_a1, self.payload(library=self.library_a1.id))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["library"], self.library_a1.id)

    def test_other_library_is_rejected_even_in_same_governorate(self):
        for library in (self.library_a2, self.library_b):
            with self.subTest(library=library.name):
                response = self.post_book(self.librarian_a1, self.payload(library=library.id))
                self.assert_rejected_on_library(response)

        self.assertFalse(Book.objects.exists())

    def test_null_library_is_rejected_not_defaulted(self):
        response = self.post_book(self.librarian_a1, self.payload(library=None))

        self.assert_rejected_on_library(response)
        self.assertFalse(Book.objects.exists())

    def test_inactive_own_library_is_rejected(self):
        self.library_a1.is_active = False
        self.library_a1.save()

        response = self.post_book(self.librarian_a1, self.payload())

        self.assert_rejected_on_library(response)
        self.assertFalse(Book.objects.exists())


class BookCreateAccessTests(BookCreateTestMixin, APITestCase):
    def test_reader_cannot_create(self):
        response = self.post_book(self.reader_a, self.payload(library=self.library_a1.id))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["code"], "PERMISSION_DENIED")
        self.assertFalse(Book.objects.exists())

    def test_anonymous_cannot_create(self):
        response = self.client.post(BOOKS_URL, self.payload(library=self.library_a1.id), format="json")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(Book.objects.exists())

    def test_other_book_actions_are_not_widened(self):
        book = Book.objects.create(
            title="Existing", description="desc", library=self.library_a1, is_archived=True
        )
        # list/retrieve are covered in test_book_read_scope.py and
        # PATCH/archive/restore in test_book_update_archive.py.
        requests = [
            ("put", f"{BOOKS_URL}{book.id}/", status.HTTP_405_METHOD_NOT_ALLOWED),
            ("get", f"{BOOKS_URL}export/", status.HTTP_403_FORBIDDEN),
        ]
        for user in (self.ministry, self.gov_admin_a, self.librarian_a1):
            self.client.force_authenticate(user=user)
            for method, url, expected in requests:
                with self.subTest(user=user.username, method=method, url=url):
                    response = getattr(self.client, method)(url, {"title": "Hijack"}, format="json")
                    self.assertEqual(response.status_code, expected)

        book.refresh_from_db()
        self.assertEqual(book.title, "Existing")
        self.assertTrue(book.is_archived)

    def test_list_response_is_enveloped(self):
        Book.objects.create(title="Existing", description="desc", library=self.library_a1)
        self.client.force_authenticate(user=self.superuser)

        response = self.client.get(BOOKS_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["code"], "BOOKS_RETRIEVED")
        self.assertEqual(response.data["data"]["count"], 1)
        self.assertEqual(len(response.data["data"]["results"]), 1)


class BookCreatePayloadTests(BookCreateTestMixin, APITestCase):
    def test_response_envelope_and_organization_fields(self):
        response = self.post_book(self.ministry, self.payload(library=self.library_a2.id))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["code"], "BOOK_CREATED")
        self.assertTrue(response.data["message"])
        self.assertEqual(response.data["meta"]["requester_role"]["code"], "MINISTRY_ADMIN")
        data = response.data["data"]
        self.assertEqual(data["library"], self.library_a2.id)
        self.assertEqual(data["library_name"], "Library A2")
        self.assertEqual(data["governorate"], self.gov_a.id)
        self.assertEqual(data["governorate_name"], "Governorate A")
        self.assertEqual(data["total_copies"], 3)
        self.assertEqual(data["available_copies"], 3)
        self.assertNotIn("count", data)
        self.assertNotIn("results", data)

    def test_author_and_category_follow_current_contract(self):
        response = self.post_book(self.ministry, self.payload(library=self.library_a1.id))

        data = response.data["data"]
        self.assertEqual(data["author"], {"id": self.author.id, "name": "Author One"})
        self.assertEqual(data["category"], {"id": self.category.id, "name": "Category One"})
        book = Book.objects.get(pk=data["id"])
        self.assertEqual((book.author_id, book.category_id), (self.author.id, self.category.id))

    def test_forbidden_and_unknown_fields_are_rejected(self):
        forbidden = {
            "id": 50,
            "library_name": "X",
            "governorate": self.gov_b.id,
            "governorate_name": "X",
            "created_at": "2020-01-01T00:00:00Z",
            "available_copies": 99,
            "count_borrowed": 5,
            "is_avaiable": False,
            "is_archived": True,
            "author": self.author.id,
            "unknown_field": "x",
        }
        for field, value in forbidden.items():
            with self.subTest(field=field):
                response = self.post_book(
                    self.ministry, self.payload(library=self.library_a1.id, **{field: value})
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(field, response.data["errors"])

        self.assertFalse(Book.objects.exists())

    def test_invalid_model_values_are_validation_errors(self):
        invalid = [
            {"title": "x" * 101},
            {"description": ""},
            {"author_id": 999999},
        ]
        for extra in invalid:
            with self.subTest(extra=extra):
                response = self.post_book(
                    self.ministry, self.payload(library=self.library_a1.id, **extra)
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertFalse(Book.objects.exists())

    def test_failed_validation_leaves_no_partial_book(self):
        response = self.post_book(
            self.gov_admin_a,
            self.payload(library=self.library_b.id, title="Should Not Exist"),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Book.objects.filter(title="Should Not Exist").exists())
        self.assertEqual(Book.objects.count(), 0)


class BookCreateCopiesTests(BookCreateTestMixin, APITestCase):
    """available_copies and is_avaiable are derived from total_copies on create."""

    def assert_copies(self, response, total, available, is_available):
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.data["data"]
        self.assertEqual(
            (data["total_copies"], data["available_copies"], data["is_avaiable"]),
            (total, available, is_available),
        )
        book = Book.objects.get(pk=data["id"])
        self.assertEqual(
            (book.total_copies, book.available_copies, book.is_avaiable),
            (total, available, is_available),
        )

    def assert_rejected_on(self, response, field):
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "VALIDATION_ERROR")
        self.assertIn(field, response.data["errors"])
        self.assertFalse(Book.objects.exists())

    def test_zero_copies_creates_unavailable_book(self):
        response = self.post_book(
            self.ministry, self.payload(library=self.library_a1.id, total_copies=0)
        )

        self.assert_copies(response, total=0, available=0, is_available=False)

    def test_positive_copies_creates_available_book(self):
        response = self.post_book(
            self.ministry, self.payload(library=self.library_a1.id, total_copies=3)
        )

        self.assert_copies(response, total=3, available=3, is_available=True)

    def test_multipart_copies_are_derived_the_same_way(self):
        for total, is_available in ((0, False), (5, True)):
            with self.subTest(total=total):
                response = self.post_book(
                    self.librarian_a1,
                    self.payload(total_copies=str(total)),
                    format="multipart",
                )
                self.assert_copies(response, total, total, is_available)

    def test_negative_copies_are_rejected(self):
        response = self.post_book(
            self.ministry, self.payload(library=self.library_a1.id, total_copies=-1)
        )

        self.assert_rejected_on(response, "total_copies")

    def test_missing_or_invalid_copies_are_rejected(self):
        for value in (None, "abc", 1.5):
            with self.subTest(value=value):
                response = self.post_book(
                    self.ministry, self.payload(library=self.library_a1.id, total_copies=value)
                )
                self.assert_rejected_on(response, "total_copies")

        data = self.payload(library=self.library_a1.id)
        del data["total_copies"]
        response = self.post_book(self.ministry, data)
        self.assert_rejected_on(response, "total_copies")

    def test_client_cannot_set_available_copies(self):
        for value in (99, 5, 0):
            with self.subTest(available_copies=value):
                response = self.post_book(
                    self.ministry,
                    self.payload(
                        library=self.library_a1.id, total_copies=5, available_copies=value
                    ),
                )
                self.assert_rejected_on(response, "available_copies")

    def test_client_cannot_set_is_avaiable(self):
        cases = ((0, True), (5, False), (5, True))
        for total, value in cases:
            with self.subTest(total_copies=total, is_avaiable=value):
                response = self.post_book(
                    self.ministry,
                    self.payload(
                        library=self.library_a1.id, total_copies=total, is_avaiable=value
                    ),
                )
                self.assert_rejected_on(response, "is_avaiable")

    def test_forbidden_copy_fields_are_rejected_in_multipart(self):
        for field, value in (("available_copies", "99"), ("is_avaiable", "true")):
            with self.subTest(field=field):
                response = self.post_book(
                    self.librarian_a1,
                    self.payload(total_copies="5", **{field: value}),
                    format="multipart",
                )
                self.assert_rejected_on(response, field)


class BookCreateMultipartTests(BookCreateTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.media_root = tempfile.mkdtemp()
        self.media_override = override_settings(MEDIA_ROOT=self.media_root)
        self.media_override.enable()

    def tearDown(self):
        self.media_override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)
        super().tearDown()

    def make_image(self):
        buffer = io.BytesIO()
        Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")
        return SimpleUploadedFile("cover.png", buffer.getvalue(), content_type="image/png")

    def test_multipart_with_image(self):
        response = self.post_book(
            self.librarian_a1,
            self.payload(image=self.make_image()),
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        book = Book.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(book.library_id, self.library_a1.id)
        self.assertTrue(book.image.name.startswith("books/"))
        self.assertTrue(response.data["data"]["image"])

    def test_multipart_with_library_id_as_text(self):
        response = self.post_book(
            self.gov_admin_a,
            self.payload(library=str(self.library_a2.id)),
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["library"], self.library_a2.id)

    def test_multipart_rejection_keeps_no_book(self):
        response = self.post_book(
            self.librarian_a1,
            self.payload(library=str(self.library_b.id), image=self.make_image()),
            format="multipart",
        )

        self.assert_rejected_on_library(response)
        self.assertFalse(Book.objects.exists())
