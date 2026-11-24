import { AnimatePresence, motion } from 'motion/react'
import type { CollectionFilm } from '../api/types.ts'
import { filmName } from '../lib/collection.ts'
import { cardCaption } from '../lib/format.ts'
import { EASE, staggerDelay } from '../lib/motion.ts'
import { Poster } from './Poster.tsx'

type Props = {
  films: CollectionFilm[]
  selectedId: number | null
  onSelect: (filmId: number) => void
  // Verilmezse (onaylı / paylaşım) kartlarda çıkar düğmesi çıkmaz.
  onRemove?: (film: CollectionFilm) => void
}

export function FilmGrid({ films, selectedId, onSelect, onRemove }: Props) {
  if (films.length === 0) {
    return <p className="no-films">Taslakta film kalmadı. Sohbetten yeni bir arama isteyebilirsin.</p>
  }
  return (
    <div className="films">
      <AnimatePresence mode="popLayout">
        {films.map((film, index) => {
          const name = filmName(film)
          return (
            // Dış sarmalayıcı yerleşimi (komşular kayarak yer değiştirir) ve çıkışı yönetir; kart ilk çizimde belirir.
            <motion.div
              key={film.film_id}
              layout="position"
              exit={{ opacity: 0, scale: 0.86 }}
              transition={{ duration: 0.35, ease: EASE }}
            >
              <motion.div
                className={`card${film.film_id === selectedId ? ' sel' : ''}`}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35, ease: EASE, delay: staggerDelay(index) }}
              >
                <button
                  className="card-hit"
                  aria-pressed={film.film_id === selectedId}
                  onClick={() => onSelect(film.film_id)}
                >
                  <Poster film={film} />
                  <span className="no">{String(index + 1).padStart(2, '0')}</span>
                  <span className="cap">
                    <b>{name}</b>
                    <small>{cardCaption(film)}</small>
                  </span>
                </button>
                {onRemove && (
                  <button
                    className="x"
                    title="Taslaktan çıkar"
                    aria-label={`${name} taslaktan çıkar`}
                    onClick={() => onRemove(film)}
                  >
                    ×
                  </button>
                )}
              </motion.div>
            </motion.div>
          )
        })}
      </AnimatePresence>
    </div>
  )
}
