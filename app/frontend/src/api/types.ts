// API sözleşmesi (docs/api-sozlesmesi.md, sürüm 1.4) ile birebir tipler.
// Dosyanın altındaki "istemci tarafı" bölümü sözleşmede olmayan, yalnız bu arayüzün kullandığı tiplerdir.

export type User = { id: number; username: string; display_name: string; initials: string }

export type Source = { kind: 'wikipedia' | 'tmdb'; label: string; url: string }

// Alıntının alındığı kaynak (sözleşme 1.4). `url` bilinmiyorsa null.
export type QuoteSource = { kind: 'plot' | 'overview' | 'review'; label: string; url: string | null }

export type CollectionFilm = {
  film_id: number
  position: number // 1'den başlar
  title: string // orijinal ad
  title_tr: string | null
  year: number | null
  countries: string[] // Türkçe ülke adları
  directors: string[] // en çok 3, boş olabilir
  actors: string[] // en çok 6, boş olabilir
  vote_count: number | null
  poster_url: string | null // tam URL; yoksa null
  rationale: string // Türkçe gerekçe
  source_quote: string // kaynaktan birebir alıntı (İngilizce), boş olabilir
  quote_source: QuoteSource | null // alıntı boşsa ya da kaynak türü kayıtlı değilse null
  sources: Source[]
}

export type CollectionStats = {
  film_count: number
  year_min: number | null
  year_max: number | null
  country_count: number
  avg_vote_count: number | null
}

export type Collection = {
  id: number
  chat_id: number | null
  title: string
  description: string
  status: 'draft' | 'approved'
  version: number // her değişiklikte artar
  films: CollectionFilm[] // position sırasıyla
  stats: CollectionStats
  share_url: string | null // yalnız approved: "/k/<token>"
  published_url: string | null // herkese açık sitedeki sayfa; yayınlanmadıysa null
  publish_enabled: boolean // "Sitede yayınla" bu kurulumda açık mı (seçkinin durumundan bağımsız)
  approved_at: string | null
  updated_at: string
}

export type CollectionSummary = {
  id: number
  title: string
  status: 'draft' | 'approved'
  film_count: number
  poster_urls: string[] // ilk 6 afiş
  share_url: string | null
  approved_at: string | null
  updated_at: string
}

export type StepKey = 'parse' | 'search' | 'read' | 'select' | 'retry' | 'update' | 'notice'
export type Step = {
  key: StepKey
  status: 'running' | 'done' | 'error'
  title: string // kalın kısım: "Arşivde dolaştım."
  detail: string // devamı: "184 aday çıktı."
  count: number | null // sağdaki sayı (varsa)
}
// Kayıtlı mesajda notice'ler de `steps` içinde `key: 'notice'`, `detail: <metin>` olarak saklanır (sözleşme 1.1).

export type Message = {
  id: number
  role: 'user' | 'assistant'
  text: string // yalnız **kalın** işaretlemesi; başka biçim yok
  created_at: string
  steps: Step[] // yalnız assistant; yoksa []
  duration_s: number | null // adımların toplam süresi
  collection_id: number | null // bu mesajın ürettiği/güncellediği koleksiyon
  suggestions: string[] // öneri düğmeleri (0-3)
  error: { detail: string; code: string } | null
}

export type ChatSummary = { id: number; title: string; updated_at: string }
export type Chat = ChatSummary & { messages: Message[]; collection: Collection | null }

export type SharedCollection = {
  title: string
  description: string
  films: CollectionFilm[]
  stats: CollectionStats
  owner_display_name: string
  approved_at: string
}

export type MessageAction = { type: 'replace_film'; film_id: number } | { type: 'research' }
export type SendBody = { text: string; action?: MessageAction }

// Akan cevap olayları (sözleşme "Akan cevap" tablosu). `event` alanı SSE'deki `event:` adıdır.
export type StreamEvent =
  | { event: 'message.start'; data: { user_message: Message; message_id: number } }
  | { event: 'step.start'; data: { key: StepKey; title: string } }
  | { event: 'step.done'; data: Step }
  | { event: 'notice'; data: { text: string } }
  | { event: 'text.delta'; data: { delta: string } }
  | { event: 'collection'; data: Collection }
  | { event: 'suggestions'; data: { items: string[] } }
  | { event: 'message.done'; data: { message: Message; chat: ChatSummary } }
  | { event: 'error'; data: { detail: string; code: string } }

export type StreamEventName = StreamEvent['event']

export type LlmProvider = 'anthropic' | 'gemini' | 'ollama'
export type LlmKeyInfo = { configured: boolean; key_hint: string | null; model: string }
export type LlmSettings = {
  provider: LlmProvider
  source: 'env' | 'saved'
  anthropic: LlmKeyInfo
  gemini: LlmKeyInfo
  ollama: { base_url: string; model: string }
}
// Boş ya da gönderilmeyen anahtar alanı kayıtlı değeri korur.
export type LlmSettingsUpdate = {
  provider: LlmProvider
  anthropic_api_key?: string
  gemini_api_key?: string
  ollama_base_url?: string
  ollama_model?: string
}
export type LlmTestResult = { ok: true; seconds: number } | { ok: false; message: string }
