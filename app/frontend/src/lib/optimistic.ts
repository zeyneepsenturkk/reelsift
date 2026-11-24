// İyimser güncelleme: ekran hemen değişir; asıl doğru sunucunun cevabıdır.
// Bekleyen işlemler boyunca ara hallere dokunulmaz; hepsi bitince ekran sunucuyla doğrulanmış son hale oturur.
export type Pending<T> = {
  count: number
  // Sunucuyla doğrulanmış son hal: dizi başlarken eldeki hal, sonra her başarılı cevapla (daha yeni sürümse) güncellenir.
  confirmed: T | null
  failed: boolean
}

export const newPending = <T>(): Pending<T> => ({ count: 0, confirmed: null, failed: false })

type Options<T> = {
  before: T
  optimistic: T
  call: () => Promise<T>
  set: (value: T) => void
  // Ekrandaki halin yerine geçip geçmeyeceği: geç dönen eski cevap ya da onaylı hali taslağa çeviren cevap reddedilir.
  accept: (current: T, incoming: T) => boolean
  current: () => T
  pending: Pending<T>
  // Dizide hata olduysa dizi bitince bir kez çağrılır.
  onError: (error: unknown) => void
  // İsteğe bağlı: hata sonrası sunucudaki hali çekmek; başarısız olursa sessizce geçilir (ekran zaten doğrulanmış halde).
  resync?: () => Promise<T>
}

export async function runOptimistic<T>(options: Options<T>): Promise<boolean> {
  const { before, optimistic, call, set, accept, current, pending, onError, resync } = options
  if (pending.count === 0) {
    pending.confirmed = before
    pending.failed = false
  }
  set(optimistic)
  pending.count += 1
  let failure: { error: unknown } | null = null
  try {
    const incoming = await call()
    if (pending.confirmed !== null && accept(pending.confirmed, incoming)) pending.confirmed = incoming
  } catch (error) {
    pending.failed = true
    failure = { error }
  }
  pending.count -= 1

  if (pending.count === 0) {
    const confirmed = pending.confirmed
    // Hata olduysa düşenler geri gelir, başarılılar korunur; hata yoksa ekran zaten son cevaptadır.
    if (confirmed !== null && accept(current(), confirmed)) set(confirmed)
    if (pending.failed) {
      onError(failure ? failure.error : new Error('Önceki işlem başarısız oldu'))
      if (resync) {
        resync()
          .then((fresh) => accept(current(), fresh) && set(fresh))
          .catch(() => undefined)
      }
    }
  }
  return failure === null
}
