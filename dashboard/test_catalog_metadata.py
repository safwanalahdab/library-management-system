from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import CustomUser, Governorate, Library
from books.models import Author, Book, Category


PASSWORD = "StrongPass123!"


class CatalogMetadataTestMixin:
    """Shared scenarios for the global Author and Category APIs.

    Concrete classes set: model, url, codes (action -> (code, message)),
    legacy_param, in_use_message and book_field.
    """

    model = None
    url = None
    codes = None
    legacy_param = None
    in_use_message = None
    book_field = None

    def setUp(self):
        self.governorate = Governorate.objects.create(name="Governorate A")
        self.library = Library.objects.create(name="Library A", governorate=self.governorate)

        self.superuser = CustomUser.objects.create_superuser(
            username="root", email="root@example.com", password=PASSWORD
        )
        self.ministry = self.create_user("ministry", CustomUser.Role.MINISTRY_ADMIN)
        self.gov_admin = self.create_user(
            "gov_admin", CustomUser.Role.GOVERNORATE_ADMIN, governorate=self.governorate
        )
        self.librarian = self.create_user(
            "librarian", CustomUser.Role.LIBRARIAN, library=self.library
        )
        self.reader = self.create_user(
            "reader", CustomUser.Role.READER, governorate=self.governorate
        )
        self.managers = (self.superuser, self.ministry, self.gov_admin)

        self.record = self.model.objects.create(name="نزار قباني")
        self.other = self.model.objects.create(name="Mahmoud Darwish")

    def create_user(self, username, role, **extra):
        return CustomUser.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password=PASSWORD,
            role=role,
            **extra,
        )

    def detail_url(self, record):
        return f"{self.url}{record.id}/"

    def request(self, user, method, url, data=None):
        self.client.force_authenticate(user=user)
        return getattr(self.client, method)(url, data, format="json")

    def link_book(self, record):
        return Book.objects.create(
            title="Linked Book",
            description="desc",
            library=self.library,
            **{self.book_field: record},
        )

    def assert_success(self, response, action, status_code=status.HTTP_200_OK):
        self.assertEqual(response.status_code, status_code)
        code, message = self.codes[action]
        self.assertIs(response.data["success"], True)
        self.assertEqual(response.data["code"], code)
        self.assertEqual(response.data["message"], message)
        self.assertIn("requester_role", response.data["meta"])
        return response.data["data"]

    def assert_error(self, response, status_code, code):
        self.assertEqual(response.status_code, status_code)
        self.assertIs(response.data["success"], False)
        self.assertEqual(response.data["code"], code)

    # Managers: superuser, ministry and governorate admins.

    def test_managers_can_list_retrieve_create_patch_and_delete(self):
        for index, user in enumerate(self.managers):
            with self.subTest(user=user.username):
                data = self.assert_success(self.request(user, "get", self.url), "list")
                self.assertEqual(set(data), {"count", "next", "previous", "results"})

                data = self.assert_success(
                    self.request(user, "get", self.detail_url(self.record)), "retrieve"
                )
                self.assertEqual(data, {"id": self.record.id, "name": self.record.name})

                created = self.assert_success(
                    self.request(user, "post", self.url, {"name": f"New {index}"}),
                    "create",
                    status.HTTP_201_CREATED,
                )
                record = self.model.objects.get(pk=created["id"])
                self.assertEqual(record.name, f"New {index}")

                updated = self.assert_success(
                    self.request(user, "patch", self.detail_url(record), {"name": f"Renamed {index}"}),
                    "partial_update",
                )
                self.assertEqual(updated["name"], f"Renamed {index}")
                record.refresh_from_db()
                self.assertEqual(record.name, f"Renamed {index}")

                deleted = self.assert_success(
                    self.request(user, "delete", self.detail_url(record)), "destroy"
                )
                self.assertIsNone(deleted)
                self.assertFalse(self.model.objects.filter(pk=record.pk).exists())

    def test_records_created_by_admins_are_global(self):
        created = self.request(self.gov_admin, "post", self.url, {"name": "Global Name"})
        record_id = created.data["data"]["id"]

        for user in (self.ministry, self.librarian, self.reader):
            with self.subTest(user=user.username):
                response = self.request(user, "get", self.url, {"search": "Global"})
                ids = [item["id"] for item in response.data["data"]["results"]]
                self.assertEqual(ids, [record_id])

    # Librarian: read only.

    def test_librarian_can_list_and_retrieve(self):
        self.assert_success(self.request(self.librarian, "get", self.url), "list")
        data = self.assert_success(
            self.request(self.librarian, "get", self.detail_url(self.record)), "retrieve"
        )
        self.assertEqual(data["id"], self.record.id)

    def test_librarian_cannot_write(self):
        self.assert_cannot_write(self.librarian)

    # Reader: list only.

    def test_reader_can_list_only(self):
        self.assert_success(self.request(self.reader, "get", self.url), "list")

        response = self.request(self.reader, "get", self.detail_url(self.record))
        self.assert_error(response, status.HTTP_403_FORBIDDEN, "PERMISSION_DENIED")

    def test_reader_cannot_write(self):
        self.assert_cannot_write(self.reader)

    def assert_cannot_write(self, user):
        count = self.model.objects.count()
        requests = [
            ("post", self.url, {"name": "Blocked"}),
            ("patch", self.detail_url(self.record), {"name": "Blocked"}),
            ("delete", self.detail_url(self.other), None),
        ]
        for method, url, data in requests:
            with self.subTest(user=user.username, method=method):
                response = self.request(user, method, url, data)
                self.assert_error(response, status.HTTP_403_FORBIDDEN, "PERMISSION_DENIED")

        self.assertEqual(self.model.objects.count(), count)
        self.record.refresh_from_db()
        self.assertEqual(self.record.name, "نزار قباني")
        self.assertTrue(self.model.objects.filter(pk=self.other.pk).exists())

    def test_anonymous_is_unauthorized(self):
        requests = [
            ("get", self.url, None),
            ("get", self.detail_url(self.record), None),
            ("post", self.url, {"name": "Blocked"}),
            ("patch", self.detail_url(self.record), {"name": "Blocked"}),
            ("delete", self.detail_url(self.record), None),
        ]
        for method, url, data in requests:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, data, format="json")
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        self.assertEqual(self.model.objects.count(), 2)

    def test_put_is_not_allowed(self):
        for user in (self.superuser, self.ministry, self.gov_admin, self.librarian, self.reader):
            with self.subTest(user=user.username):
                response = self.request(user, "put", self.detail_url(self.record), {"name": "Put"})
                self.assert_error(
                    response, status.HTTP_405_METHOD_NOT_ALLOWED, "METHOD_NOT_ALLOWED"
                )

        self.record.refresh_from_db()
        self.assertEqual(self.record.name, "نزار قباني")

    # Validation.

    def test_name_is_trimmed(self):
        created = self.request(self.ministry, "post", self.url, {"name": "  أحمد شوقي  "})
        data = self.assert_success(created, "create", status.HTTP_201_CREATED)
        self.assertEqual(data["name"], "أحمد شوقي")

        response = self.request(
            self.ministry, "patch", self.detail_url(self.record), {"name": "  نزار  "}
        )
        self.assert_success(response, "partial_update")
        self.record.refresh_from_db()
        self.assertEqual(self.record.name, "نزار")

    def test_invalid_names_are_rejected(self):
        count = self.model.objects.count()
        invalid = [{}, {"name": None}, {"name": ""}, {"name": "   "}, {"name": "x" * 101}]
        for data in invalid:
            with self.subTest(data=data):
                response = self.request(self.ministry, "post", self.url, data)
                self.assert_error(response, status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR")
                self.assertIn("name", response.data["errors"])

        for data in invalid[1:]:
            with self.subTest(patch=data):
                response = self.request(self.ministry, "patch", self.detail_url(self.record), data)
                self.assert_error(response, status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR")

        self.assertEqual(self.model.objects.count(), count)
        self.record.refresh_from_db()
        self.assertEqual(self.record.name, "نزار قباني")

    # Search, ordering and pagination.

    def test_search_is_partial_and_case_insensitive(self):
        cases = {"نزار": [self.record.id], "mahmoud": [self.other.id], "DARW": [self.other.id]}
        for term, expected in cases.items():
            with self.subTest(term=term):
                response = self.request(self.reader, "get", self.url, {"search": term})
                ids = [item["id"] for item in response.data["data"]["results"]]
                self.assertEqual(ids, expected)

    def test_legacy_parameter_is_an_alias_and_search_wins(self):
        response = self.request(self.librarian, "get", self.url, {self.legacy_param: "نزار"})
        ids = [item["id"] for item in response.data["data"]["results"]]
        self.assertEqual(ids, [self.record.id])

        response = self.request(
            self.librarian, "get", self.url, {"search": "Mahmoud", self.legacy_param: "نزار"}
        )
        ids = [item["id"] for item in response.data["data"]["results"]]
        self.assertEqual(ids, [self.other.id])

    def test_list_is_paginated_and_ordered_by_name(self):
        self.model.objects.all().delete()
        names = [f"Name {index:02d}" for index in range(25)]
        for name in reversed(names):
            self.model.objects.create(name=name)

        first = self.request(self.reader, "get", self.url).data["data"]
        second = self.request(self.reader, "get", self.url, {"page": 2}).data["data"]
        small = self.request(self.reader, "get", self.url, {"page_size": 5}).data["data"]

        self.assertEqual(first["count"], 25)
        self.assertEqual([item["name"] for item in first["results"]], names[:20])
        self.assertIsNotNone(first["next"])
        self.assertEqual([item["name"] for item in second["results"]], names[20:])
        self.assertIsNone(second["next"])
        self.assertEqual(len(small["results"]), 5)

    # Delete integrity.

    def test_unused_record_is_deleted(self):
        response = self.request(self.gov_admin, "delete", self.detail_url(self.other))

        self.assert_success(response, "destroy")
        self.assertFalse(self.model.objects.filter(pk=self.other.pk).exists())

    def test_record_linked_to_book_cannot_be_deleted(self):
        book = self.link_book(self.record)

        for user in self.managers:
            with self.subTest(user=user.username):
                response = self.request(user, "delete", self.detail_url(self.record))

                self.assert_error(response, status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR")
                self.assertIn(self.in_use_message, str(response.data["errors"]))

        self.assertTrue(self.model.objects.filter(pk=self.record.pk).exists())
        book.refresh_from_db()
        self.assertEqual(getattr(book, f"{self.book_field}_id"), self.record.id)
        self.assertEqual(book.title, "Linked Book")

    def test_missing_record_is_not_found(self):
        response = self.request(self.ministry, "delete", f"{self.url}999999/")

        self.assert_error(response, status.HTTP_404_NOT_FOUND, "NOT_FOUND")


class AuthorApiTests(CatalogMetadataTestMixin, APITestCase):
    model = Author
    url = "/dashboard/author/"
    legacy_param = "author"
    book_field = "author"
    in_use_message = "لا يمكن حذف المؤلف لأنه مرتبط بكتب موجودة."
    codes = {
        "list": ("AUTHORS_RETRIEVED", "تم جلب المؤلفين بنجاح."),
        "retrieve": ("AUTHOR_RETRIEVED", "تم جلب بيانات المؤلف بنجاح."),
        "create": ("AUTHOR_CREATED", "تم إنشاء المؤلف بنجاح."),
        "partial_update": ("AUTHOR_UPDATED", "تم تحديث بيانات المؤلف بنجاح."),
        "destroy": ("AUTHOR_DELETED", "تم حذف المؤلف بنجاح."),
    }


class CategoryApiTests(CatalogMetadataTestMixin, APITestCase):
    model = Category
    url = "/dashboard/category/"
    legacy_param = "category"
    book_field = "category"
    in_use_message = "لا يمكن حذف التصنيف لأنه مرتبط بكتب موجودة."
    codes = {
        "list": ("CATEGORIES_RETRIEVED", "تم جلب التصنيفات بنجاح."),
        "retrieve": ("CATEGORY_RETRIEVED", "تم جلب بيانات التصنيف بنجاح."),
        "create": ("CATEGORY_CREATED", "تم إنشاء التصنيف بنجاح."),
        "partial_update": ("CATEGORY_UPDATED", "تم تحديث بيانات التصنيف بنجاح."),
        "destroy": ("CATEGORY_DELETED", "تم حذف التصنيف بنجاح."),
    }
