from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import CustomUser, Governorate, Library
from books.models import Author, Book, Category


PASSWORD = "StrongPass123!"
BOOKS_URL = "/dashboard/books/"


class BookFilterTestMixin:
    """Governorate A: libraries A1, A2 and an inactive one. Governorate B: library B.

    Books vary by author, category, archive state and availability so every
    filter has matching and non-matching rows inside and outside each scope.
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

        self.ministry = self.create_user("ministry", CustomUser.Role.MINISTRY_ADMIN)
        self.gov_admin_a = self.create_user(
            "gov_admin_a", CustomUser.Role.GOVERNORATE_ADMIN, governorate=self.gov_a
        )
        self.librarian_a1 = self.create_user(
            "librarian_a1", CustomUser.Role.LIBRARIAN, library=self.library_a1
        )
        self.reader_a = self.create_user("reader_a", CustomUser.Role.READER, governorate=self.gov_a)

        self.nizar = Author.objects.create(name="نزار قباني")
        self.darwish = Author.objects.create(name="Mahmoud Darwish")
        self.poetry = Category.objects.create(name="شعر")
        self.novel = Category.objects.create(name="Novel")

        self.a1_poetry = self.create_book("A1 Poetry", self.library_a1, self.nizar, self.poetry, 3)
        self.a1_archived = self.create_book(
            "A1 Archived", self.library_a1, self.nizar, self.poetry, 2, is_archived=True
        )
        self.a1_empty = self.create_book("A1 Empty", self.library_a1, self.darwish, self.novel, 0)
        self.a2_novel = self.create_book("A2 Novel", self.library_a2, self.darwish, self.novel, 1)
        self.a_closed = self.create_book(
            "A Closed", self.library_a_closed, self.nizar, self.poetry, 1
        )
        self.b_poetry = self.create_book("B Poetry", self.library_b, self.nizar, self.poetry, 4)
        self.b_archived = self.create_book(
            "B Archived", self.library_b, self.darwish, self.novel, 0, is_archived=True
        )

    def create_user(self, username, role, **extra):
        return CustomUser.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password=PASSWORD,
            role=role,
            **extra,
        )

    def create_book(self, title, library, author, category, copies, **extra):
        return Book.objects.create(
            title=title,
            description="desc",
            library=library,
            author=author,
            category=category,
            total_copies=copies,
            **extra,
        )

    def list_response(self, user, **params):
        self.client.force_authenticate(user=user)
        return self.client.get(BOOKS_URL, params)

    def ids(self, user, **params):
        response = self.list_response(user, **params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["code"], "BOOKS_RETRIEVED")
        page = response.data["data"]
        ids = {item["id"] for item in page["results"]}
        self.assertEqual(page["count"], len(ids))
        return ids

    def expect(self, *books):
        return {book.id for book in books}


class BookFilterSemanticsTests(BookFilterTestMixin, APITestCase):
    def test_author_filter_is_partial_name_match(self):
        self.assertEqual(
            self.ids(self.ministry, author="نزار"),
            self.expect(self.a1_poetry, self.a1_archived, self.a_closed, self.b_poetry),
        )
        self.assertEqual(
            self.ids(self.ministry, author="darw"),
            self.expect(self.a1_empty, self.a2_novel, self.b_archived),
        )

    def test_category_filter_is_partial_name_match(self):
        self.assertEqual(
            self.ids(self.ministry, category="شعر"),
            self.expect(self.a1_poetry, self.a1_archived, self.a_closed, self.b_poetry),
        )
        self.assertEqual(
            self.ids(self.ministry, category="NOV"),
            self.expect(self.a1_empty, self.a2_novel, self.b_archived),
        )

    def test_library_filter_uses_library_id(self):
        self.assertEqual(
            self.ids(self.ministry, library=self.library_a1.id),
            self.expect(self.a1_poetry, self.a1_archived, self.a1_empty),
        )
        self.assertEqual(self.ids(self.ministry, library=999999), set())

    def test_governorate_filter_uses_governorate_id(self):
        self.assertEqual(
            self.ids(self.ministry, governorate=self.gov_b.id),
            self.expect(self.b_poetry, self.b_archived),
        )
        self.assertEqual(
            self.ids(self.ministry, governorate=self.gov_a.id),
            self.expect(
                self.a1_poetry, self.a1_archived, self.a1_empty, self.a2_novel, self.a_closed
            ),
        )

    def test_is_archived_true(self):
        self.assertEqual(
            self.ids(self.ministry, is_archived="true"),
            self.expect(self.a1_archived, self.b_archived),
        )

    def test_is_archived_false(self):
        self.assertEqual(
            self.ids(self.ministry, is_archived="false"),
            self.expect(
                self.a1_poetry, self.a1_empty, self.a2_novel, self.a_closed, self.b_poetry
            ),
        )

    def test_is_avaiable_true(self):
        self.assertEqual(
            self.ids(self.ministry, is_avaiable="true"),
            self.expect(
                self.a1_poetry, self.a1_archived, self.a2_novel, self.a_closed, self.b_poetry
            ),
        )

    def test_is_avaiable_false(self):
        self.assertEqual(
            self.ids(self.ministry, is_avaiable="false"),
            self.expect(self.a1_empty, self.b_archived),
        )

    def test_boolean_values_are_case_insensitive_and_accept_one_zero(self):
        archived = self.expect(self.a1_archived, self.b_archived)
        for value in ("TRUE", "True", "1"):
            with self.subTest(value=value):
                self.assertEqual(self.ids(self.ministry, is_archived=value), archived)
        self.assertEqual(
            self.ids(self.ministry, is_avaiable="0"), self.expect(self.a1_empty, self.b_archived)
        )

    def test_combined_filters_apply_all_conditions(self):
        params = {
            "governorate": self.gov_a.id,
            "library": self.library_a1.id,
            "author": "نزار",
            "category": "شعر",
            "is_archived": "false",
            "is_avaiable": "true",
        }
        self.assertEqual(self.ids(self.ministry, **params), self.expect(self.a1_poetry))

        params["is_archived"] = "true"
        self.assertEqual(self.ids(self.ministry, **params), self.expect(self.a1_archived))

        params["governorate"] = self.gov_b.id
        self.assertEqual(self.ids(self.ministry, **params), set())

    def test_empty_values_are_ignored(self):
        all_books = self.ids(self.ministry)
        self.assertEqual(
            self.ids(self.ministry, library="", governorate="", is_archived="", is_avaiable=""),
            all_books,
        )


class BookFilterValidationTests(BookFilterTestMixin, APITestCase):
    def test_malformed_values_are_validation_errors(self):
        cases = [
            ("library", "abc"),
            ("library", "1.5"),
            ("governorate", "abc"),
            ("is_archived", "hello"),
            ("is_archived", "yes"),
            ("is_avaiable", "hello"),
            ("is_avaiable", "2"),
        ]
        for param, value in cases:
            with self.subTest(param=param, value=value):
                response = self.list_response(self.ministry, **{param: value})

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertFalse(response.data["success"])
                self.assertEqual(response.data["code"], "VALIDATION_ERROR")
                self.assertIn(param, response.data["errors"])

    def test_out_of_range_ids_are_validation_errors_not_server_errors(self):
        bigint_max = 9223372036854775807
        values = ("0", "-1", str(bigint_max + 1), "9" * 40)
        for param in ("library", "governorate"):
            for value in values:
                with self.subTest(param=param, value=value):
                    response = self.list_response(self.ministry, **{param: value})

                    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                    self.assertEqual(response.data["code"], "VALIDATION_ERROR")
                    self.assertIn(param, response.data["errors"])

    def test_largest_supported_id_is_accepted(self):
        for param in ("library", "governorate"):
            with self.subTest(param=param):
                self.assertEqual(self.ids(self.ministry, **{param: "9223372036854775807"}), set())

    def test_malformed_values_are_rejected_for_every_role(self):
        for user in (self.gov_admin_a, self.librarian_a1, self.reader_a):
            with self.subTest(user=user.username):
                response = self.list_response(user, library="abc")
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_filters_do_not_affect_retrieve(self):
        self.client.force_authenticate(user=self.ministry)
        response = self.client.get(
            f"{BOOKS_URL}{self.b_poetry.id}/",
            {"library": self.library_a1.id, "is_archived": "hello"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["id"], self.b_poetry.id)


class BookFilterScopeTests(BookFilterTestMixin, APITestCase):
    def test_governorate_admin_cannot_expand_scope_with_governorate(self):
        self.assertEqual(self.ids(self.gov_admin_a, governorate=self.gov_b.id), set())
        self.assertEqual(self.ids(self.gov_admin_a, library=self.library_b.id), set())

    def test_governorate_admin_filters_inside_own_scope(self):
        self.assertEqual(
            self.ids(self.gov_admin_a, governorate=self.gov_a.id, is_archived="true"),
            self.expect(self.a1_archived),
        )
        self.assertEqual(
            self.ids(self.gov_admin_a, library=self.library_a_closed.id),
            self.expect(self.a_closed),
        )

    def test_librarian_cannot_expand_scope_with_library(self):
        # `library` is ignored for librarians: their scope is already their library.
        self.assertEqual(
            self.ids(self.librarian_a1, library=self.library_a2.id),
            self.expect(self.a1_poetry, self.a1_archived, self.a1_empty),
        )
        self.assertEqual(self.ids(self.librarian_a1, governorate=self.gov_b.id), set())
        self.assertEqual(
            self.ids(self.librarian_a1, library=self.library_a1.id),
            self.expect(self.a1_poetry, self.a1_archived, self.a1_empty),
        )

    def test_reader_cannot_expose_archived_books(self):
        self.assertEqual(self.ids(self.reader_a, is_archived="true"), set())
        self.assertEqual(
            self.ids(self.reader_a, is_archived="false"),
            self.expect(self.a1_poetry, self.a1_empty, self.a2_novel),
        )

    def test_reader_cannot_expose_inactive_library_or_other_governorate(self):
        self.assertEqual(self.ids(self.reader_a, library=self.library_a_closed.id), set())
        self.assertEqual(self.ids(self.reader_a, governorate=self.gov_b.id), set())
        self.assertEqual(self.ids(self.reader_a, library=self.library_b.id), set())

    def test_reader_availability_filter_stays_in_scope(self):
        self.assertEqual(
            self.ids(self.reader_a, is_avaiable="true"), self.expect(self.a1_poetry, self.a2_novel)
        )
        self.assertEqual(self.ids(self.reader_a, is_avaiable="false"), self.expect(self.a1_empty))


class BookFilterPaginationTests(BookFilterTestMixin, APITestCase):
    def test_pagination_counts_only_filtered_rows(self):
        extra = {
            self.create_book(f"A1 Extra {index}", self.library_a1, self.nizar, self.poetry, 1).id
            for index in range(11)
        }
        for index in range(12):
            self.create_book(f"A1 Empty {index}", self.library_a1, self.darwish, self.novel, 0)
        expected = extra | self.expect(self.a1_poetry)

        first = self.list_response(
            self.librarian_a1, is_avaiable="true", is_archived="false"
        ).data["data"]
        second = self.list_response(
            self.librarian_a1, is_avaiable="true", is_archived="false", page=2
        ).data["data"]

        self.assertEqual(first["count"], 12)
        self.assertEqual(len(first["results"]), 10)
        self.assertIsNotNone(first["next"])
        self.assertEqual(len(second["results"]), 2)
        self.assertIsNone(second["next"])
        seen = [item["id"] for item in first["results"] + second["results"]]
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(set(seen), expected)
