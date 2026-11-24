import { useEffect, useState } from 'react'
import { useParams } from 'react-router'
import { ApiError } from '../api/errors.ts'
import { api } from '../api/index.ts'
import type { SharedCollection } from '../api/types.ts'
import { Brand } from '../components/Brand.tsx'
import { Attribution, FilmSection, MetaRow } from '../components/DraftContent.tsx'
import { formatDate } from '../lib/format.ts'

type State = { phase: 'loading' } | { phase: 'missing' } | { phase: 'error' } | { phase: 'ready'; shared: SharedCollection }

// Girişsiz, salt okunur paylaşım sayfası; kenar çubuğu yok.
export default function SharePage() {
  const { token = '' } = useParams()
  const [state, setState] = useState<State>({ phase: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    setState({ phase: 'loading' })
    api
      .getShared(token)
      .then((shared) => !cancelled && setState({ phase: 'ready', shared }))
      .catch((error: unknown) => {
        if (!cancelled) setState({ phase: error instanceof ApiError && error.status === 404 ? 'missing' : 'error' })
      })
    return () => {
      cancelled = true
    }
  }, [token, attempt])

  const shared = state.phase === 'ready' ? state.shared : null
  return (
    <div className="share">
      <header className="share-bar">
        <Brand />
        {shared && (
          <span className="label">
            {shared.owner_display_name} · {formatDate(shared.approved_at)}
          </span>
        )}
      </header>
      <main className="share-col">
        {state.phase === 'loading' && (
          <div aria-busy="true">
            <div className="skel h-10 w-3/5" />
            <div className="skel mt-4 h-5 w-2/5" />
            <div className="films mt-8">
              {[0, 1, 2, 3, 4].map((index) => (
                <div className="skel aspect-[2/3]" key={index} />
              ))}
            </div>
          </div>
        )}
        {state.phase === 'missing' && (
          <div className="center-msg">
            <p>Bu seçki bulunamadı ya da artık paylaşılmıyor.</p>
          </div>
        )}
        {state.phase === 'error' && (
          <div className="center-msg">
            <p>Seçki yüklenemedi.</p>
            <button className="btn" onClick={() => setAttempt((count) => count + 1)}>
              Tekrar dene
            </button>
          </div>
        )}
        {shared && (
          <>
            <h1 className="title">{shared.title}</h1>
            {shared.description && <p className="desc">{shared.description}</p>}
            <MetaRow stats={shared.stats} />
            <FilmSection view={shared} />
            <Attribution />
          </>
        )}
      </main>
    </div>
  )
}
