from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Author, Book, BorrowedBook, Category


class RecommendationsApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="reco_user",
            email="reco@example.com",
            password="StrongPass123!",
        )
        self.author = Author.objects.create(name="Author One")
        self.category = Category.objects.create(name="Category One")

    def test_recommendations_requires_authentication(self):
        response = self.client.get("/api/recommendations/me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_recommendations_fallback_returns_non_archived_books(self):
        visible = Book.objects.create(
            title="Visible Book",
            description="desc",
            author=self.author,
            category=self.category,
            is_archived=False,
            is_avaiable=True,
            total_copies=2,
            available_copies=2,
        )
        Book.objects.create(
            title="Archived Book",
            description="desc",
            author=self.author,
            category=self.category,
            is_archived=True,
            is_avaiable=True,
            total_copies=2,
            available_copies=2,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/recommendations/me/?limit=5")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(response.data["source"], {"fallback", "rankfmc"})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], visible.id)


class BooksApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="book_user",
            email="book@example.com",
            password="StrongPass123!",
        )
        self.author = Author.objects.create(name="Author One")
        self.category = Category.objects.create(name="Category One")
        self.book = Book.objects.create(
            title="Visible Book",
            description="desc",
            author=self.author,
            category=self.category,
            is_archived=False,
            total_copies=2,
        )

    def test_books_return_zero_available_books_for_guest(self):
        response = self.client.get("/api/books/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["results"][0]["available_books"], 0)

    def test_books_return_remaining_available_books_for_authenticated_user(self):
        BorrowedBook.objects.create(book=self.book, borrower=self.user)

        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/books/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["results"][0]["available_books"], 0)
