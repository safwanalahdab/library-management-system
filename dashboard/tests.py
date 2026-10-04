from django.apps import apps
from django.contrib import admin
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import CustomUser, Governorate, Library
from books.models import Author, Book, BorrowedBook, Category


PASSWORD = "StrongPass123!"


class DashboardTestMixin:
    def setUp(self):
        self.admin = CustomUser.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password=PASSWORD,
        )
        governorate = Governorate.objects.create(name="Governorate")
        self.library = Library.objects.create(name="Library", governorate=governorate)
        self.reader = CustomUser.objects.create_user(
            username="reader",
            email="reader@example.com",
            password=PASSWORD,
            role=CustomUser.Role.READER,
            governorate=governorate,
        )
        self.author = Author.objects.create(name="Author One")
        self.category = Category.objects.create(name="Category One")
        self.book = Book.objects.create(
            title="Borrowable Book",
            description="desc",
            author=self.author,
            category=self.category,
            total_copies=2,
            library=self.library,
        )


class UserBorrowingBlockAdminTests(DashboardTestMixin, APITestCase):
    def test_admin_can_block_and_unblock_user_borrowing(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f"/dashboard/users/{self.reader.id}/block-borrowing/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["code"], "USER_BORROWING_BLOCKED")
        self.assertEqual(
            response.data["data"],
            {"user_id": self.reader.id, "borrowing_blocked": True},
        )
        self.reader.refresh_from_db()
        self.assertTrue(self.reader.borrowing_blocked)

        self.client.force_authenticate(user=self.reader)
        response = self.client.post(f"/api/books/{self.book.id}/borrow/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f"/dashboard/users/{self.reader.id}/unblock-borrowing/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["code"], "USER_BORROWING_UNBLOCKED")
        self.assertEqual(
            response.data["data"],
            {"user_id": self.reader.id, "borrowing_blocked": False},
        )
        self.reader.refresh_from_db()
        self.assertFalse(self.reader.borrowing_blocked)

        self.client.force_authenticate(user=self.reader)
        response = self.client.post(f"/api/books/{self.book.id}/borrow/")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class DashboardRemainingFeaturesTests(DashboardTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.admin)

    def test_stats_still_work(self):
        BorrowedBook.objects.create(book=self.book, borrower=self.reader)

        response = self.client.get("/dashboard/stats/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_books"], 1)
        self.assertEqual(response.data["borrowed_books"], 1)
        self.assertEqual(len(response.data["borrowed_last_7_days"]), 7)
        for key in (
            "total_users",
            "available_books",
            "pending_returns",
            "archived_books",
            "category_stats",
        ):
            self.assertIn(key, response.data)

    def test_books_export_still_works(self):
        response = self.client.get("/dashboard/books/export/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertTrue(response.content)

    def test_book_archive_and_restore_still_work(self):
        response = self.client.delete(f"/dashboard/books/{self.book.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.book.refresh_from_db()
        self.assertTrue(self.book.is_archived)

        response = self.client.post(f"/dashboard/books/{self.book.id}/restore/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.book.refresh_from_db()
        self.assertFalse(self.book.is_archived)

    def test_admin_return_book_restores_copy(self):
        self.client.force_authenticate(user=self.reader)
        self.client.post(f"/api/books/{self.book.id}/borrow/")
        borrow = BorrowedBook.objects.get(borrower=self.reader, book=self.book)

        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f"/dashboard/borrow/{borrow.id}/return_book/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        borrow.refresh_from_db()
        self.book.refresh_from_db()
        self.assertTrue(borrow.is_returned)
        self.assertEqual(self.book.available_copies, 2)

    def test_category_and_author_management_still_work(self):
        for path in ("/dashboard/category/", "/dashboard/author/", "/dashboard/borrow/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_removed_dashboard_routes_return_not_found(self):
        routes = [
            "/dashboard/reservations/",
            "/dashboard/libraryactivity/",
            "/dashboard/quotes/",
            f"/dashboard/books/{self.book.id}/summaries/",
        ]

        for path in routes:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class RemovedModelsTests(APITestCase):
    def test_removed_models_are_not_installed_or_registered(self):
        installed = {model.__name__ for model in apps.get_models()}
        for model_name in (
            "Favorite_Book",
            "BookRating",
            "BookSummary",
            "BookReservation",
            "Quote",
            "QuoteLike",
            "LibraryActivity",
            "ActivityRegistration",
        ):
            with self.subTest(model=model_name):
                self.assertNotIn(model_name, installed)

        self.assertIn("FavoriteBook", installed)

        for model in (Book, Author, Category, BorrowedBook, CustomUser, Governorate, Library):
            with self.subTest(model=model.__name__):
                self.assertTrue(admin.site.is_registered(model))


class UserScopeTestMixin:
    """Two active governorates, one inactive, with a user of each role."""

    def setUp(self):
        self.gov_a = Governorate.objects.create(name="Governorate A")
        self.gov_b = Governorate.objects.create(name="Governorate B")
        self.gov_inactive = Governorate.objects.create(name="Inactive", is_active=False)
        self.library_a = Library.objects.create(name="Library A", governorate=self.gov_a)
        self.library_b = Library.objects.create(name="Library B", governorate=self.gov_b)

        self.ministry = self.create_user("ministry", CustomUser.Role.MINISTRY_ADMIN)
        self.gov_admin_a = self.create_user(
            "gov_admin_a", CustomUser.Role.GOVERNORATE_ADMIN, governorate=self.gov_a
        )
        self.librarian_a = self.create_user(
            "librarian_a", CustomUser.Role.LIBRARIAN, library=self.library_a
        )
        self.reader_a = self.create_user(
            "reader_alpha",
            CustomUser.Role.READER,
            governorate=self.gov_a,
            first_name="Sami",
            last_name="Haddad",
            phone="0911111111",
        )
        self.reader_a2 = self.create_user(
            "reader_amal", CustomUser.Role.READER, governorate=self.gov_a
        )
        self.inactive_reader_a = self.create_user(
            "reader_asleep", CustomUser.Role.READER, governorate=self.gov_a, is_active=False
        )
        self.reader_b = self.create_user(
            "reader_beta", CustomUser.Role.READER, governorate=self.gov_b
        )

    def create_user(self, username, role, **extra):
        return CustomUser.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password=PASSWORD,
            role=role,
            **extra,
        )


class ReaderCreationTests(UserScopeTestMixin, APITestCase):
    url = "/dashboard/users/"

    def create(self, actor, **overrides):
        self.client.force_authenticate(user=actor)
        data = {
            "username": "created_reader",
            "email": "created_reader@example.com",
            "password": PASSWORD,
            "first_name": "Created",
            "last_name": "Reader",
            "role": CustomUser.Role.READER,
        }
        data.update(overrides)
        return self.client.post(self.url, data, format="json")

    def assert_created_reader(self, response, governorate):
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["code"], "USER_CREATED")
        self.assertEqual(response.data["data"]["governorate"], governorate.id)
        self.assertIsNone(response.data["data"]["library"])
        user = CustomUser.objects.get(username="created_reader")
        self.assertEqual(user.role, CustomUser.Role.READER)
        self.assertEqual(user.governorate, governorate)
        self.assertIsNone(user.library_id)
        self.assertFalse(user.is_staff)

    def assert_rejected(self, response, field):
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "VALIDATION_ERROR")
        self.assertIn(field, response.data["errors"])
        self.assertFalse(CustomUser.objects.filter(username="created_reader").exists())

    def test_librarian_creates_reader_in_library_governorate(self):
        response = self.create(self.librarian_a)

        self.assert_created_reader(response, self.gov_a)

    def test_librarian_may_send_own_governorate(self):
        response = self.create(self.librarian_a, governorate=self.gov_a.id)

        self.assert_created_reader(response, self.gov_a)

    def test_librarian_cannot_choose_other_governorate(self):
        response = self.create(self.librarian_a, governorate=self.gov_b.id)

        self.assert_rejected(response, "governorate")

    def test_librarian_cannot_link_reader_to_library(self):
        response = self.create(self.librarian_a, library=self.library_a.id)

        self.assert_rejected(response, "library")

    def test_librarian_cannot_create_higher_roles(self):
        for role, scope in (
            (CustomUser.Role.LIBRARIAN, {"library": self.library_a.id}),
            (CustomUser.Role.GOVERNORATE_ADMIN, {"governorate": self.gov_a.id}),
            (CustomUser.Role.MINISTRY_ADMIN, {}),
        ):
            with self.subTest(role=role):
                response = self.create(self.librarian_a, role=role, **scope)
                self.assert_rejected(response, "role")

    def test_admin_flags_are_rejected(self):
        for field, value in (
            ("is_staff", True),
            ("is_superuser", True),
            ("is_active", False),
            ("groups", [1]),
            ("user_permissions", [1]),
            ("borrowing_blocked", True),
        ):
            with self.subTest(field=field):
                response = self.create(self.librarian_a, **{field: value})
                self.assert_rejected(response, field)

    def test_governorate_admin_creates_reader_in_own_governorate_only(self):
        response = self.create(self.gov_admin_a, governorate=self.gov_b.id)
        self.assert_rejected(response, "governorate")

        response = self.create(self.gov_admin_a)
        self.assert_created_reader(response, self.gov_a)

    def test_ministry_creates_reader_in_chosen_active_governorate(self):
        response = self.create(self.ministry)
        self.assert_rejected(response, "governorate")

        response = self.create(self.ministry, governorate=self.gov_inactive.id)
        self.assert_rejected(response, "governorate")

        response = self.create(self.ministry, governorate=self.gov_b.id)
        self.assert_created_reader(response, self.gov_b)

    def test_reader_cannot_create_users(self):
        response = self.create(self.reader_a)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_other_role_creation_rules_are_kept(self):
        self.client.force_authenticate(user=self.gov_admin_a)
        base = {"password": PASSWORD, "role": CustomUser.Role.LIBRARIAN}

        response = self.client.post(
            self.url,
            {**base, "username": "lib_in_scope", "library": self.library_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = self.client.post(
            self.url,
            {**base, "username": "lib_out_of_scope", "library": self.library_b.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("library", response.data["errors"])

        response = self.client.post(
            self.url,
            {
                "password": PASSWORD,
                "username": "gov_admin_by_gov_admin",
                "role": CustomUser.Role.GOVERNORATE_ADMIN,
                "governorate": self.gov_a.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("role", response.data["errors"])

        self.client.force_authenticate(user=self.ministry)
        response = self.client.post(
            self.url,
            {
                "password": PASSWORD,
                "username": "gov_admin_b",
                "role": CustomUser.Role.GOVERNORATE_ADMIN,
                "governorate": self.gov_b.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class ReaderSearchTests(UserScopeTestMixin, APITestCase):
    url = "/dashboard/users/reader-search/"
    expected_fields = {"id", "username", "first_name", "last_name", "full_name", "governorate"}

    def search(self, actor, **params):
        self.client.force_authenticate(user=actor)
        return self.client.get(self.url, params)

    def usernames(self, response):
        return [item["username"] for item in response.data["data"]["results"]]

    def test_librarian_finds_only_active_readers_of_library_governorate(self):
        response = self.search(self.librarian_a, q="reader")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["code"], "READERS_RETRIEVED")
        self.assertEqual(self.usernames(response), ["reader_alpha", "reader_amal"])
        self.assertEqual(response.data["data"]["count"], 2)

    def test_results_expose_minimal_fields_only(self):
        response = self.search(self.librarian_a, q="Sami")

        results = response.data["data"]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(set(results[0]), self.expected_fields)
        self.assertEqual(results[0]["id"], self.reader_a.id)
        self.assertEqual(results[0]["full_name"], "Sami Haddad")
        self.assertEqual(results[0]["governorate"], {"id": self.gov_a.id, "name": self.gov_a.name})

    def test_exact_email_and_phone_match(self):
        for term in ("reader_alpha@example.com", "0911111111"):
            with self.subTest(term=term):
                response = self.search(self.librarian_a, q=term)
                self.assertEqual(self.usernames(response), ["reader_alpha"])

    def test_other_governorate_readers_are_hidden(self):
        response = self.search(self.librarian_a, q="reader_beta")
        self.assertEqual(response.data["data"]["count"], 0)

        response = self.search(self.gov_admin_a, q="reader")
        self.assertEqual(self.usernames(response), ["reader_alpha", "reader_amal"])

    def test_ministry_searches_all_governorates(self):
        response = self.search(self.ministry, q="reader")

        self.assertEqual(self.usernames(response), ["reader_alpha", "reader_amal", "reader_beta"])

    def test_non_reader_accounts_are_not_returned(self):
        response = self.search(self.ministry, q="librarian_a")

        self.assertEqual(response.data["data"]["count"], 0)

    def test_search_term_is_required(self):
        for params in ({}, {"q": ""}, {"q": "   "}, {"q": "r"}):
            with self.subTest(params=params):
                response = self.search(self.librarian_a, **params)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.data["code"], "VALIDATION_ERROR")
                self.assertIn("q", response.data["errors"])

    def test_results_are_paginated(self):
        response = self.search(self.ministry, q="reader", page_size=2)

        self.assertEqual(response.data["data"]["count"], 3)
        self.assertEqual(self.usernames(response), ["reader_alpha", "reader_amal"])
        self.assertIsNotNone(response.data["data"]["next"])

        response = self.search(self.ministry, q="reader", page_size=2, page=2)
        self.assertEqual(self.usernames(response), ["reader_beta"])

    def test_reader_cannot_search(self):
        response = self.search(self.reader_a, q="reader")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_search_requires_authentication(self):
        response = self.client.get(self.url, {"q": "reader"})

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class UserManagementIsolationTests(UserScopeTestMixin, APITestCase):
    def test_librarian_has_no_general_user_access(self):
        self.client.force_authenticate(user=self.librarian_a)
        reader_url = f"/dashboard/users/{self.reader_a.id}/"

        for method, path, expected in (
            ("get", "/dashboard/users/", status.HTTP_403_FORBIDDEN),
            ("get", reader_url, status.HTTP_403_FORBIDDEN),
            ("post", f"{reader_url}deactivate/", status.HTTP_403_FORBIDDEN),
            ("post", f"{reader_url}reactivate/", status.HTTP_403_FORBIDDEN),
            ("post", f"{reader_url}reset-password/", status.HTTP_403_FORBIDDEN),
            ("post", f"{reader_url}block-borrowing/", status.HTTP_404_NOT_FOUND),
            ("post", f"{reader_url}unblock-borrowing/", status.HTTP_404_NOT_FOUND),
            ("patch", reader_url, status.HTTP_405_METHOD_NOT_ALLOWED),
        ):
            with self.subTest(method=method, path=path):
                response = getattr(self.client, method)(path, {}, format="json")
                self.assertEqual(response.status_code, expected)

        self.reader_a.refresh_from_db()
        self.assertTrue(self.reader_a.is_active)
        self.assertFalse(self.reader_a.borrowing_blocked)
        self.assertTrue(self.reader_a.check_password(PASSWORD))

    def test_reader_cannot_reach_other_accounts(self):
        self.client.force_authenticate(user=self.reader_a)

        for path in (
            "/dashboard/users/",
            f"/dashboard/users/{self.reader_a2.id}/",
            f"/dashboard/users/{self.reader_b.id}/",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_governorate_admin_scope_follows_reader_governorate(self):
        self.client.force_authenticate(user=self.gov_admin_a)

        response = self.client.get("/dashboard/users/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        usernames = {user["username"] for user in response.data["data"]}
        self.assertTrue(
            {"gov_admin_a", "librarian_a", "reader_alpha", "reader_amal", "reader_asleep"} <= usernames
        )
        self.assertNotIn("reader_beta", usernames)
        self.assertNotIn("ministry", usernames)

        response = self.client.get(f"/dashboard/users/{self.reader_b.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.post(f"/dashboard/users/{self.reader_a.id}/deactivate/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.reader_a.refresh_from_db()
        self.assertFalse(self.reader_a.is_active)

        response = self.client.post(f"/dashboard/users/{self.reader_b.id}/deactivate/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_governorate_admin_resets_reader_password_in_scope(self):
        self.client.force_authenticate(user=self.gov_admin_a)
        payload = {"new_password": "AnotherPass456!", "new_password_confirm": "AnotherPass456!"}

        response = self.client.post(
            f"/dashboard/users/{self.reader_a.id}/reset-password/", payload, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.post(
            f"/dashboard/users/{self.reader_b.id}/reset-password/", payload, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_ministry_reaches_readers_of_all_governorates(self):
        self.client.force_authenticate(user=self.ministry)

        for reader in (self.reader_a, self.reader_b):
            with self.subTest(reader=reader.username):
                response = self.client.get(f"/dashboard/users/{reader.id}/")
                self.assertEqual(response.status_code, status.HTTP_200_OK)
