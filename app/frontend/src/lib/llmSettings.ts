import type { LlmKeyInfo, LlmProvider, LlmSettings, LlmSettingsUpdate, LlmTestResult } from '../api/types.ts'

export type LlmField = 'anthropicKey' | 'geminiKey' | 'ollamaBaseUrl' | 'ollamaModel'
export type LlmForm = {
  provider: LlmProvider
  anthropicKey: string
  geminiKey: string
  ollamaBaseUrl: string
  ollamaModel: string
}
export type SaveState = 'idle' | 'saving' | 'saved' | 'error'
export type TestState =
  | { status: 'idle' }
  | { status: 'running' }
  | { status: 'ok'; seconds: number }
  | { status: 'failed'; message: string }

export type LlmDialogState = {
  load: 'loading' | 'error' | 'ready'
  saved: LlmSettings | null
  form: LlmForm
  showKey: boolean
  save: SaveState
  // Sunucunun reddettiği kaydın mesajı; ilgili alanın altında gösterilir.
  saveError: string | null
  test: TestState
  // Kurulumdaki ayarın kullanıldığını söyleyen satır; ilk başarılı kayıttan sonra kapanır.
  showEnvNotice: boolean
}

export type LlmDialogAction =
  | { type: 'retry' }
  | { type: 'loaded'; settings: LlmSettings }
  | { type: 'loadFailed' }
  | { type: 'select'; provider: LlmProvider }
  | { type: 'edit'; field: LlmField; value: string }
  | { type: 'toggleKey' }
  | { type: 'saveStarted' }
  | { type: 'saveSucceeded'; settings: LlmSettings }
  | { type: 'saveFailed'; message: string }
  | { type: 'testStarted' }
  | { type: 'testFinished'; result: LlmTestResult }
  | { type: 'testFailed'; message: string }

export const emptyForm: LlmForm = {
  provider: 'anthropic',
  anthropicKey: '',
  geminiKey: '',
  ollamaBaseUrl: '',
  ollamaModel: '',
}

export const initialLlmState: LlmDialogState = {
  load: 'loading',
  saved: null,
  form: emptyForm,
  showKey: false,
  save: 'idle',
  saveError: null,
  test: { status: 'idle' },
  showEnvNotice: false,
}

// Kayıtlı ayardan form kurulur; anahtar alanları her zaman boş başlar (anahtar ekrana geri yazılmaz).
export function formFromSettings(settings: LlmSettings): LlmForm {
  return {
    provider: settings.provider,
    anthropicKey: '',
    geminiKey: '',
    ollamaBaseUrl: settings.ollama.base_url,
    ollamaModel: settings.ollama.model,
  }
}

export function llmReducer(state: LlmDialogState, action: LlmDialogAction): LlmDialogState {
  switch (action.type) {
    case 'retry':
      return { ...initialLlmState }
    case 'loaded':
      return {
        ...state,
        load: 'ready',
        saved: action.settings,
        form: formFromSettings(action.settings),
        showEnvNotice: action.settings.source === 'env',
      }
    case 'loadFailed':
      return { ...state, load: 'error' }
    case 'select':
      return { ...state, form: { ...state.form, provider: action.provider }, save: 'idle', saveError: null, test: { status: 'idle' } }
    case 'edit':
      return { ...state, form: { ...state.form, [action.field]: action.value }, save: 'idle', saveError: null, test: { status: 'idle' } }
    case 'toggleKey':
      return { ...state, showKey: !state.showKey }
    case 'saveStarted':
      return { ...state, save: 'saving', saveError: null, test: { status: 'idle' } }
    case 'saveSucceeded':
      return {
        ...state,
        saved: action.settings,
        form: formFromSettings(action.settings),
        save: 'saved',
        saveError: null,
        showEnvNotice: false,
      }
    case 'saveFailed':
      return { ...state, save: 'error', saveError: action.message }
    case 'testStarted':
      return { ...state, test: { status: 'running' } }
    case 'testFinished':
      return {
        ...state,
        test: action.result.ok
          ? { status: 'ok', seconds: action.result.seconds }
          : { status: 'failed', message: action.result.message },
      }
    case 'testFailed':
      return { ...state, test: { status: 'failed', message: action.message } }
  }
}

// Kaydedilmemiş değişiklik: seçim, yazılmış anahtar ya da Ollama alanı kayıtlıdan farklı.
export function isDirty(form: LlmForm, saved: LlmSettings | null): boolean {
  if (!saved) return false
  return (
    form.provider !== saved.provider ||
    form.anthropicKey.trim() !== '' ||
    form.geminiKey.trim() !== '' ||
    form.ollamaBaseUrl.trim() !== saved.ollama.base_url ||
    form.ollamaModel.trim() !== saved.ollama.model
  )
}

// PUT gövdesi: seçim her zaman, boş anahtar hiç, Ollama alanları yalnız değiştiyse gönderilir.
export function buildUpdateBody(form: LlmForm, saved: LlmSettings | null): LlmSettingsUpdate {
  const body: LlmSettingsUpdate = { provider: form.provider }
  const anthropicKey = form.anthropicKey.trim()
  const geminiKey = form.geminiKey.trim()
  if (anthropicKey) body.anthropic_api_key = anthropicKey
  if (geminiKey) body.gemini_api_key = geminiKey
  const baseUrl = form.ollamaBaseUrl.trim()
  const model = form.ollamaModel.trim()
  if (baseUrl && baseUrl !== saved?.ollama.base_url) body.ollama_base_url = baseUrl
  if (model && model !== saved?.ollama.model) body.ollama_model = model
  return body
}

// Kayıtlı anahtarın yalnız son hanelerini gösterir; sunucu ipucunu noktalı ya da düz verse de aynı biçime iner.
export function keyPlaceholder(info: LlmKeyInfo): string {
  if (!info.configured) return 'API anahtarını yapıştır'
  const tail = (info.key_hint ?? '').replace(/^[•*\s.]+/, '')
  return tail ? `Kayıtlı: ••••${tail}` : 'Kayıtlı anahtar var'
}

export function formatSeconds(seconds: number): string {
  return `${seconds.toLocaleString('tr-TR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} sn`
}

export function testMessage(test: TestState): string | null {
  switch (test.status) {
    case 'running':
      return 'Deneniyor… (yerel modelde bir dakika sürebilir)'
    case 'ok':
      return `Çalışıyor (${formatSeconds(test.seconds)})`
    case 'failed':
      return test.message
    case 'idle':
      return null
  }
}

export const PROVIDERS: { id: LlmProvider; title: string; note: string }[] = [
  { id: 'anthropic', title: 'Claude (Anthropic)', note: 'Ücretli. En iyi kalite; taslak yaklaşık 40-50 saniye.' },
  { id: 'gemini', title: 'Gemini (Google)', note: 'Ücretsiz kota. Taslak 1,5-5,5 dakika sürebilir.' },
  {
    id: 'ollama',
    title: 'Yerel model (Ollama)',
    note: 'Ücretsiz ve çevrimdışı. Kalite düşük; kişi adı içeren isteklerde güvenilir değil.',
  },
]

export const KEY_LINKS = {
  anthropic: 'https://console.anthropic.com/',
  gemini: 'https://aistudio.google.com/apikey',
} as const
