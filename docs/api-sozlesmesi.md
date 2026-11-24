# API sözleşmesi (arayüz <-> backend), sürüm 1.5 (2026-11-24)

Sürüm 1.5 (dil modeli ayarı, 2026-11-24): üç yeni uç eklendi (aşağıda "Dil modeli ayarı"). Yalnız ekleme; mevcut uç ve alanlar değişmedi.
Sürüm 1.4: `CollectionFilm.quote_source` eklendi: alıntının alındığı kaynak (tür, etiket, adres). Yalnız ekleme; mevcut alanlar değişmedi.

Sürüm 1.3 (kişi araması ve Türk filmleri işi, 2026-11-17): `CollectionFilm`'e `directors` ve `actors` eklendi (film ayrıntısında gösterilir; ikisi de boş liste olabilir). `title_tr`: TMDB Türkçe adı; yoksa ve filmin özgün dili Türkçeyse özgün ad; yoksa `null`. `sources` içindeki Wikipedia bağlantısı yalnız filmin hikâye metni varsa listeye girer. Akış: `text.delta` parçaları tamamlanmış cümleler halinde gelir; `message.done.message.text` kesin metindir ve akan metinden farklı olabilir (cevap sunucuda bir kez yeniden üretilmiş olabilir), istemci metni `message.done` ile değiştirir.

Sürüm 1.2: akıştaki `error` olayının kodları dört kodla sınırlandı (`collection_locked` eklendi; diğer iç kodlar `server_error`'a çevrilir). `message.start.message_id` asistan mesajının kimliğidir. `CollectionFilm.title` = `Film.title`. `countries` backend'de Türkçeye çevrilir; karşılığı olmayan ad olduğu gibi kalır.

Sürüm 1.1: `notice` kayıtlı mesajda `steps` içinde saklanır (`StepKey` += `notice`); `CollectionSummary.approved_at` eklendi. "Tekrar dene" aynı metni yeni mesaj olarak gönderir (ayrı uç yok). Kullanıcı rolü ("editör") arayüzde sabit metindir.

Arayüz ve backend bu dosyaya göre yazılır. Değişiklik gerekirse kod değil ÖNCE bu dosya değişir.

## Genel
- Kök: `/api/`. Arayüz aynı kökten servis edilir (geliştirmede Vite vekili). JSON, UTF-8. Zamanlar ISO 8601 (UTC).
- Kimlik: Django oturum çerezi. Yazan isteklerde (`POST`, `PATCH`, `DELETE`) `X-CSRFToken` başlığı (`csrftoken` çerezinden). `GET /api/auth/me` çerezi kurar.
- Hata cevabı her yerde: `{"detail": "<Türkçe mesaj>", "code": "<kod>"}` + HTTP durum kodu. Ortak kodlar: `not_authenticated` (401), `forbidden` (403), `not_found` (404), `validation_error` (422; ayrıştırılamayan gövde dahil), `conflict` (409), `rate_limited` (429), `server_error` (500). İç kütüphane mesajı (İngilizce ayrıştırıcı metni vb.) `detail`'e yazılmaz.
- Giriş gerektirmeyen uçlar: `auth/login`, `auth/logout`, `auth/me`, `share/{token}`, `health`. Diğer her uç girişsiz 401 döner. Not: yazan bir istekte hem giriş hem `X-CSRFToken` eksikse cevap 403 `forbidden` olur (CSRF denetimi önce yapılır); arayüz başlığı her zaman gönderir. `auth/login` IP başına dakikada 10, `share/{token}` dakikada 60 istekle sınırlıdır; aşımda 429 `rate_limited`. Desteklenmeyen yöntem 405 `method_not_allowed` (aynı JSON biçimi). Kullanıcı yalnız kendi sohbet ve koleksiyonunu görür (başkasınınki 404).

## Tipler
```ts
type User = { id: number; username: string; display_name: string; initials: string };

type Source = { kind: "wikipedia" | "tmdb"; label: string; url: string };

// Alıntının alındığı kaynak (1.4). `url` bilinmiyorsa null.
type QuoteSource = { kind: "plot" | "overview" | "review"; label: string; url: string | null };

type CollectionFilm = {
  film_id: number;
  position: number;            // 1'den başlar
  title: string;               // orijinal ad
  title_tr: string | null;
  year: number | null;
  countries: string[];         // Türkçe ülke adları
  vote_count: number | null;
  directors: string[];         // en çok 3 ad; yoksa []
  actors: string[];            // en çok 6 ad (künye sırasıyla); yoksa []
  poster_url: string | null;   // tam URL; yoksa null
  rationale: string;           // Türkçe gerekçe
  source_quote: string;        // kaynaktan birebir alıntı (İngilizce), boş olabilir
  quote_source: QuoteSource | null;  // 1.4: alıntı boşsa ya da kaynak türü kayıtlı değilse null
  sources: Source[];
};

type CollectionStats = {
  film_count: number;
  year_min: number | null;
  year_max: number | null;
  country_count: number;
  avg_vote_count: number | null;
};

type Collection = {
  id: number;
  chat_id: number | null;
  title: string;
  description: string;
  status: "draft" | "approved";
  version: number;             // her değişiklikte artar
  films: CollectionFilm[];     // position sırasıyla
  stats: CollectionStats;
  share_url: string | null;    // yalnız approved: "/k/<token>"
  approved_at: string | null;
  updated_at: string;
};

type CollectionSummary = {
  id: number; title: string; status: "draft" | "approved";
  film_count: number; poster_urls: string[];   // ilk 6 afiş
  share_url: string | null; approved_at: string | null; updated_at: string;
};

type StepKey = "parse" | "search" | "read" | "select" | "retry" | "update" | "notice";
type Step = {
  key: StepKey;
  status: "running" | "done" | "error";
  title: string;               // kalın kısım: "Arşivde dolaştım."
  detail: string;              // devamı: "184 aday çıktı."
  count: number | null;        // sağdaki sayı (varsa)
};
// Kayıtlı mesajda `notice` olayları da `steps` içinde, geldikleri sırada, `key: "notice"`,
// `status: "done"`, `title: ""`, `detail: <metin>`, `count: null` olarak saklanır (sohbet yeniden
// yüklenince kaybolmasın). Akış sırasında `notice` ayrı olay olarak gelmeye devam eder.

type Message = {
  id: number;
  role: "user" | "assistant";
  text: string;                // yalnız **kalın** işaretlemesi; başka biçim yok
  created_at: string;
  steps: Step[];               // yalnız assistant; yoksa []
  duration_s: number | null;   // adımların toplam süresi
  collection_id: number | null;        // bu mesajın ürettiği/güncellediği koleksiyon
  suggestions: string[];       // öneri düğmeleri (0-3)
  error: { detail: string; code: string } | null;
};

type ChatSummary = { id: number; title: string; updated_at: string };
type Chat = ChatSummary & { messages: Message[]; collection: Collection | null };
```

## Uçlar
| Yöntem ve yol | Gövde | Cevap |
|---|---|---|
| `GET /api/auth/me` | - | 200 `User`; girişsiz 401 `not_authenticated` |
| `POST /api/auth/login` | `{username, password}` | 200 `User`; 401 `invalid_credentials` |
| `POST /api/auth/logout` | - | 204 |
| `GET /api/chats` | - | 200 `ChatSummary[]` (yeniden eskiye) |
| `POST /api/chats` | - | 201 `ChatSummary` (başlık "Yeni sohbet"; ilk mesajdan sonra backend başlığı günceller) |
| `GET /api/chats/{id}` | - | 200 `Chat` |
| `POST /api/chats/{id}/messages/stream` | `{text, action?}` | 200 `text/event-stream` (aşağıda) |
| `GET /api/collections` | - | 200 `CollectionSummary[]` (yalnız `approved`, yeniden eskiye) |
| `GET /api/collections/{id}` | - | 200 `Collection` |
| `PATCH /api/collections/{id}` | `{title?, description?}` | 200 `Collection`; `approved` ise 409 `collection_locked` |
| `DELETE /api/collections/{id}/films/{film_id}` | - | 200 `Collection`; `approved` ise 409 `collection_locked` |
| `POST /api/collections/{id}/approve` | - | 200 `Collection` (`status=approved`, `share_url` dolu); film yoksa 422 `empty_collection`; zaten onaylıysa 409 `already_approved` |
| `GET /api/share/{token}` | - | 200 `SharedCollection` (girişsiz); yoksa 404 |

`SharedCollection` = `{title, description, films: CollectionFilm[], stats: CollectionStats, owner_display_name, approved_at}`.

`action` (isteğe bağlı; düğmelerden gelen yapılı istek, `text` yine dolu gelir):
- `{ "type": "replace_film", "film_id": 123 }` ("Bunun yerine başkasını bul")
- `{ "type": "research" }` ("Yeniden araştır")

Onay kuralı: koleksiyon ancak `approve` ucu çağrılınca `approved` olur ve paylaşım linki oluşur. Agent hiçbir koşulda kendisi onaylayamaz (kodda engelli). Onaylı koleksiyon salt okunurdur.

## Akan cevap: `POST /api/chats/{id}/messages/stream`
Cevap `text/event-stream`. Her olay: `event: <ad>` + `data: <tek satır JSON>` + boş satır. Sıra:

| Olay | Veri | Anlam |
|---|---|---|
| `message.start` | `{user_message: Message, message_id: number}` | Kullanıcı mesajı kaydedildi; cevap başlıyor |
| `step.start` | `{key, title}` | Adım başladı (ör. "İsteğini çözüyorum") |
| `step.done` | `Step` (`status: "done"`) | Adım bitti; başlık/ayrıntı/sayı kesinleşti |
| `notice` | `{text}` | Editöre bilgi (ör. "Yıl filtresini gevşettim, yoksa 4 film çıkıyordu") |
| `text.delta` | `{delta}` | Cevap metninin sıradaki parçası |
| `collection` | `Collection` | Taslak oluştu ya da güncellendi (tam hali) |
| `suggestions` | `{items: string[]}` | Öneri düğmeleri |
| `message.done` | `{message: Message, chat: ChatSummary}` | Cevap kaydedildi; akış biter |
| `error` | `{detail, code}` | Hata; akış biter. Kodlar YALNIZ: `model_error`, `search_error`, `collection_locked` (tur sürerken koleksiyon onaylandıysa), `server_error`. Başka her iç hata kodu `server_error`'a ve genel bir Türkçe mesaja çevrilir (iç kod ve iç mesaj istemciye gitmez) |

Kurallar:
- `step.start` ile aynı `key` için `step.done` gelir. Aynı `key` birden çok kez gelebilir (`retry`). İstisna: adım sürerken hata olursa `step.done` gelmeden `error` gelir; arayüz o an çalışan adımı hatalı sayar.
- `collection` olayı metinden önce ya da sonra gelebilir; arayüz sırayı varsaymaz.
- İstemci bağlantıyı keserse (durdur düğmesi) backend işi bırakır; yarım cevap `message.done` olmadan kalır. Sohbet yeniden yüklendiğinde yalnız kaydedilmiş mesajlar gelir.
- Akış sırasında hata olursa `error` olayı gelir; HTTP durum kodu 200 kalır. Akış başlamadan olan hatalar (401, 404, 422) normal JSON hata cevabıdır.
- 15 saniyede bir yorum satırı (`: ping`) gelebilir; arayüz yok sayar.

## Arayüz yolları
| Yol | Ekran |
|---|---|
| `/giris` | Giriş |
| `/` | Yeni sohbet (boş) |
| `/s/:chatId` | Sohbet (+ taslak paneli) |
| `/koleksiyonlar` | Koleksiyonlarım |
| `/koleksiyon/:id` | Onaylı koleksiyon (salt okunur, tam genişlik) |
| `/k/:token` | Paylaşım sayfası (girişsiz) |

## Afiş ve kaynak adresleri (backend üretir)
- `poster_url`: `https://image.tmdb.org/t/p/w342<poster_path>`; `poster_path` boşsa `null`.
- `quote_source` (1.4): `CollectionFilm` kaydındaki `source_kind` / `source_url`'den üretilir. Etiketler: `plot` "Wikipedia · hikâye", `overview` "TMDB · tanıtım", `review` "izleyici incelemesi". `source_url` boşsa `url` null.
- `sources`: Wikipedia hikâye bağlantısı (filmin `wikipedia_url`'i, etiket "Wikipedia · hikâye"), TMDB sayfası (`https://www.themoviedb.org/movie/<tmdb_id>`, etiket "TMDB · tanıtım"); olmayan kaynak listeye girmez.

## Dil modeli ayarı (1.5)
Oturum açmış her kullanıcı kullanır (yönetici şartı yok; tek kullanıcılı yerel kurulum). Yazan uçlarda `X-CSRFToken` gerekir; girişsiz 401 `not_authenticated`. Sağlayıcı ve anahtarlar sunucuyu yeniden başlatmadan, bir sonraki istekte geçerli olur. `.env` varsayılandır; kaydedilen ayar onun üstüne yazar.

```ts
type LlmProvider = "anthropic" | "gemini" | "ollama";

type LlmSettings = {
  provider: LlmProvider;
  source: "env" | "saved";    // "saved": arayüzden kaydedilmiş ayar var
  anthropic: { configured: boolean; key_hint: string | null; model: string };  // key_hint: "…abcd" (son 4 karakter)
  gemini: { configured: boolean; key_hint: string | null; model: string };
  ollama: { base_url: string; model: string };
};
```

| Yöntem ve yol | Gövde | Cevap |
|---|---|---|
| `GET /api/settings/llm` | - | 200 `LlmSettings` |
| `PUT /api/settings/llm` | `{provider, anthropic_api_key?, gemini_api_key?, ollama_base_url?, ollama_model?}` | 200 `LlmSettings`; 400 `missing_key` / `invalid_key` / `invalid_url`; 422 `validation_error` (bilinmeyen sağlayıcı) |
| `POST /api/settings/llm/test` | - | 200 `{ok: true, seconds}` ya da `{ok: false, message}` |

- Boş ya da gönderilmeyen alan "olanı koru" demektir; kayıtlı anahtar silinmez.
- `missing_key`: seçilen sağlayıcının anahtarı ne kayıtlı ne ortamda. Ollama için anahtar gerekmez.
- `invalid_key`: anahtar kırpıldıktan sonra 20 karakterden kısa, 300'den uzun, içinde boşluk / satır sonu ya da ASCII dışı / yazdırılamayan karakter var. Önek ya da alfabe denetimi yoktur (geçerli anahtar reddedilmez); gerçek geçerlilik `test` ucuyla anlaşılır. Baştaki / sondaki boşluk ve tırnak sessizce kırpılır.
- `invalid_url`: Ollama adresi `http://` ya da `https://` ile başlamalı (adreste kullanıcı bilgisi olamaz).
- Anahtarın kendisi hiçbir cevapta dönmez; yalnız `configured` ve `key_hint`.
- `test` etkin ayarla çok kısa gerçek bir model çağrısı yapar; `message` Türkçe ve kullanıcıya dönüktür (ham sağlayıcı cevabı yok). Hata da 200 ile `ok: false` döner.
