import { Link } from 'react-router'
import { MetaLine } from '../components/MetaLine.tsx'
import { Reveal } from '../components/Reveal.tsx'
import { StripPosters } from '../components/StripPosters.tsx'
import { formatDate, shortTitle } from '../lib/format.ts'
import { useLists } from '../state/lists.tsx'
import { useShell } from '../state/shell.tsx'
import { useEffect } from 'react'

export default function CollectionsPage() {
  const { collections, reloadCollections } = useLists()
  const { setPanel } = useShell()
  useEffect(() => setPanel('closed'), [setPanel])
  const { status, items } = collections

  return (
    <main className="page">
      <div className="page-in">
        <div className="page-head">
          <h1 className="title">Koleksiyonlarım</h1>
          {status === 'ready' && <span className="label">{items.length} seçki</span>}
        </div>
        {status === 'loading' && (
          <div className="coll-grid" aria-busy="true">
            {[0, 1, 2].map((index) => (
              <div className="skel skel-card" key={index} />
            ))}
          </div>
        )}
        {status === 'error' && items.length === 0 && (
          <div className="center-msg">
            <p>Koleksiyonlar yüklenemedi.</p>
            <button className="btn" onClick={reloadCollections}>
              Tekrar dene
            </button>
          </div>
        )}
        {status === 'ready' && items.length === 0 && (
          <div className="center-msg">
            <p>Henüz onaylanmış bir seçkin yok.</p>
            <Link className="btn" to="/">
              Yeni sohbet
            </Link>
          </div>
        )}
        {items.length > 0 && (
          <div className="coll-grid">
            {items.map((collection, index) => (
              <Reveal key={collection.id} index={index}>
                <Link className="ccard big" to={`/koleksiyon/${collection.id}`}>
                  <StripPosters urls={collection.poster_urls} />
                  <span className="ct">
                    <b>{shortTitle(collection.title)}</b>
                    <MetaLine parts={[`${collection.film_count} film`, formatDate(collection.approved_at ?? collection.updated_at)]} />
                  </span>
                </Link>
              </Reveal>
            ))}
          </div>
        )}
      </div>
    </main>
  )
}
