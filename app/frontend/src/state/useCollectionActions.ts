import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { api } from '../api/index.ts'
import { ApiError } from '../api/errors.ts'
import type { Collection, CollectionFilm } from '../api/types.ts'
import { acceptIncoming, filmName, withoutFilm } from '../lib/collection.ts'
import { newPending, runOptimistic } from '../lib/optimistic.ts'
import { publishErrorMessage, publishReducer, safeSiteUrl } from '../lib/publish.ts'
import { useLists } from './lists.tsx'
import { useClearToast, useToast } from './toast.tsx'

const SAVE_FAILED = 'Kaydedilemedi, bir daha dener misin?'

// Taslak üzerindeki değişiklikler (başlık/açıklama, film çıkarma, onay). Başlık ve film çıkarma iyimserdir:
// ekran hemen güncellenir; bekleyen istekler bitince sunucuyla doğrulanmış hale oturur, hata olduysa kullanıcıya söylenir.
export function useCollectionActions(collection: Collection, onChange: (next: Collection) => void) {
  const showToast = useToast()
  const clearToast = useClearToast()
  const { reloadCollections } = useLists()
  const [savedFlash, setSavedFlash] = useState(false)
  const [approving, setApproving] = useState(false)
  const [busy, setBusy] = useState(false)
  const [publishStep, dispatchPublish] = useReducer(publishReducer, 'idle')
  const latest = useRef(collection)
  latest.current = collection
  const pending = useRef(newPending<Collection>())
  const pendingFor = useRef(collection.id)
  // Panel başka koleksiyona geçerse bekleyen işlem durumu sıfırlanır; eski koleksiyonun `confirmed`'ı yenisine yazılamaz
  // (eski çağrılar eski nesneyi tutar, `acceptIncoming` de farklı kimlikli cevabı reddeder).
  if (pendingFor.current !== collection.id) {
    pendingFor.current = collection.id
    pending.current = newPending<Collection>()
  }
  const flashTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => () => clearTimeout(flashTimer.current), [])
  // Bildirim, işlemi yapılan koleksiyona etiketlenir; panel başka koleksiyona geçer ya da kapanırsa YALNIZ o
  // etiketli bildirim kapanır (giriş/ağ hatası gibi ilgisiz bildirimler açık kalır).
  const toast = (message: string, id = latest.current.id) => showToast(message, `collection:${id}`)
  useEffect(() => {
    const owner = `collection:${collection.id}`
    return () => clearToast(owner)
  }, [collection.id, clearToast])
  useEffect(() => {
    setBusy(false)
    dispatchPublish({ type: 'reset' })
  }, [collection.id])

  const flashSaved = () => {
    setSavedFlash(true)
    clearTimeout(flashTimer.current)
    flashTimer.current = setTimeout(() => setSavedFlash(false), 2000)
  }

  // `latest` render'ı beklemeden güncellenir ki art arda gelen cevaplar doğru hale karşı karşılaştırılsın.
  const set = useCallback(
    (next: Collection) => {
      latest.current = next
      onChange(next)
    },
    [onChange],
  )

  const mutate = async (optimistic: Collection, call: () => Promise<Collection>, failure: string) => {
    const before = latest.current
    setBusy(true)
    const ok = await runOptimistic({
      before,
      optimistic,
      call,
      set,
      accept: acceptIncoming,
      current: () => latest.current,
      pending: pending.current,
      onError: (error) =>
        toast(error instanceof ApiError && error.code === 'collection_locked' ? 'Kaydedilmiş seçki değiştirilemez.' : failure),
      resync: () => api.getCollection(before.id),
    })
    setBusy(pending.current.count > 0)
    return ok
  }

  const edit = async (field: 'title' | 'description', value: string) => {
    const current = latest.current
    const ok = await mutate({ ...current, [field]: value }, () => api.updateCollection(current.id, { [field]: value }), SAVE_FAILED)
    if (ok) flashSaved()
  }

  const removeFilm = async (film: CollectionFilm) => {
    const current = latest.current
    toast(`"${filmName(film)}" taslaktan çıkarıldı`)
    await mutate(withoutFilm(current, film.film_id), () => api.removeFilm(current.id, film.film_id), 'Film çıkarılamadı, bir daha dener misin?')
  }

  const approve = async () => {
    // Bekleyen başlık/film isteği varken onay gönderilmez; kullanıcının görmediği hal onaylanmasın.
    if (approving || pending.current.count > 0) return
    setApproving(true)
    try {
      const next = await api.approveCollection(latest.current.id)
      set(next)
      toast('Koleksiyon kaydedildi. Paylaşım sayfası hazır.')
      reloadCollections()
    } catch (error) {
      toast(
        error instanceof ApiError && error.code === 'empty_collection'
          ? 'Taslakta film yok; kaydedilecek bir şey yok.'
          : SAVE_FAILED,
      )
    } finally {
      setApproving(false)
    }
  }

  const copyLink = async () => {
    const share = latest.current.share_url
    if (!share) return
    try {
      await navigator.clipboard.writeText(new URL(share, window.location.origin).href)
      toast('Link kopyalandı.')
    } catch {
      toast('Link kopyalanamadı.')
    }
  }

  const askPublish = () => dispatchPublish({ type: 'ask' })
  const cancelPublish = () => dispatchPublish({ type: 'cancel' })

  // Yayın geri alınamaz; yalnız onay adımındaki açık tıklamadan başlar. Açılır pencere engeline takılmamak için
  // yeni sekme tıklama anında (istekten önce) boş açılır; başarıda adrese yönlendirilir, hatada kapatılır.
  const publish = async () => {
    if (publishStep !== 'confirm') return
    const target = latest.current.id
    const tab = window.open('', '_blank')
    dispatchPublish({ type: 'confirm' })
    try {
      const next = await api.publishCollection(target)
      if (latest.current.id === next.id) set(next)
      toast('Seçki sitede yayınlandı.', target)
      const url = safeSiteUrl(next.published_url)
      if (tab && !tab.closed && url) {
        tab.opener = null
        tab.location.href = url
      } else {
        tab?.close()
      }
    } catch (error) {
      tab?.close()
      toast(publishErrorMessage(error instanceof ApiError ? error.code : null), target)
    } finally {
      // Panel bu arada başka seçkiye geçtiyse durum zaten sıfırlandı; yeni seçkinin adımına dokunulmaz.
      if (latest.current.id === target) dispatchPublish({ type: 'settle' })
    }
  }

  return { savedFlash, approving, busy, publishStep, edit, removeFilm, approve, copyLink, askPublish, cancelPublish, publish }
}
