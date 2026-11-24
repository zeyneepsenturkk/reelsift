from .base import *  # noqa: F403  # ayar modülü deseni: base'in tamamı devralınır

DEBUG = True
SECRET_KEY = SECRET_KEY or "dev-only-insecure-key"  # noqa: F405  # yalnız yerel geliştirme için
# Vite vekili Host başlığını hedef adıyla ("backend") ilettiği için o ad gerekli.
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "backend"]
# Vekil Host'u arka uç adıyla değiştirdiği için tarayıcının Origin'i (arayüz adresi) Host'a uymaz
# ve yazan istekler CSRF denetiminde düşer; geliştirme arayüz adresleri güvenilir sayılır.
CSRF_TRUSTED_ORIGINS = [
    f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, 5174)
]
