import { computeStats } from '../../lib/collection.ts'
import type { Collection, Message, SendBody, Step, StepKey, StreamEvent } from '../types.ts'
import {
  DRAFT_DESCRIPTION,
  DRAFT_STATS,
  DRAFT_TITLE,
  FOLLOW_UPS,
  NOTES_TEXT,
  OPENING_TEXT,
  buildCollection,
  chats,
  collections,
  newId,
  summaryOf,
} from './db.ts'
import { MAIN_SELECTION, SPARE_SELECTION, filmsById } from './films.ts'

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new DOMException('Aborted', 'AbortError'))
    const onAbort = () => {
      clearTimeout(timer)
      reject(new DOMException('Aborted', 'AbortError'))
    }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

type Scripted = { key: StepKey; start: string; done: Omit<Step, 'key' | 'status'>; ms: number; notice?: string }

const FRESH_STEPS: Scripted[] = [
  { key: 'parse', start: 'İsteğini çözüyorum', ms: 1200, done: { title: 'İsteğini çözdüm.', detail: '2015 ve sonrası · az bilinen · psikolojik gerilim · kasvetli ton', count: null } },
  { key: 'search', start: 'Arşivde dolaşıyorum', ms: 2400, done: { title: 'Arşivde dolaştım.', detail: '184 aday çıktı.', count: 184 } },
  { key: 'read', start: 'Hikâyelerini okuyorum', ms: 2800, done: { title: 'Hikâyelerini tek tek okudum.', detail: "31'i gerçekten bu havayı taşıyor.", count: 31 }, notice: 'Yıl filtresini gevşettim; yoksa yalnızca 4 film çıkıyordu.' },
  { key: 'select', start: 'En iyilerini seçiyorum', ms: 1600, done: { title: "En iyi 10'u seçtim", detail: 've her biri için nedenini yazdım.', count: null } },
]

const REFINE_STEPS: Scripted[] = [
  { key: 'parse', start: 'İsteğini çözüyorum', ms: 1000, done: { title: 'İsteğini çözdüm.', detail: 'seçkide değişiklik istedin.', count: null } },
  { key: 'update', start: 'Seçkiyi güncelliyorum', ms: 2000, done: { title: 'Seçkiyi güncelledim.', detail: '1 film değişti.', count: 1 } },
]

const EMPTY_STEPS: Scripted[] = [
  { key: 'parse', start: 'İsteğini çözüyorum', ms: 1000, done: { title: 'İsteğini çözdüm.', detail: 'çok dar bir istek.', count: null } },
  { key: 'search', start: 'Arşivde dolaşıyorum', ms: 1800, done: { title: 'Arşivde dolaştım.', detail: '0 aday çıktı.', count: 0 } },
]

function* wordChunks(text: string): Generator<string> {
  for (const match of text.matchAll(/\S+\s*/g)) yield match[0]
}

function nextVersion(collection: Collection, films: Collection['films']): Collection {
  const numbered = films.map((film, index) => ({ ...film, position: index + 1 }))
  const next: Collection = {
    ...collection,
    films: numbered,
    stats: computeStats(numbered),
    version: collection.version + 1,
    updated_at: new Date().toISOString(),
  }
  collections.set(next.id, next)
  return next
}

// Gerçek sunucunun olay sırasını ve zamanlamasını taklit eder (adımlar 1-3 sn arayla).
// Sahte katman kuralları: metin "hata" içeriyorsa `error`; "boş" içeriyorsa koleksiyonsuz cevap.
export async function* mockStream(chatId: number, body: SendBody, signal: AbortSignal): AsyncGenerator<StreamEvent> {
  const chat = chats.get(chatId)
  if (!chat) throw new Error('Sohbet yok')
  const now = () => new Date().toISOString()
  const userMessage: Message = {
    id: newId(), role: 'user', text: body.text, created_at: now(), steps: [], duration_s: null, collection_id: null, suggestions: [], error: null,
  }
  chat.messages.push(userMessage)
  const messageId = newId()
  yield { event: 'message.start', data: { user_message: userMessage, message_id: messageId } }

  const startedAt = Date.now()
  const lower = body.text.toLocaleLowerCase('tr-TR')
  const existing = chat.collectionId === null ? null : (collections.get(chat.collectionId) ?? null)
  const scenario = lower.includes('hata') ? 'error' : lower.includes('boş') ? 'empty' : existing ? 'refine' : 'fresh'
  const script = scenario === 'refine' ? REFINE_STEPS : scenario === 'empty' ? EMPTY_STEPS : FRESH_STEPS

  const steps: Step[] = []
  for (const item of script) {
    yield { event: 'step.start', data: { key: item.key, title: item.start } }
    if (scenario === 'error') {
      await sleep(1400, signal)
      yield { event: 'error', data: { detail: 'Model yanıt vermedi.', code: 'model_error' } }
      return
    }
    await sleep(item.ms, signal)
    const done: Step = { key: item.key, status: 'done', ...item.done }
    steps.push(done)
    yield { event: 'step.done', data: done }
    if (item.notice) {
      await sleep(350, signal)
      // Kayıtlı mesajda notice de `steps` içinde, geldiği sırada saklanır (sözleşme 1.1).
      steps.push({ key: 'notice', status: 'done', title: '', detail: item.notice, count: null })
      yield { event: 'notice', data: { text: item.notice } }
    }
  }

  let text: string
  let collection: Collection | null = null
  let suggestions = FOLLOW_UPS
  if (scenario === 'empty') {
    text = 'Bu istekle arşivde yeterince film bulamadım. Biraz genişletirsek **dönemi ya da türü** gevşetebiliriz.'
    suggestions = ['Dönemi genişlet', 'Türü gevşet']
  } else if (scenario === 'refine' && existing) {
    const replaceId = body.action?.type === 'replace_film' ? body.action.film_id : null
    const spare = filmsById(SPARE_SELECTION).find((film) => !existing.films.some((f) => f.film_id === film.film_id))
    let films = existing.films
    if (replaceId !== null && spare) {
      films = films.map((film) => (film.film_id === replaceId ? { ...spare, position: film.position } : film))
    } else if (body.action?.type === 'research') {
      films = [...films.slice(3), ...films.slice(0, 3)]
    } else if (spare) {
      films = [...films.slice(0, -1), spare]
    }
    collection = nextVersion(existing, films)
    text = 'Seçkiyi güncelledim; **yeni isteğine daha yakın** bir sıralama çıktı.'
    suggestions = ['Daha karanlık olsun', 'Sadece Avrupa yapımları']
  } else {
    text = `${OPENING_TEXT}\n\n${NOTES_TEXT}`
    const id = newId()
    collection = buildCollection({ id, chat_id: chatId, title: DRAFT_TITLE, description: DRAFT_DESCRIPTION, filmIds: MAIN_SELECTION, updated_at: now(), stats: DRAFT_STATS })
    collections.set(id, collection)
    chat.collectionId = id
  }

  // Taslaktaki sıra: ilk paragraf, kart, sonra notlar. Kart olayı metnin ortasında gelir.
  const [first, ...rest] = text.split('\n\n')
  for (const chunk of wordChunks(first)) {
    yield { event: 'text.delta', data: { delta: chunk } }
    await sleep(38, signal)
  }
  if (collection) {
    await sleep(250, signal)
    yield { event: 'collection', data: collection }
    await sleep(500, signal)
  }
  for (const paragraph of rest) {
    yield { event: 'text.delta', data: { delta: '\n\n' } }
    for (const chunk of wordChunks(paragraph)) {
      yield { event: 'text.delta', data: { delta: chunk } }
      await sleep(38, signal)
    }
  }
  yield { event: 'suggestions', data: { items: suggestions } }
  await sleep(150, signal)

  const message: Message = {
    id: messageId,
    role: 'assistant',
    text,
    created_at: now(),
    steps,
    duration_s: Math.max(1, Math.round((Date.now() - startedAt) / 1000)),
    collection_id: collection?.id ?? null,
    suggestions,
    error: null,
  }
  chat.messages.push(message)
  if (chat.title === 'Yeni sohbet') chat.title = body.text.length > 40 ? `${body.text.slice(0, 38).trimEnd()}…` : body.text
  chat.updated_at = now()
  yield { event: 'message.done', data: { message, chat: summaryOf(chat) } }
}
