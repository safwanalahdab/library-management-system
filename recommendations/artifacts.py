import json
from dataclasses import dataclass
from datetime import datetime

import joblib

from .constants import (
    ARTIFACTS_DIR,
    MAPPINGS_PATH,
    METADATA_PATH,
    MODEL_PATH,
    TRAINING_STATE_PATH,
)


@dataclass
class RecommenderArtifacts:
    model: object
    training_users: set[int]
    training_books: set[int]
    user_seen_books: dict[int, set[int]]
    user_id_to_index: dict[int, int]
    index_to_user_id: dict[int, int]
    book_id_to_index: dict[int, int]
    index_to_book_id: dict[int, int]
    metadata: dict


def artifacts_exist() -> bool:
    return (
        MODEL_PATH.exists()
        and MAPPINGS_PATH.exists()
        and TRAINING_STATE_PATH.exists()
        and METADATA_PATH.exists()
    )


def save_artifacts(
    *,
    model,
    training_users: set[int],
    training_books: set[int],
    user_seen_books: dict[int, set[int]],
    user_id_to_index: dict[int, int],
    index_to_user_id: dict[int, int],
    book_id_to_index: dict[int, int],
    index_to_book_id: dict[int, int],
    metadata: dict,
) -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    joblib.dump(model, MODEL_PATH)
    joblib.dump(
        {
            "user_id_to_index": user_id_to_index,
            "index_to_user_id": index_to_user_id,
            "book_id_to_index": book_id_to_index,
            "index_to_book_id": index_to_book_id,
        },
        MAPPINGS_PATH,
    )
    joblib.dump(
        {
            "training_users": training_users,
            "training_books": training_books,
            "user_seen_books": user_seen_books,
        },
        TRAINING_STATE_PATH,
    )

    payload = {
        **metadata,
        "saved_at": datetime.utcnow().isoformat() + "Z",
    }
    METADATA_PATH.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def load_artifacts() -> RecommenderArtifacts:
    if not artifacts_exist():
        raise FileNotFoundError("Recommender artifacts are missing.")

    model = joblib.load(MODEL_PATH)
    mappings = joblib.load(MAPPINGS_PATH)
    training_state = joblib.load(TRAINING_STATE_PATH)
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))

    required_keys = {
        "user_id_to_index",
        "index_to_user_id",
        "book_id_to_index",
        "index_to_book_id",
    }
    if not required_keys.issubset(mappings.keys()):
        raise ValueError("Invalid recommender mappings artifact.")
    required_training_state_keys = {"training_users", "training_books", "user_seen_books"}
    if not required_training_state_keys.issubset(training_state.keys()):
        raise ValueError("Invalid recommender training_state artifact.")

    return RecommenderArtifacts(
        model=model,
        training_users=training_state["training_users"],
        training_books=training_state["training_books"],
        user_seen_books=training_state["user_seen_books"],
        user_id_to_index=mappings["user_id_to_index"],
        index_to_user_id=mappings["index_to_user_id"],
        book_id_to_index=mappings["book_id_to_index"],
        index_to_book_id=mappings["index_to_book_id"],
        metadata=metadata,
    )
