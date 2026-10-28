"""SY OS settings.

Everything that differs between a laptop, the factory server and Vercel comes from environment variables
(see .env.example). With none set you get local development: DEBUG on, local Postgres database `sy_os`.
"""

import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes")


# ---------- security ----------

# Off unless explicitly turned on. manage.py turns it on for local development; wsgi (servers, Vercel) never does.
DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or ("dev-only-insecure-key" if DEBUG else "")
if not SECRET_KEY:
    raise RuntimeError("Set DJANGO_SECRET_KEY (see .env.example)")
# Demo deployments show the sample logins on the login page and allow seed_demo; real ones never do.
DEMO_MODE = env_bool("SYOS_DEMO", DEBUG)

ALLOWED_HOSTS = ["localhost", "127.0.0.1", ".vercel.app", *filter(None, os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(","))]
CSRF_TRUSTED_ORIGINS = ["https://*.vercel.app", *filter(None, os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(","))]

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True


# ---------- apps ----------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # serves /static/ from the app itself (Vercel, factory server)
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "syos.urls"
WSGI_APPLICATION = "syos.wsgi.application"

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
                "core.permissions.nav_context",
            ],
        },
    },
]


# ---------- database ----------


def database_from_url(url):
    """postgres://user:pass@host:port/name?sslmode=require → Django DATABASES entry (Neon and Vercel give a URL)."""
    u = urlparse(url)
    options = {k: v[0] for k, v in parse_qs(u.query).items() if k in ("sslmode",)}
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": u.path.lstrip("/"),
        "USER": u.username or "",
        "PASSWORD": u.password or "",
        "HOST": u.hostname or "",
        "PORT": u.port or "",
        "OPTIONS": options,
        "CONN_MAX_AGE": 0,  # serverless: no long-lived connections; use the pooled URL in production
        "DISABLE_SERVER_SIDE_CURSORS": True,  # needed behind a transaction pooler (Neon pooled URL)
    }


_db_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
DATABASES = {
    "default": database_from_url(_db_url)
    if _db_url
    else {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("SYOS_DB", "sy_os"),
        "USER": os.environ.get("SYOS_DB_USER", ""),
        "PASSWORD": os.environ.get("SYOS_DB_PASSWORD", ""),
        "HOST": os.environ.get("SYOS_DB_HOST", ""),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ---------- language and time ----------

LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("hi", "हिन्दी"), ("ta", "தமிழ்")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True


# ---------- static files ----------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Production serves app static straight from the source folders, so no collectstatic step is needed on Vercel.
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = DEBUG


# ---------- misc ----------

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"
