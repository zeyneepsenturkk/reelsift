import { computeStats, withoutFilm } from '../../lib/collection.ts'
import { readStored, writeStored } from '../../lib/storage.ts'
import { ApiError } from '../errors.ts'
import type { Api } from '../index.ts'
import type { ChatSummary, CollectionSummary, User } from '../types.ts'
import { MOCK_PUBLISH_FAIL_KEY, chatDetail, chats, collections, mockPublishEnabled, newId, shares, summaryOf } from './db.ts'
import { mockStream } from './stream.ts'

const SESSION_KEY = 'reelsift.mock.user'
const USER: User = { id: 1, username: 'zeynep', display_name: 'Zeynep', initials: 'ZŞ' }

const wait = (ms = 180) => new Promise<void>((resolve) => setTimeout(resolve, ms))

async function guard(): Promise<void> {
  await wait()
  if (readStored(SESSION_KEY) !== '1') throw new ApiError(401, 'not_authenticated', 'Giriş gerekli.')
}

function notFound(): ApiError {
  return new ApiError(404, 'not_found', 'Bulunamadı.')
}

function summaryOfCollection(id: number): CollectionSummary {
  const collection = collections.get(id)
  if (!collection) throw notFound()
  return {
    id: collection.id,
    title: collection.title,
    status: collection.status,
    film_count: collection.films.length,
    poster_urls: collection.films.flatMap((film) => (film.poster_url ? [film.poster_url] : [])).slice(0, 6),
    share_url: collection.share_url,
    approved_at: collection.approved_at,
    updated_at: collection.updated_at,
  }
}

function editable(id: number) {
  const collection = collections.get(id)
  if (!collection) throw notFound()
  if (collection.status === 'approved') throw new ApiError(409, 'collection_locked', 'Kaydedilmiş seçki değiştirilemez.')
  return collection
}

// `VITE_MOCK=1` iken gerçek istemci yerine kullanılan sahte sürüm; aynı imzalar.
export const mockApi: Api = {
  async me() {
    await wait(120)
    if (readStored(SESSION_KEY) !== '1') throw new ApiError(401, 'not_authenticated', 'Giriş gerekli.')
    return USER
  },
  async login(_username, password) {
    await wait(350)
    if (password === 'yanlis') throw new ApiError(401, 'invalid_credentials', 'Kullanıcı adı ya da şifre yanlış.')
    writeStored(SESSION_KEY, '1')
    return USER
  },
  async logout() {
    await wait(100)
    writeStored(SESSION_KEY, '0')
  },

  async listChats() {
    await guard()
    return [...chats.values()].sort((a, b) => b.updated_at.localeCompare(a.updated_at)).map(summaryOf)
  },
  async createChat() {
    await guard()
    const stamp = new Date().toISOString()
    const chat = { id: newId(), title: 'Yeni sohbet', updated_at: stamp, messages: [], collectionId: null }
    chats.set(chat.id, chat)
    return summaryOf(chat) satisfies ChatSummary
  },
  async getChat(id) {
    await guard()
    const chat = chats.get(id)
    if (!chat) throw notFound()
    return chatDetail(chat)
  },
  streamMessage: mockStream,

  async listCollections() {
    await guard()
    return [...collections.values()]
      .filter((collection) => collection.status === 'approved')
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
      .map((collection) => summaryOfCollection(collection.id))
  },
  async getCollection(id) {
    await guard()
    const collection = collections.get(id)
    if (!collection) throw notFound()
    return collection
  },
  async updateCollection(id, patch) {
    await guard()
    const collection = editable(id)
    const next = {
      ...collection,
      title: patch.title ?? collection.title,
      description: patch.description ?? collection.description,
      version: collection.version + 1,
      updated_at: new Date().toISOString(),
    }
    collections.set(id, next)
    return next
  },
  async removeFilm(id, filmId) {
    await guard()
    const collection = editable(id)
    const trimmed = withoutFilm(collection, filmId)
    const next = {
      ...trimmed,
      stats: computeStats(trimmed.films),
      version: collection.version + 1,
      updated_at: new Date().toISOString(),
    }
    collections.set(id, next)
    return next
  },
  async approveCollection(id) {
    await guard()
    const collection = editable(id)
    if (collection.films.length === 0) throw new ApiError(422, 'empty_collection', 'Seçkide film yok.')
    const token = `${collection.title.slice(0, 8).toLowerCase().replace(/\W+/g, '-')}-${id.toString(36)}`
    const stamp = new Date().toISOString()
    const next = {
      ...collection,
      status: 'approved' as const,
      share_url: `/k/${token}`,
      approved_at: stamp,
      version: collection.version + 1,
      updated_at: stamp,
    }
    collections.set(id, next)
    shares.set(token, id)
    return next
  },
  async publishCollection(id) {
    await guard()
    const collection = collections.get(id)
    if (!collection) throw notFound()
    if (collection.status !== 'approved') throw new ApiError(409, 'not_approved', 'Yalnız onaylı seçki yayınlanabilir.')
    if (!mockPublishEnabled()) throw new ApiError(409, 'publish_disabled', 'Site yayını açık değil.')
    if (collection.published_url) return collection
    // İstek sürerken "Yayınlanıyor…" hali görülebilsin.
    await wait(1400)
    const failure = readStored(MOCK_PUBLISH_FAIL_KEY)
    if (failure) throw new ApiError(502, failure, 'Seçki yayınlanamadı.')
    const slug = collection.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'secki'
    const next = { ...collection, published_url: `https://film-sitesi.example/s/${slug}-${id.toString(36)}/`, updated_at: new Date().toISOString() }
    collections.set(id, next)
    return next
  },
  async getShared(token) {
    await wait()
    const id = shares.get(token)
    const collection = id === undefined ? undefined : collections.get(id)
    if (!collection || collection.status !== 'approved') throw notFound()
    return {
      title: collection.title,
      description: collection.description,
      films: collection.films,
      stats: collection.stats,
      owner_display_name: 'Zeynep Şentürk',
      approved_at: collection.approved_at ?? collection.updated_at,
    }
  },
}
