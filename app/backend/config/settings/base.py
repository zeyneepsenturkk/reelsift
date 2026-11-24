"""Ortak ayarlar. Varsayılanlar güvenlidir; gevşek ayarlar yalnız dev.py'dedir."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
DEBUG = False
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.core",
    "apps.accounts",
    "apps.films",
    "apps.search",
    "apps.chats",
    "apps.curation",
    "apps.agent",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "apps.core.middleware.ApiMethodNotAllowedMiddleware",
    "apps.core.middleware.ApiUnexpectedErrorMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

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

ASGI_APPLICATION = "config.asgi.application"

# pgvector gerektiği için her ortamda PostgreSQL.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DJANGO_DB_NAME", "reelsift"),
        "USER": os.environ.get("DJANGO_DB_USER", "reelsift"),
        "PASSWORD": os.environ.get("DJANGO_DB_PASSWORD", ""),
        "HOST": os.environ.get("DJANGO_DB_HOST", "localhost"),
        "PORT": os.environ.get("DJANGO_DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "tr"
TIME_ZONE = "Europe/Istanbul"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "{asctime} {levelname} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "root": {"handlers": ["console"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO")},
}

# Toplu vektör yüklemede HNSW indeksi önce düşürülür, veri bitince kurulur (yazım saatler yerine
# dakikalar sürer). Bu kadar ya da daha çok satır eklenecekse (ya da tablo boşsa) düşürülür.
FILMS_BULK_INDEX_THRESHOLD = int(os.environ.get("DJANGO_FILMS_BULK_INDEX_THRESHOLD", "20000"))
# İndeks kurulurken oturuma verilen bellek; compose'taki db `shm_size` değerinden küçük olmalı.
FILMS_INDEX_MAINTENANCE_WORK_MEM = os.environ.get("DJANGO_FILMS_INDEX_MAINTENANCE_WORK_MEM", "1GB")

# Oturum çerezi JS'den okunamaz; CSRF çerezi ise arayüz başlığa kopyalasın diye okunabilir olmalı.
# `prod.py` ikisine de `Secure` ekler.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"

# Deneme sınırı sayaçları süreç içi önbellekte (LocMem) tutulur: tek süreçli çalıştırmaya yeter;
# çok işçili üretimde ortak önbellek (CACHES) ve doğru NINJA_NUM_PROXIES gerekir.
# Sınır istemci IP'sini `REMOTE_ADDR`'dan alır; `X-Forwarded-For` sahtelenebildiği için güvenilmez.
# Önüne ters vekil konursa vekil sayısı yazılmalıdır.
NINJA_NUM_PROXIES = 0

# CSRF hatası /api altında tek tip JSON cevaba çevrilir.
CSRF_FAILURE_VIEW = "apps.core.views.csrf_failure"

# Dil modeli: anahtar yalnız ortamdan (ANTHROPIC_API_KEY) okunur, ayara girmez.
# `.env.example`'taki boş `ANTHROPIC_MODEL=` satırı ortamı boş metin yapar; boşsa varsayılan.
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL") or "claude-haiku-5-5"

# Herkese açık film sitesi (reelsift-vitrin). Adres burada; anahtar (VITRIN_API_KEY) yalnız
# ortamdan okunur, ayara girmez. İkisi de doluysa "Sitede yayınla" açılır.
VITRIN_URL = (os.environ.get("VITRIN_URL") or "").strip()

# Hangi dil modelinin kullanılacağı. Anahtar (GEMINI_API_KEY) yalnız ortamdan okunur, ayara girmez.
LLM_PROVIDERS = ("anthropic", "gemini", "ollama")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER") or "anthropic"
if LLM_PROVIDER not in LLM_PROVIDERS:
    raise ImproperlyConfigured(
        f"LLM_PROVIDER geçersiz: {LLM_PROVIDER!r}. Geçerli değerler: {', '.join(LLM_PROVIDERS)}."
    )
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.5-flash-lite"
# Ücretsiz kota dakikalık sınırlıdır: iki Gemini çağrısının başlangıcı en az 60 / GEMINI_RPM sn
# arayla olur.
try:
    GEMINI_RPM = int(os.environ.get("GEMINI_RPM") or "8")
except ValueError as exc:
    raise ImproperlyConfigured("GEMINI_RPM tam sayı olmalı (dakikada en çok çağrı).") from exc
if GEMINI_RPM < 1:
    raise ImproperlyConfigured("GEMINI_RPM en az 1 olmalı (dakikada en çok çağrı).")
# Yerel Ollama (LLM_PROVIDER=ollama): adres konteynerden host'taki Ollama'ya gider.
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL") or "http://host.docker.internal:11434"
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL") or "qwen3:4b-instruct-2507-q4_K_M"
try:
    OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX") or "12288")
except ValueError as exc:
    raise ImproperlyConfigured("OLLAMA_NUM_CTX tam sayı olmalı (bağlam penceresi, token).") from exc
if OLLAMA_NUM_CTX < 1:
    raise ImproperlyConfigured("OLLAMA_NUM_CTX en az 1 olmalı (bağlam penceresi, token).")
# Birincil model 503 denemelerini tüketirse ya da günlük kotası dolarsa sırayla denenen modeller
# (virgüllü liste; boş = yedek yok).
GEMINI_FALLBACK_MODELS = [
    name.strip()
    for name in (os.environ.get("GEMINI_FALLBACK_MODELS") or "").split(",")
    if name.strip()
]

AGENT = {
    # Adım başına düşünme derinliği (output_config.effort).
    "efforts": {"parse": "low", "judge": "low", "write": "medium", "chat": "low"},
    "search_depth": 100,  # arama servisinden istenen aday sayısı (yeniden sıralama derinliği)
    "judge_limit": 60,  # modelin okuyacağı en çok aday
    "judge_chunk": 20,  # tek değerlendirme çağrısındaki aday sayısı
    "write_chunk": 4,  # tek gerekçe çağrısındaki film sayısı
    "max_retries": 2,  # arama döngüsünün yeniden deneme sınırı
    "max_concurrent_calls": 6,  # aynı anda uçuştaki model çağrısı sınırı
    "message_max_length": 2000,  # kullanıcı mesajı üst sınırı (karakter)
    "request_timeout_s": 120,  # tek model çağrısının zaman aşımı
    "llm_max_retries": 2,  # SDK'nın bağlantı/429/5xx için otomatik yeniden deneme sayısı
    "skip_refused": False,  # model reddi turu bitirir (Gemini'de True: reddedilen atlanır)
}
if LLM_PROVIDER == "gemini":
    # Gemini iki filmin metni aynı istemde olunca PROHIBITED_CONTENT ile engelleyebiliyor (her
    # film tek başına geçiyor); gerekçe çağrısı film başına yapılır. Claude yolu değişmez.
    AGENT["write_chunk"] = 1
    # Tek filmin metni de engellenebiliyor: reddedilen film taslağa girmez, reddedilen aday
    # kümesi ikiye bölünür; tur sürer. Claude yolu değişmez.
    AGENT["skip_refused"] = True
if LLM_PROVIDER == "ollama":
    # Tek ekran kartı: çağrılar sırayla; yerel modelin yüklemesi ve uzun çıktısı için geniş süre.
    AGENT["max_concurrent_calls"] = 1
    AGENT["request_timeout_s"] = 300

# Arama hattı (apps.search). Değerler deneylerde ölçülen hattın ayarlarıdır;
# değişiklik yeniden ölçüm ister.
SEARCH = {
    "depth": 1000,  # her aday kaynağından alınan en çok film
    "rrf_k": 60,
    "min_plot_chars": 300,  # bundan kısa hikâye, model önerisi (g) değilse elenir
    "min_filtered_films": 30,  # filtre bundan az film bırakırsa kaldırılır
    # Bundan çok yönetmenli film (derleme) kişi evrenine yönetmen olarak girmez.
    "person_max_directors": 3,
    # "En iyi" sırası (Bayes ortalaması): m = ağırlık olarak sayılan oy sayısı, C = arşivde oyu
    # olan filmlerin oy ortalaması (2026-11-17'de arşivden hesaplandı: 85029 film, 6.21).
    "rating_prior_votes": 200,
    "rating_prior_mean": 6.21,
    "rerank_max_length": 1024,  # yeniden sıralama modelinin azami token uzunluğu
    "rerank_batch_size": 25,
    # Yeniden sıralama belgesi: A = özet + hikâye, B = profil + A, B_end = A + profil.
    "doc_mode": "B",
    "blend": 0.0,  # 0 = yalnız yeniden sıralama; 1 = yalnız RRF sırası
    "vector_mode": "exact",  # "exact" (kesin arama) ya da "hnsw" (indeksli, yaklaşık)
    "hnsw_ef_search": 1000,
    "hnsw_max_scan_tuples": 40000,
    "hnsw_chunk_limit": 4000,  # indeksli aramada film başına en iyi parça için okunan parça
    "embed_model": "BAAI/bge-m3",
    "embed_max_seq_length": 512,
    "rerank_model": "BAAI/bge-reranker-v2-m3",
    "index_dir": os.environ.get("SEARCH_INDEX_DIR", "/index"),
    "eval_data_dir": os.environ.get("SEARCH_EVAL_DATA_DIR", "/data"),
    # Sunucu açılışında modelleri ve indeksi arka planda yükler (varsayılan kapalı).
    "warmup": os.environ.get("SEARCH_WARMUP", "") == "1",
}
