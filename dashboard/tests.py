from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase

from books.models import Author, Book, Category


class UserBorrowingBlockAdminTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="StrongPass123!",
        )
        self.user = User.objects.create_user(
            username="blocked_user",
            email="blocked@example.com",
            password="StrongPass123!",
        )
        self.author = Author.objects.create(name="Author One")
        self.category = Category.objects.create(name="Category One")
        self.book = Book.objects.create(
            title="Borrowable Book",
            description="desc",
            author=self.author,
            category=self.category,
            total_copies=2,
        )

    def test_admin_can_block_and_unblock_user_borrowing(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f"/dashboard/users/{self.user.id}/block-borrowing/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["available_books"], -1)
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.borrowing_blocked)

        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/books/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["results"][0]["available_books"], -1)

        response = self.client.post(f"/api/books/{self.book.id}/borrow/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["max_allowed"], -1)

        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f"/dashboard/users/{self.user.id}/unblock-borrowing/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["available_books"], 1)
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.borrowing_blocked)

        self.client.force_authenticate(user=self.user)
        response = self.client.post(f"/api/books/{self.book.id}/borrow/")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
