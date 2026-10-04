import json
from datetime import datetime, time, timedelta

from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import CustomUser, Governorate, Library
from books.models import Author, Book, Borrow, BorrowedBook, BorrowRequest, Category, FavoriteBook


PASSWORD = "StrongPass123!"
OVERVIEW = "/dashboard/stats/overview/"
TIMELINE = "/dashboard/stats/timeline/"
RANKINGS = "/dashboard/stats/rankings/"
DISTRIBUTIONS = "/dashboard/stats/distributions/"
ENDPOINTS = (OVERVIEW, TIMELINE, RANKINGS, DISTRIBUTIONS)


def local_dt(days_ago, hour=12, minute=0):
    """Aware datetime `days_ago` local days before today, at a local hour."""
    day = timezone.localdate() - timedelta(days=days_ago)
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


def day_str(days_ago):
    return (timezone.localdate() - timedelta(days=days_ago)).isoformat()


class StatsFactoryMixin:
    def create_user(self, username, role, **extra):
        return CustomUser.objects.create_user(
            username=username, email=f"{username}@example.com", password=PASSWORD,
            role=role, **extra,
        )

    def create_book(self, title, library, copies, available=None, **extra):
        book = Book.objects.create(
            title=title, description="desc", library=library, total_copies=copies, **extra
        )
        if available is not None:
            Book.objects.filter(pk=book.pk).update(
                available_copies=available, is_avaiable=available > 0
            )
        return book

    def borrow(self, reader, book, borrowed_days_ago, returned_days_ago=None, request=None):
        returned = returned_days_ago is not None
        record = Borrow.objects.create(
            reader=reader, book=book, request=request,
            status=Borrow.Status.RETURNED if returned else Borrow.Status.ACTIVE,
        )
        Borrow.objects.filter(pk=record.pk).update(
            borrowed_at=local_dt(borrowed_days_ago),
            returned_at=local_dt(returned_days_ago) if returned else None,
        )
        return record

    def borrow_request(self, reader, book, state, created_days_ago, decided_days_ago=None):
        record = BorrowRequest.objects.create(reader=reader, book=book, status=state)
        BorrowRequest.objects.filter(pk=record.pk).update(
            created_at=local_dt(created_days_ago),
            decided_at=None if decided_days_ago is None else local_dt(decided_days_ago),
        )
        return record

    def favorite(self, user, book, days_ago=0):
        record = FavoriteBook.objects.create(user=user, book=book)
        FavoriteBook.objects.filter(pk=record.pk).update(created_at=local_dt(days_ago))
        return record

    def get(self, user, url, params=None):
        self.client.force_authenticate(user=user)
        return self.client.get(url, params or {})

    def data(self, user, url, params=None):
        response = self.get(user, url, params)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data["data"]


class StatsTestMixin(StatsFactoryMixin):
    """Governorate A (active): library A1 (active), A2 (inactive).
    Governorate B (active): library B. Governorate C (inactive): library C (inactive).

    Days below are "days ago" in the project timezone.
    """

    def setUp(self):
        self.gov_a = Governorate.objects.create(name="Governorate A")
        self.gov_b = Governorate.objects.create(name="Governorate B")
        self.gov_c = Governorate.objects.create(name="Governorate C", is_active=False)
        self.lib_a1 = Library.objects.create(name="Library A1", governorate=self.gov_a)
        self.lib_a2 = Library.objects.create(
            name="Library A2", governorate=self.gov_a, is_active=False
        )
        self.lib_b = Library.objects.create(name="Library B", governorate=self.gov_b)
        self.lib_c = Library.objects.create(
            name="Library C", governorate=self.gov_c, is_active=False
        )

        Role = CustomUser.Role
        self.superuser = CustomUser.objects.create_superuser(
            username="root", email="root@example.com", password=PASSWORD
        )
        self.ministry = self.create_user("ministry", Role.MINISTRY_ADMIN)
        self.gov_admin_a = self.create_user("gov_a", Role.GOVERNORATE_ADMIN, governorate=self.gov_a)
        self.gov_admin_b = self.create_user("gov_b", Role.GOVERNORATE_ADMIN, governorate=self.gov_b)
        self.librarian_a1 = self.create_user("lib_a1", Role.LIBRARIAN, library=self.lib_a1)
        self.librarian_a2 = self.create_user(
            "lib_a2", Role.LIBRARIAN, library=self.lib_a2, is_active=False
        )
        self.librarian_b = self.create_user("lib_b", Role.LIBRARIAN, library=self.lib_b)
        self.reader_a1 = self.create_user("reader_a1", Role.READER, governorate=self.gov_a)
        self.reader_a2 = self.create_user(
            "reader_a2", Role.READER, governorate=self.gov_a, borrowing_blocked=True
        )
        self.reader_a3 = self.create_user(
            "reader_a3", Role.READER, governorate=self.gov_a, is_active=False
        )
        self.reader_b1 = self.create_user("reader_b1", Role.READER, governorate=self.gov_b)
        self.reader_c1 = self.create_user("reader_c1", Role.READER, governorate=self.gov_c)

        au1, au2, au3 = (Author.objects.create(name=f"Author {i}") for i in range(1, 4))
        cat1, cat2 = (Category.objects.create(name=f"Category {i}") for i in range(1, 3))
        Author.objects.create(name="Unused author")
        Category.objects.create(name="Unused category")

        self.book_a1 = self.create_book("Book A1", self.lib_a1, 3, 2, author=au1, category=cat1)
        self.book_a1_archived = self.create_book(
            "Archived A1", self.lib_a1, 1, 1, author=au2, category=cat1, is_archived=True
        )
        self.book_a2 = self.create_book("Book A2", self.lib_a2, 2, 1, author=au2)
        self.book_b = self.create_book("Book B", self.lib_b, 2, 1, author=au3, category=cat2)
        self.book_b_empty = self.create_book("Empty B", self.lib_b, 0, 0)
        self.book_c = self.create_book("Book C", self.lib_c, 1, 1, author=au3, category=cat2)

        Status = BorrowRequest.Status
        self.r_approved = self.borrow_request(self.reader_a2, self.book_a1, Status.APPROVED, 11, 10)
        self.borrow_request(self.reader_a1, self.book_a1, Status.REJECTED, 2, 1)
        self.borrow_request(self.reader_a1, self.book_a2, Status.PENDING, 0)
        self.borrow_request(self.reader_b1, self.book_b, Status.REJECTED, 20, 20)
        self.borrow_request(self.reader_c1, self.book_c, Status.PENDING, 60)
        self.borrow_request(self.reader_a3, self.book_a1_archived, Status.APPROVED, 100, 100)

        self.borrow(self.reader_a1, self.book_a1, 1)
        self.borrow(self.reader_a2, self.book_a1, 10, 2, request=self.r_approved)
        self.borrow(self.reader_a1, self.book_a2, 40)
        self.borrow(self.reader_b1, self.book_b, 3)
        self.borrow(self.reader_c1, self.book_c, 5, 5)
        self.borrow(self.reader_a3, self.book_a1_archived, 100, 50)

        self.favorite(self.reader_a1, self.book_a1)
        self.favorite(self.reader_a2, self.book_a1, 40)
        self.favorite(self.reader_a1, self.book_a1_archived)
        self.favorite(self.reader_b1, self.book_b)
        self.favorite(self.reader_c1, self.book_c)


def iter_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from iter_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_keys(item)


class PermissionTests(StatsTestMixin, APITestCase):
    def test_anonymous_is_rejected(self):
        for url in ENDPOINTS:
            response = self.client.get(url)
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED, url)
            self.assertEqual(response.data["code"], "AUTHENTICATION_REQUIRED")

    def test_reader_is_forbidden(self):
        for url in ENDPOINTS:
            response = self.get(self.reader_a1, url)
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, url)
            self.assertEqual(response.data["code"], "PERMISSION_DENIED")

    def test_admin_roles_are_allowed_with_envelope(self):
        codes = {
            OVERVIEW: "DASHBOARD_OVERVIEW_RETRIEVED",
            TIMELINE: "DASHBOARD_TIMELINE_RETRIEVED",
            RANKINGS: "DASHBOARD_RANKINGS_RETRIEVED",
            DISTRIBUTIONS: "DASHBOARD_DISTRIBUTIONS_RETRIEVED",
        }
        for user in (self.superuser, self.ministry, self.gov_admin_a, self.librarian_a1):
            for url, code in codes.items():
                with self.subTest(user=user.username, url=url):
                    response = self.get(user, url)
                    self.assertEqual(response.status_code, status.HTTP_200_OK)
                    self.assertTrue(response.data["success"])
                    self.assertEqual(response.data["code"], code)
                    self.assertTrue(response.data["message"])
                    self.assertIn("requester_role", response.data["meta"])

    def test_write_methods_are_not_allowed(self):
        self.client.force_authenticate(user=self.ministry)
        for url in ENDPOINTS:
            for method in ("post", "put", "patch", "delete"):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class ScopeTests(StatsTestMixin, APITestCase):
    def scope(self, user, params=None):
        return self.data(user, OVERVIEW, params)["scope"]

    def test_ministry_and_superuser_scope(self):
        for user in (self.ministry, self.superuser):
            self.assertEqual(
                self.scope(user), {"level": "MINISTRY", "governorate": None, "library": None}
            )

    def test_ministry_governorate_filter(self):
        self.assertEqual(
            self.scope(self.ministry, {"governorate": self.gov_a.pk}),
            {
                "level": "GOVERNORATE",
                "governorate": {"id": self.gov_a.pk, "name": "Governorate A", "is_active": True},
                "library": None,
            },
        )

    def test_ministry_library_filter_with_and_without_governorate(self):
        expected = {
            "level": "LIBRARY",
            "governorate": {"id": self.gov_a.pk, "name": "Governorate A", "is_active": True},
            "library": {"id": self.lib_a1.pk, "name": "Library A1", "is_active": True},
        }
        self.assertEqual(self.scope(self.ministry, {"library": self.lib_a1.pk}), expected)
        self.assertEqual(
            self.scope(self.ministry, {"library": self.lib_a1.pk, "governorate": self.gov_a.pk}),
            expected,
        )

    def test_contradicting_filters_are_rejected(self):
        for url in ENDPOINTS:
            response = self.get(
                self.ministry, url, {"governorate": self.gov_b.pk, "library": self.lib_a1.pk}
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.data["code"], "VALIDATION_ERROR")
            self.assertIn("library", response.data["errors"])

    def test_missing_units_are_not_found(self):
        for params in ({"governorate": 999999}, {"library": 999999}):
            response = self.get(self.ministry, OVERVIEW, params)
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
            self.assertEqual(response.data["code"], "NOT_FOUND")

    def test_gov_admin_scope_and_filters(self):
        self.assertEqual(self.scope(self.gov_admin_a)["level"], "GOVERNORATE")
        self.assertEqual(self.scope(self.gov_admin_a)["governorate"]["id"], self.gov_a.pk)
        self.assertEqual(
            self.scope(self.gov_admin_a, {"governorate": self.gov_a.pk})["level"], "GOVERNORATE"
        )
        scope = self.scope(self.gov_admin_a, {"library": self.lib_a2.pk})
        self.assertEqual(scope["level"], "LIBRARY")
        self.assertEqual(scope["library"]["id"], self.lib_a2.pk)

    def test_gov_admin_cannot_expand_scope(self):
        for url in ENDPOINTS:
            for params in (
                {"library": self.lib_b.pk},
                {"governorate": self.gov_b.pk},
                {"governorate": self.gov_b.pk, "library": self.lib_b.pk},
            ):
                with self.subTest(url=url, params=params):
                    response = self.get(self.gov_admin_a, url, params)
                    self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
                    self.assertEqual(response.data["code"], "NOT_FOUND")

    def test_librarian_is_fixed_to_own_library(self):
        expected = {
            "level": "LIBRARY",
            "governorate": {"id": self.gov_a.pk, "name": "Governorate A", "is_active": True},
            "library": {"id": self.lib_a1.pk, "name": "Library A1", "is_active": True},
        }
        self.assertEqual(self.scope(self.librarian_a1), expected)
        self.assertEqual(self.scope(self.librarian_a1, {"library": self.lib_a1.pk}), expected)
        self.assertEqual(self.scope(self.librarian_a1, {"governorate": self.gov_a.pk}), expected)

    def test_librarian_cannot_expand_scope(self):
        for url in ENDPOINTS:
            for params in (
                {"library": self.lib_a2.pk},
                {"library": self.lib_b.pk},
                {"governorate": self.gov_b.pk},
            ):
                with self.subTest(url=url, params=params):
                    response = self.get(self.librarian_a1, url, params)
                    self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_invalid_ids_are_rejected(self):
        for name in ("governorate", "library"):
            for value in ("abc", "0", "-1", "1.5", "99999999999999999999"):
                with self.subTest(name=name, value=value):
                    response = self.get(self.ministry, OVERVIEW, {name: value})
                    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                    self.assertEqual(response.data["code"], "VALIDATION_ERROR")
                    self.assertIn(name, response.data["errors"])

    def test_no_cross_governorate_leakage(self):
        data = self.data(self.gov_admin_b, OVERVIEW)
        self.assertEqual(data["catalog"]["books_count"], 2)
        self.assertEqual(data["users"]["readers_count"], 1)
        self.assertEqual(data["borrowing"]["current"]["active_borrows"], 1)
        self.assertEqual(data["requests"]["current"]["pending_requests"], 0)
        self.assertEqual(data["favorites"]["current"]["favorites_count"], 1)
        rankings = self.data(self.gov_admin_b, RANKINGS)
        self.assertEqual(
            [b["book_id"] for b in rankings["most_borrowed_books"]], [self.book_b.pk]
        )
        self.assertEqual(
            [b["book_id"] for b in rankings["most_requested_books"]], [self.book_b.pk]
        )
        self.assertEqual(
            [b["book_id"] for b in rankings["most_favorited_books"]], [self.book_b.pk]
        )
        libraries = self.data(self.gov_admin_b, DISTRIBUTIONS)["libraries"]
        self.assertEqual([row["library_id"] for row in libraries], [self.lib_b.pk])


class OverviewTests(StatsTestMixin, APITestCase):
    def test_ministry_overview(self):
        data = self.data(self.ministry, OVERVIEW)
        self.assertEqual(
            data["organization"],
            {
                "governorates_count": 3,
                "active_governorates_count": 2,
                "inactive_governorates_count": 1,
                "libraries_count": 4,
                "active_libraries_count": 2,
                "inactive_libraries_count": 2,
            },
        )
        self.assertEqual(
            data["users"],
            {
                "readers_basis": "SYSTEM",
                "readers_count": 5,
                "active_readers_count": 4,
                "inactive_readers_count": 1,
                "borrowing_blocked_readers_count": 1,
                "librarians_count": 3,
                "active_librarians_count": 2,
                "inactive_librarians_count": 1,
            },
        )
        self.assertEqual(
            data["catalog"],
            {
                "books_count": 6,
                "active_books_count": 5,
                "archived_books_count": 1,
                "total_copies": 9,
                "available_copies": 6,
                "borrowed_copies": 3,
                "unavailable_books_count": 1,
                "authors_count": 3,
                "categories_count": 2,
            },
        )
        self.assertEqual(
            data["borrowing"],
            {
                "current": {"active_borrows": 3, "returned_borrows_total": 3},
                "period": {
                    "borrows_created": 4,
                    "direct_borrows": 3,
                    "request_borrows": 1,
                    "returns": 2,
                },
            },
        )
        self.assertEqual(
            data["requests"],
            {
                "current": {"pending_requests": 2},
                "period": {
                    "requests_created": 4,
                    "approved_requests": 1,
                    "rejected_requests": 2,
                    "decided_requests": 3,
                    "approval_rate": 33.33,
                    "rejection_rate": 66.67,
                },
            },
        )
        self.assertEqual(
            data["favorites"],
            {"current": {"favorites_count": 5}, "period": {"favorites_added": 4}},
        )

    def test_governorate_overview(self):
        data = self.data(self.gov_admin_a, OVERVIEW)
        self.assertEqual(
            data["organization"],
            {"libraries_count": 2, "active_libraries_count": 1, "inactive_libraries_count": 1},
        )
        self.assertEqual(
            data["users"],
            {
                "readers_basis": "GOVERNORATE",
                "readers_count": 3,
                "active_readers_count": 2,
                "inactive_readers_count": 1,
                "borrowing_blocked_readers_count": 1,
                "librarians_count": 2,
                "active_librarians_count": 1,
                "inactive_librarians_count": 1,
            },
        )
        self.assertEqual(data["catalog"]["books_count"], 3)
        self.assertEqual(data["catalog"]["total_copies"], 6)
        self.assertEqual(data["catalog"]["available_copies"], 4)
        self.assertEqual(data["catalog"]["borrowed_copies"], 2)
        self.assertEqual(data["catalog"]["authors_count"], 2)
        self.assertEqual(data["catalog"]["categories_count"], 1)
        self.assertEqual(data["borrowing"]["current"], {"active_borrows": 2, "returned_borrows_total": 2})
        self.assertEqual(data["borrowing"]["period"]["borrows_created"], 2)
        self.assertEqual(data["borrowing"]["period"]["returns"], 1)
        self.assertEqual(data["requests"]["current"]["pending_requests"], 1)
        self.assertEqual(data["requests"]["period"]["approval_rate"], 50.0)
        self.assertEqual(data["requests"]["period"]["rejection_rate"], 50.0)
        self.assertEqual(data["favorites"]["current"]["favorites_count"], 3)

    def test_library_overview(self):
        data = self.data(self.librarian_a1, OVERVIEW)
        self.assertIsNone(data["organization"])
        self.assertEqual(
            data["users"],
            {
                "readers_basis": None,
                "readers_count": None,
                "active_readers_count": None,
                "inactive_readers_count": None,
                "borrowing_blocked_readers_count": None,
                "librarians_count": 1,
                "active_librarians_count": 1,
                "inactive_librarians_count": 0,
            },
        )
        self.assertEqual(data["catalog"]["books_count"], 2)
        self.assertEqual(data["catalog"]["archived_books_count"], 1)
        self.assertEqual(data["catalog"]["borrowed_copies"], 1)
        self.assertEqual(data["catalog"]["authors_count"], 2)
        self.assertEqual(data["catalog"]["categories_count"], 1)
        self.assertEqual(data["borrowing"]["current"]["active_borrows"], 1)
        self.assertEqual(data["requests"]["period"]["requests_created"], 2)
        # Favorites of the archived book stay in the administrative total.
        self.assertEqual(data["favorites"]["current"]["favorites_count"], 3)

    def test_library_scope_reader_metrics_are_null_for_every_role(self):
        # Ministry/GovAdmin narrowing to a library get the same contract;
        # librarian counts still follow the library (lib_a2 has an inactive one).
        for user in (self.ministry, self.gov_admin_a):
            users = self.data(user, OVERVIEW, {"library": self.lib_a2.pk})["users"]
            for key in ("readers_basis", "readers_count", "active_readers_count",
                        "inactive_readers_count", "borrowing_blocked_readers_count"):
                self.assertIsNone(users[key], key)
            self.assertEqual(
                (users["librarians_count"], users["active_librarians_count"],
                 users["inactive_librarians_count"]),
                (1, 0, 1),
            )

    def test_snapshot_metrics_ignore_period(self):
        week = self.data(self.ministry, OVERVIEW, {"period": "7d"})
        month = self.data(self.ministry, OVERVIEW, {"period": "30d"})
        for section in ("organization", "users", "catalog"):
            self.assertEqual(week[section], month[section])
        for section in ("borrowing", "requests", "favorites"):
            self.assertEqual(week[section]["current"], month[section]["current"])
        self.assertEqual(week["borrowing"]["period"]["borrows_created"], 3)
        self.assertEqual(month["borrowing"]["period"]["borrows_created"], 4)

    def test_rates_exclude_pending_and_are_zero_without_decisions(self):
        data = self.data(self.ministry, OVERVIEW, {"governorate": self.gov_c.pk})
        self.assertEqual(data["requests"]["current"]["pending_requests"], 1)
        self.assertEqual(data["requests"]["period"]["decided_requests"], 0)
        self.assertEqual(data["requests"]["period"]["approval_rate"], 0.0)
        self.assertEqual(data["requests"]["period"]["rejection_rate"], 0.0)

    def test_zero_data_returns_zeros_not_nulls(self):
        Borrow.objects.all().delete()
        BorrowRequest.objects.all().delete()
        FavoriteBook.objects.all().delete()
        Book.objects.all().delete()
        for url in ENDPOINTS:
            data = self.data(self.ministry, url)
            for section in ("users", "catalog", "borrowing", "requests", "favorites"):
                if section in data:
                    for value in iter_values(data[section]):
                        self.assertIsNotNone(value, (url, section))
        data = self.data(self.ministry, OVERVIEW)
        self.assertEqual(data["catalog"]["total_copies"], 0)
        self.assertEqual(data["catalog"]["borrowed_copies"], 0)
        self.assertEqual(data["requests"]["period"]["approval_rate"], 0.0)
        rankings = self.data(self.ministry, RANKINGS)
        self.assertEqual(rankings["most_borrowed_books"], [])
        self.assertEqual(rankings["most_active_governorates"], [])
        series = self.data(self.ministry, TIMELINE, {"period": "7d"})["series"]
        self.assertEqual({row["borrows"] for row in series}, {0})


def iter_values(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from iter_values(item)
    else:
        yield value


class InactiveUnitTests(StatsTestMixin, APITestCase):
    def test_inactive_governorate_history_is_visible(self):
        data = self.data(self.ministry, OVERVIEW, {"governorate": self.gov_c.pk})
        self.assertFalse(data["scope"]["governorate"]["is_active"])
        self.assertEqual(
            data["organization"],
            {"libraries_count": 1, "active_libraries_count": 0, "inactive_libraries_count": 1},
        )
        self.assertEqual(data["catalog"]["books_count"], 1)
        self.assertEqual(data["borrowing"]["current"]["returned_borrows_total"], 1)
        self.assertEqual(data["borrowing"]["period"]["borrows_created"], 1)
        self.assertEqual(data["borrowing"]["period"]["returns"], 1)

    def test_inactive_library_history_is_visible(self):
        data = self.data(self.gov_admin_a, OVERVIEW, {"library": self.lib_a2.pk})
        self.assertFalse(data["scope"]["library"]["is_active"])
        self.assertEqual(data["borrowing"]["current"]["active_borrows"], 1)
        self.assertEqual(data["requests"]["current"]["pending_requests"], 1)
        custom = self.data(
            self.gov_admin_a, TIMELINE,
            {"library": self.lib_a2.pk, "date_from": day_str(45), "date_to": day_str(0)},
        )
        self.assertEqual(sum(row["borrows"] for row in custom["series"]), 1)


class PeriodTests(StatsTestMixin, APITestCase):
    def period(self, params):
        return self.data(self.ministry, OVERVIEW, params)["period"]

    def test_default_is_30_days(self):
        self.assertEqual(
            self.period({}),
            {
                "type": "30d",
                "date_from": day_str(29),
                "date_to": day_str(0),
                "days": 30,
                "timezone": timezone.get_current_timezone_name(),
            },
        )

    def test_7_days(self):
        period = self.period({"period": "7d"})
        self.assertEqual((period["type"], period["date_from"], period["days"]), ("7d", day_str(6), 7))

    def test_custom_range(self):
        period = self.period({"date_from": day_str(11), "date_to": day_str(10)})
        self.assertEqual(
            (period["type"], period["date_from"], period["date_to"], period["days"]),
            ("custom", day_str(11), day_str(10), 2),
        )
        data = self.data(self.ministry, OVERVIEW, {"date_from": day_str(11), "date_to": day_str(10)})
        self.assertEqual(data["borrowing"]["period"]["borrows_created"], 1)
        self.assertEqual(data["requests"]["period"]["requests_created"], 1)
        self.assertEqual(data["requests"]["period"]["approved_requests"], 1)
        self.assertEqual(data["requests"]["period"]["approval_rate"], 100.0)

    def test_date_to_today_is_allowed(self):
        period = self.period({"date_from": day_str(0), "date_to": day_str(0)})
        self.assertEqual((period["type"], period["date_to"], period["days"]), ("custom", day_str(0), 1))

    def test_future_dates_are_rejected(self):
        tomorrow = day_str(-1)
        cases = (
            {"date_from": day_str(3), "date_to": tomorrow},
            {"date_from": tomorrow, "date_to": day_str(-5)},
        )
        for url in ENDPOINTS:
            for params in cases:
                with self.subTest(url=url, params=params):
                    response = self.get(self.ministry, url, params)
                    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                    self.assertEqual(response.data["code"], "VALIDATION_ERROR")
                    self.assertEqual(set(response.data["errors"]), {"date_to"})
                    self.assertEqual(
                        str(response.data["errors"]["date_to"]),
                        "لا يمكن أن يكون تاريخ النهاية في المستقبل.",
                    )

    def test_max_custom_range(self):
        self.assertEqual(
            self.period({"date_from": day_str(365), "date_to": day_str(0)})["days"], 366
        )
        response = self.get(
            self.ministry, OVERVIEW, {"date_from": day_str(366), "date_to": day_str(0)}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("date_to", response.data["errors"])

    def test_invalid_periods(self):
        cases = [
            ({"period": "90d"}, "period"),
            ({"period": "7"}, "period"),
            ({"period": "7d", "date_from": day_str(3), "date_to": day_str(0)}, "period"),
            ({"date_from": day_str(3)}, "date_to"),
            ({"date_to": day_str(3)}, "date_from"),
            ({"date_from": "2026/10/01", "date_to": day_str(0)}, "date_from"),
            ({"date_from": "20261001", "date_to": day_str(0)}, "date_from"),
            ({"date_from": day_str(0), "date_to": "not-a-date"}, "date_to"),
            ({"date_from": day_str(0), "date_to": day_str(1)}, "date_from"),
        ]
        for url in ENDPOINTS:
            for params, field in cases:
                with self.subTest(url=url, params=params):
                    response = self.get(self.ministry, url, params)
                    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                    self.assertEqual(response.data["code"], "VALIDATION_ERROR")
                    self.assertIn(field, response.data["errors"])


class TimelineTests(StatsTestMixin, APITestCase):
    def series(self, user=None, params=None):
        return self.data(user or self.ministry, TIMELINE, params)["series"]

    def test_7_days_has_7_ordered_points_including_zero_days(self):
        series = self.series(params={"period": "7d"})
        self.assertEqual([row["date"] for row in series], [day_str(d) for d in range(6, -1, -1)])
        by_date = {row["date"]: row for row in series}
        zero = {"borrows": 0, "returns": 0, "requests": 0, "approved_requests": 0, "rejected_requests": 0}
        self.assertEqual({k: by_date[day_str(4)][k] for k in zero}, zero)
        self.assertEqual(by_date[day_str(1)]["borrows"], 1)
        self.assertEqual(by_date[day_str(3)]["borrows"], 1)
        self.assertEqual(by_date[day_str(5)]["borrows"], 1)
        self.assertEqual(by_date[day_str(2)]["returns"], 1)
        self.assertEqual(by_date[day_str(5)]["returns"], 1)
        self.assertEqual(by_date[day_str(2)]["requests"], 1)
        self.assertEqual(by_date[day_str(0)]["requests"], 1)
        self.assertEqual(by_date[day_str(1)]["rejected_requests"], 1)
        self.assertEqual(sum(row["approved_requests"] for row in series), 0)

    def test_30_days_has_30_points(self):
        series = self.series()
        self.assertEqual(len(series), 30)
        self.assertEqual(series[0]["date"], day_str(29))
        self.assertEqual(series[-1]["date"], day_str(0))
        self.assertEqual(sum(row["borrows"] for row in series), 4)
        self.assertEqual(sum(row["returns"] for row in series), 2)
        self.assertEqual(sum(row["requests"] for row in series), 4)
        self.assertEqual(sum(row["approved_requests"] for row in series), 1)
        self.assertEqual(sum(row["rejected_requests"] for row in series), 2)

    def test_uses_decision_date_for_decisions(self):
        series = self.series(params={"date_from": day_str(11), "date_to": day_str(10)})
        self.assertEqual(
            series,
            [
                {"date": day_str(11), "borrows": 0, "returns": 0, "requests": 1,
                 "approved_requests": 0, "rejected_requests": 0},
                {"date": day_str(10), "borrows": 1, "returns": 0, "requests": 0,
                 "approved_requests": 1, "rejected_requests": 0},
            ],
        )

    def test_days_follow_project_timezone(self):
        # 00:30 local time is still the previous day in UTC.
        record = self.borrow(self.reader_b1, self.book_b_empty, 2)
        Borrow.objects.filter(pk=record.pk).update(borrowed_at=local_dt(2, 0, 30))
        by_date = {row["date"]: row for row in self.series(self.gov_admin_b, {"period": "7d"})}
        self.assertEqual(by_date[day_str(2)]["borrows"], 1)
        self.assertEqual(by_date[day_str(3)]["borrows"], 1)

    def test_scoped(self):
        series = self.series(self.librarian_a1, {"period": "7d"})
        self.assertEqual(sum(row["borrows"] for row in series), 1)
        self.assertEqual(sum(row["requests"] for row in series), 1)


class RankingsTests(StatsTestMixin, APITestCase):
    def test_ministry_rankings(self):
        data = self.data(self.ministry, RANKINGS)
        self.assertEqual(data["limit"], 5)
        self.assertEqual(data["favorites_window"], "LIFETIME")
        self.assertEqual(
            data["most_borrowed_books"][0],
            {"book_id": self.book_a1.pk, "title": "Book A1", "library_id": self.lib_a1.pk,
             "library_name": "Library A1", "count": 2},
        )
        self.assertEqual(
            [(r["book_id"], r["count"]) for r in data["most_borrowed_books"]],
            [(self.book_a1.pk, 2), (self.book_b.pk, 1), (self.book_c.pk, 1)],
        )
        self.assertEqual(
            [(r["book_id"], r["count"]) for r in data["most_requested_books"]],
            [(self.book_a1.pk, 2), (self.book_a2.pk, 1), (self.book_b.pk, 1)],
        )
        # Lifetime: the 40-day-old favorite still counts; the archived book is included.
        self.assertEqual(
            [(r["book_id"], r["count"]) for r in data["most_favorited_books"]],
            [(self.book_a1.pk, 2), (self.book_a1_archived.pk, 1), (self.book_b.pk, 1),
             (self.book_c.pk, 1)],
        )
        self.assertEqual(
            data["most_active_libraries"],
            [
                {"library_id": self.lib_a1.pk, "library_name": "Library A1",
                 "governorate_id": self.gov_a.pk, "governorate_name": "Governorate A",
                 "borrows_count": 2},
                {"library_id": self.lib_b.pk, "library_name": "Library B",
                 "governorate_id": self.gov_b.pk, "governorate_name": "Governorate B",
                 "borrows_count": 1},
                {"library_id": self.lib_c.pk, "library_name": "Library C",
                 "governorate_id": self.gov_c.pk, "governorate_name": "Governorate C",
                 "borrows_count": 1},
            ],
        )
        self.assertEqual(
            data["most_active_governorates"],
            [
                {"governorate_id": self.gov_a.pk, "governorate_name": "Governorate A", "borrows_count": 2},
                {"governorate_id": self.gov_b.pk, "governorate_name": "Governorate B", "borrows_count": 1},
                {"governorate_id": self.gov_c.pk, "governorate_name": "Governorate C", "borrows_count": 1},
            ],
        )

    def test_period_specific_rankings(self):
        data = self.data(self.ministry, RANKINGS, {"period": "7d"})
        self.assertEqual(
            [(r["book_id"], r["count"]) for r in data["most_borrowed_books"]],
            [(self.book_a1.pk, 1), (self.book_b.pk, 1), (self.book_c.pk, 1)],
        )
        self.assertEqual(len(data["most_favorited_books"]), 4)

    def test_governorate_and_library_levels(self):
        data = self.data(self.gov_admin_a, RANKINGS)
        self.assertEqual([r["library_id"] for r in data["most_active_libraries"]], [self.lib_a1.pk])
        self.assertEqual(data["most_active_governorates"], [])
        data = self.data(self.librarian_a1, RANKINGS)
        self.assertEqual(data["most_active_libraries"], [])
        self.assertEqual(data["most_active_governorates"], [])
        self.assertEqual([r["book_id"] for r in data["most_borrowed_books"]], [self.book_a1.pk])

    def test_limit(self):
        data = self.data(self.ministry, RANKINGS, {"limit": 1})
        self.assertEqual(data["limit"], 1)
        for key in ("most_borrowed_books", "most_requested_books", "most_favorited_books",
                    "most_active_libraries", "most_active_governorates"):
            self.assertEqual(len(data[key]), 1, key)
        self.assertEqual(self.data(self.ministry, RANKINGS, {"limit": 10})["limit"], 10)
        for value in ("0", "11", "-1", "abc", "2.5"):
            response = self.get(self.ministry, RANKINGS, {"limit": value})
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, value)
            self.assertIn("limit", response.data["errors"])


class DistributionsTests(StatsTestMixin, APITestCase):
    def test_ministry_by_governorate(self):
        data = self.data(self.ministry, DISTRIBUTIONS)
        self.assertEqual(data["libraries"], [])
        self.assertEqual(
            data["governorates"],
            [
                {"governorate_id": self.gov_a.pk, "governorate_name": "Governorate A",
                 "is_active": True, "libraries_count": 2, "readers_count": 3, "books_count": 3,
                 "active_borrows_count": 2, "period_borrows_count": 2},
                {"governorate_id": self.gov_b.pk, "governorate_name": "Governorate B",
                 "is_active": True, "libraries_count": 1, "readers_count": 1, "books_count": 2,
                 "active_borrows_count": 1, "period_borrows_count": 1},
                {"governorate_id": self.gov_c.pk, "governorate_name": "Governorate C",
                 "is_active": False, "libraries_count": 1, "readers_count": 1, "books_count": 1,
                 "active_borrows_count": 0, "period_borrows_count": 1},
            ],
        )

    def test_governorate_with_no_data_is_listed_with_zeros(self):
        empty = Governorate.objects.create(name="Governorate Z")
        rows = self.data(self.ministry, DISTRIBUTIONS)["governorates"]
        self.assertEqual(
            rows[-1],
            {"governorate_id": empty.pk, "governorate_name": "Governorate Z", "is_active": True,
             "libraries_count": 0, "readers_count": 0, "books_count": 0,
             "active_borrows_count": 0, "period_borrows_count": 0},
        )

    def test_gov_admin_by_library(self):
        data = self.data(self.gov_admin_a, DISTRIBUTIONS)
        self.assertEqual(data["governorates"], [])
        self.assertEqual(
            data["libraries"],
            [
                {"library_id": self.lib_a1.pk, "library_name": "Library A1", "is_active": True,
                 "books_count": 2, "librarians_count": 1, "active_borrows_count": 1,
                 "period_borrows_count": 2},
                {"library_id": self.lib_a2.pk, "library_name": "Library A2", "is_active": False,
                 "books_count": 1, "librarians_count": 1, "active_borrows_count": 1,
                 "period_borrows_count": 0},
            ],
        )

    def test_ministry_governorate_filter_gives_library_distribution(self):
        data = self.data(self.ministry, DISTRIBUTIONS, {"governorate": self.gov_b.pk})
        self.assertEqual(data["governorates"], [])
        self.assertEqual([row["library_id"] for row in data["libraries"]], [self.lib_b.pk])

    def test_librarian_gets_empty_arrays(self):
        data = self.data(self.librarian_a1, DISTRIBUTIONS)
        self.assertEqual((data["governorates"], data["libraries"]), ([], []))

    def test_no_readers_by_library_metric(self):
        for user in (self.ministry, self.gov_admin_a):
            data = self.data(user, DISTRIBUTIONS)
            keys = set(iter_keys(data))
            self.assertNotIn("readers_by_library", keys)
            for row in data["libraries"]:
                self.assertNotIn("readers_count", row)


class LegacyAndFakeMetricTests(StatsTestMixin, APITestCase):
    FORBIDDEN_KEYS = {
        "overdue_books", "late_returns", "average_delay", "pending_returns",
        "due_date", "readers_by_library",
    }

    def test_new_endpoints_never_query_borrowed_book(self):
        BorrowedBook.objects.create(book=self.book_a1, borrower=self.reader_a1)
        for user in (self.ministry, self.gov_admin_a, self.librarian_a1):
            for url in ENDPOINTS:
                self.client.force_authenticate(user=user)
                with CaptureQueriesContext(connection) as ctx:
                    response = self.client.get(url)
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                for query in ctx.captured_queries:
                    self.assertNotIn("borrowedbook", query["sql"].lower(), url)

    def test_no_due_date_or_return_request_metrics(self):
        for url in ENDPOINTS:
            keys = set(iter_keys(self.data(self.ministry, url)))
            self.assertFalse(keys & self.FORBIDDEN_KEYS, url)
            self.assertFalse({key for key in keys if "overdue" in key or "late" in key}, url)

    def test_legacy_stats_is_marked_deprecated(self):
        self.client.force_authenticate(user=self.superuser)
        response = self.client.get("/dashboard/stats/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Deprecation"], "true")
        self.assertIn("/dashboard/stats/overview/", response["Link"])


class QueryCountTests(StatsFactoryMixin, APITestCase):
    """Query count must stay constant as governorates/libraries/books grow."""

    MAX_QUERIES = {OVERVIEW: 8, TIMELINE: 5, RANKINGS: 6, DISTRIBUTIONS: 5}

    def setUp(self):
        self.ministry = self.create_user("ministry", CustomUser.Role.MINISTRY_ADMIN)
        self.grow(1, 1)
        governorate = Governorate.objects.order_by("pk").first()
        library = Library.objects.order_by("pk").first()
        self.gov_admin = self.create_user(
            "gov_admin", CustomUser.Role.GOVERNORATE_ADMIN, governorate=governorate
        )
        self.librarian = self.create_user("librarian", CustomUser.Role.LIBRARIAN, library=library)

    def grow(self, governorates, libraries_per_governorate):
        """Add governorates, each with libraries, books, readers and activity."""
        Status = BorrowRequest.Status
        start = Governorate.objects.count()
        for g in range(start, start + governorates):
            governorate = Governorate.objects.create(name=f"G{g}", is_active=g % 2 == 0)
            author = Author.objects.create(name=f"Author {g}")
            readers = [
                self.create_user(f"r{g}_{i}", CustomUser.Role.READER, governorate=governorate)
                for i in range(2)
            ]
            for lib_index in range(libraries_per_governorate):
                library = Library.objects.create(name=f"L{g}_{lib_index}", governorate=governorate)
                self.create_user(f"lib{g}_{lib_index}", CustomUser.Role.LIBRARIAN, library=library)
                for b in range(2):
                    book = self.create_book(f"B{g}_{lib_index}_{b}", library, 3, 2, author=author)
                    self.borrow(readers[0], book, 1)
                    self.borrow(readers[1], book, 5, 2)
                    self.borrow_request(readers[0], book, Status.APPROVED, 3, 2)
                    self.borrow_request(readers[1], book, Status.PENDING, 1)
                    self.favorite(readers[0], book)

    def count_queries(self, user, url):
        self.client.force_authenticate(user=user)
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url, {"period": "30d"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return len(ctx.captured_queries)

    def snapshot(self):
        return {
            (user.username, url): self.count_queries(user, url)
            for user in (self.ministry, self.gov_admin, self.librarian)
            for url in ENDPOINTS
        }

    def test_query_count_is_bounded_and_does_not_grow(self):
        small = self.snapshot()
        self.grow(6, 4)
        large = self.snapshot()
        self.assertEqual(Library.objects.count(), 25)
        self.assertEqual(small, large)
        for (username, url), count in large.items():
            self.assertLessEqual(count, self.MAX_QUERIES[url], (username, url))

    def test_ministry_query_counts(self):
        # One aggregate per dataset; scope resolution costs nothing at ministry level.
        expected = {OVERVIEW: 7, TIMELINE: 4, RANKINGS: 5, DISTRIBUTIONS: 4}
        for url, count in expected.items():
            self.assertEqual(self.count_queries(self.ministry, url), count, url)

    def test_overview_query_counts_per_level(self):
        # Governorate: scope + organization + 5 aggregates. Library: scope + 5
        # aggregates; the users query there counts librarians only, no readers.
        self.assertEqual(self.count_queries(self.gov_admin, OVERVIEW), 7)
        self.assertEqual(self.count_queries(self.librarian, OVERVIEW), 6)
        self.client.force_authenticate(user=self.librarian)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(OVERVIEW)
        users_sql = [q["sql"] for q in ctx.captured_queries if "accounts_customuser" in q["sql"]]
        self.assertEqual(len(users_sql), 1)
        self.assertNotIn("READER", users_sql[0])


class SwaggerTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        response = Client().get("/api/schema/", {"format": "json"})
        cls.schema = json.loads(response.content)
        cls.paths = cls.schema["paths"]

    def methods(self, path):
        return {
            method for method in self.paths.get(path, {})
            if method in {"get", "post", "put", "patch", "delete"}
        }

    def parameters(self, path):
        return {param["name"] for param in self.paths[path]["get"].get("parameters", [])}

    def test_four_routes_are_documented_get_only(self):
        for url in ENDPOINTS:
            self.assertEqual(self.methods(url), {"get"}, url)
            self.assertEqual(self.paths[url]["get"]["tags"], ["Dashboard Statistics"])

    def test_filters_are_documented(self):
        common = {"period", "date_from", "date_to", "governorate", "library"}
        for url in ENDPOINTS:
            self.assertTrue(common <= self.parameters(url), url)
        self.assertIn("limit", self.parameters(RANKINGS))
        for url in (OVERVIEW, TIMELINE, DISTRIBUTIONS):
            self.assertNotIn("limit", self.parameters(url))

    def test_response_schema_is_documented(self):
        responses = self.paths[OVERVIEW]["get"]["responses"]
        for code in ("200", "400", "401", "403", "404"):
            self.assertIn(code, responses)

    def test_legacy_stats_is_hidden(self):
        self.assertNotIn("/dashboard/stats/", self.paths)
