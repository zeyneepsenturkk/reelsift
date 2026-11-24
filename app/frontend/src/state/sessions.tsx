import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  type ReactNode,
} from 'react'
import { api } from '../api/index.ts'
import { ApiError, isAbort } from '../api/errors.ts'
import type { Collection, MessageAction } from '../api/types.ts'
import { useLists } from './lists.tsx'
import { sessionsReducer, unansweredLastMessage, type ChatAction, type ChatView, type SessionsState } from './chatReducer.ts'

type SessionsActions = {
  ensureLoaded: (chatId: number) => void
  startChat: (text: string) => Promise<number>
  send: (chatId: number, text: string, action?: MessageAction) => void
  stop: (chatId: number) => void
  retry: (chatId: number) => void
  retryUnanswered: (chatId: number) => void
  setCollection: (chatId: number, collection: Collection) => void
  ackAutoOpen: (chatId: number) => void
  markSeen: (chatId: number) => void
}

const ViewsContext = createContext<SessionsState>({})
const ActionsContext = createContext<SessionsActions | null>(null)

// Sohbet görünümleri ve çalışan akışlar uygulama düzeyinde tutulur: kullanıcı başka sayfaya geçse de
// cevap akmaya devam eder, yeni sohbetten `/s/:id`ye geçişte akış kesilmez.
export function SessionsProvider({ children }: { children: ReactNode }) {
  const [views, dispatch] = useReducer(sessionsReducer, {})
  const { upsertChat } = useLists()
  const viewsRef = useRef(views)
  viewsRef.current = views
  const controllers = useRef(new Map<number, AbortController>())
  const loading = useRef(new Set<number>())
  const counter = useRef(0)

  const post = useCallback(
    (chatId: number, action: ChatAction) => dispatch({ type: 'chat', chatId, action }),
    [],
  )

  const run = useCallback(
    async (chatId: number, text: string, action?: MessageAction) => {
      const controller = new AbortController()
      controllers.current.set(chatId, controller)
      const seq = ++counter.current
      post(chatId, { type: 'sendStarted', userKey: `u-${seq}`, assistantKey: `a-${seq}`, text, ...(action ? { action } : {}), now: Date.now() })
      let settled = false
      try {
        for await (const event of api.streamMessage(chatId, action ? { text, action } : { text }, controller.signal)) {
          post(chatId, { type: 'event', event, now: Date.now() })
          if (event.event === 'message.done') upsertChat(event.data.chat)
          if (event.event === 'message.done' || event.event === 'error') settled = true
        }
        if (!settled) post(chatId, { type: 'failed', detail: '', code: 'stream_closed', now: Date.now() })
      } catch (error) {
        if (isAbort(error) || controller.signal.aborted) {
          post(chatId, { type: 'stopped', now: Date.now() })
        } else {
          const code = error instanceof ApiError ? error.code : 'network_error'
          post(chatId, { type: 'failed', detail: '', code, now: Date.now() })
        }
      } finally {
        controllers.current.delete(chatId)
      }
    },
    [post, upsertChat],
  )

  const send = useCallback(
    (chatId: number, text: string, action?: MessageAction) => {
      const trimmed = text.trim()
      if (!trimmed || controllers.current.has(chatId)) return
      void run(chatId, trimmed, action)
    },
    [run],
  )

  const actions = useMemo<SessionsActions>(
    () => ({
      ensureLoaded: (chatId) => {
        const current = viewsRef.current[chatId]
        if ((current && current.phase !== 'error') || loading.current.has(chatId)) return
        loading.current.add(chatId)
        post(chatId, { type: 'loadStarted' })
        api
          .getChat(chatId)
          .then((chat) => post(chatId, { type: 'loaded', chat }))
          .catch((error: unknown) =>
            post(chatId, { type: 'loadFailed', missing: error instanceof ApiError && error.status === 404 }),
          )
          .finally(() => loading.current.delete(chatId))
      },
      startChat: async (text) => {
        const summary = await api.createChat()
        dispatch({ type: 'create', chatId: summary.id, title: summary.title })
        upsertChat(summary)
        send(summary.id, text)
        return summary.id
      },
      send,
      stop: (chatId) => controllers.current.get(chatId)?.abort(),
      retry: (chatId) => {
        const messages = viewsRef.current[chatId]?.messages ?? []
        const failedAt = messages.length - 1
        const request = messages[failedAt - 1]
        if (messages[failedAt]?.status !== 'failed' || !request?.text) return
        post(chatId, { type: 'discardFailed' })
        send(chatId, request.text, request.action)
      },
      retryUnanswered: (chatId) => {
        const view = viewsRef.current[chatId]
        const request = view && unansweredLastMessage(view)
        if (!request || controllers.current.has(chatId)) return
        post(chatId, { type: 'discardUnanswered' })
        send(chatId, request.text, request.action)
      },
      setCollection: (chatId, collection) => post(chatId, { type: 'collectionChanged', collection }),
      ackAutoOpen: (chatId) => post(chatId, { type: 'autoOpenHandled' }),
      markSeen: (chatId) => post(chatId, { type: 'markSeen' }),
    }),
    [post, send, upsertChat],
  )

  useEffect(() => {
    const active = controllers.current
    return () => active.forEach((controller) => controller.abort())
  }, [])

  return (
    <ActionsContext.Provider value={actions}>
      <ViewsContext.Provider value={views}>{children}</ViewsContext.Provider>
    </ActionsContext.Provider>
  )
}

export function useChatView(chatId: number | null): ChatView | undefined {
  const views = useContext(ViewsContext)
  return chatId === null ? undefined : views[chatId]
}

export function useSessionViews(): SessionsState {
  return useContext(ViewsContext)
}

export function useSessionActions(): SessionsActions {
  const value = useContext(ActionsContext)
  if (!value) throw new Error('SessionsProvider eksik')
  return value
}
