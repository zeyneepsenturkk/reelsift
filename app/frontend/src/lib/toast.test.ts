import { describe, expect, it } from 'vitest'
import { initialToast, toastReducer } from './toast.ts'

describe('toastReducer', () => {
  it('gösterir ve sahibini tutar', () => {
    const state = toastReducer(initialToast, { type: 'show', message: 'Çıkarıldı', owner: 'collection:1' })
    expect(state).toEqual({ message: 'Çıkarıldı', owner: 'collection:1', visible: true })
  })

  it('sahibi giden bildirimi kapatır', () => {
    const shown = toastReducer(initialToast, { type: 'show', message: 'Çıkarıldı', owner: 'collection:1' })
    expect(toastReducer(shown, { type: 'clear', owner: 'collection:1' }).visible).toBe(false)
  })

  it('başka koleksiyonun ya da sahipsiz bildirimi kapatmaz', () => {
    const other = toastReducer(initialToast, { type: 'show', message: 'Çıkarıldı', owner: 'collection:2' })
    expect(toastReducer(other, { type: 'clear', owner: 'collection:1' })).toBe(other)
    const unrelated = toastReducer(initialToast, { type: 'show', message: 'Bağlantı yok', owner: null })
    expect(toastReducer(unrelated, { type: 'clear', owner: 'collection:1' })).toBe(unrelated)
  })

  it('kapalıyken kapatma isteği durumu değiştirmez', () => {
    expect(toastReducer(initialToast, { type: 'clear', owner: 'collection:1' })).toBe(initialToast)
    expect(toastReducer(initialToast, { type: 'hide' })).toBe(initialToast)
  })

  it('yeni bildirim eskisinin sahibini devralır', () => {
    const first = toastReducer(initialToast, { type: 'show', message: 'A', owner: 'collection:1' })
    const second = toastReducer(first, { type: 'show', message: 'B', owner: null })
    expect(toastReducer(second, { type: 'clear', owner: 'collection:1' })).toBe(second)
  })
})
