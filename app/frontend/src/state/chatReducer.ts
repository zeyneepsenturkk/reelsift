import type { Chat, Collection, Message, MessageAction, Step, StreamEvent } from '../api/types.ts'

export type TimelineItem = { kind: 'step'; step: Step } | { kind: 'notice'; text: string }

export type MessageStatus = 'done' | 'streaming' | 'stopped' | 'failed'

export type ViewMessage = {
  key: string
  id: number | null
  role: 'user' | 'assistant'
  text: string
  created_at: string
  timeline: TimelineItem[]
  duration_s: number | null
  collection_id: number | null
  suggestions: string[]
  error: { detail: string; code: string } | null
  status: MessageStatus
  startedAt: number | null
  endedAt: number | null
  // Kullanıcı mesajında düğmeden gelen yapılı istek; "Tekrar dene" bunu kaybetmeden yeniden gönderir.
  action?: MessageAction
}

export type ChatView = {
  phase: 'loading' | 'ready' | 'missing' | 'error'
  title: string
  messages: ViewMessage[]
  collection: Collection | null
  // Her `collection` olayında artar; kartın kısa parlaması bunu izler.
  collectionTick: number
  // Taslak paneli ilk kez kendiliğinden açılsın diye bir kez true olur.
  autoOpen: boolean
  streaming: boolean
  // Cevap, kullanıcı sohbete bakmıyorken (ya da bakıp bitmeden) bitti ve henüz görülmedi; kenar çubuğunda sarı nokta.
  unseen: boolean
}

export type ChatAction =
  | { type: 'loadStarted' }
  | { type: 'loaded'; chat: Chat }
  | { type: 'loadFailed'; missing: boolean }
  | { type: 'sendStarted'; userKey: string; assistantKey: string; text: string; action?: MessageAction; now: number }
  | { type: 'event'; event: StreamEvent; now: number }
  | { type: 'stopped'; now: number }
  | { type: 'failed'; detail: string; code: string; now: number }
  | { type: 'discardFailed' }
  | { type: 'discardUnanswered' }
  | { type: 'collectionChanged'; collection: Collection }
  | { type: 'autoOpenHandled' }
  | { type: 'markSeen' }

export const emptyView = (phase: ChatView['phase'], title = ''): ChatView => ({
  phase,
  title,
  messages: [],
  collection: null,
  collectionTick: 0,
  autoOpen: false,
  streaming: false,
  unseen: false,
})

// Kayıtlı `key: 'notice'` adımı bilgi satırıdır (noktasız, italik); diğerleri adım satırıdır.
export function stepsToTimeline(steps: Step[]): TimelineItem[] {
  return steps.map((step) => (step.key === 'notice' ? { kind: 'notice', text: step.detail } : { kind: 'step', step }))
}

export function fromMessage(message: Message): ViewMessage {
  return {
    key: `m-${message.id}`,
    id: message.id,
    role: message.role,
    text: message.text,
    created_at: message.created_at,
    timeline: stepsToTimeline(message.steps),
    duration_s: message.duration_s,
    collection_id: message.collection_id,
    suggestions: message.suggestions,
    error: message.error,
    status: message.error ? 'failed' : 'done',
    startedAt: null,
    endedAt: null,
  }
}

// Sohbet yeniden açıldığında son mesaj cevapsız bir kullanıcı mesajıysa akış yarıda kalmıştır
// (sayfa yenilendi ya da bağlantı koptu; cevap kaydedilmeden turun kaydı kesildi).
export function unansweredLastMessage(view: ChatView): ViewMessage | null {
  if (view.phase !== 'ready' || view.streaming) return null
  const lastMessage = view.messages[view.messages.length - 1]
  return lastMessage && lastMessage.role === 'user' && lastMessage.text.trim() !== '' ? lastMessage : null
}

function lastStreamingIndex(messages: ViewMessage[]): number {
  for (let index = messages.length - 1; index >= 0; index--) {
    const message = messages[index]
    if (message.role === 'assistant' && message.status === 'streaming') return index
  }
  return -1
}

function patchStreaming(view: ChatView, patch: (message: ViewMessage) => ViewMessage): ChatView {
  const index = lastStreamingIndex(view.messages)
  if (index === -1) return view
  const messages = view.messages.slice()
  messages[index] = patch(messages[index])
  return { ...view, messages }
}

function settleSteps(timeline: TimelineItem[], to: 'error' | 'drop'): TimelineItem[] {
  if (to === 'drop') {
    return timeline.filter((item) => !(item.kind === 'step' && item.step.status === 'running'))
  }
  return timeline.map((item) =>
    item.kind === 'step' && item.step.status === 'running'
      ? { kind: 'step', step: { ...item.step, status: 'error' } }
      : item,
  )
}

function applyEvent(view: ChatView, event: StreamEvent, now: number): ChatView {
  switch (event.event) {
    case 'message.start': {
      const { user_message, message_id } = event.data
      const messages = view.messages.slice()
      const assistant = lastStreamingIndex(messages)
      // Geçici kullanıcı mesajı sunucudaki kayıtla değişir; anahtar aynı kalır (yeniden çizim yok).
      const user = assistant - 1
      if (user >= 0 && messages[user].role === 'user') {
        messages[user] = { ...messages[user], id: user_message.id, created_at: user_message.created_at }
      }
      if (assistant >= 0) messages[assistant] = { ...messages[assistant], id: message_id }
      return { ...view, messages }
    }
    case 'step.start':
      return patchStreaming(view, (message) => ({
        ...message,
        timeline: [
          ...message.timeline,
          {
            kind: 'step',
            step: { key: event.data.key, status: 'running', title: event.data.title, detail: '', count: null },
          },
        ],
      }))
    case 'step.done':
      return patchStreaming(view, (message) => {
        // Aynı `key` birden çok kez gelebilir (retry): sondaki çalışan adım bitirilir.
        let target = -1
        message.timeline.forEach((item, index) => {
          if (item.kind === 'step' && item.step.status === 'running' && item.step.key === event.data.key) target = index
        })
        const done: TimelineItem = { kind: 'step', step: event.data }
        const timeline =
          target === -1
            ? [...message.timeline, done]
            : message.timeline.map((item, index) => (index === target ? done : item))
        return { ...message, timeline }
      })
    case 'notice':
      return patchStreaming(view, (message) => ({
        ...message,
        timeline: [...message.timeline, { kind: 'notice', text: event.data.text }],
      }))
    case 'text.delta':
      return patchStreaming(view, (message) => ({ ...message, text: message.text + event.data.delta }))
    case 'collection': {
      const collection = event.data
      const next = patchStreaming(view, (message) => ({ ...message, collection_id: collection.id }))
      return {
        ...next,
        collection,
        collectionTick: view.collectionTick + 1,
        autoOpen: view.collection === null ? true : view.autoOpen,
      }
    }
    case 'suggestions':
      return patchStreaming(view, (message) => ({ ...message, suggestions: event.data.items }))
    case 'message.done': {
      const { message: done, chat } = event.data
      const next = patchStreaming(view, (message) => ({
        ...message,
        id: done.id,
        text: done.text,
        created_at: done.created_at,
        // Canlı çizgideki notice'ler korunur; sunucunun adım listesi yalnız canlı adım yoksa kullanılır.
        timeline: message.timeline.some((item) => item.kind === 'step')
          ? message.timeline
          : stepsToTimeline(done.steps),
        duration_s: done.duration_s ?? (message.startedAt === null ? null : Math.round((now - message.startedAt) / 1000)),
        collection_id: done.collection_id ?? message.collection_id,
        suggestions: done.suggestions.length ? done.suggestions : message.suggestions,
        error: null,
        status: 'done',
        endedAt: now,
      }))
      return { ...next, title: chat.title, streaming: false, unseen: true }
    }
    case 'error':
      return {
        ...patchStreaming(view, (message) => ({
          ...message,
          timeline: settleSteps(message.timeline, 'error'),
          error: event.data,
          status: 'failed',
          suggestions: [],
          endedAt: now,
        })),
        streaming: false,
        unseen: true,
      }
  }
}

export function chatReducer(view: ChatView, action: ChatAction): ChatView {
  switch (action.type) {
    case 'loadStarted':
      return view.phase === 'ready' ? view : emptyView('loading', view.title)
    case 'loaded':
      return {
        ...emptyView('ready', action.chat.title),
        messages: action.chat.messages.map(fromMessage),
        collection: action.chat.collection,
      }
    case 'loadFailed':
      return emptyView(action.missing ? 'missing' : 'error')
    case 'sendStarted': {
      const user: ViewMessage = {
        key: action.userKey, id: null, role: 'user', text: action.text, created_at: new Date(action.now).toISOString(),
        timeline: [], duration_s: null, collection_id: null, suggestions: [], error: null, status: 'done', startedAt: null, endedAt: null,
        ...(action.action ? { action: action.action } : {}),
      }
      const assistant: ViewMessage = {
        key: action.assistantKey, id: null, role: 'assistant', text: '', created_at: user.created_at,
        timeline: [], duration_s: null, collection_id: null, suggestions: [], error: null, status: 'streaming', startedAt: action.now, endedAt: null,
      }
      return { ...view, phase: 'ready', messages: [...view.messages, user, assistant], streaming: true, unseen: false }
    }
    case 'event':
      return applyEvent(view, action.event, action.now)
    case 'stopped':
      return {
        ...patchStreaming(view, (message) => ({
          ...message,
          timeline: settleSteps(message.timeline, 'drop'),
          suggestions: [],
          status: 'stopped',
          endedAt: action.now,
        })),
        streaming: false,
      }
    case 'failed':
      return applyEvent(view, { event: 'error', data: { detail: action.detail, code: action.code } }, action.now)
    case 'discardFailed': {
      // "Tekrar dene": hatalı cevap ve onu doğuran kullanıcı mesajı görünümden kalkar; metin yeniden gönderilir.
      const messages = view.messages.slice()
      const last = messages[messages.length - 1]
      if (!last || last.status !== 'failed') return view
      messages.pop()
      if (messages[messages.length - 1]?.role === 'user') messages.pop()
      return { ...view, messages }
    }
    case 'discardUnanswered': {
      // Cevapsız kullanıcı mesajı görünümden kalkar; "Tekrar dene" aynı metni yeni mesaj olarak gönderir.
      if (!unansweredLastMessage(view)) return view
      return { ...view, messages: view.messages.slice(0, -1) }
    }
    case 'collectionChanged':
      return { ...view, collection: action.collection }
    case 'autoOpenHandled':
      return view.autoOpen ? { ...view, autoOpen: false } : view
    case 'markSeen':
      return view.unseen ? { ...view, unseen: false } : view
  }
}

// Kenar çubuğundaki gösterge: cevap hazırlanıyor ya da görülmemiş yeni cevap var.
export function chatIndicator(view: ChatView | undefined): 'working' | 'unseen' | null {
  if (!view) return null
  if (view.streaming) return 'working'
  return view.unseen ? 'unseen' : null
}

export type SessionsState = Record<number, ChatView>

export type SessionsAction =
  | { type: 'create'; chatId: number; title: string }
  | { type: 'chat'; chatId: number; action: ChatAction }

export function sessionsReducer(state: SessionsState, action: SessionsAction): SessionsState {
  if (action.type === 'create') return { ...state, [action.chatId]: { ...emptyView('ready', action.title) } }
  const current = state[action.chatId] ?? emptyView('loading')
  const next = chatReducer(current, action.action)
  return next === current ? state : { ...state, [action.chatId]: next }
}
