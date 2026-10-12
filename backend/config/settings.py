"""Django settings. Everything deploy-specific comes from environment variables."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
# The app keeps no sessions, cookies or user data, but Django still requires a key.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-change-me")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,.onrender.com,.railway.app,.fly.dev")
if render_host := os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(render_host)
if DEBUG:
    ALLOWED_HOSTS.append("*")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "corsheaders",
    "routing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.gzip.GZipMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# The built React app (frontend/dist) is served by Django/WhiteNoise in production.
FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST", REPO_DIR / "frontend" / "dist"))

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [FRONTEND_DIST],
        "APP_DIRS": False,
        "OPTIONS": {"context_processors": []},
    }
]

DATABASES = {}  # stateless API: no models, no database

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "truck-routing",
        "OPTIONS": {"MAX_ENTRIES": 20000},
    }
}

STATIC_URL = "/static/"
STATIC_ROOT = None  # nothing to collect; see WHITENOISE_ROOT
# WhiteNoise serves the Vite build (frontend/dist: /assets/*, favicon) from the site root;
# index.html itself is returned by routing.views.spa for every non-API path.
WHITENOISE_ROOT = FRONTEND_DIST if FRONTEND_DIST.exists() else None
WHITENOISE_MAX_AGE = 3600
WHITENOISE_AUTOREFRESH = DEBUG  # pick up new Vite builds without a restart in dev
WHITENOISE_IMMUTABLE_FILE_TEST = r"/assets/.+-[A-Za-z0-9_-]{8,}\.\w+$"

USE_TZ = True
TIME_ZONE = "UTC"
LANGUAGE_CODE = "en-us"
USE_I18N = False

# CORS: only needed when the frontend is hosted on a different origin (e.g. Vercel/Netlify).
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_ALL_ORIGINS = env_bool("CORS_ALLOW_ALL", DEBUG)
CORS_URLS_REGEX = r"^/api/.*$"

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_CONTENT_TYPE_NOSNIFF = True

# ---- Third-party providers ----
PROVIDER_MODE = os.environ.get("PROVIDER_MODE", "live")  # "live" or "fake" (offline demo/tests)
OSRM_URL = os.environ.get("OSRM_URL", "https://router.project-osrm.org")
# Free tier needs no key. With a commercial key, also set OPEN_METEO_URL=https://customer-api.open-meteo.com
OPEN_METEO_URL = os.environ.get("OPEN_METEO_URL", "https://api.open-meteo.com")
OPEN_METEO_API_KEY = os.environ.get("OPEN_METEO_API_KEY", "")
PHOTON_URL = os.environ.get("PHOTON_URL", "https://photon.komoot.io")
HTTP_USER_AGENT = os.environ.get("HTTP_USER_AGENT", "weather-aware-truck-routing/1.0 (assessment demo)")

# ---- Truck model ----
TRUCK_MAX_MPH = float(os.environ.get("TRUCK_MAX_MPH", "65"))
MAX_LOAD_LB = 80_000  # US federal gross weight limit without permits

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
