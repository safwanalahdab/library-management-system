from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import CustomUser, Governorate, Library
from books.models import Author, Book, Category


PASSWORD = "StrongPass123!"
BOOKS_URL = "/dashboard/books/"


class BookReadScopeTestMixin:
    """Governorate A: libraries A1, A2 and an inactive one. Governorate B: library B.

    Library A1 also holds an archived book.
    """

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

        self.author = Author.objects.create(name="Shared Author")
        self.foreign_author = Author.objects.create(name="Foreign Author")
        self.category = Category.objects.create(name="Shared Category")
        self.foreign_category = Category.objects.create(name="Foreign Category")

        self.book_a1 = self.create_book("Book A1", self.library_a1)
        self.book_a1_archived = self.create_book(
            "Book A1 Archived", self.library_a1, is_archived=True
        )
        self.book_a2 = self.create_book("Book A2", self.library_a2)
        self.book_a_closed = self.create_book("Book A Closed", self.library_a_closed)
        self.book_b = self.create_book("Book B", self.library_b)
        self.book_b_foreign = self.create_book(
            "Book B Foreign",
            self.library_b,
            author=self.foreign_author,
            category=self.foreign_category,
        )
        self.all_books = {
            self.book_a1,
            self.book_a1_archived,
            self.book_a2,
            self.book_a_closed,
            self.book_b,
            self.book_b_foreign,
        }

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

    def list_books(self, user, **params):
        self.client.force_authenticate(user=user)
        response = self.client.get(BOOKS_URL, params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response

    def listed_ids(self, user, **params):
        response = self.list_books(user, **params)
        page = response.data["data"]
        ids = {item["id"] for item in page["results"]}
        self.assertEqual(page["count"], len(ids))
        return ids

    def retrieve(self, user, book):
        self.client.force_authenticate(user=user)
        return self.client.get(f"{BOOKS_URL}{book.id}/")

    def assert_sees_exactly(self, user, books):
        self.assertEqual(self.listed_ids(user), {book.id for book in books})
        for book in books:
            with self.subTest(user=user.username, book=book.title):
                response = self.retrieve(user, book)
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(response.data["data"]["id"], book.id)
        for book in self.all_books - set(books):
            with self.subTest(user=user.username, hidden=book.title):
                self.assert_not_found(self.retrieve(user, book), book)

    def assert_not_found(self, response, book):
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["code"], "NOT_FOUND")
        self.assertIsNone(response.data["data"])
        self.assertNotIn(book.title, str(response.data))


class MinistryBookReadTests(BookReadScopeTestMixin, APITestCase):
    def test_sees_every_book_including_archived_and_inactive_library(self):
        self.assert_sees_exactly(self.ministry, self.all_books)

    def test_superuser_sees_every_book(self):
        self.assert_sees_exactly(self.superuser, self.all_books)


class GovernorateAdminBookReadTests(BookReadScopeTestMixin, APITestCase):
    def test_sees_all_books_of_own_governorate_only(self):
        self.assert_sees_exactly(
            self.gov_admin_a,
            {self.book_a1, self.book_a1_archived, self.book_a2, self.book_a_closed},
        )

    def test_other_governorate_book_is_not_found(self):
        for book in (self.book_b, self.book_b_foreign):
            with self.subTest(book=book.title):
                self.assert_not_found(self.retrieve(self.gov_admin_a, book), book)

    def test_inactive_library_in_own_governorate_stays_visible(self):
        self.assertIn(self.book_a_closed.id, self.listed_ids(self.gov_admin_a))
        response = self.retrieve(self.gov_admin_a, self.book_a_closed)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class LibrarianBookReadTests(BookReadScopeTestMixin, APITestCase):
    def test_sees_own_library_books_only_including_archived(self):
        self.assert_sees_exactly(self.librarian_a1, {self.book_a1, self.book_a1_archived})

    def test_same_governorate_and_other_governorate_books_are_not_found(self):
        for book in (self.book_a2, self.book_a_closed, self.book_b):
            with self.subTest(book=book.title):
                self.assert_not_found(self.retrieve(self.librarian_a1, book), book)

    def test_library_query_parameter_does_not_widen_scope(self):
        ids = self.listed_ids(self.librarian_a1, library=self.library_a2.id)

        self.assertEqual(ids, {self.book_a1.id, self.book_a1_archived.id})


class ReaderBookReadTests(BookReadScopeTestMixin, APITestCase):
    def test_sees_non_archived_books_of_active_libraries_in_own_governorate(self):
        self.assert_sees_exactly(self.reader_a, {self.book_a1, self.book_a2})

    def test_archived_inactive_library_and_other_governorate_are_not_found(self):
        for book in (self.book_a1_archived, self.book_a_closed, self.book_b):
            with self.subTest(book=book.title):
                self.assert_not_found(self.retrieve(self.reader_a, book), book)

    def test_inactive_governorate_hides_all_books(self):
        self.gov_a.is_active = False
        self.gov_a.save()

        self.assert_sees_exactly(self.reader_a, set())

    def test_reader_cannot_use_admin_book_actions(self):
        self.client.force_authenticate(user=self.reader_a)
        forbidden = status.HTTP_403_FORBIDDEN
        requests = [
            ("patch", f"{BOOKS_URL}{self.book_a1.id}/", forbidden),
            ("put", f"{BOOKS_URL}{self.book_a1.id}/", status.HTTP_405_METHOD_NOT_ALLOWED),
            ("delete", f"{BOOKS_URL}{self.book_a1.id}/", forbidden),
            ("post", f"{BOOKS_URL}{self.book_a1.id}/restore/", forbidden),
            ("get", f"{BOOKS_URL}export/", forbidden),
        ]
        for method, url, expected in requests:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, {"title": "Hijack"}, format="json")
                self.assertEqual(response.status_code, expected)

        self.book_a1.refresh_from_db()
        self.assertEqual(self.book_a1.title, "Book A1")
        self.assertFalse(self.book_a1.is_archived)


class BookReadAccessTests(BookReadScopeTestMixin, APITestCase):
    def test_anonymous_cannot_list_or_retrieve(self):
        for url in (BOOKS_URL, f"{BOOKS_URL}{self.book_a1.id}/"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_id_tampering_cannot_reach_out_of_scope_books(self):
        hidden = {
            self.gov_admin_a: (self.book_b, self.book_b_foreign),
            self.librarian_a1: (self.book_a2, self.book_a_closed, self.book_b),
            self.reader_a: (self.book_a1_archived, self.book_a_closed, self.book_b),
        }
        for user, books in hidden.items():
            for book in books:
                with self.subTest(user=user.username, book=book.title):
                    self.assert_not_found(self.retrieve(user, book), book)

        missing = self.retrieve(self.reader_a, Book(pk=999999, title="Missing"))
        out_of_scope = self.retrieve(self.reader_a, self.book_b)
        self.assertEqual(missing.data, out_of_scope.data)


class BookReadFilterTests(BookReadScopeTestMixin, APITestCase):
    def test_author_filter_does_not_cross_scope(self):
        self.assertEqual(self.listed_ids(self.gov_admin_a, author="Foreign"), set())
        self.assertEqual(self.listed_ids(self.librarian_a1, author="Foreign"), set())
        self.assertEqual(self.listed_ids(self.reader_a, author="Foreign"), set())
        self.assertEqual(
            self.listed_ids(self.ministry, author="Foreign"), {self.book_b_foreign.id}
        )

    def test_category_filter_does_not_cross_scope(self):
        self.assertEqual(self.listed_ids(self.gov_admin_a, category="Foreign"), set())
        self.assertEqual(
            self.listed_ids(self.ministry, category="Foreign"), {self.book_b_foreign.id}
        )

    def test_shared_author_returns_in_scope_books_only(self):
        self.assertEqual(
            self.listed_ids(self.gov_admin_a, author="Shared"),
            {self.book_a1.id, self.book_a1_archived.id, self.book_a2.id, self.book_a_closed.id},
        )
        self.assertEqual(
            self.listed_ids(self.reader_a, category="Shared"),
            {self.book_a1.id, self.book_a2.id},
        )


class BookReadPaginationTests(BookReadScopeTestMixin, APITestCase):
    def test_pagination_runs_on_scoped_queryset(self):
        extra_in_scope = {
            self.create_book(f"A1 Extra {index}", self.library_a1).id for index in range(10)
        }
        for index in range(15):
            self.create_book(f"B Extra {index}", self.library_b)
        expected = extra_in_scope | {self.book_a1.id, self.book_a1_archived.id}

        first_response = self.list_books(self.librarian_a1)
        second_response = self.list_books(self.librarian_a1, page=2)

        for response in (first_response, second_response):
            self.assertEqual(response.data["code"], "BOOKS_RETRIEVED")
            self.assertNotIn("results", response.data)
        first = first_response.data["data"]
        second = second_response.data["data"]
        self.assertEqual(set(first), {"count", "next", "previous", "results"})
        self.assertEqual((first["count"], second["count"]), (12, 12))
        self.assertEqual(len(first["results"]), 10)
        self.assertIsNotNone(first["next"])
        self.assertIsNone(first["previous"])
        self.assertEqual(len(second["results"]), 2)
        self.assertIsNone(second["next"])
        self.assertIsNotNone(second["previous"])
        seen = [item["id"] for item in first["results"] + second["results"]]
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(set(seen), expected)


class BookReadResponseTests(BookReadScopeTestMixin, APITestCase):
    def assert_organization_fields(self, data, library):
        self.assertEqual(data["library"], library.id)
        self.assertEqual(data["library_name"], library.name)
        self.assertEqual(data["governorate"], library.governorate_id)
        self.assertEqual(data["governorate_name"], library.governorate.name)

    def test_list_items_include_organization_fields(self):
        response = self.list_books(self.ministry)

        books = {book.id: book for book in self.all_books}
        for item in response.data["data"]["results"]:
            with self.subTest(book=item["title"]):
                self.assert_organization_fields(item, books[item["id"]].library)

    def test_retrieve_includes_organization_and_book_fields(self):
        response = self.retrieve(self.gov_admin_a, self.book_a2)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assert_organization_fields(data, self.library_a2)
        self.assertEqual(data["author"], {"id": self.author.id, "name": "Shared Author"})
        self.assertEqual(data["category"], {"id": self.category.id, "name": "Shared Category"})
        for field in (
            "total_copies",
            "available_copies",
            "is_avaiable",
            "count_borrowed",
            "is_archived",
        ):
            self.assertIn(field, data)


class BookReadEnvelopeTests(BookReadScopeTestMixin, APITestCase):
    role_codes = {
        "root": "SUPERUSER",
        "ministry": "MINISTRY_ADMIN",
        "gov_admin_a": "GOVERNORATE_ADMIN",
        "librarian_a1": "LIBRARIAN",
        "reader_a": "READER",
    }

    def actors(self):
        return (
            self.superuser,
            self.ministry,
            self.gov_admin_a,
            self.librarian_a1,
            self.reader_a,
        )

    def assert_envelope(self, response, code, message, user):
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIs(response.data["success"], True)
        self.assertEqual(response.data["code"], code)
        self.assertEqual(response.data["message"], message)
        self.assertEqual(
            response.data["meta"]["requester_role"]["code"], self.role_codes[user.username]
        )
        return response.data["data"]

    def test_list_is_enveloped_with_paginated_data_for_every_role(self):
        expected = {
            self.superuser: self.all_books,
            self.ministry: self.all_books,
            self.gov_admin_a: {
                self.book_a1,
                self.book_a1_archived,
                self.book_a2,
                self.book_a_closed,
            },
            self.librarian_a1: {self.book_a1, self.book_a1_archived},
            self.reader_a: {self.book_a1, self.book_a2},
        }
        for user in self.actors():
            with self.subTest(user=user.username):
                response = self.list_books(user)

                data = self.assert_envelope(
                    response, "BOOKS_RETRIEVED", "تم جلب الكتب بنجاح.", user
                )
                self.assertEqual(set(data), {"count", "next", "previous", "results"})
                self.assertEqual(data["count"], len(expected[user]))
                self.assertIsNone(data["next"])
                self.assertIsNone(data["previous"])
                self.assertEqual(
                    {item["id"] for item in data["results"]},
                    {book.id for book in expected[user]},
                )

    def test_retrieve_is_enveloped_with_book_data(self):
        visible = {
            self.superuser: self.book_b,
            self.ministry: self.book_b,
            self.gov_admin_a: self.book_a_closed,
            self.librarian_a1: self.book_a1_archived,
            self.reader_a: self.book_a2,
        }
        for user, book in visible.items():
            with self.subTest(user=user.username, book=book.title):
                response = self.retrieve(user, book)

                data = self.assert_envelope(
                    response, "BOOK_RETRIEVED", "تم جلب بيانات الكتاب بنجاح.", user
                )
                self.assertEqual(data["id"], book.id)
                self.assertEqual(data["title"], book.title)
                self.assertEqual(data["library"], book.library_id)
                self.assertEqual(data["library_name"], book.library.name)
                self.assertEqual(data["governorate"], book.library.governorate_id)
                self.assertEqual(data["governorate_name"], book.library.governorate.name)

    def test_out_of_scope_retrieve_keeps_error_envelope(self):
        response = self.retrieve(self.gov_admin_a, self.book_b)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            set(response.data), {"success", "code", "message", "data", "errors", "meta"}
        )
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["code"], "NOT_FOUND")
        self.assertIsNone(response.data["data"])
        self.assertIsNone(response.data["errors"])
        self.assertEqual(
            response.data["meta"]["requester_role"]["code"], "GOVERNORATE_ADMIN"
        )
