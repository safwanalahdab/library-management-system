from pathlib import Path

from django.conf import settings


# Interaction weights:
# Favorite is a stronger explicit preference than borrow history.
BORROW_INTERACTION_WEIGHT = 2.0
FAVORITE_INTERACTION_WEIGHT = 4.0

# rankfmc RankFM defaults tuned for implicit ranking.
RANKFM_FACTORS = 64
RANKFM_EPOCHS = 30
RANKFM_LOSS = "warp"
RANKFM_MAX_SAMPLES = 20
RANKFM_ALPHA = 0.01
RANKFM_BETA = 0.1
RANKFM_SIGMA = 0.1
RANKFM_LEARNING_RATE = 0.05
RANKFM_LEARNING_SCHEDULE = "invscaling"
RANKFM_LEARNING_EXPONENT = 0.25

DEFAULT_TOP_K = 10
MAX_TOP_K = 30
RECOMMENDATION_BATCH_FACTOR = 5
MIN_CANDIDATE_BATCH = 50

ARTIFACTS_DIR = Path(settings.BASE_DIR) / "recommendations" / "artifacts"
MODEL_PATH = ARTIFACTS_DIR / "rankfmc_model.joblib"
MAPPINGS_PATH = ARTIFACTS_DIR / "mappings.joblib"
TRAINING_STATE_PATH = ARTIFACTS_DIR / "training_state.joblib"
METADATA_PATH = ARTIFACTS_DIR / "metadata.json"
