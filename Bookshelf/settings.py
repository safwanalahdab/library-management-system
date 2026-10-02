from pathlib import Path
from datetime import timedelta
import os
from corsheaders.defaults import default_headers
import dj_database_url
from dotenv import load_dotenv

# -----------------------------
# Paths
# -----------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

# -----------------------------
# Security / Debug
# -----------------------------
def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]
NGROK_HOST = os.getenv("NGROK_HOST", "").strip()


# -----------------------------
# Applications
# -----------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    "rest_framework",
    "drf_spectacular",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",

    "books",
    "accounts",
    "Home",
    "dashboard",
]

AUTH_USER_MODEL = "accounts.CustomUser"

# -----------------------------
# REST Framework
# -----------------------------
REST_FRAMEWORK = {
    "EXCEPTION_HANDLER": "Bookshelf.api_responses.custom_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Library Management System API",
    "DESCRIPTION": "توثيق API لنظام إدارة المكتبة",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "PREPROCESSING_HOOKS": ["Bookshelf.openapi.keep_documented_endpoints"],
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": False,
}

JWT_REFRESH_COOKIE_NAME = "refresh_token"
JWT_REFRESH_COOKIE_PATH = "/accounts/"
JWT_REFRESH_COOKIE_SECURE = env_bool("JWT_REFRESH_COOKIE_SECURE", not DEBUG)
JWT_REFRESH_COOKIE_SAMESITE = os.getenv("JWT_REFRESH_COOKIE_SAMESITE", "Lax")

# -----------------------------
# Middleware
# -----------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",

    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",

    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# -----------------------------
# URLs / WSGI
# -----------------------------
ROOT_URLCONF = "Bookshelf.urls"

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "")


TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "Bookshelf.wsgi.application"

# -----------------------------
# Database
# -----------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required and must point to a PostgreSQL database.")

DATABASE_CONFIG = dj_database_url.parse(DATABASE_URL, conn_max_age=600)
if DATABASE_CONFIG.get("ENGINE") != "django.db.backends.postgresql":
    raise RuntimeError("DATABASE_URL must point to a PostgreSQL database.")

DATABASES = {"default": DATABASE_CONFIG}

# -----------------------------
# Password validation
# -----------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# -----------------------------
# i18n / TZ
# -----------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Damascus"
USE_I18N = True
USE_TZ = True

# -----------------------------
# Static / Media
# -----------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# -----------------------------
# CORS / CSRF
# -----------------------------
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https://.*\.ngrok-free\.dev$",
    r"^https://.*\.ngrok\.io$",
]

CORS_ALLOW_HEADERS = list(default_headers) + [
    "ngrok-skip-browser-warning",
]

CSRF_TRUSTED_ORIGINS = [f"https://{NGROK_HOST}"] if NGROK_HOST else []
