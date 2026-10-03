from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import CustomUser, Governorate, Library
from .models import Author, Book, BorrowedBook, Category


PASSWORD = "StrongPass123!"


class BooksTestMixin:
    def setUp(self):
        self.governorate = Governorate.objects.create(name="Governorate")
        self.library = Library.objects.create(name="Library", governorate=self.governorate)
        self.reader = self.create_reader("reader")
        self.author = Author.objects.create(name="Author One")
        self.category = Category.objects.create(name="Category One")

    def create_reader(self, username):
        return CustomUser.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password=PASSWORD,
            role=CustomUser.Role.READER,
            governorate=self.governorate,
        )

    def create_book(self, title="Book", total_copies=1, **extra):
        extra.setdefault("library", self.library)
        return Book.objects.create(
            title=title,
            description="desc",
            author=self.author,
            category=self.category,
            total_copies=total_copies,
            **extra,
        )


class BooksApiTests(BooksTestMixin, APITestCase):
    def test_book_list_returns_only_non_archived_books(self):
        visible = self.create_book(title="Visible Book")
        self.create_book(title="Archived Book", is_archived=True)

        response = self.client.get("/api/books/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], visible.id)

    def test_book_detail_has_no_removed_feature_fields(self):
        book = self.create_book()
        self.client.force_authenticate(user=self.reader)

        response = self.client.get(f"/api/books/{book.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for removed_field in (
            "is_like",
            "average_rating",
            "rating_count",
            "available_books",
        ):
            self.assertNotIn(removed_field, response.data)
        self.assertEqual(response.data["available_copies"], 1)
        self.assertTrue(response.data["is_avaiable"])
        self.assertEqual(response.data["author"]["name"], self.author.name)
        self.assertEqual(response.data["category"]["name"], self.category.name)

    def test_categories_are_public(self):
        response = self.client.get("/api/category/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)


class BorrowBookTests(BooksTestMixin, APITestCase):
    def borrow(self, book):
        return self.client.post(f"/api/books/{book.id}/borrow/")

    def test_borrow_requires_authentication(self):
        book = self.create_book()

        response = self.borrow(book)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_borrowing_has_no_numeric_limit(self):
        books = [self.create_book(title=f"Book {index}") for index in range(4)]
        self.client.force_authenticate(user=self.reader)

        for book in books:
            with self.subTest(book=book.title):
                response = self.borrow(book)
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(
            BorrowedBook.objects.filter(borrower=self.reader, is_returned=False).count(),
            4,
        )

    def test_borrow_decrements_available_copies(self):
        book = self.create_book(total_copies=2)
        self.client.force_authenticate(user=self.reader)

        response = self.borrow(book)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        book.refresh_from_db()
        self.assertEqual(book.available_copies, 1)
        self.assertEqual(book.count_borrowed, 1)
        self.assertTrue(book.is_avaiable)

    def test_borrow_rejected_when_book_unavailable(self):
        book = self.create_book(total_copies=1)
        other_reader = self.create_reader("other_reader")
        self.client.force_authenticate(user=other_reader)
        self.assertEqual(self.borrow(book).status_code, status.HTTP_201_CREATED)

        self.client.force_authenticate(user=self.reader)
        response = self.borrow(book)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(
            BorrowedBook.objects.filter(borrower=self.reader, book=book).exists()
        )

    def test_borrow_rejected_when_borrowing_blocked(self):
        book = self.create_book(total_copies=2)
        self.reader.borrowing_blocked = True
        self.reader.save(update_fields=["borrowing_blocked"])
        self.client.force_authenticate(user=self.reader)

        response = self.borrow(book)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        book.refresh_from_db()
        self.assertEqual(book.available_copies, 2)
        self.assertFalse(BorrowedBook.objects.filter(borrower=self.reader).exists())

    def test_borrow_rejected_when_same_book_already_borrowed(self):
        book = self.create_book(total_copies=2)
        self.client.force_authenticate(user=self.reader)
        self.assertEqual(self.borrow(book).status_code, status.HTTP_201_CREATED)

        response = self.borrow(book)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_borrow_rejected_for_archived_book(self):
        book = self.create_book(is_archived=True)
        self.client.force_authenticate(user=self.reader)

        response = self.borrow(book)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class RemovedPublicRoutesTests(BooksTestMixin, APITestCase):
    def test_removed_feature_routes_return_not_found(self):
        book = self.create_book()
        self.client.force_authenticate(user=self.reader)
        routes = [
            ("get", "/api/recommendations/me/"),
            ("get", "/api/activity/"),
            ("get", "/api/quotes/"),
            ("post", f"/api/books/{book.id}/like/"),
            ("post", f"/api/books/{book.id}/unlike/"),
            ("post", f"/api/books/{book.id}/rate/"),
            ("post", f"/api/books/{book.id}/reserve/"),
            ("post", f"/api/books/{book.id}/summarize/"),
            ("get", f"/api/books/{book.id}/summaries/"),
        ]

        for method, path in routes:
            with self.subTest(path=path):
                response = getattr(self.client, method)(path)
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
