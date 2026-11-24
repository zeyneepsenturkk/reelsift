import * as client from './client.ts'
import { guardApi } from './guard.ts'
import { notifyUnauthorized } from './session.ts'
import { streamMessage } from './stream.ts'
import type {
  Chat,
  ChatSummary,
  Collection,
  CollectionSummary,
  LlmSettings,
  LlmSettingsUpdate,
  LlmTestResult,
  SendBody,
  SharedCollection,
  StreamEvent,
  User,
} from './types.ts'

export type Api = {
  me(): Promise<User>
  login(username: string, password: string): Promise<User>
  logout(): Promise<void>
  listChats(): Promise<ChatSummary[]>
  createChat(): Promise<ChatSummary>
  getChat(id: number): Promise<Chat>
  streamMessage(chatId: number, body: SendBody, signal: AbortSignal): AsyncGenerator<StreamEvent>
  listCollections(): Promise<CollectionSummary[]>
  getCollection(id: number): Promise<Collection>
  updateCollection(id: number, patch: { title?: string; description?: string }): Promise<Collection>
  removeFilm(id: number, filmId: number): Promise<Collection>
  approveCollection(id: number): Promise<Collection>
  publishCollection(id: number): Promise<Collection>
  getShared(token: string): Promise<SharedCollection>
  getLlmSettings(): Promise<LlmSettings>
  updateLlmSettings(body: LlmSettingsUpdate): Promise<LlmSettings>
  testLlmSettings(): Promise<LlmTestResult>
}

const realApi: Api = { ...client, streamMessage }

// Sahte/gerçek seçimi tek yerde. Koşul derleme zamanında sabitlenir: VITE_MOCK=1 değilken sahte katman
// (örnek film verisi dahil) paket çıktısına girmez.
const chosen: Api = import.meta.env.VITE_MOCK === '1' ? (await import('./mock/index.ts')).mockApi : realApi

export const api: Api = guardApi(chosen, notifyUnauthorized)
