import json
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import Client
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import CustomUser, Governorate, Library
from books.models import Book, FavoriteBook


PASSWORD = "StrongPass123!"
FAVORITES_URL = "/dashboard/favorites/"


class FavoriteApiTestMixin:
    def setUp(self):
        self.gov_a = Governorate.objects.create(name="Governorate A")
        self.gov_b = Governorate.objects.create(name="Governorate B")
        self.gov_inactive = Governorate.objects.create(name="Inactive Governorate", is_active=False)
        self.library_a = Library.objects.create(name="Library A", governorate=self.gov_a)
        self.library_b = Library.objects.create(name="Library B", governorate=self.gov_b)
        self.library_inactive = Library.objects.create(
            name="Inactive Library", governorate=self.gov_a, is_active=False
        )
        self.library_in_inactive_gov = Library.objects.create(
            name="Library in inactive governorate", governorate=self.gov_inactive
        )

        self.reader = self.create_user("reader", CustomUser.Role.READER, governorate=self.gov_a)
        self.other_reader = self.create_user(
            "other_reader", CustomUser.Role.READER, governorate=self.gov_a
        )
        self.librarian = self.create_user(
            "librarian", CustomUser.Role.LIBRARIAN, library=self.library_a
        )
        self.gov_admin = self.create_user(
            "gov_admin", CustomUser.Role.GOVERNORATE_ADMIN, governorate=self.gov_a
        )
        self.ministry = self.create_user("ministry", CustomUser.Role.MINISTRY_ADMIN)
        self.superuser = CustomUser.objects.create_superuser(
            username="root", email="root@example.com", password=PASSWORD
        )

        self.book = self.create_book("Visible book", self.library_a)
        self.other_book = self.create_book("Other governorate", self.library_b)
        self.archived_book = self.create_book("Archived", self.library_a, is_archived=True)
        self.inactive_library_book = self.create_book("Inactive library", self.library_inactive)
        self.inactive_governorate_book = self.create_book(
            "Inactive governorate", self.library_in_inactive_gov
        )

    def create_user(self, username, role, **extra):
        return CustomUser.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password=PASSWORD,
            role=role,
            **extra,
        )

    def create_book(self, title, library, **extra):
        return Book.objects.create(
            title=title,
            description="desc",
            library=library,
            total_copies=1,
            **extra,
        )

    def favorite_url(self, book_or_id):
        pk = getattr(book_or_id, "pk", book_or_id)
        return f"/dashboard/books/{pk}/favorite/"

    def request_as(self, method, user, url, data=None):
        self.client.force_authenticate(user=user)
        return getattr(self.client, method)(url, data=data, format="json")

    def assert_success(self, response, code, expected_status=status.HTTP_200_OK):
        self.assertEqual(response.status_code, expected_status, response.data)
        self.assertIs(response.data["success"], True)
        self.assertEqual(response.data["code"], code)
        self.assertTrue(response.data["message"])
        self.assertIn("data", response.data)

    def assert_error(self, response, expected_status, code):
        self.assertEqual(response.status_code, expected_status, response.data)
        self.assertIs(response.data["success"], False)
        self.assertEqual(response.data["code"], code)


class AuthenticationAndPermissionTests(FavoriteApiTestMixin, APITestCase):
    def test_anonymous_is_rejected_for_every_favorite_operation(self):
        self.client.force_authenticate(user=None)
        for method, url in (
            ("post", self.favorite_url(self.book)),
            ("delete", self.favorite_url(self.book)),
            ("get", FAVORITES_URL),
        ):
            with self.subTest(method=method):
                response = getattr(self.client, method)(url, {}, format="json")
                self.assert_error(response, status.HTTP_401_UNAUTHORIZED, "AUTHENTICATION_REQUIRED")

    def test_non_reader_roles_are_rejected_for_every_favorite_operation(self):
        for user in (self.librarian, self.gov_admin, self.ministry, self.superuser):
            for method, url in (
                ("post", self.favorite_url(self.book)),
                ("delete", self.favorite_url(self.book)),
                ("get", FAVORITES_URL),
            ):
                with self.subTest(role=user.username, method=method):
                    response = self.request_as(method, user, url, {})
                    self.assert_error(response, status.HTTP_403_FORBIDDEN, "PERMISSION_DENIED")


class FavoriteCreateTests(FavoriteApiTestMixin, APITestCase):
    def test_reader_adds_visible_book_and_user_comes_from_request(self):
        response = self.request_as("post", self.reader, self.favorite_url(self.book), {})

        self.assert_success(response, "FAVORITE_CREATED", status.HTTP_201_CREATED)
        favorite = FavoriteBook.objects.get()
        self.assertEqual((favorite.user_id, favorite.book_id), (self.reader.pk, self.book.pk))
        self.assertEqual(response.data["data"]["id"], self.book.pk)

    def test_post_accepts_no_body_but_rejects_every_input_field(self):
        self.client.force_authenticate(user=self.reader)
        response = self.client.post(self.favorite_url(self.book))
        self.assert_success(response, "FAVORITE_CREATED", status.HTTP_201_CREATED)

        for field in ("unexpected", "user_id", "book_id"):
            with self.subTest(field=field):
                other = self.create_book(f"Book {field}", self.library_a)
                response = self.client.post(
                    self.favorite_url(other), {field: 1}, format="json"
                )
                self.assert_error(response, status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR")
                self.assertFalse(FavoriteBook.objects.filter(book=other).exists())

    def test_duplicate_add_is_idempotent(self):
        FavoriteBook.objects.create(user=self.reader, book=self.book)

        response = self.request_as("post", self.reader, self.favorite_url(self.book), {})

        self.assert_success(response, "FAVORITE_ALREADY_EXISTS")
        self.assertEqual(FavoriteBook.objects.filter(user=self.reader, book=self.book).count(), 1)

    def test_out_of_scope_or_missing_books_are_not_disclosed(self):
        for book_id in (
            self.other_book.pk,
            self.archived_book.pk,
            self.inactive_library_book.pk,
            self.inactive_governorate_book.pk,
            999999,
        ):
            with self.subTest(book_id=book_id):
                response = self.request_as("post", self.reader, self.favorite_url(book_id), {})
                self.assert_error(response, status.HTTP_404_NOT_FOUND, "NOT_FOUND")
        self.assertEqual(FavoriteBook.objects.count(), 0)

    def test_reader_without_governorate_sees_book_as_missing(self):
        # An unsaved user represents legacy/inconsistent data without bypassing
        # the database constraint that correctly prevents creating such rows.
        reader_without_scope = CustomUser(username="scope_less", role=CustomUser.Role.READER)

        response = self.request_as(
            "post", reader_without_scope, self.favorite_url(self.book), {}
        )

        self.assert_error(response, status.HTTP_404_NOT_FOUND, "NOT_FOUND")


class FavoriteListTests(FavoriteApiTestMixin, APITestCase):
    def test_list_returns_only_current_users_books_in_book_shape(self):
        FavoriteBook.objects.create(user=self.reader, book=self.book)
        FavoriteBook.objects.create(user=self.other_reader, book=self.create_book("Other", self.library_a))

        response = self.request_as("get", self.reader, FAVORITES_URL)

        self.assert_success(response, "FAVORITES_RETRIEVED")
        results = response.data["data"]["results"]
        self.assertEqual([item["id"] for item in results], [self.book.pk])
        self.assertIn("library_name", results[0])
        self.assertNotIn("favorite_id", results[0])
        self.assertNotIn("favorited_at", results[0])

    def test_list_is_paginated_at_ten_books_without_duplicates(self):
        books = [self.create_book(f"Favorite {index}", self.library_a) for index in range(12)]
        FavoriteBook.objects.bulk_create(
            [FavoriteBook(user=self.reader, book=book) for book in books]
        )

        response = self.request_as("get", self.reader, FAVORITES_URL, {"page_size": 100})

        self.assert_success(response, "FAVORITES_RETRIEVED")
        data = response.data["data"]
        self.assertEqual(data["count"], 12)
        self.assertEqual(len(data["results"]), 10)
        ids = [item["id"] for item in data["results"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_list_orders_by_favorite_timestamp_then_favorite_pk(self):
        older_book = self.create_book("Older", self.library_a)
        newer_book = self.create_book("Newer", self.library_a)
        older = FavoriteBook.objects.create(user=self.reader, book=older_book)
        newer = FavoriteBook.objects.create(user=self.reader, book=newer_book)
        FavoriteBook.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=1))
        FavoriteBook.objects.filter(pk=newer.pk).update(created_at=timezone.now())

        response = self.request_as("get", self.reader, FAVORITES_URL)

        ids = [item["id"] for item in response.data["data"]["results"]]
        self.assertEqual(ids, [newer_book.pk, older_book.pk])

    def test_hidden_favorite_is_retained_and_reappears_when_access_returns(self):
        favorite = FavoriteBook.objects.create(user=self.reader, book=self.book)
        self.book.is_archived = True
        self.book.save(update_fields=["is_archived"])

        hidden = self.request_as("get", self.reader, FAVORITES_URL)
        self.assertEqual(hidden.data["data"]["results"], [])
        self.assertTrue(FavoriteBook.objects.filter(pk=favorite.pk).exists())

        self.book.is_archived = False
        self.book.save(update_fields=["is_archived"])
        visible = self.request_as("get", self.reader, FAVORITES_URL)
        self.assertEqual([item["id"] for item in visible.data["data"]["results"]], [self.book.pk])


class FavoriteDeleteTests(FavoriteApiTestMixin, APITestCase):
    def test_delete_removes_only_current_users_favorite(self):
        FavoriteBook.objects.create(user=self.reader, book=self.book)
        other = FavoriteBook.objects.create(user=self.other_reader, book=self.book)

        response = self.request_as("delete", self.reader, self.favorite_url(self.book), {})

        self.assert_success(response, "FAVORITE_REMOVED")
        self.assertFalse(FavoriteBook.objects.filter(user=self.reader, book=self.book).exists())
        self.assertTrue(FavoriteBook.objects.filter(pk=other.pk).exists())

    def test_delete_absent_or_nonexistent_book_id_is_idempotent(self):
        for book_id in (self.book.pk, 999999):
            with self.subTest(book_id=book_id):
                response = self.request_as("delete", self.reader, self.favorite_url(book_id), {})
                self.assert_success(response, "FAVORITE_ALREADY_ABSENT")

    def test_delete_works_for_archived_and_out_of_scope_books(self):
        FavoriteBook.objects.create(user=self.reader, book=self.archived_book)
        FavoriteBook.objects.create(user=self.reader, book=self.other_book)

        for book in (self.archived_book, self.other_book):
            with self.subTest(book=book.title):
                response = self.request_as("delete", self.reader, self.favorite_url(book), {})
                self.assert_success(response, "FAVORITE_REMOVED")
                self.assertFalse(FavoriteBook.objects.filter(user=self.reader, book=book).exists())

    def test_repeated_delete_is_idempotent(self):
        FavoriteBook.objects.create(user=self.reader, book=self.book)
        first = self.request_as("delete", self.reader, self.favorite_url(self.book), {})
        second = self.request_as("delete", self.reader, self.favorite_url(self.book), {})
        self.assert_success(first, "FAVORITE_REMOVED")
        self.assert_success(second, "FAVORITE_ALREADY_ABSENT")


class FavoriteDatabaseTests(FavoriteApiTestMixin, APITestCase):
    def test_database_constraint_rejects_duplicate_user_and_book(self):
        FavoriteBook.objects.create(user=self.reader, book=self.book)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                FavoriteBook.objects.create(user=self.reader, book=self.book)


class FavoriteLegacyAndSwaggerTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        response = Client().get("/api/schema/", {"format": "json"})
        cls.schema = json.loads(response.content)
        cls.paths = cls.schema["paths"]

    def methods(self, path):
        return {
            method
            for method in self.paths.get(path, {})
            if method in {"get", "post", "put", "patch", "delete"}
        }

    def test_legacy_profile_favorites_route_stays_missing(self):
        response = self.client.get("/accounts/FavoriteBooksProfileView/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_swagger_contains_only_new_favorite_operations(self):
        self.assertEqual(self.methods("/dashboard/favorites/"), {"get"})
        self.assertEqual(
            self.methods("/dashboard/books/{id}/favorite/"), {"post", "delete"}
        )
        for path in self.paths:
            with self.subTest(path=path):
                self.assertNotIn("/like/", path)
                self.assertNotIn("/unlike/", path)
                self.assertNotIn("FavoriteBooksProfileView", path)
