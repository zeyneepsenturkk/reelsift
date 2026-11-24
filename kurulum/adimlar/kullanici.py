"""Kurulumda sorulan kullaniciyi olusturur ya da sifresini kurulumun urettigi degere getirir (yonetici DEGIL).

Kullanici adi ve sifre ortam degiskenlerinden (KURULUM_KULLANICI, KURULUM_SIFRE) gelir; repoda sifre tutulmaz.
`manage.py shell -c "exec(open('/kurulum/kullanici.py').read())"` ile calisir.
"""

import os

from django.contrib.auth import get_user_model

ad = os.environ.get("KURULUM_KULLANICI", "").strip()
sifre = os.environ.get("KURULUM_SIFRE", "")
if not ad or len(sifre) < 12:
    raise SystemExit("KULLANICI_HATA kullanici adi ya da sifre gelmedi")

User = get_user_model()
user, created = User.objects.get_or_create(username=ad)
user.set_password(sifre)
user.is_active = True
user.is_staff = False
user.is_superuser = False
user.save()
print("KULLANICI_TAMAM " + ("olusturuldu" if created else "guncellendi"))
