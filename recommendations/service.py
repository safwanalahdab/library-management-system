from dataclasses import dataclass

import numpy as np
from django.db.models import Count

from books.models import Book, BorrowedBook, Favorite_Book

from .artifacts import load_artifacts
from .constants import (
    DEFAULT_TOP_K,
    MAX_TOP_K,
    MIN_CANDIDATE_BATCH,
    RECOMMENDATION_BATCH_FACTOR,
)


@dataclass
class RecommendationPayload:
    source: str
    books: list[Book]


class BookRecommendationService:
    def __init__(self):
        self._artifacts = None

    def recommend_for_user(
        self,
        *,
        user_id: int,
        top_k: int = DEFAULT_TOP_K,
        available_only: bool = False,
    ) -> RecommendationPayload:
        safe_top_k = max(1, min(int(top_k), MAX_TOP_K))
        known_book_ids = self._known_book_ids(user_id=user_id)

        try:
            ranked_ids = self._rank_with_model(
                user_id=user_id,
                top_k=safe_top_k,
                available_only=available_only,
                known_book_ids=known_book_ids,
            )
        except Exception:
            ranked_ids = []

        if not ranked_ids:
            ranked_ids = self._fallback_book_ids(
                top_k=safe_top_k,
                available_only=available_only,
                known_book_ids=known_book_ids,
            )
            source = "fallback"
        else:
            source = "rankfmc"

        return RecommendationPayload(source=source, books=self._books_from_ids(ranked_ids))

    def _rank_with_model(
        self,
        *,
        user_id: int,
        top_k: int,
        available_only: bool,
        known_book_ids: set[int],
    ) -> list[int]:
        artifacts = self._load_artifacts_once()
        if user_id not in artifacts.training_users:
            return []

        eligible_qs = Book.objects.filter(is_archived=False)
        if available_only:
            eligible_qs = eligible_qs.filter(is_avaiable=True)
        eligible_book_ids = set(eligible_qs.values_list("id", flat=True))

        # Ask for a larger internal candidate set to survive post-filtering.
        candidate_n = max(top_k * RECOMMENDATION_BATCH_FACTOR, MIN_CANDIDATE_BATCH)
        recommend_kwargs = {
            "users": np.array([user_id], dtype=np.int64),
            "n_items": candidate_n,
            "filter_previous": True,
            "cold_start": "nan",
        }
        recommendations = artifacts.model.recommend(**recommend_kwargs)
        ranked_candidate_ids = self._extract_ranked_items_for_user(
            recommendations=recommendations,
            user_id=user_id,
        )

        ranked: list[int] = []
        for book_id in ranked_candidate_ids:
            if book_id in known_book_ids:
                continue
            if book_id not in eligible_book_ids:
                continue
            ranked.append(book_id)
            if len(ranked) >= top_k:
                break
        return ranked

    def _load_artifacts_once(self):
        if self._artifacts is None:
            self._artifacts = load_artifacts()
        return self._artifacts

    def _extract_ranked_items_for_user(self, *, recommendations, user_id: int) -> list[int]:
        # Expected rankfmc output is a DataFrame with user ids as index and
        # recommended item ids in columns; this parser is defensive for variants.
        if recommendations is None:
            return []
        if hasattr(recommendations, "loc"):
            if user_id not in recommendations.index:
                return []
            row_values = recommendations.loc[user_id].tolist()
        elif isinstance(recommendations, dict):
            row_values = recommendations.get(user_id, [])
        else:
            row_values = list(recommendations)

        parsed: list[int] = []
        for value in row_values:
            if value is None:
                continue
            try:
                if isinstance(value, float) and np.isnan(value):
                    continue
                parsed.append(int(value))
            except (TypeError, ValueError):
                continue
        return parsed

    def _known_book_ids(self, *, user_id: int) -> set[int]:
        borrowed_ids = set(
            BorrowedBook.objects.filter(borrower_id=user_id).values_list("book_id", flat=True)
        )
        favorite_ids = set(
            Favorite_Book.objects.filter(user_id=user_id).values_list("book_id", flat=True)
        )
        return borrowed_ids.union(favorite_ids)

    def _fallback_book_ids(
        self,
        *,
        top_k: int,
        available_only: bool,
        known_book_ids: set[int],
    ) -> list[int]:
        fallback = (
            Book.objects.filter(is_archived=False)
            .annotate(favorites_count=Count("book_fav", distinct=True))
            .order_by("-count_borrowed", "-favorites_count", "-created_at")
        )
        if available_only:
            fallback = fallback.filter(is_avaiable=True)
        if known_book_ids:
            fallback = fallback.exclude(id__in=known_book_ids)
        return list(fallback.values_list("id", flat=True)[:top_k])

    def _books_from_ids(self, book_ids: list[int]) -> list[Book]:
        if not book_ids:
            return []
        queryset = Book.objects.filter(id__in=book_ids).select_related("author", "category")
        by_id = {book.id: book for book in queryset}
        return [by_id[book_id] for book_id in book_ids if book_id in by_id]
