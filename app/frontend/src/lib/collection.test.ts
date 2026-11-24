import { describe, expect, it } from 'vitest'
import type { CollectionFilm } from '../api/types.ts'
import { computeStats, filmName, neighborAfterRemoval, withoutFilm } from './collection.ts'

const film = (id: number, patch: Partial<CollectionFilm> = {}): CollectionFilm => ({
  film_id: id,
  position: id,
  title: `Film ${id}`,
  title_tr: null,
  year: 2020 + id,
  countries: ['ABD'],
  vote_count: 100 * id,
  directors: [],
  actors: [],
  poster_url: null,
  rationale: '',
  source_quote: '',
  quote_source: null,
  sources: [],
  ...patch,
})

describe('computeStats', () => {
  it('yıl aralığı, ülke sayısı ve ortalama oyu hesaplar', () => {
    const films = [film(1, { countries: ['ABD', 'Fransa'] }), film(2), film(3, { countries: ['Kanada'] })]
    expect(computeStats(films)).toEqual({
      film_count: 3,
      year_min: 2021,
      year_max: 2023,
      country_count: 3,
      avg_vote_count: 200,
    })
  })

  it('boş listede boş değerler verir', () => {
    expect(computeStats([])).toEqual({ film_count: 0, year_min: null, year_max: null, country_count: 0, avg_vote_count: null })
  })

  it('yıl ve oyu bilinmeyen filmleri hesaba katmaz', () => {
    const stats = computeStats([film(1, { year: null, vote_count: null }), film(2)])
    expect(stats.year_min).toBe(2022)
    expect(stats.avg_vote_count).toBe(200)
  })
})

describe('withoutFilm', () => {
  it('filmi çıkarır, sırayı yeniden numaralar ve sayıyı günceller', () => {
    const collection = { films: [film(1), film(2), film(3)], stats: computeStats([film(1), film(2), film(3)]) }
    const next = withoutFilm(collection, 2)
    expect(next.films.map((f) => [f.film_id, f.position])).toEqual([[1, 1], [3, 2]])
    expect(next.stats.film_count).toBe(2)
  })

  it('olmayan filmde listeyi değiştirmez', () => {
    const collection = { films: [film(1)], stats: computeStats([film(1)]) }
    expect(withoutFilm(collection, 99).films).toHaveLength(1)
  })
})

describe('neighborAfterRemoval', () => {
  const films = [film(1), film(2), film(3)]
  it('sıradaki filmi seçer', () => {
    expect(neighborAfterRemoval(films, 2)).toBe(3)
  })
  it('sonuncuysa öncekine düşer', () => {
    expect(neighborAfterRemoval(films, 3)).toBe(2)
  })
  it('tek film ya da bilinmeyen film için null verir', () => {
    expect(neighborAfterRemoval([film(1)], 1)).toBeNull()
    expect(neighborAfterRemoval(films, 99)).toBeNull()
  })
})

describe('filmName', () => {
  it('Türkçe ad varsa onu, yoksa orijinali verir', () => {
    expect(filmName({ title: 'Swallow', title_tr: 'Saplantı' })).toBe('Saplantı')
    expect(filmName({ title: 'Red Rooms', title_tr: null })).toBe('Red Rooms')
    expect(filmName({ title: 'Red Rooms', title_tr: '' })).toBe('Red Rooms')
  })
})
