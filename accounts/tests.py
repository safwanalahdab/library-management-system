from contextlib import contextmanager
from importlib import import_module

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, migrations, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from rest_framework import status
from rest_framework.test import APITestCase

from books.models import Author, Book, BorrowedBook, Category
from .models import CustomUser, Governorate, Library


PASSWORD = "StrongPass123!"


def create_reader(username="reader", governorate=None):
    if governorate is None:
        governorate = Governorate.objects.create(name=f"Governorate {username}")
    return CustomUser.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password=PASSWORD,
        role=CustomUser.Role.READER,
        governorate=governorate,
    )


class RoleScopeModelTests(TestCase):
    def setUp(self):
        self.governorate = Governorate.objects.create(name="Governorate")
        self.library = Library.objects.create(name="Library", governorate=self.governorate)

    def build_user(self, username, role, governorate=None, library=None):
        return CustomUser(
            username=username,
            email=f"{username}@example.com",
            role=role,
            governorate=governorate,
            library=library,
        )

    def assert_rejected_by_database(self, user):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                user.save()

    def test_reader_requires_governorate(self):
        reader = self.build_user("reader", CustomUser.Role.READER)

        with self.assertRaises(ValidationError) as ctx:
            reader.full_clean(exclude=["password"])
        self.assertIn("governorate", ctx.exception.message_dict)
        self.assert_rejected_by_database(reader)

    def test_reader_rejects_library(self):
        reader = self.build_user(
            "reader",
            CustomUser.Role.READER,
            governorate=self.governorate,
            library=self.library,
        )

        with self.assertRaises(ValidationError) as ctx:
            reader.full_clean(exclude=["password"])
        self.assertIn("library", ctx.exception.message_dict)
        self.assert_rejected_by_database(reader)

    def test_reader_with_governorate_only_is_valid(self):
        reader = self.build_user("reader", CustomUser.Role.READER, governorate=self.governorate)
        reader.set_password(PASSWORD)

        reader.full_clean()
        reader.save()

        self.assertEqual(reader.effective_governorate, self.governorate)

    def test_other_role_scopes_are_unchanged(self):
        valid_users = [
            self.build_user("ministry", CustomUser.Role.MINISTRY_ADMIN),
            self.build_user(
                "gov_admin", CustomUser.Role.GOVERNORATE_ADMIN, governorate=self.governorate
            ),
            self.build_user("librarian", CustomUser.Role.LIBRARIAN, library=self.library),
        ]
        for user in valid_users:
            with self.subTest(role=user.role):
                user.set_password(PASSWORD)
                user.full_clean()
                user.save()

        librarian = CustomUser.objects.get(username="librarian")
        self.assertEqual(librarian.effective_governorate, self.governorate)

        invalid_users = [
            self.build_user("bad_ministry", CustomUser.Role.MINISTRY_ADMIN, governorate=self.governorate),
            self.build_user("bad_gov_admin", CustomUser.Role.GOVERNORATE_ADMIN),
            self.build_user(
                "bad_gov_admin_lib",
                CustomUser.Role.GOVERNORATE_ADMIN,
                governorate=self.governorate,
                library=self.library,
            ),
            self.build_user("bad_librarian", CustomUser.Role.LIBRARIAN),
            self.build_user(
                "bad_librarian_gov",
                CustomUser.Role.LIBRARIAN,
                governorate=self.governorate,
                library=self.library,
            ),
        ]
        for user in invalid_users:
            with self.subTest(username=user.username):
                with self.assertRaises(ValidationError):
                    user.full_clean(exclude=["password"])
                self.assert_rejected_by_database(user)


class RegistrationTests(APITestCase):
    url = "/accounts/register"

    def setUp(self):
        self.governorate = Governorate.objects.create(name="Active Governorate")
        self.inactive_governorate = Governorate.objects.create(
            name="Inactive Governorate", is_active=False
        )

    def payload(self, **overrides):
        data = {
            "username": "NewReader",
            "email": "NewReader@Example.com",
            "first_name": "New",
            "last_name": "Reader",
            "password": PASSWORD,
            "password2": PASSWORD,
            "governorate": self.governorate.id,
        }
        data.update(overrides)
        return data

    def register(self, **overrides):
        return self.client.post(self.url, self.payload(**overrides), format="json")

    def test_registration_creates_reader_in_selected_governorate(self):
        response = self.register()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["code"], "ACCOUNT_REGISTERED")
        data = response.data["data"]
        self.assertEqual(data["username"], "newreader")
        self.assertEqual(data["email"], "newreader@example.com")
        self.assertEqual(data["role"]["code"], "READER")
        self.assertEqual(data["governorate"], self.governorate.id)
        self.assertIsNone(data["library"])
        self.assertNotIn("password", data)

        user = CustomUser.objects.get(username="newreader")
        self.assertEqual(user.role, CustomUser.Role.READER)
        self.assertEqual(user.governorate, self.governorate)
        self.assertIsNone(user.library_id)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password(PASSWORD))

    def test_registered_reader_can_log_in(self):
        self.register()

        response = self.client.post(
            "/accounts/login",
            {"identifier": "newreader", "password": PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_registration_rejects_missing_unknown_or_inactive_governorate(self):
        cases = {
            "missing": {"governorate": None},
            "unknown": {"governorate": 999999},
            "inactive": {"governorate": self.inactive_governorate.id},
        }
        for label, overrides in cases.items():
            with self.subTest(case=label):
                response = self.register(**overrides)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.data["code"], "VALIDATION_ERROR")
                self.assertIn("governorate", response.data["errors"])
        self.assertFalse(CustomUser.objects.filter(username="newreader").exists())

    def test_registration_rejects_role_scope_and_admin_fields(self):
        library = Library.objects.create(name="Library", governorate=self.governorate)
        forbidden = {
            "role": CustomUser.Role.MINISTRY_ADMIN,
            "library": library.id,
            "is_staff": True,
            "is_superuser": True,
            "is_active": False,
            "groups": [1],
            "user_permissions": [1],
            "borrowing_blocked": False,
        }
        for field, value in forbidden.items():
            with self.subTest(field=field):
                response = self.register(**{field: value})
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(field, response.data["errors"])
        self.assertFalse(CustomUser.objects.filter(username="newreader").exists())

    def test_registration_rejects_reader_role_choice_too(self):
        response = self.register(role=CustomUser.Role.READER)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("role", response.data["errors"])

    def test_registration_rejects_duplicate_username_and_email_case_insensitively(self):
        create_reader("newreader", governorate=self.governorate)
        CustomUser.objects.filter(username="newreader").update(email="taken@example.com")

        response = self.register(username="NEWREADER", email="fresh@example.com")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("username", response.data["errors"])

        response = self.register(username="another", email="TAKEN@example.com")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data["errors"])

    def test_registration_validates_passwords(self):
        response = self.register(password2="Different123!")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password2", response.data["errors"])

        response = self.register(password="123", password2="123")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data["errors"])

    def test_registration_requires_identity_fields(self):
        for field in ("username", "email", "first_name", "last_name", "password"):
            with self.subTest(field=field):
                data = self.payload()
                data.pop(field)
                response = self.client.post(self.url, data, format="json")
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(field, response.data["errors"])


class GovernorateListTests(APITestCase):
    def test_lists_only_active_governorates_with_id_and_name(self):
        active = Governorate.objects.create(name="Active")
        Governorate.objects.create(name="Inactive", is_active=False)

        response = self.client.get("/accounts/governorates")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["code"], "GOVERNORATES_RETRIEVED")
        self.assertEqual(response.data["data"], [{"id": active.id, "name": "Active"}])


class AuthenticationJwtTests(APITestCase):
    def setUp(self):
        self.user = create_reader()

    def login(self, identifier=None):
        return self.client.post(
            "/accounts/login",
            {"identifier": identifier or self.user.username, "password": PASSWORD},
            format="json",
        )

    def test_login_returns_access_token_and_refresh_cookie(self):
        response = self.login()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["code"], "LOGIN_SUCCESS")
        self.assertTrue(response.data["data"]["access"])
        user_data = response.data["data"]["user"]
        self.assertEqual(user_data["id"], self.user.id)
        self.assertEqual(user_data["role"]["code"], "READER")
        self.assertEqual(user_data["governorate"], self.user.governorate_id)
        self.assertIsNone(user_data["library"])
        self.assertIn(settings.JWT_REFRESH_COOKIE_NAME, response.cookies)
        self.assertNotIn("refresh", response.data["data"])

    def test_login_accepts_email_identifier(self):
        response = self.login(identifier=self.user.email)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_login_rejects_wrong_password(self):
        response = self.client.post(
            "/accounts/login",
            {"identifier": self.user.username, "password": "wrong-password"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "INVALID_CREDENTIALS")

    def test_access_token_authenticates_me_endpoint(self):
        access = self.login().data["data"]["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = self.client.get("/accounts/me")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["id"], self.user.id)
        self.assertEqual(response.data["data"]["governorate"], self.user.governorate_id)
        self.assertIsNone(response.data["data"]["library"])

    def test_me_requires_authentication(self):
        response = self.client.get("/accounts/me")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_uses_cookie_and_returns_new_access_token(self):
        self.login()

        response = self.client.post("/accounts/refresh")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["data"]["access"])


class ProfileTests(APITestCase):
    def setUp(self):
        self.user = create_reader()
        self.client.force_authenticate(user=self.user)

    def test_profile_contains_only_remaining_fields(self):
        author = Author.objects.create(name="Author")
        category = Category.objects.create(name="Category")
        library = Library.objects.create(name="Library", governorate=self.user.governorate)
        book = Book.objects.create(
            title="Book",
            description="desc",
            author=author,
            category=category,
            total_copies=1,
            library=library,
        )
        BorrowedBook.objects.create(book=book, borrower=self.user)

        response = self.client.get("/accounts/profile")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(data["borrowed_books_count"], 1)
        self.assertEqual(data["overdue_books_count"], 0)
        self.assertEqual(data["governorate"], self.user.governorate_id)
        self.assertIsNone(data["library"])
        for removed_field in (
            "favorites_count",
            "tier",
            "activities",
            "available_books",
        ):
            self.assertNotIn(removed_field, data)

    def test_profile_updates_allowed_fields(self):
        response = self.client.patch(
            "/accounts/profile",
            {"first_name": "Updated", "profile": {"phone": "0999"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Updated")
        self.assertEqual(self.user.phone, "0999")

    def test_profile_rejects_role_scope_and_admin_fields(self):
        other_governorate = Governorate.objects.create(name="Other")
        library = Library.objects.create(name="Library", governorate=self.user.governorate)
        forbidden = {
            "role": CustomUser.Role.MINISTRY_ADMIN,
            "governorate": other_governorate.id,
            "library": library.id,
            "is_staff": True,
            "is_superuser": True,
            "is_active": False,
            "groups": [1],
            "user_permissions": [1],
            "password": "NewStrongPass123!",
        }
        for field, value in forbidden.items():
            with self.subTest(field=field):
                response = self.client.patch(
                    "/accounts/profile",
                    {"first_name": "Changed", field: value},
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(field, response.data["errors"])

        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "")
        self.assertEqual(self.user.role, CustomUser.Role.READER)
        self.assertIsNone(self.user.library_id)
        self.assertNotEqual(self.user.governorate_id, other_governorate.id)
        self.assertFalse(self.user.is_staff)
        self.assertTrue(self.user.is_active)
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_profile_accepts_echoed_current_scope(self):
        response = self.client.patch(
            "/accounts/profile",
            {"first_name": "Echo", "governorate": self.user.governorate_id, "library": None},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_borrowing_blocked_is_read_only(self):
        response = self.client.patch(
            "/accounts/profile",
            {"borrowing_blocked": True, "profile": {"borrowing_blocked": True}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertFalse(self.user.borrowing_blocked)

    def test_favorites_route_is_removed(self):
        response = self.client.get("/accounts/FavoriteBooksProfileView/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_borrowed_books_profile_routes_still_work(self):
        for path in ("/accounts/profileborrwoed/", "/accounts/Recoveredbooks/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, status.HTTP_200_OK)


reader_scope_migration = import_module("accounts.migrations.0003_reader_governorate_scope")
BEFORE_READER_SCOPE = [("accounts", "0002_remove_customuser_accounts_user_role_scope_valid_and_more")]
AFTER_READER_SCOPE = [("accounts", "0003_reader_governorate_scope")]


class ReaderScopeMigrationTests(TransactionTestCase):
    """Runs accounts.0003 against data shaped like the previous schema."""

    def setUp(self):
        executor = MigrationExecutor(connection)
        executor.migrate(BEFORE_READER_SCOPE)
        self.old_apps = executor.loader.project_state(BEFORE_READER_SCOPE).apps
        self.OldUser = self.old_apps.get_model("accounts", "CustomUser")
        self.OldGovernorate = self.old_apps.get_model("accounts", "Governorate")
        self.OldLibrary = self.old_apps.get_model("accounts", "Library")

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def migrate_forward(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(AFTER_READER_SCOPE)

    @contextmanager
    def at_state_before_data_migration(self):
        """Apply only the first operation of 0003 (drop the old constraint).

        Yields the intermediate app registry, where rows the old constraint
        blocks can be created before the data step runs. The table must be
        rebuilt from the post-operation model state: on SQLite,
        remove_constraint() remakes the table from the model it receives, so
        passing the pre-migration model would recreate the old constraint.
        """
        executor = MigrationExecutor(connection)
        before_state = executor.loader.project_state(BEFORE_READER_SCOPE)
        migration = executor.loader.get_migration(*AFTER_READER_SCOPE[0])
        drop_old_constraint = migration.operations[0]
        self.assertIsInstance(drop_old_constraint, migrations.RemoveConstraint)
        self.assertEqual(drop_old_constraint.name, "accounts_user_role_scope_valid")

        intermediate_state = before_state.clone()
        drop_old_constraint.state_forwards("accounts", intermediate_state)
        with connection.schema_editor() as editor:
            drop_old_constraint.database_forwards(
                "accounts", editor, before_state, intermediate_state
            )

        intermediate_apps = intermediate_state.apps
        try:
            yield intermediate_apps
        finally:
            # Remove the test rows (they may violate the old constraint), then
            # restore the old constraint so tearDown can migrate forward normally.
            intermediate_apps.get_model("accounts", "CustomUser").objects.all().delete()
            intermediate_apps.get_model("accounts", "Library").objects.all().delete()
            intermediate_apps.get_model("accounts", "Governorate").objects.all().delete()
            with connection.schema_editor() as editor:
                drop_old_constraint.database_backwards(
                    "accounts", editor, intermediate_state, before_state
                )

    def test_readers_move_to_library_governorate_and_keep_relations(self):
        gov_a = self.OldGovernorate.objects.create(name="A")
        gov_b = self.OldGovernorate.objects.create(name="B")
        library_a = self.OldLibrary.objects.create(name="Library A", governorate=gov_a)
        library_b = self.OldLibrary.objects.create(name="Library B", governorate=gov_b)
        reader_a = self.OldUser.objects.create(username="reader_a", role="READER", library=library_a)
        reader_b = self.OldUser.objects.create(username="reader_b", role="READER", library=library_b)
        librarian = self.OldUser.objects.create(
            username="librarian", role="LIBRARIAN", library=library_a
        )
        gov_admin = self.OldUser.objects.create(
            username="gov_admin", role="GOVERNORATE_ADMIN", governorate=gov_b
        )
        ministry = self.OldUser.objects.create(username="ministry", role="MINISTRY_ADMIN")
        superuser = self.OldUser.objects.create(username="root", is_superuser=True, is_staff=True)

        author = Author.objects.create(name="Author")
        book = Book.objects.create(
            title="Book",
            description="desc",
            author=author,
            total_copies=1,
            library_id=library_a.pk,
        )
        borrow = BorrowedBook.objects.create(book=book, borrower_id=reader_a.pk)

        self.migrate_forward()

        reader_a = CustomUser.objects.get(pk=reader_a.pk)
        reader_b = CustomUser.objects.get(pk=reader_b.pk)
        self.assertEqual((reader_a.governorate_id, reader_a.library_id), (gov_a.pk, None))
        self.assertEqual((reader_b.governorate_id, reader_b.library_id), (gov_b.pk, None))

        librarian = CustomUser.objects.get(pk=librarian.pk)
        self.assertEqual((librarian.governorate_id, librarian.library_id), (None, library_a.pk))
        gov_admin = CustomUser.objects.get(pk=gov_admin.pk)
        self.assertEqual((gov_admin.governorate_id, gov_admin.library_id), (gov_b.pk, None))
        self.assertTrue(CustomUser.objects.filter(pk=ministry.pk).exists())
        self.assertTrue(CustomUser.objects.filter(pk=superuser.pk, is_superuser=True).exists())
        self.assertEqual(CustomUser.objects.count(), 6)

        self.assertEqual(BorrowedBook.objects.get(pk=borrow.pk).borrower_id, reader_a.pk)

    def test_plan_keeps_already_migrated_and_consistent_readers(self):
        with self.at_state_before_data_migration() as intermediate_apps:
            User = intermediate_apps.get_model("accounts", "CustomUser")
            IntermediateGovernorate = intermediate_apps.get_model("accounts", "Governorate")
            IntermediateLibrary = intermediate_apps.get_model("accounts", "Library")

            gov = IntermediateGovernorate.objects.create(name="A")
            library = IntermediateLibrary.objects.create(name="Library A", governorate=gov)
            governorate_only = User.objects.create(
                username="gov_only", role="READER", governorate=gov
            )
            consistent = User.objects.create(
                username="consistent", role="READER", governorate=gov, library=library
            )
            library_only = User.objects.create(
                username="library_only", role="READER", library=library
            )

            updates = reader_scope_migration.plan_reader_scope_updates(User, connection.alias)

            self.assertEqual(updates, {consistent.pk: gov.pk, library_only.pk: gov.pk})
            self.assertNotIn(governorate_only.pk, updates)

            with connection.schema_editor() as editor:
                reader_scope_migration.move_readers_to_governorate(intermediate_apps, editor)

            for user in (governorate_only, consistent, library_only):
                with self.subTest(username=user.username):
                    user.refresh_from_db()
                    self.assertEqual((user.governorate_id, user.library_id), (gov.pk, None))
            self.assertEqual(User.objects.count(), 3)

    def test_conflicting_or_unresolved_readers_stop_without_changes(self):
        with self.at_state_before_data_migration() as intermediate_apps:
            User = intermediate_apps.get_model("accounts", "CustomUser")
            IntermediateGovernorate = intermediate_apps.get_model("accounts", "Governorate")
            IntermediateLibrary = intermediate_apps.get_model("accounts", "Library")

            gov_a = IntermediateGovernorate.objects.create(name="A")
            gov_b = IntermediateGovernorate.objects.create(name="B")
            library_a = IntermediateLibrary.objects.create(name="Library A", governorate=gov_a)
            valid = User.objects.create(username="valid", role="READER", library=library_a)
            conflicting = User.objects.create(
                username="conflicting", role="READER", governorate=gov_b, library=library_a
            )
            unresolved = User.objects.create(username="unresolved", role="READER")

            with self.assertRaises(reader_scope_migration.ReaderScopeMigrationError) as ctx:
                with connection.schema_editor() as editor:
                    reader_scope_migration.move_readers_to_governorate(intermediate_apps, editor)

            message = str(ctx.exception)
            self.assertIn(f"{conflicting.pk} (governorate={gov_b.pk}", message)
            self.assertIn(str(unresolved.pk), message)

            for user, expected in (
                (valid, (None, library_a.pk)),
                (conflicting, (gov_b.pk, library_a.pk)),
                (unresolved, (None, None)),
            ):
                user.refresh_from_db()
                self.assertEqual((user.governorate_id, user.library_id), expected)
