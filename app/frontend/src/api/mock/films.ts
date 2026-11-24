import type { CollectionFilm } from '../types.ts'

// Örnek içerik: tasarim/taslak-v2.html'deki 10 filmlik seçki (afişler TMDB w342). Yalnız VITE_MOCK=1 ile kullanılır.
const POSTER = 'https://image.tmdb.org/t/p/w342'

type Seed = {
  id: number
  title: string
  tr: string | null
  year: number
  countries: string[]
  votes: number
  poster: string | null
  why: string
  quote: string
}

const SEEDS: Seed[] = [
  { id: 1, title: 'Red Rooms', tr: null, year: 2023, countries: ['Kanada'], votes: 576, poster: '/uBJvbf0g9rcsYElcwZCMYU0Vrj8.jpg', why: "Bir seri katil davasını takıntı haline getiren Kelly-Anne'in gerçekle fantezi arasındaki çizgiyi kaybedişi. Şiddeti göstermeden, sadece bir yüzün ifadesiyle geren nadir filmlerden.", quote: 'When reality blurs with her morbid fantasies, she goes down a dark path…' },
  { id: 2, title: 'Swallow', tr: 'Saplantı', year: 2020, countries: ['ABD', 'Fransa'], votes: 897, poster: '/40Zrwud1EVxNvcjQkotZo7jmr4L.jpg', why: 'Kusursuz görünen bir evin içinde kontrolü elinden alınan bir kadın. Gerilim bir suçtan değil, karakterin kendi bedenine yönelen dürtüsünden doğuyor.', quote: 'As her husband and his family tighten their control over her life, she must confront the dark secret behind her new obsession.' },
  { id: 3, title: 'The Wolf Hour', tr: 'Kurt Saati', year: 2019, countries: ['ABD'], votes: 140, poster: '/5SyTpTdc2cWnqHECMvI5lBxuq2Y.jpg', why: 'Tek mekân, tek karakter: evinden çıkamayan bir yazar ve kapı zilini çalan görünmeyen biri. Seçkinin en az bilinen ve en klostrofobik filmi.', quote: "When an unseen tormentor begins exploiting June's weaknesses, her insular universe begins to unravel." },
  { id: 4, title: "Mothers' Instinct", tr: 'Annelik İçgüdüsü', year: 2024, countries: ['Belçika', 'Birleşik Krallık'], votes: 725, poster: '/6EtPToJlGpjyuIxkIoztnBXYFgJ.jpg', why: 'Bir kazadan sonra iki komşunun dostluğu suçluluk ve şüpheyle çürüyor. Paranoya temasını yas üzerinden işliyor.', quote: '…guilt, suspicion and paranoia begin to unravel their sisterly bond.' },
  { id: 5, title: 'The Lesson', tr: 'Ders', year: 2023, countries: ['Almanya', 'Birleşik Krallık'], votes: 89, poster: '/o4VDbFrzujtEBmCB8UVm4kfayMN.jpg', why: 'Hayran olduğu yazarın malikânesine giren genç bir öğretmen, aile sırlarının içine çekiliyor. Yavaş ilerleyen bir zihin oyunu.', quote: '…Liam realizes that he is ensnared in a web of family secrets, resentment…' },
  { id: 6, title: 'Inside', tr: 'İçeride', year: 2023, countries: ['Belçika', 'Almanya'], votes: 571, poster: '/dXsiWJWwGwYwOQ6DfYFt5pPBMwT.jpg', why: 'Lüks bir çatı katında mahsur kalan bir sanat hırsızı. Düşman yok; sadece zaman, açlık ve yavaş yavaş çözülen bir akıl var.', quote: 'Locked inside with nothing but priceless works of art, he must use all his cunning and invention to survive.' },
  { id: 7, title: 'Sleeping Dogs', tr: 'Ölümlü Anılar', year: 2024, countries: ['ABD', 'Avustralya'], votes: 686, poster: '/5DwQhh1HvTo7edaOeMX49NUyZqy.jpg', why: 'Hafızası parçalanmış eski bir dedektif, hatırlamadığı bir davaya dönüyor. Güvenilmez anlatıcı burada bir hile değil, hastalığın kendisi.', quote: "…an ex-homicide detective with a fractured memory, is forced to revisit a case he can't remember." },
  { id: 8, title: 'Archive', tr: 'Arşiv', year: 2020, countries: ['Birleşik Krallık', 'Macaristan'], votes: 897, poster: '/hmz9ySdCqW9FiHpM9JdSCkjQzFA.jpg', why: 'Karlar içinde izole bir tesiste, ölen eşini geri getirmeye çalışan bir mühendis. Türü bilim kurgu ama derdi yas ve yalnızlık.', quote: '…he has a goal that must be hidden at all costs—being reunited with his dead wife.' },
  { id: 9, title: 'Blackwater Lane', tr: null, year: 2024, countries: ['ABD'], votes: 160, poster: '/tdUFd56CFC0o6XoAkn4WRNHwqod.jpg', why: 'Gece yolda gördüğü arabadaki kadının öldürüldüğünü öğrenen bir öğretmen, gördüklerinden emin olamamaya başlıyor.', quote: 'An American school teacher in England drives past an abandoned car late one night…' },
  { id: 10, title: 'Fair Play', tr: null, year: 2023, countries: ['ABD'], votes: 682, poster: '/btExhxzdUZoQagLaYyXgT4KgT2e.jpg', why: 'Bir terfi, nişanlı bir çifti yavaş yavaş birbirine düşman ediyor. Seçkinin en az kasvetli, en çok öfkeli filmi.', quote: "An unexpected promotion at a cutthroat hedge fund pushes a young couple's relationship to the brink…" },
  // Yedek filmler ("Bunun yerine başkasını bul" için). Afişsiz: afiş yedek görünümünü de sınar.
  { id: 11, title: 'Saint Maud', tr: null, year: 2019, countries: ['Birleşik Krallık'], votes: 420, poster: null, why: 'Örnek içerik: yalnız yedek film davranışını denemek için.', quote: '' },
  { id: 12, title: 'Relic', tr: 'Kalıntı', year: 2020, countries: ['Avustralya', 'ABD'], votes: 310, poster: null, why: 'Örnek içerik: yalnız yedek film davranışını denemek için.', quote: '' },
  { id: 13, title: 'Hagazussa', tr: null, year: 2017, countries: ['Avusturya', 'Almanya'], votes: 95, poster: null, why: 'Örnek içerik: yalnız yedek film davranışını denemek için.', quote: '' },
]

// Örnek künye (yaklaşık, yalnız arayüzü denemek için). Listede olmayan film künyesiz görünür.
const CREDITS: Record<number, { directors: string[]; actors: string[] }> = {
  1: { directors: ['Pascal Plante'], actors: ['Juliette Gariépy', 'Laurie Babin', 'Elisabeth Locas'] },
  2: { directors: ['Carlo Mirabella-Davis'], actors: ['Haley Bennett', 'Austin Stowell', 'Elizabeth Marvel', 'Denis O’Hare'] },
  3: { directors: ['Alistair Banks Griffin'], actors: ['Naomi Watts'] },
  4: { directors: ['Benoît Delhomme'], actors: ['Jessica Chastain', 'Anne Hathaway', 'Josh Charles', 'Eamon Farren', 'Kayla Fine', 'Anders Danielsen Lie'] },
  5: { directors: [], actors: [] },
}

function toFilm(seed: Seed, position: number): CollectionFilm {
  const credits = CREDITS[seed.id] ?? { directors: [], actors: [] }
  const wikipediaUrl = `https://en.wikipedia.org/wiki/${encodeURIComponent(seed.title.replaceAll(' ', '_'))}`
  return {
    film_id: seed.id,
    position,
    title: seed.title,
    title_tr: seed.tr,
    year: seed.year,
    countries: seed.countries,
    directors: credits.directors,
    actors: credits.actors,
    vote_count: seed.votes,
    poster_url: seed.poster ? POSTER + seed.poster : null,
    rationale: seed.why,
    source_quote: seed.quote,
    quote_source: seed.quote ? { kind: 'plot', label: 'Wikipedia · hikâye', url: wikipediaUrl } : null,
    sources: [
      { kind: 'wikipedia', label: 'Wikipedia · hikâye', url: wikipediaUrl },
      { kind: 'tmdb', label: 'TMDB · tanıtım', url: `https://www.themoviedb.org/search?query=${encodeURIComponent(seed.title)}` },
    ],
  }
}

export function filmsById(ids: number[]): CollectionFilm[] {
  return ids.map((id, index) => {
    const seed = SEEDS.find((candidate) => candidate.id === id)
    if (!seed) throw new Error(`Örnek film yok: ${id}`)
    return toFilm(seed, index + 1)
  })
}

export const MAIN_SELECTION = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
export const SPARE_SELECTION = [11, 12, 13]
