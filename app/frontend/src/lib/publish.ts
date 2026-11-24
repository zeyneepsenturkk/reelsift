import type { Collection } from '../api/types.ts'

// "Sitede yayınla" iki adımlı onayının saf durumu. Düğme alanı üç adımdan birindedir:
// idle (düğme), confirm ("Geri alınamaz" metni + Evet / Vazgeç), publishing (istek sürüyor).
export type PublishStep = 'idle' | 'confirm' | 'publishing'

export type PublishAction =
  | { type: 'ask' }
  | { type: 'cancel' }
  | { type: 'confirm' }
  | { type: 'settle' } // istek bitti (başarı ya da hata): düğme alanı başa döner
  | { type: 'reset' } // panel başka seçkiye geçti

export function publishReducer(step: PublishStep, action: PublishAction): PublishStep {
  switch (action.type) {
    case 'ask':
      return step === 'idle' ? 'confirm' : step
    case 'cancel':
      // İstek uçarken vazgeçilemez: yayın zaten yola çıktı.
      return step === 'confirm' ? 'idle' : step
    case 'confirm':
      return step === 'confirm' ? 'publishing' : step
    case 'settle':
      return step === 'publishing' ? 'idle' : step
    case 'reset':
      return 'idle'
  }
}

// Onaylı seçkinin düğme alanı: yayın kapalıyken bugünkü hal, açıkken yayınlama sunulur, yayınlanmışsa site bağlantısı.
export type ActionsLayout = 'share-only' | 'offer-publish' | 'published'

export function actionsLayout(collection: Pick<Collection, 'publish_enabled' | 'published_url'>): ActionsLayout {
  if (collection.published_url) return 'published'
  return collection.publish_enabled ? 'offer-publish' : 'share-only'
}

export const PUBLISH_FAILED = 'Seçki yayınlanamadı, bir daha dener misin?'

export function publishErrorMessage(code: string | null): string {
  switch (code) {
    case 'publish_unreachable':
      return 'Siteye ulaşılamadı. Bağlantını kontrol edip tekrar dene.'
    case 'publish_unauthorized':
      return 'Site anahtarı kabul etmedi. Anahtarı kontrol et.'
    default:
      return PUBLISH_FAILED
  }
}

// Sunucudan dönen adres yeni sekmeye yönlendirilmeden önce yalnız http(s) olduğundan emin olunur.
export function safeSiteUrl(value: string | null): string | null {
  if (!value) return null
  try {
    const url = new URL(value)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null
  } catch {
    return null
  }
}
