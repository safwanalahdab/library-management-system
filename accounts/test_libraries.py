from rest_framework import status
from rest_framework.test import APITestCase

from .models import CustomUser, Governorate, Library


PASSWORD = "StrongPass123!"
LIST_URL = "/accounts/libraries/"


def detail_url(library):
    pk = library.pk if isinstance(library, Library) else library
    return f"{LIST_URL}{pk}/"


def status_url(library, operation):
    return f"{detail_url(library)}{operation}/"


class LibraryScopeTestMixin:
    """Two governorates, each with an active and an inactive library, and a user of each role."""

    def setUp(self):
        self.gov_a = Governorate.objects.create(name="Governorate A")
        self.gov_b = Governorate.objects.create(name="Governorate B")
        self.library_a = Library.objects.create(name="Alpha Library", governorate=self.gov_a)
        self.inactive_library_a = Library.objects.create(
            name="Alpha Archive", governorate=self.gov_a, is_active=False
        )
        self.library_b = Library.objects.create(name="Beta Library", governorate=self.gov_b)
        self.inactive_library_b = Library.objects.create(
            name="Beta Archive", governorate=self.gov_b, is_active=False
        )

        self.ministry = self.create_user("ministry", CustomUser.Role.MINISTRY_ADMIN)
        self.gov_admin_a = self.create_user(
            "gov_admin_a", CustomUser.Role.GOVERNORATE_ADMIN, governorate=self.gov_a
        )
        self.librarian_a = self.create_user(
            "librarian_a", CustomUser.Role.LIBRARIAN, library=self.library_a
        )
        self.reader_a = self.create_user(
            "reader_a", CustomUser.Role.READER, governorate=self.gov_a
        )

    def create_user(self, username, role, **extra):
        return CustomUser.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password=PASSWORD,
            role=role,
            **extra,
        )

    def result_ids(self, response):
        return {item["id"] for item in response.data["data"]["results"]}


class MinistryLibraryManagementTests(LibraryScopeTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.ministry)

    def test_ministry_lists_all_libraries_of_both_governorates(self):
        response = self.client.get(LIST_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["code"], "LIBRARIES_RETRIEVED")
        self.assertEqual(
            self.result_ids(response),
            {
                self.library_a.id,
                self.inactive_library_a.id,
                self.library_b.id,
                self.inactive_library_b.id,
            },
        )

    def test_ministry_creates_libraries_in_two_governorates(self):
        for governorate in (self.gov_a, self.gov_b):
            with self.subTest(governorate=governorate.name):
                response = self.client.post(
                    LIST_URL,
                    {"name": f"New {governorate.name}", "governorate": governorate.id},
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                self.assertEqual(response.data["code"], "LIBRARY_CREATED")
                self.assertEqual(response.data["data"]["governorate"], governorate.id)
                self.assertTrue(response.data["data"]["is_active"])
                self.assertEqual(response.data["data"]["address"], "")

    def test_ministry_must_choose_governorate(self):
        response = self.client.post(LIST_URL, {"name": "Orphan"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("governorate", response.data["errors"])

    def test_ministry_cannot_create_in_inactive_governorate(self):
        inactive = Governorate.objects.create(name="Inactive", is_active=False)
        response = self.client.post(
            LIST_URL, {"name": "Closed", "governorate": inactive.id}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Library.objects.filter(name="Closed").exists())

    def test_ministry_updates_and_toggles_libraries_in_both_governorates(self):
        for library in (self.library_a, self.library_b):
            with self.subTest(library=library.name):
                response = self.client.patch(
                    detail_url(library),
                    {"phone": "0110000000", "email": "lib@example.com"},
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(response.data["code"], "LIBRARY_UPDATED")

                response = self.client.post(status_url(library, "deactivate"))
                self.assertEqual(response.data["code"], "LIBRARY_DEACTIVATED")
                response = self.client.post(status_url(library, "activate"))
                self.assertEqual(response.data["code"], "LIBRARY_ACTIVATED")

                library.refresh_from_db()
                self.assertEqual(library.phone, "0110000000")
                self.assertTrue(library.is_active)


class GovernorateAdminLibraryTests(LibraryScopeTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.gov_admin_a)

    def test_lists_only_own_governorate_including_inactive(self):
        response = self.client.get(LIST_URL)

        self.assertEqual(
            self.result_ids(response), {self.library_a.id, self.inactive_library_a.id}
        )

    def test_creates_library_in_own_governorate_without_sending_it(self):
        response = self.client.post(
            LIST_URL, {"name": "Gov Library", "address": "Main street"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        library = Library.objects.get(pk=response.data["data"]["id"])
        self.assertEqual(library.governorate_id, self.gov_a.id)
        self.assertTrue(library.is_active)

    def test_may_send_own_governorate(self):
        response = self.client.post(
            LIST_URL, {"name": "Gov Library", "governorate": self.gov_a.id}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_other_governorate_is_rejected_not_ignored(self):
        response = self.client.post(
            LIST_URL, {"name": "Foreign", "governorate": self.gov_b.id}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("governorate", response.data["errors"])
        self.assertFalse(Library.objects.filter(name="Foreign").exists())

    def test_manages_own_governorate_libraries(self):
        response = self.client.patch(
            detail_url(self.library_a), {"name": "Renamed"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.post(status_url(self.library_a, "deactivate"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.library_a.refresh_from_db()
        self.assertEqual(self.library_a.name, "Renamed")
        self.assertFalse(self.library_a.is_active)

    def test_other_governorate_libraries_are_not_found(self):
        requests = [
            ("get", detail_url(self.library_b)),
            ("patch", detail_url(self.library_b)),
            ("post", status_url(self.library_b, "deactivate")),
            ("post", status_url(self.inactive_library_b, "activate")),
        ]
        for method, url in requests:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, {"name": "Hijack"}, format="json")
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.library_b.refresh_from_db()
        self.inactive_library_b.refresh_from_db()
        self.assertEqual(self.library_b.name, "Beta Library")
        self.assertTrue(self.library_b.is_active)
        self.assertFalse(self.inactive_library_b.is_active)


class LibrarianLibraryTests(LibraryScopeTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.librarian_a)

    def test_sees_only_own_library(self):
        response = self.client.get(LIST_URL)
        self.assertEqual(self.result_ids(response), {self.library_a.id})

        response = self.client.get(detail_url(self.library_a))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["code"], "LIBRARY_RETRIEVED")

        for other in (self.inactive_library_a, self.library_b):
            with self.subTest(library=other.name):
                response = self.client.get(detail_url(other))
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_sees_own_library_even_when_inactive(self):
        self.library_a.is_active = False
        self.library_a.save()

        response = self.client.get(detail_url(self.library_a))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["data"]["is_active"])

    def test_updates_name_address_and_contact_of_own_library(self):
        payload = {
            "name": "Alpha Central",
            "address": "Square 1",
            "phone": "0999999999",
            "email": "alpha@example.com",
        }
        response = self.client.patch(detail_url(self.library_a), payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.library_a.refresh_from_db()
        for field, value in payload.items():
            self.assertEqual(getattr(self.library_a, field), value)

    def test_cannot_update_other_library(self):
        response = self.client.patch(
            detail_url(self.inactive_library_a), {"name": "Hijack"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_create_or_change_status(self):
        response = self.client.post(LIST_URL, {"name": "Mine"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        for operation in ("activate", "deactivate"):
            with self.subTest(operation=operation):
                response = self.client.post(status_url(self.library_a, operation))
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.library_a.refresh_from_db()
        self.assertTrue(self.library_a.is_active)

    def test_cannot_change_governorate_or_status_through_patch(self):
        for payload in ({"governorate": self.gov_b.id}, {"is_active": False}):
            with self.subTest(payload=payload):
                response = self.client.patch(detail_url(self.library_a), payload, format="json")
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.library_a.refresh_from_db()
        self.assertEqual(self.library_a.governorate_id, self.gov_a.id)
        self.assertTrue(self.library_a.is_active)


class ReaderLibraryTests(LibraryScopeTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.reader_a)

    def test_sees_only_active_libraries_of_own_governorate(self):
        response = self.client.get(LIST_URL)

        self.assertEqual(self.result_ids(response), {self.library_a.id})

    def test_direct_access_to_hidden_libraries_is_not_found(self):
        for library in (self.inactive_library_a, self.library_b, self.inactive_library_b):
            with self.subTest(library=library.name):
                response = self.client.get(detail_url(library))
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_filters_cannot_widen_scope(self):
        queries = [
            {"is_active": "false"},
            {"governorate": self.gov_b.id},
            {"governorate": self.gov_b.id, "is_active": "true"},
        ]
        for query in queries:
            with self.subTest(query=query):
                response = self.client.get(LIST_URL, query)
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(self.result_ids(response), set())

    def test_cannot_write(self):
        requests = [
            ("post", LIST_URL),
            ("patch", detail_url(self.library_a)),
            ("post", status_url(self.library_a, "deactivate")),
            ("post", status_url(self.library_a, "activate")),
        ]
        for method, url in requests:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, {"name": "Reader"}, format="json")
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.library_a.refresh_from_db()
        self.assertEqual(self.library_a.name, "Alpha Library")
        self.assertTrue(self.library_a.is_active)


class LibraryRequestHardeningTests(LibraryScopeTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.ministry)

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(LIST_URL)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_governorate_cannot_change_after_creation(self):
        response = self.client.patch(
            detail_url(self.library_a), {"governorate": self.gov_b.id}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("governorate", response.data["errors"])
        self.library_a.refresh_from_db()
        self.assertEqual(self.library_a.governorate_id, self.gov_a.id)

    def test_sending_current_governorate_is_accepted_without_change(self):
        response = self.client.patch(
            detail_url(self.library_a),
            {"governorate": self.gov_a.id, "name": "Same Gov"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.library_a.refresh_from_db()
        self.assertEqual(self.library_a.governorate_id, self.gov_a.id)
        self.assertEqual(self.library_a.name, "Same Gov")

    def test_is_active_is_rejected_on_create_and_patch(self):
        response = self.client.post(
            LIST_URL,
            {"name": "Sleeping", "governorate": self.gov_a.id, "is_active": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("is_active", response.data["errors"])
        self.assertFalse(Library.objects.filter(name="Sleeping").exists())

        response = self.client.patch(
            detail_url(self.library_a), {"is_active": False}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.library_a.refresh_from_db()
        self.assertTrue(self.library_a.is_active)

    def test_unknown_and_read_only_fields_are_rejected(self):
        for field, value in (("id", 999), ("created_at", "2020-01-01"), ("owner", 1)):
            with self.subTest(field=field):
                response = self.client.patch(
                    detail_url(self.library_a), {field: value}, format="json"
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(field, response.data["errors"])

    def test_delete_and_put_are_not_allowed(self):
        response = self.client.delete(detail_url(self.library_a))
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        response = self.client.put(
            detail_url(self.library_a),
            {"name": "Put", "governorate": self.gov_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertTrue(Library.objects.filter(pk=self.library_a.pk, name="Alpha Library").exists())

    def test_invalid_filter_values_are_rejected(self):
        for query in ({"is_active": "maybe"}, {"governorate": "abc"}):
            with self.subTest(query=query):
                response = self.client.get(LIST_URL, query)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_filters_narrow_ministry_results(self):
        response = self.client.get(LIST_URL, {"governorate": self.gov_b.id, "is_active": "false"})

        self.assertEqual(self.result_ids(response), {self.inactive_library_b.id})


class LibraryStatusTests(LibraryScopeTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.gov_admin_a)

    def test_repeated_activation_and_deactivation_are_idempotent(self):
        expected = [
            ("deactivate", "LIBRARY_DEACTIVATED", False),
            ("deactivate", "LIBRARY_ALREADY_INACTIVE", False),
            ("activate", "LIBRARY_ACTIVATED", True),
            ("activate", "LIBRARY_ALREADY_ACTIVE", True),
        ]
        for operation, code, is_active in expected:
            with self.subTest(operation=operation, code=code):
                response = self.client.post(status_url(self.library_a, operation))
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertTrue(response.data["success"])
                self.assertEqual(response.data["code"], code)
                self.assertEqual(response.data["data"]["is_active"], is_active)

    def test_deactivation_keeps_library_relations_and_librarian_account(self):
        self.client.post(status_url(self.library_a, "deactivate"))
        self.client.post(status_url(self.library_a, "deactivate"))

        self.library_a.refresh_from_db()
        self.librarian_a.refresh_from_db()
        self.assertFalse(self.library_a.is_active)
        self.assertEqual(self.library_a.governorate_id, self.gov_a.id)
        self.assertEqual(self.librarian_a.library_id, self.library_a.id)
        self.assertTrue(self.librarian_a.is_active)
        self.assertIn(self.librarian_a, self.library_a.users.all())

        self.client.post(status_url(self.library_a, "activate"))
        self.librarian_a.refresh_from_db()
        self.assertEqual(self.librarian_a.library_id, self.library_a.id)
        self.assertTrue(self.librarian_a.is_active)


class LibrarySearchAndPaginationTests(LibraryScopeTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        for index in range(3):
            Library.objects.create(name=f"Alpha Branch {index}", governorate=self.gov_a)
            Library.objects.create(name=f"Alpha Foreign {index}", governorate=self.gov_b)

    def test_search_does_not_leak_out_of_scope_libraries(self):
        self.client.force_authenticate(user=self.reader_a)

        response = self.client.get(LIST_URL, {"search": "alpha"})

        names = [item["name"] for item in response.data["data"]["results"]]
        self.assertEqual(
            names,
            ["Alpha Branch 0", "Alpha Branch 1", "Alpha Branch 2", "Alpha Library"],
        )

    def test_pagination_counts_only_scoped_libraries_in_stable_order(self):
        self.client.force_authenticate(user=self.gov_admin_a)

        first = self.client.get(LIST_URL, {"page_size": 2})
        second = self.client.get(LIST_URL, {"page_size": 2, "page": 2})
        third = self.client.get(LIST_URL, {"page_size": 2, "page": 3})

        self.assertEqual(first.data["data"]["count"], 5)
        self.assertIsNone(third.data["data"]["next"])
        names = [
            item["name"]
            for page in (first, second, third)
            for item in page.data["data"]["results"]
        ]
        self.assertEqual(
            names,
            [
                "Alpha Archive",
                "Alpha Branch 0",
                "Alpha Branch 1",
                "Alpha Branch 2",
                "Alpha Library",
            ],
        )

    def test_librarian_search_matches_only_own_library(self):
        self.client.force_authenticate(user=self.librarian_a)

        response = self.client.get(LIST_URL, {"search": "branch"})

        self.assertEqual(response.data["data"]["count"], 0)
