import type { Collection, CollectionFilm, CollectionStats } from '../api/types.ts'

export function computeStats(films: CollectionFilm[]): CollectionStats {
  const years = films.map((film) => film.year).filter((year): year is number => year !== null)
  const votes = films.map((film) => film.vote_count).filter((vote): vote is number => vote !== null)
  const countries = new Set(films.flatMap((film) => film.countries))
  return {
    film_count: films.length,
    year_min: years.length ? Math.min(...years) : null,
    year_max: years.length ? Math.max(...years) : null,
    country_count: countries.size,
    avg_vote_count: votes.length ? Math.round(votes.reduce((sum, vote) => sum + vote, 0) / votes.length) : null,
  }
}

// Film çıkarma iyimser güncellemesi: yalnız sayıyı yerinde düşürür; diğer sayılar sunucudan gelen `stats` ile oturur.
export function withoutFilm<T extends { films: CollectionFilm[]; stats: CollectionStats }>(
  collection: T,
  filmId: number,
): T {
  const films = collection.films
    .filter((film) => film.film_id !== filmId)
    .map((film, index) => ({ ...film, position: index + 1 }))
  return { ...collection, films, stats: { ...collection.stats, film_count: films.length } }
}

export function filmName(film: Pick<CollectionFilm, 'title' | 'title_tr'>): string {
  return film.title_tr || film.title
}

// Seçili film çıkarılınca sıradaki seçilir; sıradaki yoksa öncekine düşülür (taslaktaki davranış).
export function neighborAfterRemoval(films: CollectionFilm[], filmId: number): number | null {
  const index = films.findIndex((film) => film.film_id === filmId)
  if (index === -1) return null
  return (films[index + 1] ?? films[index - 1])?.film_id ?? null
}

// Geç dönen cevap yeni hali geri çevirmez: eldekinden eski sürüm, onaylı hali taslağa döndüren cevap ya da
// başka bir koleksiyonun cevabı (panel bu arada başka seçkiye geçtiyse) yok sayılır.
export function acceptIncoming(
  current: Pick<Collection, 'version' | 'status'> & { id?: number },
  incoming: Pick<Collection, 'version' | 'status'> & { id?: number },
): boolean {
  if (current.id !== undefined && incoming.id !== undefined && current.id !== incoming.id) return false
  if (current.status === 'approved' && incoming.status !== 'approved') return false
  return incoming.version >= current.version
}
