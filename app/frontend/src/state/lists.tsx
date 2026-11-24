import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '../api/index.ts'
import type { ChatSummary, CollectionSummary } from '../api/types.ts'

type Loadable<T> = { status: 'loading' | 'ready' | 'error'; items: T[] }

type ListsValue = {
  chats: Loadable<ChatSummary>
  collections: Loadable<CollectionSummary>
  reloadChats: () => void
  reloadCollections: () => void
  upsertChat: (chat: ChatSummary) => void
}

const ListsContext = createContext<ListsValue | null>(null)

// Kenar çubuğundaki sohbet ve koleksiyon listeleri; giriş yapıldığında bir kez yüklenir.
export function ListsProvider({ children }: { children: ReactNode }) {
  const [chats, setChats] = useState<Loadable<ChatSummary>>({ status: 'loading', items: [] })
  const [collections, setCollections] = useState<Loadable<CollectionSummary>>({ status: 'loading', items: [] })

  const reloadChats = useCallback(() => {
    setChats((current) => ({ ...current, status: current.items.length ? current.status : 'loading' }))
    api
      .listChats()
      .then((items) => setChats({ status: 'ready', items }))
      .catch(() => setChats((current) => ({ ...current, status: 'error' })))
  }, [])

  const reloadCollections = useCallback(() => {
    setCollections((current) => ({ ...current, status: current.items.length ? current.status : 'loading' }))
    api
      .listCollections()
      .then((items) => setCollections({ status: 'ready', items }))
      .catch(() => setCollections((current) => ({ ...current, status: 'error' })))
  }, [])

  useEffect(() => {
    reloadChats()
    reloadCollections()
  }, [reloadChats, reloadCollections])

  // Yeni ya da başlığı değişen sohbet listenin başına gelir.
  const upsertChat = useCallback((chat: ChatSummary) => {
    setChats((current) => ({
      status: 'ready',
      items: [chat, ...current.items.filter((item) => item.id !== chat.id)],
    }))
  }, [])

  const value = useMemo(
    () => ({ chats, collections, reloadChats, reloadCollections, upsertChat }),
    [chats, collections, reloadChats, reloadCollections, upsertChat],
  )
  return <ListsContext.Provider value={value}>{children}</ListsContext.Provider>
}

export function useLists(): ListsValue {
  const value = useContext(ListsContext)
  if (!value) throw new Error('ListsProvider eksik')
  return value
}
