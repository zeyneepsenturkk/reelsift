# ReelSift: yapay zekâ asistanı için rehber

Bu dosya, depoyu açan yapay zekâ kodlama asistanı (Claude Code, Cursor, Codex vb.) içindir. Kullanıcı "projeyi kur", "kuruluma başlayalım" ya da "çalıştır" derse aşağıdaki akışı izle. Projenin ne olduğu ve nasıl çalıştığı [`README.md`](README.md) dosyasında, ölçümler [`KALITE.md`](KALITE.md) dosyasındadır.

## Proje, tek paragraf

ReelSift film editörleri için bir kürasyon masasıdır: editör doğal dille istek yazar, sistem 94.683 filmlik arşivde arar (RAG: vektör + BM25 + yeniden sıralama, LangGraph akışı) ve her film için gerekçe ile kaynak alıntısı içeren bir seçki taslağı çıkarır; onayı yalnız editör verir. Backend Django (`app/backend`), arayüz React (`app/frontend`), hepsi Docker Compose ile çalışır.

## Kurulumdan önce

- Windows 10 / 11, Docker Desktop açık ("Engine running"), Git.
- NVIDIA ekran kartı (arama modelleri CUDA ile çalışır) ve yaklaşık 45 GB boş disk.
- Dil modeli için üç seçenekten biri: Claude (Anthropic anahtarı), Gemini (ücretsiz Google AI Studio anahtarı) ya da yerel model (Ollama kurulu olmalı). Seçim kurulum sayfasında yapılır.

## Kurulum akışı

1. Depo kökünde kurulum sunucusunu başlat (uzun yaşayan süreç; arka planda çalıştır):

   ```
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File kurulum\sunucu.ps1
   ```

   Tarayıcıda `http://localhost:5174/` kendiliğinden açılır; açılmazsa adresi kullanıcıya ver. Kullanıcı ortadaki **Başla** düğmesine basar; adımları sayfa yürütür.
2. İlerlemeyi `kurulum/.durum/durum.json` dosyasından izle (30-60 saniyede bir oku). Yapı: `genel` (`hazir` / `suruyor` / `kullanici` / `hata` / `tamam`) ve `adimlar[]` (her birinde `ad`, `durum`, `mesaj`, `ne_oldu`, `ne_yapmali`, `gunluk`). Adım değiştikçe tek cümleyle haber ver.
3. Adım durumları:
   - `suruyor`: bekle. "Uygulamanın hazırlanması" 10-25 dakika, "Arşivin yüklenmesi" yaklaşık 10 dakika sürer. Takılmış gibi görünürse `kurulum/.durum/kurulum.log` dosyasının son satırlarına bak.
   - `kullanici`: sayfa kullanıcıdan bir şey bekliyor; `ne_yapmali` metnini aktar. "Dil modeli" adımında API anahtarı SAYFADAKİ kutuya yapıştırılır; sohbete yazılmasını isteme, yazılırsa tekrar etme.
   - `hata`: `ne_oldu` ve `ne_yapmali` metinlerini aktar, sayfadaki "Tekrar dene"ye basılmasını söyle. İkinci denemede de olmazsa adımın `gunluk` dosyasını ve `kurulum/.durum/kurulum.log` dosyasının son 60 satırını oku, nedeni bul.
   - `tamam`: sayfadaki "Projeye git" düğmesi uygulamayı açar (`http://localhost:5173`). Kullanıcı adı `editor`; şifre kurulum sırasında rastgele üretilir ve kurulum sonu ekranında gösterilir.
4. Sunucuyu durdurmak için `kurulum/.durum/sunucu-dur` adında boş bir dosya oluştur.
5. Kurulum motorunu (`kurulum\kur.ps1`) elle çalıştırma; sayfa onu kendisi başlatır. `-Bastan` anahtarını kullanıcı açıkça istemedikçe kullanma (yapılan adımları yok sayar).

Kurulum yarıda kesilirse aynı komut kaldığı yerden sürer. Kurulum sayfası kullanılamıyorsa README'deki "B. Elle kurulum" adımlarını izle.

## Günlük kullanım

- Başlat: `docker compose up -d`. Arama modelleri 2-4 dakikada ısınır; `docker compose logs --tail 50 backend` çıktısında "Arama hazır" satırını bekle, o satır çıkmadan arama deneme.
- Uygulama `http://localhost:5173`, sağlık denetimi `http://localhost:8000/api/health`, MCP sunucusu `http://localhost:8000/mcp`.
- Durdur: `docker compose stop` (veri silinmez).
- Dil modelini değiştirmek: uygulamada sol alttaki kullanıcı menüsü, **Ayarlar**, "Dil modeli".

## Sorun giderme

| Belirti | Büyük ihtimalle | Ne yap |
|---|---|---|
| `localhost:5174` açılmıyor | Kurulum sunucusu kapalı | Sunucu komutunu yeniden başlat |
| `localhost:5173` açılmıyor | Docker kapalı ya da uygulama durmuş | Docker Desktop'ı aç, `docker compose up -d`, "Arama hazır"ı bekle |
| Arama ya da taslak çok yavaş | Modeller ısınıyor ya da ekran kartı görünmüyor | 4 dakika bekle; sürerse `http://localhost:8000/api/health` çıktısına bak |
| Dil modeli cevap vermiyor | Anahtar geçersiz, kota dolmuş ya da Ollama kapalı | Uygulamada Ayarlar, "Dil modeli", "Bağlantıyı dene"; mesaja göre anahtarı yenile ya da modeli değiştir |
| Yerel modelde kişi adı içeren istek taslak üretmiyor | Bilinen sınır (README, "Yerel model denemesi") | Claude ya da Gemini'ye geç |
| Giriş olmuyor | Şifre unutulmuş | Şifre `kurulum/.durum/hesap.json` dosyasındadır; kullanıcıya dosyayı açmasını söyle, içeriğini sohbete yazdırma |
| Disk doldu | Docker imajları ve indirilenler | `docker system df` ile bak; hiçbir şeyi sormadan silme |

## Kurallar

- API anahtarlarını ve `.env` dosyasının içeriğini ekrana yazdırma, sohbete kopyalama, commit'leme. `.env` git'e eklenmez.
- Veri silen komutları kullanıcıya sormadan çalıştırma: `docker compose down -v`, `docker volume rm`, `docker system prune`; `veri/`, `modeller/` ya da `kurulum/.durum/` klasörlerini silmek.
- Bilmediğin bir şeyi uydurma; ekranda görmediğin bir düğmeyi ya da olmayan bir ayarı tarif etme.
- Testler: README'deki "Testler" bölümündeki komutlar. Kod değiştirdiysen ilgili testleri çalıştırmadan "çalışıyor" deme.
