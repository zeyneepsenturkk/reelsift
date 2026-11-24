import { useEffect, useRef } from 'react'
import type { Collection } from '../api/types.ts'
import { actionsLayout, type PublishStep } from '../lib/publish.ts'

type Props = {
  collection: Collection
  publishStep: PublishStep
  onCopyLink: () => void
  onAskPublish: () => void
  onCancelPublish: () => void
  onPublish: () => void
}

// Onaylı seçkinin düğme alanı. Yayın kapalıyken ve adres yokken bugünkü iki düğme aynen kalır;
// yayın açıksa "Sitede yayınla" (iki adımlı onayla), yayınlanmışsa "Sitede aç" bağlantısı gelir.
export function ApprovedActions({ collection, publishStep, onCopyLink, onAskPublish, onCancelPublish, onPublish }: Props) {
  const layout = actionsLayout(collection)
  const askRef = useRef<HTMLButtonElement>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const siteRef = useRef<HTMLAnchorElement>(null)
  const previous = useRef<PublishStep>(publishStep)

  // Odak: onay açılınca en az zararlı seçenekte ("Vazgeç"); kapanınca düğmenin kendisine ya da yeni "Sitede aç" bağlantısına.
  useEffect(() => {
    const before = previous.current
    previous.current = publishStep
    if (publishStep === 'confirm') cancelRef.current?.focus()
    else if (publishStep === 'idle' && before !== 'idle') (siteRef.current ?? askRef.current)?.focus()
  }, [publishStep])

  useEffect(() => {
    if (publishStep !== 'confirm') return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCancelPublish()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [publishStep, onCancelPublish])

  const pageLink = (
    <a className="btn" href={collection.share_url ?? '#'} target="_blank" rel="noopener noreferrer">
      Sayfayı aç
    </a>
  )

  if (layout === 'share-only') {
    return (
      <>
        {pageLink}
        <button className="btn primary" onClick={onCopyLink}>
          Paylaşım linkini kopyala
        </button>
      </>
    )
  }

  const copyLink = (
    <button className="btn" onClick={onCopyLink}>
      Paylaşım linkini kopyala
    </button>
  )

  if (layout === 'published') {
    return (
      <>
        {pageLink}
        {copyLink}
        <a ref={siteRef} className="btn primary" href={collection.published_url ?? '#'} target="_blank" rel="noopener noreferrer">
          Sitede aç
        </a>
      </>
    )
  }

  if (publishStep === 'idle') {
    return (
      <>
        {pageLink}
        {copyLink}
        <button ref={askRef} className="btn primary" onClick={onAskPublish}>
          Sitede yayınla
        </button>
      </>
    )
  }

  const publishing = publishStep === 'publishing'
  return (
    <div className="publish-confirm" role="group" aria-labelledby="publish-note">
      <p className="note" id="publish-note">
        Seçki herkese açık sitede yayınlanacak. Geri alınamaz.
      </p>
      <button className="btn primary" disabled={publishing} onClick={onPublish}>
        {publishing ? 'Yayınlanıyor…' : 'Evet, yayınla'}
      </button>
      <button ref={cancelRef} className="btn" disabled={publishing} onClick={onCancelPublish}>
        Vazgeç
      </button>
    </div>
  )
}
