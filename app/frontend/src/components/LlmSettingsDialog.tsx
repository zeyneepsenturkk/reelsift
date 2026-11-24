import { useCallback, useEffect, useReducer, useRef, type KeyboardEvent } from 'react'
import { api } from '../api/index.ts'
import { ApiError } from '../api/errors.ts'
import type { LlmKeyInfo, LlmProvider } from '../api/types.ts'
import {
  KEY_LINKS,
  PROVIDERS,
  buildUpdateBody,
  initialLlmState,
  isDirty,
  keyPlaceholder,
  llmReducer,
  testMessage,
  type LlmField,
} from '../lib/llmSettings.ts'

const GENERIC_SAVE_ERROR = 'Kaydedilemedi. Bağlantını kontrol edip tekrar dene.'
const GENERIC_TEST_ERROR = 'Deneme tamamlanamadı. Bağlantını kontrol edip tekrar dene.'

// Reddedilen kaydın mesajı yalnız sunucu 400 döndüyse gösterilir; diğer hatalarda genel metin.
const saveMessage = (error: unknown) =>
  error instanceof ApiError && error.status === 400 && error.message ? error.message : GENERIC_SAVE_ERROR

type KeyFieldProps = {
  provider: 'anthropic' | 'gemini'
  info: LlmKeyInfo
  value: string
  visible: boolean
  error: string | null
  onChange: (value: string) => void
  onToggle: () => void
}

function KeyField({ provider, info, value, visible, error, onChange, onToggle }: KeyFieldProps) {
  const id = `llm-key-${provider}`
  return (
    <div className="llm-field">
      <label htmlFor={id}>API anahtarı</label>
      <div className="llm-keyrow">
        <input
          id={id}
          type={visible ? 'text' : 'password'}
          value={value}
          placeholder={keyPlaceholder(info)}
          autoComplete="off"
          spellCheck={false}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-err` : undefined}
          onChange={(event) => onChange(event.target.value)}
        />
        <button type="button" className="btn" aria-pressed={visible} onClick={onToggle}>
          {visible ? 'Gizle' : 'Göster'}
        </button>
      </div>
      <a className="llm-link" href={KEY_LINKS[provider]} target="_blank" rel="noreferrer">
        Anahtarı buradan al
      </a>
      {error && (
        <p className="llm-err" id={`${id}-err`} role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

export function LlmSettingsDialog({ onClose }: { onClose: () => void }) {
  const [state, dispatch] = useReducer(llmReducer, initialLlmState)
  const dialog = useRef<HTMLDialogElement>(null)
  const { load, saved, form, showKey, save, saveError, test, showEnvNotice } = state

  useEffect(() => {
    const element = dialog.current
    if (element && !element.open) element.showModal()
  }, [])

  useEffect(() => {
    if (load !== 'loading') return
    let current = true
    api
      .getLlmSettings()
      .then((settings) => current && dispatch({ type: 'loaded', settings }))
      .catch(() => current && dispatch({ type: 'loadFailed' }))
    return () => {
      current = false
    }
  }, [load])

  const dirty = isDirty(form, saved)
  const busy = save === 'saving' || test.status === 'running'

  // Kayıt başarılıysa true döner; hata durumunda mesaj forma yazılır.
  const persist = useCallback(async (): Promise<boolean> => {
    dispatch({ type: 'saveStarted' })
    try {
      const settings = await api.updateLlmSettings(buildUpdateBody(form, saved))
      dispatch({ type: 'saveSucceeded', settings })
      return true
    } catch (error) {
      dispatch({ type: 'saveFailed', message: saveMessage(error) })
      return false
    }
  }, [form, saved])

  const onSave = () => void persist()

  const onTest = async () => {
    if (dirty && !(await persist())) return
    dispatch({ type: 'testStarted' })
    try {
      dispatch({ type: 'testFinished', result: await api.testLlmSettings() })
    } catch {
      dispatch({ type: 'testFailed', message: GENERIC_TEST_ERROR })
    }
  }

  // Esc yalnız bu diyaloğu kapatır; sayfadaki Esc dinleyicilerine ulaşmaz.
  const onKeyDown = (event: KeyboardEvent<HTMLDialogElement>) => {
    if (event.key !== 'Escape') return
    event.preventDefault()
    event.stopPropagation()
    onClose()
  }

  const edit = (field: LlmField) => (value: string) => dispatch({ type: 'edit', field, value })
  const cloud = form.provider === 'ollama' ? null : form.provider
  const message = testMessage(test)

  return (
    <dialog
      ref={dialog}
      className="llm-dialog"
      aria-labelledby="llm-title"
      onKeyDown={onKeyDown}
      onClose={onClose}
      onClick={(event) => event.target === dialog.current && onClose()}
    >
      <div className="llm-body">
        <h2 id="llm-title">Dil modeli</h2>
        <p className="llm-lead">
          ReelSift'in isteği anlamak, filmleri değerlendirmek ve gerekçe yazmak için kullandığı model.
        </p>

        {load === 'loading' && (
          <div aria-busy="true" aria-label="Ayarlar yükleniyor">
            <div className="skel llm-skel" />
            <div className="skel llm-skel" />
            <div className="skel llm-skel" />
          </div>
        )}

        {load === 'error' && (
          <p className="list-note">
            Ayarlar yüklenemedi. <button onClick={() => dispatch({ type: 'retry' })}>Tekrar dene</button>
          </p>
        )}

        {load === 'ready' && saved && (
          <>
            {showEnvNotice && <p className="llm-info">Şu an kurulumdaki ayar kullanılıyor.</p>}
            <fieldset className="llm-cards" disabled={busy}>
              <legend className="sr-only">Model seçimi</legend>
              {PROVIDERS.map((provider) => (
                <label key={provider.id} className="llm-card">
                  <input
                    type="radio"
                    name="llm-provider"
                    value={provider.id}
                    checked={form.provider === provider.id}
                    onChange={() => dispatch({ type: 'select', provider: provider.id as LlmProvider })}
                  />
                  <span className="llm-card-title">{provider.title}</span>
                  <span className="llm-card-note">{provider.note}</span>
                </label>
              ))}
            </fieldset>

            {cloud && (
              <KeyField
                key={cloud}
                provider={cloud}
                info={saved[cloud]}
                value={cloud === 'anthropic' ? form.anthropicKey : form.geminiKey}
                visible={showKey}
                error={saveError}
                onChange={edit(cloud === 'anthropic' ? 'anthropicKey' : 'geminiKey')}
                onToggle={() => dispatch({ type: 'toggleKey' })}
              />
            )}

            {form.provider === 'ollama' && (
              <>
                <div className="llm-field">
                  <label htmlFor="llm-ollama-url">Adres</label>
                  <input
                    id="llm-ollama-url"
                    type="text"
                    value={form.ollamaBaseUrl}
                    autoComplete="off"
                    spellCheck={false}
                    onChange={(event) => edit('ollamaBaseUrl')(event.target.value)}
                  />
                </div>
                <div className="llm-field">
                  <label htmlFor="llm-ollama-model">Model</label>
                  <input
                    id="llm-ollama-model"
                    type="text"
                    value={form.ollamaModel}
                    autoComplete="off"
                    spellCheck={false}
                    aria-invalid={saveError ? true : undefined}
                    aria-describedby={saveError ? 'llm-ollama-err' : undefined}
                    onChange={(event) => edit('ollamaModel')(event.target.value)}
                  />
                  {saveError && (
                    <p className="llm-err" id="llm-ollama-err" role="alert">
                      {saveError}
                    </p>
                  )}
                </div>
              </>
            )}

            <div className="llm-status" aria-live="polite">
              {save === 'saved' && !message && (
                <p className="llm-ok">Kaydedildi. Bir sonraki istekte bu model kullanılır.</p>
              )}
              {message && <p className={test.status === 'failed' ? 'llm-err' : test.status === 'ok' ? 'llm-ok' : 'llm-wait'}>{message}</p>}
              {save === 'saving' && <p className="llm-wait">Kaydediliyor…</p>}
            </div>

            <div className="llm-actions">
              <button className="btn primary" onClick={onSave} disabled={busy || !dirty}>
                {save === 'saving' ? 'Kaydediliyor…' : 'Kaydet'}
              </button>
              <button className="btn" onClick={() => void onTest()} disabled={busy}>
                Bağlantıyı dene
              </button>
              <button className="btn" onClick={onClose}>
                Kapat
              </button>
            </div>
          </>
        )}
        {load !== 'ready' && (
          <div className="llm-actions">
            <button className="btn" onClick={onClose}>
              Kapat
            </button>
          </div>
        )}
      </div>
    </dialog>
  )
}
