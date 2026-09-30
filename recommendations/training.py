from collections import defaultdict
from dataclasses import dataclass

import numpy as np
import pandas as pd

from books.models import Book, BorrowedBook, Favorite_Book

from .artifacts import save_artifacts
from .constants import (
    BORROW_INTERACTION_WEIGHT,
    FAVORITE_INTERACTION_WEIGHT,
    RANKFM_ALPHA,
    RANKFM_BETA,
    RANKFM_EPOCHS,
    RANKFM_FACTORS,
    RANKFM_LEARNING_EXPONENT,
    RANKFM_LEARNING_RATE,
    RANKFM_LEARNING_SCHEDULE,
    RANKFM_LOSS,
    RANKFM_MAX_SAMPLES,
    RANKFM_SIGMA,
)


@dataclass
class TrainingConfig:
    factors: int = RANKFM_FACTORS
    epochs: int = RANKFM_EPOCHS
    loss: str = RANKFM_LOSS
    max_samples: int = RANKFM_MAX_SAMPLES
    alpha: float = RANKFM_ALPHA
    beta: float = RANKFM_BETA
    sigma: float = RANKFM_SIGMA
    learning_rate: float = RANKFM_LEARNING_RATE
    learning_schedule: str = RANKFM_LEARNING_SCHEDULE
    learning_exponent: float = RANKFM_LEARNING_EXPONENT


def _weighted_interactions() -> dict[tuple[int, int], float]:
    interactions: dict[tuple[int, int], float] = defaultdict(float)

    borrow_rows = BorrowedBook.objects.select_related("book", "borrower").filter(
        book__is_archived=False
    )
    for row in borrow_rows:
        interactions[(row.borrower_id, row.book_id)] += BORROW_INTERACTION_WEIGHT

    favorite_rows = Favorite_Book.objects.select_related("book", "user").filter(
        book__is_archived=False
    )
    for row in favorite_rows:
        interactions[(row.user_id, row.book_id)] += FAVORITE_INTERACTION_WEIGHT

    return interactions


def train_recommender(config: TrainingConfig | None = None) -> dict:
    """
    Train rankfmc model using only:
    - BorrowedBook interactions
    - Favorite_Book interactions
    Summary/review/comment signals are intentionally excluded.
    """
    try:
        from rankfmc import RankFM
    except Exception as exc:
        return {"trained": False, "reason": f"rankfmc_unavailable: {exc}"}

    config = config or TrainingConfig()
    interactions = _weighted_interactions()
    if not interactions:
        return {"trained": False, "reason": "no_interactions"}

    eligible_book_ids = set(
        Book.objects.filter(is_archived=False).values_list("id", flat=True)
    )
    if not eligible_book_ids:
        return {"trained": False, "reason": "no_eligible_books"}

    filtered = {
        (user_id, book_id): weight
        for (user_id, book_id), weight in interactions.items()
        if book_id in eligible_book_ids
    }
    if not filtered:
        return {"trained": False, "reason": "no_interactions_after_filtering"}

    user_ids = sorted({user_id for user_id, _ in filtered.keys()})
    book_ids = sorted({book_id for _, book_id in filtered.keys()})

    interactions_df = pd.DataFrame(
        [
            {"user_id": user_id, "item_id": book_id}
            for (user_id, book_id) in filtered.keys()
        ]
    )
    interaction_weights = np.fromiter(filtered.values(), dtype=np.float32)

    model = RankFM(
        factors=config.factors,
        loss=config.loss,
    )
    try:
        model.fit(
            interactions=interactions_df,
            epochs=config.epochs,
            sample_weight=interaction_weights,
            alpha=config.alpha,
            beta=config.beta,
            sigma=config.sigma,
            learning_rate=config.learning_rate,
            learning_schedule=config.learning_schedule,
            learning_exponent=config.learning_exponent,
            max_samples=config.max_samples,
        )
    except TypeError:
        # Backward/variant API compatibility across rankfmc builds.
        model.fit(
            interactions=interactions_df,
            epochs=config.epochs,
            sample_weight=interaction_weights,
        )

    user_id_to_index = {user_id: idx for idx, user_id in enumerate(user_ids)}
    index_to_user_id = {idx: user_id for user_id, idx in user_id_to_index.items()}
    book_id_to_index = {book_id: idx for idx, book_id in enumerate(book_ids)}
    index_to_book_id = {idx: book_id for book_id, idx in book_id_to_index.items()}
    user_seen_books: dict[int, set[int]] = defaultdict(set)
    for user_id, book_id in filtered.keys():
        user_seen_books[user_id].add(book_id)

    metadata = {
        "algorithm": "rankfmc.RankFM",
        "factors": config.factors,
        "loss": config.loss,
        "epochs": config.epochs,
        "max_samples": config.max_samples,
        "alpha": config.alpha,
        "beta": config.beta,
        "sigma": config.sigma,
        "learning_rate": config.learning_rate,
        "learning_schedule": config.learning_schedule,
        "learning_exponent": config.learning_exponent,
        "borrow_weight": BORROW_INTERACTION_WEIGHT,
        "favorite_weight": FAVORITE_INTERACTION_WEIGHT,
        "user_count": len(user_ids),
        "book_count": len(book_ids),
        "interaction_count": len(filtered),
    }
    save_artifacts(
        model=model,
        training_users=set(user_ids),
        training_books=set(book_ids),
        user_seen_books=dict(user_seen_books),
        user_id_to_index=user_id_to_index,
        index_to_user_id=index_to_user_id,
        book_id_to_index=book_id_to_index,
        index_to_book_id=index_to_book_id,
        metadata=metadata,
    )
    return {"trained": True, **metadata}
