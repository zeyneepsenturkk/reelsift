import { describe, expect, it } from 'vitest'
import type { LlmSettings } from '../api/types.ts'
import {
  buildUpdateBody,
  formatSeconds,
  initialLlmState,
  isDirty,
  keyPlaceholder,
  llmReducer,
  testMessage,
  type LlmDialogState,
} from './llmSettings.ts'

const settings: LlmSettings = {
  provider: 'anthropic',
  source: 'env',
  anthropic: { configured: true, key_hint: 'abcd', model: 'claude-haiku-5-5' },
  gemini: { configured: false, key_hint: null, model: 'gemini-3.5-flash-lite' },
  ollama: { base_url: 'http://localhost:11434', model: 'qwen3:8b' },
}

const ready = (): LlmDialogState => llmReducer(initialLlmState, { type: 'loaded', settings })

describe('llmReducer', () => {
  it('yüklenince formu doldurur, anahtar alanları boş kalır, kurulum satırını gösterir', () => {
    const state = ready()
    expect(state.load).toBe('ready')
    expect(state.form).toEqual({
      provider: 'anthropic',
      anthropicKey: '',
      geminiKey: '',
      ollamaBaseUrl: 'http://localhost:11434',
      ollamaModel: 'qwen3:8b',
    })
    expect(state.showEnvNotice).toBe(true)
  })

  it('kaydedilmiş kaynakta kurulum satırı çıkmaz; yükleme hatası ve yeniden deneme', () => {
    const saved = llmReducer(initialLlmState, { type: 'loaded', settings: { ...settings, source: 'saved' } })
    expect(saved.showEnvNotice).toBe(false)
    const failed = llmReducer(initialLlmState, { type: 'loadFailed' })
    expect(failed.load).toBe('error')
    expect(llmReducer(failed, { type: 'retry' }).load).toBe('loading')
  })

  it('seçim değişince kaydedilmemiş değişiklik olur ve eski sonuçlar silinir', () => {
    const tested = llmReducer(ready(), { type: 'testFinished', result: { ok: true, seconds: 1.2 } })
    const state = llmReducer(tested, { type: 'select', provider: 'gemini' })
    expect(state.form.provider).toBe('gemini')
    expect(state.test).toEqual({ status: 'idle' })
    expect(isDirty(state.form, state.saved)).toBe(true)
  })

  it('başarılı kayıt anahtar alanını temizler, kurulum satırını kapatır, yeni durumu esas alır', () => {
    let state = llmReducer(ready(), { type: 'select', provider: 'gemini' })
    state = llmReducer(state, { type: 'edit', field: 'geminiKey', value: 'AIza-gizli-1234' })
    state = llmReducer(state, { type: 'saveStarted' })
    expect(state.save).toBe('saving')
    const next: LlmSettings = {
      ...settings,
      provider: 'gemini',
      source: 'saved',
      gemini: { configured: true, key_hint: '1234', model: 'gemini-3.5-flash-lite' },
    }
    state = llmReducer(state, { type: 'saveSucceeded', settings: next })
    expect(state.save).toBe('saved')
    expect(state.form.geminiKey).toBe('')
    expect(state.showEnvNotice).toBe(false)
    expect(isDirty(state.form, state.saved)).toBe(false)
  })

  it('kayıt hatasında mesajı tutar, yazılan anahtarı korur; yeni düzenleme mesajı siler', () => {
    let state = llmReducer(ready(), { type: 'edit', field: 'anthropicKey', value: 'x' })
    state = llmReducer(state, { type: 'saveFailed', message: 'Anahtar geçersiz.' })
    expect(state.save).toBe('error')
    expect(state.saveError).toBe('Anahtar geçersiz.')
    expect(state.form.anthropicKey).toBe('x')
    state = llmReducer(state, { type: 'edit', field: 'anthropicKey', value: 'xy' })
    expect(state.saveError).toBeNull()
  })

  it('deneme sonucu: çalışıyor ve hata', () => {
    let state = llmReducer(ready(), { type: 'testStarted' })
    expect(testMessage(state.test)).toBe('Deneniyor… (yerel modelde bir dakika sürebilir)')
    state = llmReducer(state, { type: 'testFinished', result: { ok: true, seconds: 1.2 } })
    expect(testMessage(state.test)).toBe('Çalışıyor (1,2 sn)')
    state = llmReducer(state, { type: 'testFinished', result: { ok: false, message: 'Model yanıt vermedi.' } })
    expect(testMessage(state.test)).toBe('Model yanıt vermedi.')
    state = llmReducer(state, { type: 'testFailed', message: 'Ağ hatası.' })
    expect(state.test).toEqual({ status: 'failed', message: 'Ağ hatası.' })
  })
})

describe('isDirty', () => {
  it('kayıt yokken ve değişiklik yokken temiz, boşluktan ibaret anahtar değişiklik değil', () => {
    const state = ready()
    expect(isDirty(state.form, null)).toBe(false)
    expect(isDirty(state.form, state.saved)).toBe(false)
    expect(isDirty({ ...state.form, geminiKey: '   ' }, state.saved)).toBe(false)
    expect(isDirty({ ...state.form, ollamaModel: 'llama3' }, state.saved)).toBe(true)
  })
})

describe('buildUpdateBody', () => {
  it('boş anahtar gönderilmez, yalnız seçim gider', () => {
    const { form, saved } = ready()
    expect(buildUpdateBody(form, saved)).toEqual({ provider: 'anthropic' })
  })

  it('yazılan anahtar kırpılarak gider; Ollama alanları yalnız değiştiyse', () => {
    const { form, saved } = ready()
    expect(buildUpdateBody({ ...form, provider: 'gemini', geminiKey: '  AIza1  ' }, saved)).toEqual({
      provider: 'gemini',
      gemini_api_key: 'AIza1',
    })
    expect(buildUpdateBody({ ...form, provider: 'ollama', ollamaModel: 'llama3' }, saved)).toEqual({
      provider: 'ollama',
      ollama_model: 'llama3',
    })
  })

  it('boşaltılmış Ollama alanı gönderilmez (olan korunur)', () => {
    const { form, saved } = ready()
    expect(buildUpdateBody({ ...form, ollamaBaseUrl: '  ' }, saved)).toEqual({ provider: 'anthropic' })
  })
})

describe('keyPlaceholder ve formatSeconds', () => {
  it('kayıtlı anahtar için son haneleri, yoksa yönlendirmeyi gösterir', () => {
    expect(keyPlaceholder(settings.anthropic)).toBe('Kayıtlı: ••••abcd')
    expect(keyPlaceholder({ configured: true, key_hint: '••••wxyz', model: 'm' })).toBe('Kayıtlı: ••••wxyz')
    expect(keyPlaceholder({ configured: true, key_hint: null, model: 'm' })).toBe('Kayıtlı anahtar var')
    expect(keyPlaceholder(settings.gemini)).toBe('API anahtarını yapıştır')
  })

  it('saniyeyi virgüllü gösterir', () => {
    expect(formatSeconds(1.2)).toBe('1,2 sn')
    expect(formatSeconds(12)).toBe('12,0 sn')
  })
})
