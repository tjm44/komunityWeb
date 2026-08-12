import os
import dj_database_url
from .settings import *
from .settings import BASE_DIR


# -------------------------------------------------------------------
# Core secrets — must be set as env vars
# -------------------------------------------------------------------
SECRET_KEY = os.environ.get('SECRET') or os.environ.get('SECRET_KEY')

DEBUG = False

# -------------------------------------------------------------------
# Hosts — Detect from environment (Railway, Render, etc.)
# -------------------------------------------------------------------
PRODUCTION_HOST = os.environ.get('RAILWAY_STATIC_URL') or os.environ.get('RENDER_EXTERNAL_HOSTNAME')

ALLOWED_HOSTS = [
    '127.0.0.1',
    'localhost',
]
if PRODUCTION_HOST:
    ALLOWED_HOSTS.append(PRODUCTION_HOST)

env_hosts = os.environ.get('ALLOWED_HOSTS', '')
if env_hosts:
    ALLOWED_HOSTS.extend([h.strip() for h in env_hosts.split(',') if h.strip()])

CSRF_TRUSTED_ORIGINS = []
if PRODUCTION_HOST:
    CSRF_TRUSTED_ORIGINS.append(f'https://{PRODUCTION_HOST}')

env_csrf = os.environ.get('CSRF_TRUSTED_ORIGINS', '')
if env_csrf:
    CSRF_TRUSTED_ORIGINS.extend([origin.strip() for origin in env_csrf.split(',') if origin.strip()])

# -------------------------------------------------------------------
# Middleware — add WhiteNoise right after SecurityMiddleware
# -------------------------------------------------------------------
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',   # serves static files
    'django.contrib.sessions.middleware.SessionMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# -------------------------------------------------------------------
# Static files — WhiteNoise compressed storage
# -------------------------------------------------------------------
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'
WHITENOISE_MANIFEST_STRICT = False

STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# -------------------------------------------------------------------
# Database — Configure via environment DATABASE_URL
# -------------------------------------------------------------------
DATABASES = {
    'default': dj_database_url.config(
        env='DATABASE_URL',
        conn_max_age=600,
    )
}

# -------------------------------------------------------------------
# Email — use real SMTP in production
# -------------------------------------------------------------------
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', 'manyadzatocky@gmail.com')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_PASSWORD', '')

# -------------------------------------------------------------------
# CORS — restrict in production to known origins
# -------------------------------------------------------------------
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = []
if PRODUCTION_HOST:
    CORS_ALLOWED_ORIGINS.append(f'https://{PRODUCTION_HOST}')

env_cors = os.environ.get('CORS_ALLOWED_ORIGINS', '')
if env_cors:
    CORS_ALLOWED_ORIGINS.extend([origin.strip() for origin in env_cors.split(',') if origin.strip()])

# -------------------------------------------------------------------
# Security hardening
# -------------------------------------------------------------------
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# HTTPS & HSTS Hardening
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
