import type { CollectionFilm, CollectionStats } from '../api/types.ts'

const DATE_FORMAT = new Intl.DateTimeFormat('tr-TR', { day: 'numeric', month: 'long', year: 'numeric' })

export function formatDate(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '' : DATE_FORMAT.format(date)
}

export type MetaPart = { key: string; pre: string; bold: string | null; post: string }

// Taslaktaki meta satırı: "10 film · 2015 – 2024 · 6 ülke · ortalama oy sayısı 540". Boş değerler atlanır.
export function metaParts(stats: CollectionStats): MetaPart[] {
  const parts: MetaPart[] = [{ key: 'films', pre: '', bold: String(stats.film_count), post: ' film' }]
  if (stats.year_min !== null && stats.year_max !== null) {
    const years = stats.year_min === stats.year_max ? String(stats.year_min) : `${stats.year_min} – ${stats.year_max}`
    parts.push({ key: 'years', pre: years, bold: null, post: '' })
  }
  if (stats.country_count > 0) parts.push({ key: 'countries', pre: `${stats.country_count} ülke`, bold: null, post: '' })
  if (stats.avg_vote_count !== null) {
    parts.push({ key: 'votes', pre: 'ortalama oy sayısı ', bold: String(stats.avg_vote_count), post: '' })
  }
  return parts
}

// Izgarada kartın altı: "2023 · Kanada" (yalnız ilk ülke).
export function cardCaption(film: CollectionFilm): string {
  return [film.year, film.countries[0]].filter((part) => part !== null && part !== undefined && part !== '').join(' · ')
}

// Detayda alt satır: "2023 · Kanada · 576 oy" (bütün ülkeler).
export function detailSubline(film: CollectionFilm): string {
  const parts: (string | number)[] = []
  if (film.year !== null) parts.push(film.year)
  if (film.countries.length) parts.push(film.countries.join(' · '))
  if (film.vote_count !== null) parts.push(`${film.vote_count} oy`)
  return parts.join(' · ')
}

export type CreditRow = { label: string; names: string }

// Detayda künye: yönetmen ve oyuncu satırları; verisi olmayan satır hiç üretilmez.
export function creditRows(film: CollectionFilm): CreditRow[] {
  const rows: CreditRow[] = []
  if (film.directors.length) {
    rows.push({ label: film.directors.length > 1 ? 'yönetmenler' : 'yönetmen', names: film.directors.join(' · ') })
  }
  if (film.actors.length) rows.push({ label: 'oyuncular', names: film.actors.join(' · ') })
  return rows
}

export type StepText = { lead: string; count: string | null; rest: string }

// Taslakta sayı cümlenin içinde ve mono: "<184> aday çıktı." `count` ayrıntının başındaysa orada vurgulanır,
// değilse ayrıntının sonuna eklenir; başlık sayıyı zaten taşıyorsa ("En iyi 8'i seçtim") sona eklenmez.
export function splitStepDetail(detail: string, count: number | null, title = ''): StepText {
  if (count === null) return { lead: '', count: null, rest: detail }
  const text = String(count)
  if (detail.startsWith(text)) return { lead: '', count: text, rest: detail.slice(text.length) }
  if (count === 0) return { lead: detail, count: null, rest: '' }
  if (new RegExp(`(?<!\\d)${text}(?!\\d)`).test(title)) return { lead: detail, count: null, rest: '' }
  return { lead: detail, count: text, rest: '' }
}

// Kartlarda başlığın ":" öncesi kısa hali gösterilir ("Kendi Evinde Yabancı: Son On Yılın…" -> "Kendi Evinde Yabancı").
export function shortTitle(title: string): string {
  const head = title.split(':')[0].trim()
  return head || title
}
