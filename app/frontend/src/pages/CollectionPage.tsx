import { useCallback, useEffect, useState } from 'react'
import { Link, Navigate, useParams } from 'react-router'
import { ApiError } from '../api/errors.ts'
import { api } from '../api/index.ts'
import type { Collection } from '../api/types.ts'
import { DraftContent } from '../components/DraftContent.tsx'
import { useShell } from '../state/shell.tsx'

type State = { phase: 'loading' } | { phase: 'missing' } | { phase: 'error' } | { phase: 'ready'; collection: Collection }

export default function CollectionPage() {
  const id = Number(useParams().id)
  const { setPanel } = useShell()
  const [state, setState] = useState<State>({ phase: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => setPanel('closed'), [setPanel])

  useEffect(() => {
    if (!Number.isInteger(id)) return setState({ phase: 'missing' })
    let cancelled = false
    setState({ phase: 'loading' })
    api
      .getCollection(id)
      .then((collection) => !cancelled && setState({ phase: 'ready', collection }))
      .catch((error: unknown) => {
        if (!cancelled) setState({ phase: error instanceof ApiError && error.status === 404 ? 'missing' : 'error' })
      })
    return () => {
      cancelled = true
    }
  }, [id, attempt])

  const onChange = useCallback((collection: Collection) => setState({ phase: 'ready', collection }), [])

  // Henüz onaylanmamış taslak kendi sohbetinde düzenlenir.
  if (state.phase === 'ready' && state.collection.status === 'draft' && state.collection.chat_id !== null) {
    return <Navigate to={`/s/${state.collection.chat_id}`} replace />
  }

  return (
    <main className="page">
      <div className="page-in">
        <Link className="back" to="/koleksiyonlar">
          ‹ Koleksiyonlarım
        </Link>
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
            <p>Bu koleksiyon bulunamadı.</p>
          </div>
        )}
        {state.phase === 'error' && (
          <div className="center-msg">
            <p>Koleksiyon yüklenemedi.</p>
            <button className="btn" onClick={() => setAttempt((count) => count + 1)}>
              Tekrar dene
            </button>
          </div>
        )}
        {state.phase === 'ready' && (
          <>
            <h1 className="sr-only">{state.collection.title}</h1>
            <DraftContent collection={state.collection} onChange={onChange} />
          </>
        )}
      </div>
    </main>
  )
}
