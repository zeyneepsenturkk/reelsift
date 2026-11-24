import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { Link, NavLink } from 'react-router'
import { shortTitle } from '../lib/format.ts'
import { chatIndicator, type ChatView } from '../state/chatReducer.ts'
import { useAuth } from '../state/auth.tsx'
import { useLists } from '../state/lists.tsx'
import { useSessionViews } from '../state/sessions.tsx'
import { useShell } from '../state/shell.tsx'
import { Brand } from './Brand.tsx'
import { LlmSettingsDialog } from './LlmSettingsDialog.tsx'
import { Reveal } from './Reveal.tsx'

const navClass = ({ isActive }: { isActive: boolean }) => (isActive ? 'on' : '')

function UserRow() {
  const { user, signOut } = useAuth()
  const [menu, setMenu] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const items = useRef<HTMLDivElement>(null)

  // Dışarı tıklanınca kapanır; kullanıcı düğmesinin ve menünün kendi pointerdown'ı durdurulur.
  useEffect(() => {
    if (!menu) return
    const close = () => setMenu(false)
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [menu])

  // Menü açılınca odak ilk öğeye gider.
  useEffect(() => {
    if (menu) items.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus()
  }, [menu])

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      // Panelin Esc ile kapanması da dinleniyor; menüyü kapatırken panel kapanmasın.
      event.stopPropagation()
      setMenu(false)
      trigger.current?.focus()
      return
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    event.preventDefault()
    const list = [...(items.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])]
    const at = list.indexOf(document.activeElement as HTMLElement)
    const step = event.key === 'ArrowDown' ? 1 : -1
    list[(at + step + list.length) % list.length]?.focus()
  }

  if (!user) return null
  return (
    <>
    <div
      className="mt-auto"
      onKeyDown={onKeyDown}
      onBlur={(event) => {
        // Odak menüden ve düğmeden çıkarsa menü kapanır.
        if (menu && !event.currentTarget.contains(event.relatedTarget)) setMenu(false)
      }}
    >
      <button
        ref={trigger}
        className="user"
        aria-haspopup="menu"
        aria-expanded={menu}
        onPointerDown={(event) => event.stopPropagation()}
        onClick={() => setMenu((open) => !open)}
      >
        <span className="av">{user.initials}</span>
        <span className="hide block">
          {user.display_name}
          <small>editör</small>
        </span>
      </button>
      {menu && (
        <div className="usermenu" role="menu" ref={items} onPointerDown={(event) => event.stopPropagation()}>
          <button
            role="menuitem"
            onClick={() => {
              setMenu(false)
              setSettingsOpen(true)
            }}
          >
            <svg className="gear" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="3" />
              <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1" />
            </svg>
            Ayarlar
          </button>
          <button role="menuitem" onClick={() => void signOut()}>
            Çıkış yap
          </button>
        </div>
      )}
    </div>
    {settingsOpen && <LlmSettingsDialog onClose={() => { setSettingsOpen(false); trigger.current?.focus() }} />}
    </>
  )
}

const INDICATOR_LABEL = { working: 'cevap hazırlanıyor', unseen: 'yeni cevap var' }

function indicatorTitle(title: string, view: ChatView | undefined): string {
  const indicator = chatIndicator(view)
  return indicator ? `${title} (${INDICATOR_LABEL[indicator]})` : title
}

function ChatList() {
  const { chats, reloadChats } = useLists()
  const views = useSessionViews()
  if (chats.status === 'loading') {
    return (
      <div className="list" aria-busy="true">
        {[0, 1, 2, 3].map((index) => (
          <div className="skel" key={index} />
        ))}
      </div>
    )
  }
  if (chats.status === 'error' && chats.items.length === 0) {
    return (
      <p className="list-note">
        Sohbetler yüklenemedi. <button onClick={reloadChats}>Tekrar dene</button>
      </p>
    )
  }
  if (chats.items.length === 0) return <p className="list-note">Henüz sohbet yok.</p>
  return (
    <div className="list">
      {chats.items.map((chat, index) => (
        <Reveal key={chat.id} index={index}>
          <NavLink
            to={`/s/${chat.id}`}
            className={({ isActive }) => `chat-row ${isActive ? 'on' : ''}`}
            title={indicatorTitle(chat.title, views[chat.id])}
          >
            {({ isActive }) => {
              const indicator = chatIndicator(views[chat.id])
              // Açık sohbette nokta çizilmez: kullanıcı cevabı zaten görüyor (işaret `markSeen` ile de silinir).
              const shown = indicator === 'unseen' && isActive ? null : indicator
              return (
                <>
                  <span className="chat-title">{chat.title}</span>
                  {shown && (
                    <span
                      className={shown === 'working' ? 'chat-spin' : 'chat-dot'}
                      role="img"
                      aria-label={INDICATOR_LABEL[shown]}
                    />
                  )}
                </>
              )
            }}
          </NavLink>
        </Reveal>
      ))}
    </div>
  )
}

function CollectionList() {
  const { collections, reloadCollections } = useLists()
  if (collections.status === 'loading') {
    return (
      <div className="list" aria-busy="true">
        {[0, 1].map((index) => (
          <div className="skel" key={index} />
        ))}
      </div>
    )
  }
  if (collections.status === 'error' && collections.items.length === 0) {
    return (
      <p className="list-note">
        Koleksiyonlar yüklenemedi. <button onClick={reloadCollections}>Tekrar dene</button>
      </p>
    )
  }
  if (collections.items.length === 0) return <p className="list-note">Onayladığın seçkiler burada görünür.</p>
  return (
    <>
      <div className="list">
        {collections.items.slice(0, 5).map((collection, index) => (
          <Reveal key={collection.id} index={index}>
            <NavLink to={`/koleksiyon/${collection.id}`} className={navClass} title={collection.title}>
              {shortTitle(collection.title)} <small>{collection.film_count} film</small>
            </NavLink>
          </Reveal>
        ))}
      </div>
      <Link className="more" to="/koleksiyonlar">
        tümü ›
      </Link>
    </>
  )
}

export function Sidebar() {
  const { toggleSlim, panel, setPanel, compact } = useShell()

  // Tam ekranda kenar çubuğu düğmesi paneli `open` haline döndürür (taslaktaki davranış). Dar pencerede panel açıkken
  // kenar çubuğuna yer yoktur: düğme paneli kapatır, kenar çubuğu tercihine döner.
  const onToggle = () => {
    if (panel === 'full') setPanel('open')
    else if (panel === 'open' && compact) setPanel('closed')
    else toggleSlim()
  }

  return (
    <aside className="side">
      <div className="side-top">
        <Brand className="hide" />
        <button className="icon" title="Kenar çubuğunu daralt" aria-label="Kenar çubuğunu daralt" onClick={onToggle}>
          ☰
        </button>
      </div>
      <Link className="newbtn" to="/" aria-label="Yeni sohbet">
        <span>+</span>
        <b className="hide font-medium">Yeni sohbet</b>
      </Link>
      <div className="hide side-lists">
        <div className="label">sohbetler</div>
        <ChatList />
        <div className="label">koleksiyonlarım</div>
        <CollectionList />
      </div>
      <UserRow />
    </aside>
  )
}
