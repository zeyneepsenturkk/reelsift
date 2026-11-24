import { memo, useState } from 'react'
import type { Collection, CollectionFilm, CollectionStats, MessageAction } from '../api/types.ts'
import { neighborAfterRemoval } from '../lib/collection.ts'
import { metaParts } from '../lib/format.ts'
import { actionsLayout } from '../lib/publish.ts'
import { useCollectionActions } from '../state/useCollectionActions.ts'
import { ApprovedActions } from './ApprovedActions.tsx'
import { EditableText } from './EditableText.tsx'
import { FilmDetail } from './FilmDetail.tsx'
import { FilmGrid } from './FilmGrid.tsx'

export const ATTRIBUTION =
  "Film bilgileri ve afişler TMDB'den, hikâye metinleri Wikipedia'dan. Bu ürün TMDB API'sini kullanır ancak TMDB tarafından onaylanmamıştır."

// Taslak paneli, onaylı koleksiyon sayfası ve paylaşım sayfası aynı içeriği kullanır; fark `variant`ta.
type View = { title: string; description: string; films: CollectionFilm[]; stats: CollectionStats }

export function MetaRow({ stats }: { stats: CollectionStats }) {
  return (
    <div className="meta label">
      {metaParts(stats).map((part) => (
        <span key={part.key}>
          {part.pre}
          {part.bold !== null && <b>{part.bold}</b>}
          {part.post}
        </span>
      ))}
    </div>
  )
}

export function Attribution() {
  return <p className="foot">{ATTRIBUTION}</p>
}

// Seçili film ve detayı: üç varyantta da aynı.
export function FilmSection({
  view,
  onRemove,
  onReplace,
}: {
  view: View
  onRemove?: (film: CollectionFilm) => void
  onReplace?: (film: CollectionFilm) => void
}) {
  const [picked, setPicked] = useState<number | null>(null)
  const selected = view.films.find((film) => film.film_id === picked) ?? view.films[0] ?? null

  const remove = onRemove
    ? (film: CollectionFilm) => {
        // Seçili film çıkarılırsa sıradaki seçilir (taslaktaki davranış).
        if (selected && film.film_id === selected.film_id) setPicked(neighborAfterRemoval(view.films, film.film_id))
        onRemove(film)
      }
    : undefined

  return (
    <>
      <FilmGrid films={view.films} selectedId={selected?.film_id ?? null} onSelect={setPicked} onRemove={remove} />
      {selected && <FilmDetail film={selected} onReplace={onReplace} />}
    </>
  )
}

type PanelProps = {
  collection: Collection
  onChange: (next: Collection) => void
  // Sohbetten gelen istek: "Yeniden araştır" / "Bunun yerine başkasını bul". Yoksa bu düğmeler çıkmaz.
  onAsk?: (text: string, action: MessageAction) => void
  onFull?: () => void
  onClose?: () => void
  full?: boolean
}

function DraftContentView({ collection, onChange, onAsk, onFull, onClose, full = false }: PanelProps) {
  const approved = collection.status === 'approved'
  const actions = useCollectionActions(collection, onChange)

  return (
    <>
      <div className="bar">
        <span className="state">
          <span className={approved ? 'still' : 'pulse'} />
          <span className="label">{approved ? 'kaydedildi · paylaşılabilir' : 'taslak · onay bekliyor'}</span>
          <span className="label saved" data-on={actions.savedFlash} aria-live="polite">
            {actions.savedFlash ? 'kaydedildi' : ''}
          </span>
        </span>
        {onFull && (
          <button className="icon" title="Tam ekran" aria-label="Tam ekran" aria-pressed={full} onClick={onFull}>
            ⤢
          </button>
        )}
        {onClose && (
          <button className="icon" title="Paneli kapat" aria-label="Paneli kapat" onClick={onClose}>
            ×
          </button>
        )}
      </div>
      <div className="draft-head">
        <div className="t">
          <EditableText
            as="h2"
            className="title"
            value={collection.title}
            editable={!approved}
            label="Seçki başlığı"
            onCommit={(value) => void actions.edit('title', value)}
          />
          <EditableText
            as="p"
            className="desc"
            value={collection.description}
            editable={!approved}
            label="Seçki açıklaması"
            placeholder="Bir açıklama ekle…"
            allowEmpty
            onCommit={(value) => void actions.edit('description', value)}
          />
        </div>
        <div className={`actions${approved && actionsLayout(collection) !== 'share-only' ? ' wrap' : ''}`}>
          {approved ? (
            <ApprovedActions
              collection={collection}
              publishStep={actions.publishStep}
              onCopyLink={() => void actions.copyLink()}
              onAskPublish={actions.askPublish}
              onCancelPublish={actions.cancelPublish}
              onPublish={() => void actions.publish()}
            />
          ) : (
            <>
              {onAsk && (
                <button className="btn" onClick={() => onAsk('Yeniden araştır', { type: 'research' })}>
                  Yeniden araştır
                </button>
              )}
              <button
                className="btn primary"
                disabled={actions.approving || actions.busy || collection.films.length === 0}
                onClick={() => void actions.approve()}
              >
                {actions.approving ? 'Kaydediliyor…' : 'Onayla ve kaydet'}
              </button>
            </>
          )}
        </div>
      </div>
      <MetaRow stats={collection.stats} />
      <FilmSection
        view={collection}
        onRemove={approved ? undefined : (film) => void actions.removeFilm(film)}
        onReplace={
          approved || !onAsk
            ? undefined
            : (film) =>
                onAsk(`${film.title_tr || film.title} yerine başka bir film bul`, {
                  type: 'replace_film',
                  film_id: film.film_id,
                })
        }
      />
      <Attribution />
    </>
  )
}

// Akan metin sırasında panelin (10+ kart) her parçada yeniden çizilmemesi için.
export const DraftContent = memo(DraftContentView)
