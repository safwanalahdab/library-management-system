import json

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import CustomUser, Governorate, Library
from books import borrowing_services as services
from books.models import Book, Borrow, BorrowRequest


PASSWORD = "StrongPass123!"
REQUESTS_URL = "/dashboard/borrow-requests/"
BORROWS_URL = "/dashboard/borrows/"


class BorrowApiTestMixin:
    """Governorate A: libraries A1 and A2. Governorate B: library B.

    Integration fixtures: the real borrowing services run behind every API call.
    """

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
        self.gov_admin_b = self.create_user(
            "gov_admin_b", CustomUser.Role.GOVERNORATE_ADMIN, governorate=self.gov_b
        )
        self.librarian_a1 = self.create_user(
            "librarian_a1", CustomUser.Role.LIBRARIAN, library=self.library_a1
        )
        self.librarian_a2 = self.create_user(
            "librarian_a2", CustomUser.Role.LIBRARIAN, library=self.library_a2
        )
        self.reader = self.create_user("reader_a", CustomUser.Role.READER, governorate=self.gov_a)
        self.other_reader = self.create_user(
            "reader_a2", CustomUser.Role.READER, governorate=self.gov_a
        )
        self.reader_b = self.create_user("reader_b", CustomUser.Role.READER, governorate=self.gov_b)
        self.reader_b2 = self.create_user(
            "reader_b2", CustomUser.Role.READER, governorate=self.gov_b
        )

        self.book = self.create_book("Book A1", self.library_a1, 3)
        self.empty_book = self.create_book("Empty A1", self.library_a1, 0)
        self.book_a2 = self.create_book("Book A2", self.library_a2, 2)
        self.book_b = self.create_book("Book B", self.library_b, 2)

    def create_user(self, username, role, **extra):
        return CustomUser.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password=PASSWORD,
            role=role,
            **extra,
        )

    def create_book(self, title, library, copies):
        return Book.objects.create(
            title=title, description="desc", library=library, total_copies=copies
        )

    # Requests

    def get(self, user, url, params=None):
        self.client.force_authenticate(user=user)
        return self.client.get(url, params or {})

    def post(self, user, url, data=None):
        self.client.force_authenticate(user=user)
        return self.client.post(url, data or {}, format="json")

    def detail(self, base, record, suffix=""):
        return f"{base}{record.id}/{suffix}"

    def book_request_url(self, book):
        return f"/dashboard/books/{book.id}/borrow-requests/"

    # Fixtures through the real services

    def pending(self, reader=None, book=None):
        return services.create_borrow_request(reader=reader or self.reader, book=book or self.book)

    def active_borrow(self, reader=None, book=None, actor=None):
        return services.direct_borrow(
            actor=actor or self.superuser, reader=reader or self.reader, book=book or self.book
        )

    # Assertions

    def quantities(self, book):
        book.refresh_from_db()
        return (book.total_copies, book.available_copies, book.is_avaiable, book.count_borrowed)

    def assert_success(self, response, code, status_code=status.HTTP_200_OK):
        self.assertEqual(response.status_code, status_code, response.data)
        self.assertIs(response.data["success"], True)
        self.assertEqual(response.data["code"], code)
        self.assertTrue(response.data["message"])
        self.assertNotIn("errors", response.data)
        self.assertIn("requester_role", response.data["meta"])
        return response.data["data"]

    def assert_error(self, response, status_code, code, field=None):
        self.assertEqual(response.status_code, status_code, response.data)
        self.assertIs(response.data["success"], False)
        self.assertEqual(response.data["code"], code)
        self.assertIsNone(response.data["data"])
        if field is not None:
            self.assertIn(field, response.data["errors"])

    def assert_validation(self, response, field=None):
        self.assert_error(response, status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", field)

    def assert_forbidden(self, response):
        self.assert_error(response, status.HTTP_403_FORBIDDEN, "PERMISSION_DENIED")

    def assert_not_found(self, response):
        self.assert_error(response, status.HTTP_404_NOT_FOUND, "NOT_FOUND")

    def result_ids(self, response):
        return {item["id"] for item in response.data["data"]["results"]}


class AuthenticationTests(BorrowApiTestMixin, APITestCase):
    def test_anonymous_cannot_use_borrow_requests(self):
        request = self.pending()
        self.client.force_authenticate(user=None)
        for method, url in (
            ("get", REQUESTS_URL),
            ("get", self.detail(REQUESTS_URL, request)),
            ("post", self.book_request_url(self.book)),
            ("post", self.detail(REQUESTS_URL, request, "approve/")),
            ("post", self.detail(REQUESTS_URL, request, "reject/")),
        ):
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, {}, format="json")
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_anonymous_cannot_use_borrows(self):
        borrow = self.active_borrow()
        self.client.force_authenticate(user=None)
        for method, url in (
            ("get", BORROWS_URL),
            ("get", self.detail(BORROWS_URL, borrow)),
            ("post", BORROWS_URL),
            ("post", self.detail(BORROWS_URL, borrow, "return/")),
        ):
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, {}, format="json")
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_reader_cannot_approve(self):
        request = self.pending()

        self.assert_forbidden(self.post(self.reader, self.detail(REQUESTS_URL, request, "approve/")))
        request.refresh_from_db()
        self.assertEqual(request.status, BorrowRequest.Status.PENDING)

    def test_reader_cannot_reject(self):
        request = self.pending()

        self.assert_forbidden(self.post(self.reader, self.detail(REQUESTS_URL, request, "reject/")))
        request.refresh_from_db()
        self.assertEqual(request.status, BorrowRequest.Status.PENDING)

    def test_reader_cannot_direct_borrow(self):
        response = self.post(
            self.reader, BORROWS_URL, {"reader_id": self.reader.id, "book_id": self.book.id}
        )

        self.assert_forbidden(response)
        self.assertFalse(Borrow.objects.exists())

    def test_reader_cannot_return(self):
        borrow = self.active_borrow()

        self.assert_forbidden(self.post(self.reader, self.detail(BORROWS_URL, borrow, "return/")))
        borrow.refresh_from_db()
        self.assertEqual(borrow.status, Borrow.Status.ACTIVE)


class ReaderRequestFlowTests(BorrowApiTestMixin, APITestCase):
    """POST /dashboard/books/{id}/borrow-requests/ with an empty body."""

    def create(self, book=None, data=None, user=None):
        return self.post(user or self.reader, self.book_request_url(book or self.book), data)

    def test_reader_creates_pending_request(self):
        response = self.create()

        data = self.assert_success(response, "BORROW_REQUEST_CREATED", status.HTTP_201_CREATED)
        self.assertEqual(response.data["message"], "تم إرسال طلب الاستعارة بنجاح.")
        self.assertEqual(data["status"], "PENDING")
        self.assertEqual(data["book"], self.book.id)
        self.assertEqual(data["book_title"], "Book A1")
        self.assertEqual(data["library"], self.library_a1.id)
        self.assertEqual(data["governorate"], self.gov_a.id)
        self.assertIsNone(data["decided_by"])
        self.assertIsNone(data["decided_by_username"])
        self.assertEqual(self.quantities(self.book), (3, 3, True, 0))

    def test_reader_is_always_request_user(self):
        data = self.assert_success(self.create(), "BORROW_REQUEST_CREATED", status.HTTP_201_CREATED)

        self.assertEqual(data["reader"], self.reader.id)
        self.assertEqual(data["reader_username"], "reader_a")
        self.assertEqual(BorrowRequest.objects.get(pk=data["id"]).reader, self.reader)

    def test_no_body_is_accepted(self):
        self.client.force_authenticate(user=self.reader)

        response = self.client.post(self.book_request_url(self.book))

        self.assert_success(response, "BORROW_REQUEST_CREATED", status.HTTP_201_CREATED)

    def test_any_body_field_is_rejected(self):
        for field, value in (
            ("reader", self.other_reader.id),
            ("book", self.book_a2.id),
            ("book_id", self.book_a2.id),
            ("status", "APPROVED"),
            ("decided_by", self.librarian_a1.id),
            ("rejection_reason", "x"),
            ("unknown", 1),
        ):
            with self.subTest(field=field):
                self.assert_validation(self.create(data={field: value}), field)
        self.assertFalse(BorrowRequest.objects.exists())

    def test_no_available_copies_still_allows_request(self):
        data = self.assert_success(
            self.create(book=self.empty_book), "BORROW_REQUEST_CREATED", status.HTTP_201_CREATED
        )

        self.assertEqual(data["status"], "PENDING")

    def test_blocked_reader_is_rejected(self):
        self.reader.borrowing_blocked = True
        self.reader.save(update_fields=["borrowing_blocked"])

        self.assert_validation(self.create(), "reader")
        self.assertFalse(BorrowRequest.objects.exists())

    def test_active_borrow_for_same_book_is_rejected(self):
        self.active_borrow()

        self.assert_validation(self.create(), "book")
        self.assertFalse(BorrowRequest.objects.exists())

    def test_duplicate_pending_request_is_rejected(self):
        self.create()

        self.assert_validation(self.create(), "book")
        self.assertEqual(BorrowRequest.objects.count(), 1)

    def test_archived_missing_and_other_governorate_books_are_not_found(self):
        archived = self.create_book("Archived", self.library_a1, 1)
        Book.objects.filter(pk=archived.pk).update(is_archived=True)
        for book in (archived, self.book_b, Book(pk=999999)):
            with self.subTest(book=book.pk):
                self.assert_not_found(self.create(book=book))
        self.assertFalse(BorrowRequest.objects.exists())

    def test_inactive_library_or_governorate_is_not_found(self):
        for instance in (self.library_a1, self.gov_a):
            with self.subTest(instance=instance.name):
                instance.is_active = False
                instance.save()
                self.assert_not_found(self.create())
                instance.is_active = True
                instance.save()
        self.assertFalse(BorrowRequest.objects.exists())

    def test_operators_cannot_create_requests(self):
        for user in (self.librarian_a1, self.gov_admin_a, self.ministry, self.superuser):
            with self.subTest(user=user.username):
                self.assert_forbidden(self.create(user=user))
        self.assertFalse(BorrowRequest.objects.exists())

    def test_anonymous_is_unauthorized(self):
        self.client.force_authenticate(user=None)

        response = self.client.post(self.book_request_url(self.book), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_old_collection_create_is_gone(self):
        for user in (self.reader, self.librarian_a1, self.ministry):
            with self.subTest(user=user.username):
                response = self.post(user, REQUESTS_URL, {"book": self.book.id})
                self.assert_error(
                    response, status.HTTP_405_METHOD_NOT_ALLOWED, "METHOD_NOT_ALLOWED"
                )
        self.assertFalse(BorrowRequest.objects.exists())


class ReaderReadScopeTests(BorrowApiTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.own_request = self.pending()
        self.other_request = self.pending(reader=self.other_reader)
        self.own_borrow = self.active_borrow(book=self.book_a2)
        self.other_borrow = self.active_borrow(reader=self.other_reader, book=self.book_a2)

    def test_reader_lists_only_own_requests(self):
        response = self.get(self.reader, REQUESTS_URL)

        self.assert_success(response, "BORROW_REQUESTS_RETRIEVED")
        self.assertEqual(self.result_ids(response), {self.own_request.id})

    def test_reader_retrieves_own_request(self):
        data = self.assert_success(
            self.get(self.reader, self.detail(REQUESTS_URL, self.own_request)),
            "BORROW_REQUEST_RETRIEVED",
        )

        self.assertEqual(data["id"], self.own_request.id)

    def test_reader_cannot_retrieve_other_reader_request(self):
        self.assert_not_found(self.get(self.reader, self.detail(REQUESTS_URL, self.other_request)))

    def test_reader_lists_only_own_borrows(self):
        response = self.get(self.reader, BORROWS_URL)

        self.assert_success(response, "BORROWS_RETRIEVED")
        self.assertEqual(self.result_ids(response), {self.own_borrow.id})

    def test_reader_retrieves_own_borrow(self):
        data = self.assert_success(
            self.get(self.reader, self.detail(BORROWS_URL, self.own_borrow)), "BORROW_RETRIEVED"
        )

        self.assertEqual(data["id"], self.own_borrow.id)
        self.assertEqual(data["source"], "DIRECT")

    def test_reader_cannot_retrieve_other_reader_borrow(self):
        self.assert_not_found(self.get(self.reader, self.detail(BORROWS_URL, self.other_borrow)))

    def test_reader_filters_cannot_reach_other_readers(self):
        response = self.get(self.reader, REQUESTS_URL, {"reader": self.other_reader.id})

        self.assertEqual(self.result_ids(response), set())


class LibrarianTests(BorrowApiTestMixin, APITestCase):
    def test_sees_requests_of_own_library_only(self):
        own = self.pending()
        self.pending(book=self.book_a2)
        self.pending(reader=self.reader_b, book=self.book_b)

        self.assertEqual(self.result_ids(self.get(self.librarian_a1, REQUESTS_URL)), {own.id})

    def test_sees_borrows_of_own_library_only(self):
        own = self.active_borrow()
        self.active_borrow(book=self.book_a2)
        self.active_borrow(reader=self.reader_b, book=self.book_b)

        self.assertEqual(self.result_ids(self.get(self.librarian_a1, BORROWS_URL)), {own.id})

    def test_approves_own_library_request(self):
        request = self.pending()

        data = self.assert_success(
            self.post(self.librarian_a1, self.detail(REQUESTS_URL, request, "approve/")),
            "BORROW_REQUEST_APPROVED",
        )

        self.assertEqual(data["request"]["status"], "APPROVED")
        self.assertEqual(data["request"]["decided_by"], self.librarian_a1.id)
        self.assertEqual(data["borrow"]["source"], "REQUEST")
        self.assertEqual(data["borrow"]["created_by_username"], "librarian_a1")

    def test_cannot_approve_other_library_request(self):
        request = self.pending(book=self.book_a2)

        self.assert_not_found(
            self.post(self.librarian_a1, self.detail(REQUESTS_URL, request, "approve/"))
        )
        request.refresh_from_db()
        self.assertEqual(request.status, BorrowRequest.Status.PENDING)
        self.assertEqual(self.quantities(self.book_a2), (2, 2, True, 0))

    def test_rejects_own_library_request(self):
        request = self.pending()

        data = self.assert_success(
            self.post(self.librarian_a1, self.detail(REQUESTS_URL, request, "reject/")),
            "BORROW_REQUEST_REJECTED",
        )

        self.assertEqual(data["status"], "REJECTED")

    def test_cannot_reject_other_library_request(self):
        request = self.pending(book=self.book_a2)

        self.assert_not_found(
            self.post(self.librarian_a1, self.detail(REQUESTS_URL, request, "reject/"))
        )

    def test_direct_borrows_own_library_book(self):
        data = self.assert_success(
            self.post(self.librarian_a1, BORROWS_URL, {"reader_id": self.reader.id, "book_id": self.book.id}),
            "BORROW_CREATED",
            status.HTTP_201_CREATED,
        )

        self.assertEqual(data["created_by"], self.librarian_a1.id)
        self.assertEqual(self.quantities(self.book), (3, 2, True, 1))

    def test_cannot_direct_borrow_other_library_book(self):
        response = self.post(
            self.librarian_a1, BORROWS_URL, {"reader_id": self.reader.id, "book_id": self.book_a2.id}
        )

        self.assert_validation(response, "book_id")
        self.assertFalse(Borrow.objects.exists())
        self.assertEqual(self.quantities(self.book_a2), (2, 2, True, 0))

    def test_cannot_direct_borrow_for_reader_of_other_governorate(self):
        response = self.post(
            self.librarian_a1, BORROWS_URL, {"reader_id": self.reader_b.id, "book_id": self.book.id}
        )

        self.assert_validation(response, "reader_id")
        missing = self.post(self.librarian_a1, BORROWS_URL, {"reader_id": 999999, "book_id": self.book.id})
        self.assertEqual(response.data["errors"], missing.data["errors"])

    def test_returns_own_library_borrow(self):
        borrow = self.active_borrow()

        data = self.assert_success(
            self.post(self.librarian_a1, self.detail(BORROWS_URL, borrow, "return/")),
            "BORROW_RETURNED",
        )

        self.assertEqual(data["status"], "RETURNED")
        self.assertEqual(data["returned_by_username"], "librarian_a1")

    def test_cannot_return_other_library_borrow(self):
        borrow = self.active_borrow(book=self.book_a2)

        self.assert_not_found(self.post(self.librarian_a1, self.detail(BORROWS_URL, borrow, "return/")))
        borrow.refresh_from_db()
        self.assertEqual(borrow.status, Borrow.Status.ACTIVE)


class GovernorateAdminTests(BorrowApiTestMixin, APITestCase):
    def test_sees_all_requests_and_borrows_of_own_governorate(self):
        requests = {self.pending().id, self.pending(book=self.book_a2).id}
        self.pending(reader=self.reader_b, book=self.book_b)
        borrows = {
            self.active_borrow(reader=self.other_reader).id,
            self.active_borrow(reader=self.other_reader, book=self.book_a2).id,
        }
        self.active_borrow(reader=self.reader_b2, book=self.book_b)

        self.assertEqual(self.result_ids(self.get(self.gov_admin_a, REQUESTS_URL)), requests)
        self.assertEqual(self.result_ids(self.get(self.gov_admin_a, BORROWS_URL)), borrows)

    def test_does_not_see_other_governorate(self):
        request = self.pending(reader=self.reader_b, book=self.book_b)
        borrow = self.active_borrow(reader=self.reader_b2, book=self.book_b)

        self.assert_not_found(self.get(self.gov_admin_a, self.detail(REQUESTS_URL, request)))
        self.assert_not_found(self.get(self.gov_admin_a, self.detail(BORROWS_URL, borrow)))
        self.assertEqual(
            self.result_ids(self.get(self.gov_admin_a, REQUESTS_URL, {"governorate": self.gov_b.id})),
            set(),
        )

    def test_approves_in_governorate(self):
        request = self.pending(book=self.book_a2)

        self.assert_success(
            self.post(self.gov_admin_a, self.detail(REQUESTS_URL, request, "approve/")),
            "BORROW_REQUEST_APPROVED",
        )

    def test_rejects_in_governorate(self):
        request = self.pending(book=self.book_a2)

        self.assert_success(
            self.post(self.gov_admin_a, self.detail(REQUESTS_URL, request, "reject/")),
            "BORROW_REQUEST_REJECTED",
        )

    def test_direct_borrows_in_governorate(self):
        self.assert_success(
            self.post(self.gov_admin_a, BORROWS_URL, {"reader_id": self.other_reader.id, "book_id": self.book_a2.id}),
            "BORROW_CREATED",
            status.HTTP_201_CREATED,
        )

    def test_returns_in_governorate(self):
        borrow = self.active_borrow(book=self.book_a2)

        self.assert_success(
            self.post(self.gov_admin_a, self.detail(BORROWS_URL, borrow, "return/")),
            "BORROW_RETURNED",
        )

    def test_cannot_operate_across_governorates(self):
        request = self.pending(reader=self.reader_b, book=self.book_b)
        borrow = self.active_borrow(reader=self.reader_b2, book=self.book_b)

        self.assert_not_found(self.post(self.gov_admin_a, self.detail(REQUESTS_URL, request, "approve/")))
        self.assert_not_found(self.post(self.gov_admin_a, self.detail(REQUESTS_URL, request, "reject/")))
        self.assert_not_found(self.post(self.gov_admin_a, self.detail(BORROWS_URL, borrow, "return/")))
        self.assert_validation(
            self.post(self.gov_admin_a, BORROWS_URL, {"reader_id": self.reader_b2.id, "book_id": self.book_b.id}),
            "book_id",
        )
        request.refresh_from_db()
        borrow.refresh_from_db()
        self.assertEqual((request.status, borrow.status), ("PENDING", "ACTIVE"))


class MinistryAndSuperuserTests(BorrowApiTestMixin, APITestCase):
    def test_ministry_sees_everything(self):
        requests = {
            self.pending().id,
            self.pending(book=self.book_a2).id,
            self.pending(reader=self.reader_b, book=self.book_b).id,
        }
        borrows = {
            self.active_borrow(reader=self.other_reader).id,
            self.active_borrow(reader=self.reader_b2, book=self.book_b).id,
        }

        self.assertEqual(self.result_ids(self.get(self.ministry, REQUESTS_URL)), requests)
        self.assertEqual(self.result_ids(self.get(self.ministry, BORROWS_URL)), borrows)

    def test_ministry_and_superuser_operate_system_wide(self):
        for index, actor in enumerate((self.ministry, self.superuser)):
            with self.subTest(actor=actor.username):
                reader = self.create_user(
                    f"sys_reader_{index}", CustomUser.Role.READER, governorate=self.gov_b
                )
                approved = self.pending(reader=reader, book=self.book_b)
                self.assert_success(
                    self.post(actor, self.detail(REQUESTS_URL, approved, "approve/")),
                    "BORROW_REQUEST_APPROVED",
                )

                other_book = self.create_book(f"B Extra {index}", self.library_b, 1)
                rejected = self.pending(reader=reader, book=other_book)
                self.assert_success(
                    self.post(actor, self.detail(REQUESTS_URL, rejected, "reject/"), {"reason": "x"}),
                    "BORROW_REQUEST_REJECTED",
                )

                direct = self.assert_success(
                    self.post(actor, BORROWS_URL, {"reader_id": reader.id, "book_id": other_book.id}),
                    "BORROW_CREATED",
                    status.HTTP_201_CREATED,
                )
                self.assert_success(
                    self.post(actor, f"{BORROWS_URL}{direct['id']}/return/"),
                    "BORROW_RETURNED",
                )


class BusinessIntegrityTests(BorrowApiTestMixin, APITestCase):
    def test_ministry_cannot_direct_borrow_across_governorates(self):
        response = self.post(self.ministry, BORROWS_URL, {"reader_id": self.reader.id, "book_id": self.book_b.id})

        self.assert_validation(response, "book_id")
        self.assertEqual(self.quantities(self.book_b), (2, 2, True, 0))

    def test_approve_without_copies_fails_and_keeps_request_pending(self):
        request = self.pending(book=self.empty_book)

        self.assert_validation(
            self.post(self.librarian_a1, self.detail(REQUESTS_URL, request, "approve/")), "book"
        )
        request.refresh_from_db()
        self.assertEqual(request.status, BorrowRequest.Status.PENDING)
        self.assertIsNone(request.decided_by)
        self.assertFalse(Borrow.objects.exists())

    def test_approve_creates_active_borrow_and_updates_quantities(self):
        request = self.pending()

        data = self.assert_success(
            self.post(self.librarian_a1, self.detail(REQUESTS_URL, request, "approve/")),
            "BORROW_REQUEST_APPROVED",
        )

        borrow = Borrow.objects.get(pk=data["borrow"]["id"])
        self.assertEqual(borrow.status, Borrow.Status.ACTIVE)
        self.assertEqual(borrow.request, request)
        self.assertEqual(data["borrow"]["request"], request.id)
        self.assertEqual(self.quantities(self.book), (3, 2, True, 1))

    def test_direct_borrow_has_no_request(self):
        data = self.assert_success(
            self.post(self.librarian_a1, BORROWS_URL, {"reader_id": self.reader.id, "book_id": self.book.id}),
            "BORROW_CREATED",
            status.HTTP_201_CREATED,
        )

        self.assertIsNone(data["request"])
        self.assertEqual(data["source"], "DIRECT")
        self.assertFalse(BorrowRequest.objects.exists())

    def test_direct_borrow_with_pending_request_is_rejected(self):
        request = self.pending()

        self.assert_validation(
            self.post(self.librarian_a1, BORROWS_URL, {"reader_id": self.reader.id, "book_id": self.book.id}),
            "book_id",
        )
        request.refresh_from_db()
        self.assertEqual(request.status, BorrowRequest.Status.PENDING)
        self.assertEqual(self.quantities(self.book), (3, 3, True, 0))

    def test_double_return_is_rejected_and_copy_returns_once(self):
        borrow = self.active_borrow()
        url = self.detail(BORROWS_URL, borrow, "return/")
        self.assert_success(self.post(self.librarian_a1, url), "BORROW_RETURNED")

        self.assert_validation(self.post(self.librarian_a1, url), "status")
        self.assertEqual(self.quantities(self.book), (3, 3, True, 1))

    def test_return_keeps_count_borrowed(self):
        borrow = self.active_borrow()
        self.assertEqual(self.quantities(self.book), (3, 2, True, 1))

        self.post(self.librarian_a1, self.detail(BORROWS_URL, borrow, "return/"))

        self.assertEqual(self.quantities(self.book)[3], 1)

    def test_reject_trims_reason_and_rejects_unknown_fields(self):
        request = self.pending()
        url = self.detail(REQUESTS_URL, request, "reject/")

        self.assert_validation(self.post(self.librarian_a1, url, {"reason": "x", "status": "APPROVED"}), "status")
        data = self.assert_success(
            self.post(self.librarian_a1, url, {"reason": "  لا توجد نسخ  "}), "BORROW_REQUEST_REJECTED"
        )
        self.assertEqual(data["rejection_reason"], "لا توجد نسخ")

    def test_approve_and_return_reject_unexpected_body(self):
        request = self.pending()
        borrow = self.active_borrow(book=self.book_a2)

        self.assert_validation(
            self.post(self.ministry, self.detail(REQUESTS_URL, request, "approve/"), {"x": 1}), "x"
        )
        self.assert_validation(
            self.post(self.ministry, self.detail(BORROWS_URL, borrow, "return/"), {"x": 1}), "x"
        )
        request.refresh_from_db()
        borrow.refresh_from_db()
        self.assertEqual((request.status, borrow.status), ("PENDING", "ACTIVE"))

    def test_direct_borrow_rejects_old_field_names(self):
        cases = (
            {"reader": self.reader.id, "book": self.book.id},
            {"reader_id": self.reader.id, "book": self.book.id},
            {"reader": self.reader.id, "book_id": self.book.id},
            {"reader_id": self.reader.id, "book_id": self.book.id, "book": self.book.id},
        )
        for data in cases:
            with self.subTest(data=sorted(data)):
                response = self.post(self.librarian_a1, BORROWS_URL, data)
                self.assert_validation(response)
                for old in ("reader", "book"):
                    if old in data:
                        self.assertIn(old, response.data["errors"])
        self.assertFalse(Borrow.objects.exists())

    def test_direct_borrow_ids_are_required_and_valid(self):
        for data, field in (
            ({"book_id": self.book.id}, "reader_id"),
            ({"reader_id": self.reader.id}, "book_id"),
            ({"reader_id": "abc", "book_id": self.book.id}, "reader_id"),
            ({"reader_id": self.reader.id, "book_id": 0}, "book_id"),
        ):
            with self.subTest(data=data):
                self.assert_validation(self.post(self.librarian_a1, BORROWS_URL, data), field)

    def test_direct_borrow_rejects_server_managed_fields(self):
        for field in ("request", "status", "borrowed_at", "returned_at", "created_by", "returned_by"):
            with self.subTest(field=field):
                response = self.post(
                    self.ministry,
                    BORROWS_URL,
                    {"reader_id": self.reader.id, "book_id": self.book.id, field: 1},
                )
                self.assert_validation(response, field)
        self.assertFalse(Borrow.objects.exists())


class RequestFilterTests(BorrowApiTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.r1 = BorrowRequest.objects.create(reader=self.reader, book=self.book)
        self.r2 = BorrowRequest.objects.create(
            reader=self.other_reader, book=self.book_a2, status=BorrowRequest.Status.REJECTED
        )
        self.r3 = BorrowRequest.objects.create(reader=self.reader_b, book=self.book_b)
        self.r4 = BorrowRequest.objects.create(
            reader=self.reader, book=self.book_a2, status=BorrowRequest.Status.APPROVED
        )

    def ids(self, user=None, **params):
        response = self.get(user or self.ministry, REQUESTS_URL, params)
        self.assert_success(response, "BORROW_REQUESTS_RETRIEVED")
        return self.result_ids(response)

    def test_status_filter(self):
        self.assertEqual(self.ids(status="PENDING"), {self.r1.id, self.r3.id})
        self.assertEqual(self.ids(status="rejected"), {self.r2.id})

    def test_reader_filter(self):
        self.assertEqual(self.ids(reader=self.reader.id), {self.r1.id, self.r4.id})

    def test_book_filter(self):
        self.assertEqual(self.ids(book=self.book_a2.id), {self.r2.id, self.r4.id})

    def test_library_filter(self):
        self.assertEqual(self.ids(library=self.library_a1.id), {self.r1.id})

    def test_governorate_filter(self):
        self.assertEqual(self.ids(governorate=self.gov_a.id), {self.r1.id, self.r2.id, self.r4.id})

    def test_filters_combine(self):
        self.assertEqual(
            self.ids(governorate=self.gov_a.id, reader=self.reader.id, status="APPROVED"),
            {self.r4.id},
        )
        self.assertEqual(self.ids(library=self.library_b.id, reader=self.reader.id), set())

    def test_invalid_status_is_rejected(self):
        self.assert_validation(self.get(self.ministry, REQUESTS_URL, {"status": "ACTIVE"}), "status")

    def test_malformed_ids_are_rejected(self):
        for param in ("reader", "book", "library", "governorate"):
            for value in ("abc", "0", "-1", "9" * 30):
                with self.subTest(param=param, value=value):
                    self.assert_validation(self.get(self.ministry, REQUESTS_URL, {param: value}), param)

    def test_scope_is_applied_before_filters(self):
        self.assertEqual(self.ids(self.librarian_a1, library=self.library_a2.id), set())
        self.assertEqual(self.ids(self.gov_admin_a, governorate=self.gov_b.id), set())
        self.assertEqual(self.ids(self.librarian_a1, status="PENDING"), {self.r1.id})


class BorrowFilterTests(BorrowApiTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.b1 = Borrow.objects.create(reader=self.reader, book=self.book)
        self.b2 = Borrow.objects.create(
            reader=self.other_reader, book=self.book_a2, status=Borrow.Status.RETURNED
        )
        self.b3 = Borrow.objects.create(reader=self.reader_b, book=self.book_b)
        self.b4 = Borrow.objects.create(
            reader=self.reader, book=self.book_a2, status=Borrow.Status.RETURNED
        )

    def ids(self, user=None, **params):
        response = self.get(user or self.ministry, BORROWS_URL, params)
        self.assert_success(response, "BORROWS_RETRIEVED")
        return self.result_ids(response)

    def test_status_filter(self):
        self.assertEqual(self.ids(status="ACTIVE"), {self.b1.id, self.b3.id})
        self.assertEqual(self.ids(status="returned"), {self.b2.id, self.b4.id})

    def test_reader_filter(self):
        self.assertEqual(self.ids(reader=self.reader.id), {self.b1.id, self.b4.id})

    def test_book_filter(self):
        self.assertEqual(self.ids(book=self.book_a2.id), {self.b2.id, self.b4.id})

    def test_library_filter(self):
        self.assertEqual(self.ids(library=self.library_a1.id), {self.b1.id})

    def test_governorate_filter(self):
        self.assertEqual(self.ids(governorate=self.gov_b.id), {self.b3.id})

    def test_filters_combine(self):
        self.assertEqual(
            self.ids(governorate=self.gov_a.id, reader=self.reader.id, status="RETURNED"),
            {self.b4.id},
        )

    def test_invalid_status_is_rejected(self):
        self.assert_validation(self.get(self.ministry, BORROWS_URL, {"status": "PENDING"}), "status")

    def test_malformed_ids_are_rejected(self):
        for param in ("reader", "book", "library", "governorate"):
            for value in ("abc", "0", "-1", "9" * 30):
                with self.subTest(param=param, value=value):
                    self.assert_validation(self.get(self.ministry, BORROWS_URL, {param: value}), param)

    def test_scope_is_applied_before_filters(self):
        self.assertEqual(self.ids(self.librarian_a1, book=self.book_a2.id), set())
        self.assertEqual(self.ids(self.gov_admin_b, governorate=self.gov_a.id), set())
        self.assertEqual(self.ids(self.reader, reader=self.other_reader.id), set())


class PaginationAndResponseTests(BorrowApiTestMixin, APITestCase):
    def test_requests_are_paginated_newest_first(self):
        created = [
            BorrowRequest.objects.create(
                reader=self.reader, book=self.book, status=BorrowRequest.Status.REJECTED
            ).id
            for _ in range(23)
        ]

        first = self.assert_success(self.get(self.librarian_a1, REQUESTS_URL), "BORROW_REQUESTS_RETRIEVED")
        second = self.get(self.librarian_a1, REQUESTS_URL, {"page": 2}).data["data"]
        small = self.get(self.librarian_a1, REQUESTS_URL, {"page_size": 5}).data["data"]

        self.assertEqual(set(first), {"count", "next", "previous", "results"})
        self.assertEqual(first["count"], 23)
        self.assertEqual(len(first["results"]), 20)
        self.assertEqual([item["id"] for item in first["results"]], sorted(created, reverse=True)[:20])
        self.assertEqual(len(second["results"]), 3)
        self.assertEqual(len(small["results"]), 5)

    def test_borrows_are_paginated(self):
        for _ in range(21):
            Borrow.objects.create(reader=self.reader, book=self.book, status=Borrow.Status.RETURNED)

        first = self.assert_success(self.get(self.reader, BORROWS_URL), "BORROWS_RETRIEVED")
        second = self.get(self.reader, BORROWS_URL, {"page": 2}).data["data"]

        self.assertEqual(first["count"], 21)
        self.assertEqual(len(first["results"]), 20)
        self.assertIsNotNone(first["next"])
        self.assertEqual(len(second["results"]), 1)

    def test_envelope_codes_and_requester_role(self):
        request = self.pending()
        cases = (
            (self.get(self.reader, REQUESTS_URL), "BORROW_REQUESTS_RETRIEVED", "READER"),
            (self.get(self.librarian_a1, self.detail(REQUESTS_URL, request)), "BORROW_REQUEST_RETRIEVED", "LIBRARIAN"),
            (self.get(self.gov_admin_a, BORROWS_URL), "BORROWS_RETRIEVED", "GOVERNORATE_ADMIN"),
            (self.get(self.ministry, REQUESTS_URL), "BORROW_REQUESTS_RETRIEVED", "MINISTRY_ADMIN"),
            (self.get(self.superuser, BORROWS_URL), "BORROWS_RETRIEVED", "SUPERUSER"),
        )
        for response, code, role in cases:
            with self.subTest(code=code, role=role):
                self.assert_success(response, code)
                self.assertEqual(
                    set(response.data), {"success", "code", "message", "data", "meta"}
                )
                self.assertEqual(response.data["meta"]["requester_role"]["code"], role)

    def test_read_fields(self):
        request = self.pending()
        services.reject_borrow_request(actor=self.librarian_a1, borrow_request=request, reason="r")
        borrow = self.active_borrow(actor=self.librarian_a1)

        request_data = self.get(self.ministry, self.detail(REQUESTS_URL, request)).data["data"]
        borrow_data = self.get(self.ministry, self.detail(BORROWS_URL, borrow)).data["data"]

        self.assertEqual(
            set(request_data),
            {
                "id", "reader", "reader_username", "reader_first_name", "reader_last_name",
                "book", "book_title", "library", "library_name", "governorate",
                "governorate_name", "status", "created_at", "decided_at", "decided_by",
                "decided_by_username", "rejection_reason",
            },
        )
        self.assertEqual(request_data["decided_by_username"], "librarian_a1")
        self.assertEqual(request_data["library_name"], "Library A1")
        self.assertEqual(request_data["governorate_name"], "Governorate A")
        self.assertEqual(
            set(borrow_data),
            {
                "id", "reader", "reader_username", "reader_first_name", "reader_last_name",
                "book", "book_title", "library", "library_name", "governorate",
                "governorate_name", "request", "source", "status", "borrowed_at",
                "returned_at", "created_by", "created_by_username", "returned_by",
                "returned_by_username",
            },
        )
        self.assertIsNone(borrow_data["returned_by_username"])
        self.assertNotIn("password", json.dumps(request_data) + json.dumps(borrow_data))

    def test_errors_use_unified_format(self):
        request = self.pending()
        responses = (
            self.post(self.reader, self.detail(REQUESTS_URL, request, "approve/")),
            self.get(self.librarian_a2, self.detail(REQUESTS_URL, request)),
            self.get(self.ministry, REQUESTS_URL, {"status": "nope"}),
        )
        for response in responses:
            with self.subTest(status=response.status_code):
                self.assertEqual(
                    set(response.data), {"success", "code", "message", "data", "errors", "meta"}
                )
                self.assertIs(response.data["success"], False)


class MethodTests(BorrowApiTestMixin, APITestCase):
    def assert_methods_not_allowed(self, url):
        for method in ("put", "patch", "delete"):
            with self.subTest(url=url, method=method):
                response = self.client.generic(method.upper(), url, "{}", content_type="application/json")
                self.assert_error(response, status.HTTP_405_METHOD_NOT_ALLOWED, "METHOD_NOT_ALLOWED")

    def test_borrow_request_put_patch_delete_are_not_allowed(self):
        request = self.pending()
        for user in (self.ministry, self.librarian_a1, self.reader):
            self.client.force_authenticate(user=user)
            self.assert_methods_not_allowed(self.detail(REQUESTS_URL, request))
            self.assert_methods_not_allowed(REQUESTS_URL)
            response = self.client.post(REQUESTS_URL, {"book": self.book.id}, format="json")
            self.assert_error(response, status.HTTP_405_METHOD_NOT_ALLOWED, "METHOD_NOT_ALLOWED")
        request.refresh_from_db()
        self.assertEqual(request.status, BorrowRequest.Status.PENDING)
        self.assertTrue(BorrowRequest.objects.filter(pk=request.pk).exists())

    def test_borrow_put_patch_delete_are_not_allowed(self):
        borrow = self.active_borrow()
        for user in (self.ministry, self.librarian_a1, self.reader):
            self.client.force_authenticate(user=user)
            self.assert_methods_not_allowed(self.detail(BORROWS_URL, borrow))
            self.assert_methods_not_allowed(BORROWS_URL)
        borrow.refresh_from_db()
        self.assertEqual(borrow.status, Borrow.Status.ACTIVE)


class SwaggerTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from django.test import Client

        response = Client().get("/api/schema/", {"format": "json"})
        cls.schema = json.loads(response.content)
        cls.paths = cls.schema["paths"]

    def methods(self, path):
        return {
            method for method in self.paths.get(path, {})
            if method in {"get", "post", "put", "patch", "delete"}
        }

    def test_borrow_request_operations_are_documented(self):
        self.assertEqual(self.methods("/dashboard/books/{id}/borrow-requests/"), {"post"})
        self.assertEqual(self.methods("/dashboard/borrow-requests/"), {"get"})
        self.assertEqual(self.methods("/dashboard/borrow-requests/{id}/"), {"get"})
        self.assertEqual(self.methods("/dashboard/borrow-requests/{id}/approve/"), {"post"})
        self.assertEqual(self.methods("/dashboard/borrow-requests/{id}/reject/"), {"post"})

    def test_borrow_operations_are_documented(self):
        self.assertEqual(self.methods("/dashboard/borrows/"), {"get", "post"})
        self.assertEqual(self.methods("/dashboard/borrows/{id}/"), {"get"})
        self.assertEqual(self.methods("/dashboard/borrows/{id}/return/"), {"post"})

    def test_direct_borrow_body_uses_id_fields(self):
        operation = self.paths["/dashboard/borrows/"]["post"]
        ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        properties = self.schema["components"]["schemas"][ref.split("/")[-1]]["properties"]
        self.assertEqual(set(properties), {"reader_id", "book_id"})

    def test_block_borrowing_uses_hyphenated_paths_only(self):
        self.assertEqual(self.methods("/dashboard/users/{id}/block-borrowing/"), {"post"})
        self.assertEqual(self.methods("/dashboard/users/{id}/unblock-borrowing/"), {"post"})
        for path in self.paths:
            with self.subTest(path=path):
                self.assertNotIn("block_borrowing", path)
                self.assertNotIn("[_-]", path)

    def test_tags_are_set(self):
        self.assertEqual(self.paths["/dashboard/borrow-requests/"]["get"]["tags"], ["Borrow Requests"])
        self.assertEqual(self.paths["/dashboard/borrows/"]["post"]["tags"], ["Borrows"])

    def test_legacy_borrowing_endpoints_stay_hidden(self):
        for path in self.paths:
            with self.subTest(path=path):
                self.assertFalse(path.startswith("/dashboard/borrow/"))
                self.assertNotIn("profileborrwoed", path)
                self.assertNotIn("Recoveredbooks", path)
                self.assertFalse(path.startswith("/api/books/"))
