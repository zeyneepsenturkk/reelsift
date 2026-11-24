import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router'
import type { Collection, MessageAction } from '../api/types.ts'
import { ChatInput } from '../components/ChatInput.tsx'
import { DraftContent } from '../components/DraftContent.tsx'
import { MessageList } from '../components/MessageList.tsx'
import { unansweredLastMessage } from '../state/chatReducer.ts'
import { useChatView, useSessionActions } from '../state/sessions.tsx'
import { useShell } from '../state/shell.tsx'
import { useToast } from '../state/toast.tsx'

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <main className="chat solo">
      <div className="center-msg">{children}</div>
    </main>
  )
}

export default function ChatPage() {
  const params = useParams()
  const chatId = Number(params.chatId)
  const validId = Number.isInteger(chatId)
  const view = useChatView(validId ? chatId : null)
  const actions = useSessionActions()
  const { panel, setPanel } = useShell()
  const toast = useToast()
  const [sendTick, setSendTick] = useState(0)
  const panelRef = useRef(panel)
  panelRef.current = panel

  useEffect(() => {
    if (validId) actions.ensureLoaded(chatId)
  }, [chatId, validId, actions])

  // Sohbet ekrandayken biten (ya da ekrana gelen) cevap görülmüş sayılır; kenar çubuğunda nokta kalmaz.
  const unseen = view?.unseen ?? false
  useLayoutEffect(() => {
    if (unseen) actions.markSeen(chatId)
  }, [unseen, chatId, actions])

  // Başka sohbete ya da sayfaya geçince panel kapalı başlar.
  useEffect(() => {
    setPanel('closed')
    return () => setPanel('closed')
  }, [chatId, setPanel])

  // İlk `collection` olayında panel kendiliğinden açılır; sonraki güncellemelerde açılmaz.
  const autoOpen = view?.autoOpen ?? false
  useEffect(() => {
    if (!autoOpen) return
    setPanel('open')
    actions.ackAutoOpen(chatId)
  }, [autoOpen, chatId, actions, setPanel])

  // Panel kapanırken odak, paneli açan öğeye (sohbetteki koleksiyon kartı) döner; yoksa gövdeye düşerdi.
  const closePanel = useCallback(() => {
    document.querySelector<HTMLElement>('.stream .ccard')?.focus()
    setPanel('closed')
  }, [setPanel])

  // Esc paneli kapatır (tam ekrandaysa önce `open`a döner). Düzenleme alanı Esc'i kendi tüketir.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return
      if (panelRef.current === 'full') setPanel('open')
      else if (panelRef.current === 'open') closePanel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setPanel, closePanel])

  const send = useCallback(
    (text: string, action?: MessageAction) => {
      setSendTick((tick) => tick + 1)
      actions.send(chatId, text, action)
    },
    [actions, chatId],
  )

  const onCollectionChange = useCallback(
    (next: Collection) => actions.setCollection(chatId, next),
    [actions, chatId],
  )

  // Aşağıdaki geri çağrılar sabit tutulur: akan metinde yalnız akan mesaj yeniden çizilsin (memo).
  const streaming = view?.streaming ?? false
  const onChip = useCallback((text: string) => send(text), [send])
  const onRetry = useCallback(() => actions.retry(chatId), [actions, chatId])
  const onRetryUnanswered = useCallback(() => actions.retryUnanswered(chatId), [actions, chatId])
  const onToggleCard = useCallback(() => setPanel(panelRef.current === 'closed' ? 'open' : 'closed'), [setPanel])
  const onFull = useCallback(() => setPanel(panelRef.current === 'full' ? 'open' : 'full'), [setPanel])
  const onClose = closePanel
  const ask = useCallback(
    (text: string, action: MessageAction) => {
      if (streaming) return toast('Cevap sürerken yeni istek gönderemem; bitmesini bekle.')
      if (panelRef.current === 'full') setPanel('open')
      send(text, action)
    },
    [streaming, toast, setPanel, send],
  )

  if (!validId || view?.phase === 'missing') {
    return (
      <Centered>
        <p>Bu sohbet bulunamadı.</p>
        <Link className="btn" to="/">
          Yeni sohbet
        </Link>
      </Centered>
    )
  }
  if (!view || view.phase === 'loading') {
    return (
      <main className="chat solo">
        <div className="stream" aria-busy="true">
          <div className="col">
            <div className="skel skel-bubble w-[58%] self-end" />
            <div className="skel skel-bubble w-[82%]" />
          </div>
        </div>
      </main>
    )
  }
  if (view.phase === 'error') {
    return (
      <Centered>
        <p>Sohbet yüklenemedi.</p>
        <button className="btn" onClick={() => actions.ensureLoaded(chatId)}>
          Tekrar dene
        </button>
      </Centered>
    )
  }

  const collection = view.collection
  return (
    <>
      <main className="chat">
        <h1 className="sr-only">{view.title || 'Sohbet'}</h1>
        <MessageList
          messages={view.messages}
          collection={collection}
          collectionTick={view.collectionTick}
          panelOpen={panel !== 'closed'}
          busy={view.streaming}
          sendTick={sendTick}
          onToggleCard={onToggleCard}
          onChip={onChip}
          onRetry={onRetry}
          unanswered={unansweredLastMessage(view) !== null}
          onRetryUnanswered={onRetryUnanswered}
        />
        <div className="composer">
          <ChatInput
            placeholder="Taslağı değiştir ya da bir film hakkında sor…"
            streaming={view.streaming}
            onStop={() => actions.stop(chatId)}
            onSend={(text) => send(text)}
          />
          <div className="hint">Cevaplar arşivdeki kaynaklara dayanır. Son karar senin.</div>
        </div>
      </main>
      <section className="draft" inert={panel === 'closed'} aria-label="Taslak paneli">
        {collection && (
          <div className="draft-in">
            <DraftContent
              collection={collection}
              onChange={onCollectionChange}
              onAsk={ask}
              full={panel === 'full'}
              onFull={onFull}
              onClose={onClose}
            />
          </div>
        )}
      </section>
    </>
  )
}
