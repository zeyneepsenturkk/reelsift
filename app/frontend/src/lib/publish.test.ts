import { describe, expect, it } from 'vitest'
import { actionsLayout, publishErrorMessage, publishReducer, safeSiteUrl, type PublishStep } from './publish.ts'

const run = (start: PublishStep, ...types: Parameters<typeof publishReducer>[1]['type'][]) =>
  types.reduce<PublishStep>((step, type) => publishReducer(step, { type }), start)

describe('publishReducer', () => {
  it('düğme, onay, yayınlama, başa dönüş sırasını izler', () => {
    expect(run('idle', 'ask')).toBe('confirm')
    expect(run('idle', 'ask', 'confirm')).toBe('publishing')
    expect(run('idle', 'ask', 'confirm', 'settle')).toBe('idle')
  })

  it('Vazgeç ya da Escape onaydan eski hale döner', () => {
    expect(run('idle', 'ask', 'cancel')).toBe('idle')
  })

  it('onay adımı atlanamaz: idle iken "evet" yayınlamaya geçmez', () => {
    expect(run('idle', 'confirm')).toBe('idle')
    expect(run('idle', 'settle')).toBe('idle')
  })

  it('istek sürerken vazgeçilemez ve yeniden sorulamaz', () => {
    expect(run('publishing', 'cancel')).toBe('publishing')
    expect(run('publishing', 'ask')).toBe('publishing')
    expect(run('publishing', 'confirm')).toBe('publishing')
  })

  it('panel başka seçkiye geçerse her adım başa döner', () => {
    for (const step of ['idle', 'confirm', 'publishing'] as const) {
      expect(publishReducer(step, { type: 'reset' })).toBe('idle')
    }
  })

  it('durum değişmiyorsa aynı değeri döndürür', () => {
    expect(publishReducer('idle', { type: 'cancel' })).toBe('idle')
    expect(publishReducer('confirm', { type: 'ask' })).toBe('confirm')
  })
})

describe('actionsLayout', () => {
  it('yayın kapalı ve adres yoksa bugünkü hal', () => {
    expect(actionsLayout({ publish_enabled: false, published_url: null })).toBe('share-only')
  })

  it('yayın açık ve adres yoksa yayınlama sunulur', () => {
    expect(actionsLayout({ publish_enabled: true, published_url: null })).toBe('offer-publish')
  })

  it('adres varsa yayın açık olsun olmasın site bağlantısı', () => {
    expect(actionsLayout({ publish_enabled: true, published_url: 'https://site.test/s/a/' })).toBe('published')
    expect(actionsLayout({ publish_enabled: false, published_url: 'https://site.test/s/a/' })).toBe('published')
  })

  it('boş adres yok sayılır', () => {
    expect(actionsLayout({ publish_enabled: false, published_url: '' })).toBe('share-only')
  })
})

describe('publishErrorMessage', () => {
  it('koda göre Türkçe metin verir', () => {
    expect(publishErrorMessage('publish_unreachable')).toBe('Siteye ulaşılamadı. Bağlantını kontrol edip tekrar dene.')
    expect(publishErrorMessage('publish_unauthorized')).toBe('Site anahtarı kabul etmedi. Anahtarı kontrol et.')
  })

  it('diğer kodlar, bilinmeyen kod ve kodsuz hata aynı genel metni alır', () => {
    for (const code of ['publish_failed', 'publish_rejected', 'not_approved', 'network_error', 'x', null]) {
      expect(publishErrorMessage(code)).toBe('Seçki yayınlanamadı, bir daha dener misin?')
    }
  })
})

describe('safeSiteUrl', () => {
  it('http ve https adreslerini kabul eder', () => {
    expect(safeSiteUrl('https://site.test/s/a/')).toBe('https://site.test/s/a/')
    expect(safeSiteUrl('http://localhost:8002/s/a/')).toBe('http://localhost:8002/s/a/')
  })

  it('başka şemayı, bozuk ve boş değeri reddeder', () => {
    for (const value of ['javascript:alert(1)', 'data:text/html,x', '/s/a/', 'not a url', '', null]) {
      expect(safeSiteUrl(value)).toBeNull()
    }
  })
})
