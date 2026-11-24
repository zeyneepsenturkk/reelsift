import { useEffect, useLayoutEffect, useRef } from 'react'
import type { Collection } from '../api/types.ts'
import type { ViewMessage } from '../state/chatReducer.ts'
import { AssistantMessage } from './AssistantMessage.tsx'

type Props = {
  messages: ViewMessage[]
  collection: Collection | null
  collectionTick: number
  panelOpen: boolean
  busy: boolean
  // Kullanıcı yeni mesaj gönderince sayfa zorla en alta iner; sayaç artınca tetiklenir.
  sendTick: number
  onToggleCard: () => void
  onChip: (text: string) => void
  onRetry: () => void
  // Son kullanıcı mesajının cevabı yarıda kalmışsa altında küçük bir satır çıkar.
  unanswered: boolean
  onRetryUnanswered: () => void
}

// Kullanıcı yukarı kaydırdıysa akış sürerken zorla aşağı indirilmez.
const NEAR_BOTTOM_PX = 80

export function MessageList({ messages, collection, collectionTick, panelOpen, busy, sendTick, onToggleCard, onChip, onRetry, unanswered, onRetryUnanswered }: Props) {
  const scroller = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  const seenSend = useRef(sendTick)
  // Kendi başlattığımız yumuşak kaydırmanın ara konumları "kullanıcı yukarı çıktı" sayılmasın.
  const programmatic = useRef(false)
  const settle = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useLayoutEffect(() => {
    const el = scroller.current
    if (!el) return
    if (sendTick !== seenSend.current) {
      seenSend.current = sendTick
      stick.current = true
    }
    if (stick.current && el.scrollHeight - el.scrollTop - el.clientHeight > 1) {
      programmatic.current = true
      clearTimeout(settle.current)
      settle.current = setTimeout(() => (programmatic.current = false), 600)
      const calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      el.scrollTo({ top: el.scrollHeight, behavior: calm ? 'auto' : 'smooth' })
    }
  })

  useEffect(() => () => clearTimeout(settle.current), [])

  const onScroll = () => {
    const el = scroller.current
    if (el && !programmatic.current) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX
  }

  // Kart, seçkiyi en son üreten mesajda durur; metin gelmeden kart önde çizilip aşağı itilmesin diye
  // akan mesaj ancak ilk paragrafı geldikten sonra sahip sayılır.
  const cardOwner = collection
    ? messages.findLastIndex(
        (message) =>
          message.role === 'assistant' &&
          message.status !== 'failed' &&
          message.collection_id === collection.id &&
          (message.text.trim() !== '' || message.status !== 'streaming'),
      )
    : -1

  return (
    <div className="stream" ref={scroller} onScroll={onScroll}>
      <div className="col">
        {messages.map((message, index) =>
          message.role === 'user' ? (
            <div className="me" key={message.key}>
              {message.text}
            </div>
          ) : (
            <AssistantMessage
              key={message.key}
              message={message}
              isLast={index === messages.length - 1}
              collection={collection}
              showCard={index === cardOwner}
              collectionTick={collectionTick}
              panelOpen={panelOpen}
              chatBusy={busy}
              onToggleCard={onToggleCard}
              onChip={onChip}
              onRetry={onRetry}
            />
          ),
        )}
        {unanswered && (
          <div className="bot">
            <div className="errbox" role="status">
              <span>Bu mesajın cevabı yarıda kaldı.</span>
              <button className="btn" onClick={onRetryUnanswered} disabled={busy}>
                Tekrar dene
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
