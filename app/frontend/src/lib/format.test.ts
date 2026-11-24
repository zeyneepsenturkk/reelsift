import { describe, expect, it } from 'vitest'
import type { CollectionFilm, CollectionStats } from '../api/types.ts'
import { cardCaption, creditRows, detailSubline, formatDate, metaParts, shortTitle, splitStepDetail } from './format.ts'

const film = (patch: Partial<CollectionFilm> = {}): CollectionFilm => ({
  film_id: 1,
  position: 1,
  title: 'Red Rooms',
  title_tr: null,
  year: 2023,
  countries: ['Kanada', 'Fransa'],
  vote_count: 576,
  directors: [],
  actors: [],
  poster_url: null,
  rationale: '',
  source_quote: '',
  quote_source: null,
  sources: [],
  ...patch,
})

describe('metaParts', () => {
  it('taslaktaki dört değeri üretir', () => {
    const stats: CollectionStats = { film_count: 10, year_min: 2015, year_max: 2024, country_count: 6, avg_vote_count: 540 }
    expect(metaParts(stats)).toEqual([
      { key: 'films', pre: '', bold: '10', post: ' film' },
      { key: 'years', pre: '2015 – 2024', bold: null, post: '' },
      { key: 'countries', pre: '6 ülke', bold: null, post: '' },
      { key: 'votes', pre: 'ortalama oy sayısı ', bold: '540', post: '' },
    ])
  })

  it('bilinmeyen değerleri atlar, tek yılı aralık yapmaz', () => {
    const stats: CollectionStats = { film_count: 1, year_min: 2020, year_max: 2020, country_count: 0, avg_vote_count: null }
    expect(metaParts(stats).map((part) => part.key)).toEqual(['films', 'years'])
    expect(metaParts(stats)[1].pre).toBe('2020')
  })

  it('film kalmayınca yalnız sayıyı verir', () => {
    const stats: CollectionStats = { film_count: 0, year_min: null, year_max: null, country_count: 0, avg_vote_count: null }
    expect(metaParts(stats)).toHaveLength(1)
  })
})

describe('cardCaption ve detailSubline', () => {
  it('kartta yalnız ilk ülkeyi, detayda hepsini ve oyu yazar', () => {
    expect(cardCaption(film())).toBe('2023 · Kanada')
    expect(detailSubline(film())).toBe('2023 · Kanada · Fransa · 576 oy')
  })

  it('eksik alanlarda boş parça bırakmaz', () => {
    const bare = film({ year: null, countries: [], vote_count: null })
    expect(cardCaption(bare)).toBe('')
    expect(detailSubline(bare)).toBe('')
  })
})

describe('creditRows', () => {
  it('iki satır: tek yönetmende "yönetmen", oyuncular " · " ile', () => {
    expect(creditRows(film({ directors: ['Zeki Demirkubuz'], actors: ['Haluk Bilginer', 'Derya Alabora'] }))).toEqual([
      { label: 'yönetmen', names: 'Zeki Demirkubuz' },
      { label: 'oyuncular', names: 'Haluk Bilginer · Derya Alabora' },
    ])
  })

  it('birden çok yönetmende "yönetmenler"', () => {
    expect(creditRows(film({ directors: ['A', 'B'] }))).toEqual([{ label: 'yönetmenler', names: 'A · B' }])
  })

  it('yalnız yönetmen varsa oyuncu satırı üretilmez', () => {
    expect(creditRows(film({ directors: ['A'], actors: [] })).map((row) => row.label)).toEqual(['yönetmen'])
  })

  it('hiçbiri yoksa satır yok', () => {
    expect(creditRows(film())).toEqual([])
  })
})

describe('splitStepDetail', () => {
  it('sayı ayrıntının başındaysa orada vurgulanır', () => {
    expect(splitStepDetail('184 aday çıktı.', 184)).toEqual({ lead: '', count: '184', rest: ' aday çıktı.' })
    expect(splitStepDetail("31'i gerçekten bu havayı taşıyor.", 31)).toEqual({
      lead: '',
      count: '31',
      rest: "'i gerçekten bu havayı taşıyor.",
    })
  })

  it('sayı başta değilse ayrıntının sonuna eklenir', () => {
    expect(splitStepDetail('aday çıktı.', 184)).toEqual({ lead: 'aday çıktı.', count: '184', rest: '' })
  })

  it('sayı başlıkta zaten yazıyorsa sondaki tekrar çizilmez', () => {
    expect(splitStepDetail('ve her biri için nedenini yazdım.', 8, "En iyi 8'i seçtim")).toEqual({
      lead: 've her biri için nedenini yazdım.',
      count: null,
      rest: '',
    })
    expect(splitStepDetail('aday çıktı.', 184, 'Arşivde dolaştım.')).toEqual({
      lead: 'aday çıktı.',
      count: '184',
      rest: '',
    })
    expect(splitStepDetail('aday çıktı.', 8, 'Toplam 18 film')).toEqual({ lead: 'aday çıktı.', count: '8', rest: '' })
  })

  it('sayı 0 ve ayrıntı sayıyla başlamıyorsa sayı hiç çizilmez', () => {
    expect(splitStepDetail('Seçkideki filmler aynı kaldı.', 0)).toEqual({
      lead: 'Seçkideki filmler aynı kaldı.',
      count: null,
      rest: '',
    })
    expect(splitStepDetail('aday çıktı.', 184)).toEqual({ lead: 'aday çıktı.', count: '184', rest: '' })
  })

  it('sayı yoksa ayrıntı olduğu gibi kalır', () => {
    expect(splitStepDetail('ve her biri için nedenini yazdım.', null)).toEqual({
      lead: '',
      count: null,
      rest: 've her biri için nedenini yazdım.',
    })
  })
})

describe('shortTitle', () => {
  it('iki nokta öncesini verir', () => {
    expect(shortTitle('Kendi Evinde Yabancı: Son On Yılın Gölgede Kalmış Gerilimleri')).toBe('Kendi Evinde Yabancı')
  })
  it('iki nokta yoksa ya da baş boşsa başlığın tamamını verir', () => {
    expect(shortTitle('Karda Kaybolanlar')).toBe('Karda Kaybolanlar')
    expect(shortTitle(': yalnız')).toBe(': yalnız')
  })
})

describe('formatDate', () => {
  it('Türkçe uzun tarih üretir', () => {
    expect(formatDate('2026-11-14T12:00:00Z')).toBe('14 Kasım 2026')
  })
  it('bozuk tarihte boş döner', () => {
    expect(formatDate('yarın')).toBe('')
  })
})
