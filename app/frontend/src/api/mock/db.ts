import { computeStats } from '../../lib/collection.ts'
import { readStored } from '../../lib/storage.ts'
import type { Chat, ChatSummary, Collection, CollectionStats, Message, Step } from '../types.ts'
import { MAIN_SELECTION, filmsById } from './films.ts'

// Bellekte tutulan sahte veri tabanı; sayfa yenilenince başa döner.
export type StoredChat = {
  id: number
  title: string
  updated_at: string
  messages: Message[]
  collectionId: number | null
}

// Sahte katmanda "Sitede yayınla" varsayılan KAPALI (gerçek varsayılan gibi). Açmak için VITE_MOCK_PUBLISH=1 ya da
// localStorage `reelsift.mock.publish` = '1'; hata denemek için `reelsift.mock.publish_fail` = hata kodu.
export const MOCK_PUBLISH_KEY = 'reelsift.mock.publish'
export const MOCK_PUBLISH_FAIL_KEY = 'reelsift.mock.publish_fail'
export const mockPublishEnabled = () => import.meta.env.VITE_MOCK_PUBLISH === '1' || readStored(MOCK_PUBLISH_KEY) === '1'

export const chats = new Map<number, StoredChat>()
export const collections = new Map<number, Collection>()
export const shares = new Map<string, number>()

let nextId = 1000
export const newId = () => ++nextId

export const DRAFT_TITLE = 'Kendi Evinde Yabancı: Son On Yılın Gölgede Kalmış Gerilimleri'
export const DRAFT_DESCRIPTION =
  'Tehdidin kapıdan değil, zihnin içinden geldiği on film. Büyük gişe yapmadılar; ama izleyeni günlerce bırakmayan türden.'

// Taslaktaki meta satırının değerleri (2015 – 2024 · 6 ülke · ortalama oy 540); örnek içerik olarak sabit.
export const DRAFT_STATS: CollectionStats = { film_count: 10, year_min: 2015, year_max: 2024, country_count: 6, avg_vote_count: 540 }

export function buildCollection(init: {
  id: number
  chat_id: number | null
  title: string
  description: string
  filmIds: number[]
  status?: 'draft' | 'approved'
  updated_at: string
  token?: string
  stats?: CollectionStats
}): Collection {
  const films = filmsById(init.filmIds)
  const approved = init.status === 'approved'
  return {
    id: init.id,
    chat_id: init.chat_id,
    title: init.title,
    description: init.description,
    status: init.status ?? 'draft',
    version: 1,
    films,
    stats: init.stats ?? computeStats(films),
    share_url: approved && init.token ? `/k/${init.token}` : null,
    published_url: null,
    publish_enabled: mockPublishEnabled(),
    approved_at: approved ? init.updated_at : null,
    updated_at: init.updated_at,
  }
}

export const DONE_STEPS: Step[] = [
  { key: 'parse', status: 'done', title: 'İsteğini çözdüm.', detail: '2015 ve sonrası · az bilinen · psikolojik gerilim · kasvetli ton', count: null },
  { key: 'search', status: 'done', title: 'Arşivde dolaştım.', detail: '184 aday çıktı.', count: 184 },
  { key: 'read', status: 'done', title: 'Hikâyelerini tek tek okudum.', detail: "31'i gerçekten bu havayı taşıyor.", count: 31 },
  { key: 'select', status: 'done', title: "En iyi 10'u seçtim", detail: 've her biri için nedenini yazdım.', count: null },
]

export const OPENING_TEXT =
  'Seçki hazır. Ortak noktaları şu: hepsinde tehdit dışarıdan değil, **karakterin kendi zihninden ya da evinin içinden** geliyor.'
export const NOTES_TEXT =
  'İki not: **Fair Play** diğerlerine göre daha az kasvetli, istersen değiştiririm. **Archive** bilim kurguya kayıyor ama yalnızlık ve yas teması güçlü olduğu için aldım.'
export const FOLLOW_UPS = ['Daha karanlık olsun', 'Sadece Avrupa yapımları', "Fair Play'i değiştir"]

function plainMessage(id: number, role: 'user' | 'assistant', text: string, createdAt: string): Message {
  return { id, role, text, created_at: createdAt, steps: [], duration_s: null, collection_id: null, suggestions: [], error: null }
}

function seedChat(id: number, title: string, updatedAt: string, prompt: string, answer: string): StoredChat {
  return {
    id,
    title,
    updated_at: updatedAt,
    collectionId: null,
    messages: [plainMessage(id * 10 + 1, 'user', prompt, updatedAt), plainMessage(id * 10 + 2, 'assistant', answer, updatedAt)],
  }
}

function seed(): void {
  const draft = buildCollection({
    id: 101,
    chat_id: 1,
    title: DRAFT_TITLE,
    description: DRAFT_DESCRIPTION,
    filmIds: MAIN_SELECTION,
    updated_at: '2026-11-15T20:40:00Z',
    stats: DRAFT_STATS,
  })
  collections.set(draft.id, draft)
  chats.set(1, {
    id: 1,
    title: 'Gölgede kalmış gerilimler',
    updated_at: '2026-11-15T20:40:00Z',
    collectionId: draft.id,
    messages: [
      plainMessage(11, 'user', '2015 sonrası, çok bilinmeyen, kasvetli psikolojik gerilimlerden 10 filmlik bir seçki hazırlar mısın?', '2026-11-15T20:38:00Z'),
      {
        ...plainMessage(12, 'assistant', `${OPENING_TEXT}\n\n${NOTES_TEXT}`, '2026-11-15T20:40:00Z'),
        steps: DONE_STEPS,
        duration_s: 14,
        collection_id: draft.id,
        suggestions: FOLLOW_UPS,
      },
    ],
  })
  chats.set(2, seedChat(2, "90'lar Japon korkusu", '2026-11-14T18:10:00Z', "90'lar Japon korkusundan beş film önerir misin?", 'Bu seçkiyi birlikte kurarız; önce hangi havayı istediğini söyle.'))
  chats.set(3, seedChat(3, 'Ayrılık sonrası umut veren filmler', '2026-11-13T21:00:00Z', 'Ayrılık sonrası umut veren filmler arıyorum.', 'Hüzünlü ama sonunda ferahlatan filmleri tarayabilirim; dönem sınırı koyalım mı?'))
  chats.set(4, seedChat(4, 'Tek mekânda geçen filmler', '2026-11-12T16:30:00Z', 'Tek mekânda geçen filmler.', 'Tek mekânda geçen filmlerde gerilim genelde zamandan doğar; bunu esas alalım mı?'))
  chats.set(5, seedChat(5, 'Bu film neden bu kadar yavaş?', '2026-11-11T09:20:00Z', 'Bu film neden bu kadar yavaş?', 'Yavaşlık çoğu zaman bilinçli bir tercihtir; hangi filmden söz ettiğini yazarsan bakarım.'))

  const snow = buildCollection({ id: 201, chat_id: null, title: 'Karda Kaybolanlar', description: 'Karın sustuğu, insanın kendiyle kaldığı filmler.', filmIds: [8, 3, 2, 5, 1, 4, 6, 7, 9, 10], status: 'approved', updated_at: '2026-11-14T12:00:00Z', token: 'karda-kaybolanlar-7k2q' })
  const summer = buildCollection({ id: 202, chat_id: null, title: 'Yaz Sonu Hüznü', description: 'Bir mevsimin bitişini anlatan sakin filmler.', filmIds: [4, 6, 2, 9, 7, 5, 10, 1], status: 'approved', updated_at: '2026-11-10T09:00:00Z', token: 'yaz-sonu-huznu-4m9d' })
  for (const collection of [snow, summer]) {
    collections.set(collection.id, collection)
    shares.set((collection.share_url ?? '').slice('/k/'.length), collection.id)
  }
}
seed()

export function summaryOf(chat: StoredChat): ChatSummary {
  return { id: chat.id, title: chat.title, updated_at: chat.updated_at }
}

export function chatDetail(chat: StoredChat): Chat {
  const collection = chat.collectionId === null ? null : (collections.get(chat.collectionId) ?? null)
  return { ...summaryOf(chat), messages: chat.messages, collection }
}
