import { Fragment, memo } from 'react'
import type { Collection } from '../api/types.ts'
import { parseInline, splitParagraphs } from '../lib/markup.ts'
import type { ViewMessage } from '../state/chatReducer.ts'
import { CollectionCard } from './CollectionCard.tsx'
import { StepsBlock } from './StepsBlock.tsx'

type Props = {
  message: ViewMessage
  isLast: boolean
  collection: Collection | null
  // Koleksiyon kartı yalnız onu en son üreten/güncelleyen mesajda çıkar (aynı seçki için kart tekrarlanmaz).
  showCard: boolean
  collectionTick: number
  panelOpen: boolean
  chatBusy: boolean
  onToggleCard: () => void
  onChip: (text: string) => void
  onRetry: () => void
}

function Paragraph({ text, streaming, cursor }: { text: string; streaming: boolean; cursor: boolean }) {
  // Metin yalnız düz metin düğümleri ve <strong> olarak basılır; başka işaretleme yorumlanmaz.
  return (
    <p>
      {parseInline(text, streaming).map((part, index) =>
        part.strong ? <strong key={index}>{part.text}</strong> : <Fragment key={index}>{part.text}</Fragment>,
      )}
      {cursor && <span className="cursor" aria-hidden="true" />}
    </p>
  )
}

function finalSeconds(message: ViewMessage): number | null {
  if (message.duration_s !== null) return message.duration_s
  if (message.startedAt !== null && message.endedAt !== null) {
    return Math.max(1, Math.round((message.endedAt - message.startedAt) / 1000))
  }
  return null
}

function AssistantMessageView(props: Props) {
  const { message, isLast, collection, showCard, collectionTick, panelOpen, chatBusy, onToggleCard, onChip, onRetry } = props
  const streaming = message.status === 'streaming'
  const failed = message.status === 'failed'
  const paragraphs = splitParagraphs(message.text)
  const showSteps = message.timeline.length > 0 || streaming

  const head = paragraphs.slice(0, 1)
  const tail = paragraphs.slice(1)
  const cursorAt = streaming ? paragraphs.length - 1 : -1

  return (
    <div className="bot">
      {showSteps && (
        <StepsBlock
          timeline={message.timeline}
          running={streaming}
          startedAt={message.startedAt}
          finalSeconds={finalSeconds(message)}
          animate={message.startedAt !== null}
        />
      )}
      {failed ? (
        <div className="errbox" role="alert">
          <span>Bir şey ters gitti, cevabı tamamlayamadım.</span>
          {isLast && (
            <button className="btn" onClick={onRetry} disabled={chatBusy}>
              Tekrar dene
            </button>
          )}
        </div>
      ) : (
        <>
          {head.map((text, index) => (
            <Paragraph key={index} text={text} streaming={streaming} cursor={cursorAt === index} />
          ))}
          {showCard && !failed && collection && (
            <CollectionCard
              collection={collection}
              open={panelOpen}
              onToggle={onToggleCard}
              animate={streaming}
              tick={collectionTick}
            />
          )}
          {tail.map((text, index) => (
            <Paragraph key={index + 1} text={text} streaming={streaming} cursor={cursorAt === index + 1} />
          ))}
          {message.status === 'stopped' && <p className="stopped">Durduruldu.</p>}
          {isLast && message.status === 'done' && message.suggestions.length > 0 && (
            <div className="chips">
              {message.suggestions.map((text) => (
                <button key={text} className="chip" disabled={chatBusy} onClick={() => onChip(text)}>
                  {text}
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

// Her `text.delta` yalnız akan mesajı yeniden çizsin (diğer mesajların props'u değişmez).
export const AssistantMessage = memo(AssistantMessageView)
