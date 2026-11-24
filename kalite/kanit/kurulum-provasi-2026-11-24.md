# Kurulum provası: temiz klonla baştan sona (2026-11-24)

Amaç: bu depoyu ilk kez gören birinin `kurulum\sunucu.ps1` ile çalışan bir ReelSift'e ulaşıp ulaşamadığını görmek.

Ortam: Windows 11, RTX 4060 (8 GB), Docker Desktop (derleme önbelleği dolu), ev interneti. Depo `https://github.com/zeyneepsenturkk/reelsift` adresinden kimlik sorulmadan klonlandı (commit `ce520f6`). Dil modeli adımında yerel model (Ollama, `qwen3:4b-instruct-2507-q4_K_M`) seçildi; API anahtarı kullanılmadı.

Sonuç: 11 adımın 11'i hatasız, "Tekrar dene" hiç gerekmedi. Başlangıç 22:28:18, bitiş 23:03:55, toplam 35 dakika 37 saniye.

| Adım | Süre | Not |
|---|---|---|
| Bilgisayar kontrolü | 8 sn | ekran kartı tanındı |
| Dil modeli | 3 sn | yerel model hazır |
| Film arşivi | 1 dk 27 sn | Releases'ten girişsiz indi (1,7 GB), SHA-256 doğrulandı |
| Uygulamanın hazırlanması | 3 dk 42 sn | Docker önbelleği dolu; soğuk kurulum ölçülmedi |
| Arama modelleri | 6 dk 3 sn | 4,6 GB indirme |
| Arşivin yüklenmesi | 18 dk 8 sn | `pg_restore` 10,5 dk; 94.683 film, 220.998 parça |
| Arama dizini | 1 dk 14 sn | |
| Kullanıcı | 5 sn | `editor`; şifre rastgele üretildi |
| Başlatma | 4 dk 44 sn | arama modellerinin ısınması dahil |
| Son kontrol | 2 sn | gerçek giriş denemesi 200 |

(Tanıtım videosu adımı bu depoda kullanılmıyor, atlandı.)

Kurulumdan sonra yapılan denetimler:

| Denetim | Sonuç |
|---|---|
| `editor` ile giriş (`/api/auth/login`) | 200 |
| `http://localhost:8000/api/health` ve `http://localhost:5173` | 200 |
| Yerel modelle "Taşrada sıkışmışlık üzerine 3 Türk filmi" | İlk deneme 161 sn sonra "model cevabı yarıda kesildi" hatasıyla düştü; ikinci deneme 69,6 sn'de 3 filmlik taslak üretti |
| MCP ucu (`/mcp`, `initialize`) | 200 |

Denenmeyenler: kurulum sayfasının düğmelerine tarayıcıda elle değil HTTP ile basıldı; Claude ve Gemini seçenekleri bu provada denenmedi (ayrı denemelerde kullanıldı); soğuk Docker derlemesi ölçülmedi.
