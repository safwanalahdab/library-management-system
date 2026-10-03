from importlib import import_module

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import ProtectedError
from django.test import TestCase, TransactionTestCase

from accounts.models import CustomUser, Governorate, Library
from .models import Book


book_library_migration = import_module("books.migrations.0003_book_library")
BEFORE_BOOK_LIBRARY = [("books", "0002_remove_bookreservation_book_and_more")]
AFTER_BOOK_LIBRARY = [("books", "0003_book_library")]


class BookLibraryModelTests(TestCase):
    def setUp(self):
        self.governorate = Governorate.objects.create(name="Governorate")
        self.library_a = Library.objects.create(name="Library A", governorate=self.governorate)
        self.library_b = Library.objects.create(name="Library B", governorate=self.governorate)

    def create_book(self, **extra):
        return Book.objects.create(title="Same Title", description="desc", **extra)

    def test_book_is_created_linked_to_library(self):
        book = self.create_book(library=self.library_a)

        book.refresh_from_db()
        self.assertEqual(book.library_id, self.library_a.id)
        self.assertEqual(book.library.governorate_id, self.governorate.id)
        self.assertIn(book, self.library_a.books.all())

    def test_database_rejects_book_without_library(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_book()

        self.assertFalse(Book.objects.exists())

    def test_same_title_can_exist_in_two_libraries(self):
        book_a = self.create_book(library=self.library_a)
        book_b = self.create_book(library=self.library_b)

        self.assertNotEqual(book_a.pk, book_b.pk)
        self.assertEqual(Book.objects.filter(title="Same Title").count(), 2)

    def test_library_with_books_cannot_be_deleted(self):
        book = self.create_book(library=self.library_a)

        with self.assertRaises(ProtectedError):
            self.library_a.delete()

        self.assertTrue(Library.objects.filter(pk=self.library_a.pk).exists())
        self.assertTrue(Book.objects.filter(pk=book.pk, library=self.library_a).exists())


class BookLibraryMigrationTests(TransactionTestCase):
    """Runs books.0003 from the previous books schema; accounts tables are untouched."""

    def setUp(self):
        executor = MigrationExecutor(connection)
        executor.migrate(BEFORE_BOOK_LIBRARY)
        self.old_apps = executor.loader.project_state(BEFORE_BOOK_LIBRARY).apps
        self.OldBook = self.old_apps.get_model("books", "Book")

    def tearDown(self):
        # Rows without a library would block the forward migration below.
        self.OldBook.objects.all().delete()
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def migrate_forward(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(AFTER_BOOK_LIBRARY)

    def applied_book_migrations(self):
        executor = MigrationExecutor(connection)
        return {name for app, name in executor.recorder.applied_migrations() if app == "books"}

    def library_column(self):
        with connection.cursor() as cursor:
            description = connection.introspection.get_table_description(
                cursor, Book._meta.db_table
            )
        return next((column for column in description if column.name == "library_id"), None)

    def organization_snapshot(self):
        return (
            list(Governorate.objects.order_by("pk").values_list("pk", "name", "is_active", "updated_at")),
            list(Library.objects.order_by("pk").values_list("pk", "name", "governorate_id", "is_active", "updated_at")),
            list(
                CustomUser.objects.order_by("pk").values_list(
                    "pk", "username", "role", "governorate_id", "library_id", "is_active"
                )
            ),
        )

    def test_migration_succeeds_without_books_and_keeps_organization_data(self):
        governorate = Governorate.objects.create(name="Governorate")
        library = Library.objects.create(name="Library", governorate=governorate)
        CustomUser.objects.create_user(
            username="librarian", password="StrongPass123!", role="LIBRARIAN", library=library
        )
        CustomUser.objects.create_user(
            username="reader", password="StrongPass123!", role="READER", governorate=governorate
        )
        before = self.organization_snapshot()
        self.assertIsNone(self.library_column())

        self.migrate_forward()

        self.assertIn("0003_book_library", self.applied_book_migrations())
        column = self.library_column()
        self.assertIsNotNone(column)
        self.assertFalse(column.null_ok)
        self.assertEqual(self.organization_snapshot(), before)
        self.assertFalse(Book.objects.exists())

    def test_migration_stops_on_books_without_library_and_keeps_them(self):
        first = self.OldBook.objects.create(title="Orphan One", description="desc", total_copies=3)
        second = self.OldBook.objects.create(title="Orphan Two", description="desc", total_copies=1)
        before = list(
            self.OldBook.objects.order_by("pk").values_list("pk", "title", "total_copies", "available_copies")
        )
        libraries_before = Library.objects.count()

        with self.assertRaises(book_library_migration.BooksWithoutLibraryError) as ctx:
            self.migrate_forward()

        message = str(ctx.exception)
        self.assertIn(str(first.pk), message)
        self.assertIn(str(second.pk), message)
        self.assertNotIn("0003_book_library", self.applied_book_migrations())
        self.assertIsNone(self.library_column())
        self.assertEqual(
            list(
                self.OldBook.objects.order_by("pk").values_list(
                    "pk", "title", "total_copies", "available_copies"
                )
            ),
            before,
        )
        self.assertEqual(Library.objects.count(), libraries_before)
