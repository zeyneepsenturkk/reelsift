import { ApiError } from './errors.ts'
import type {
  Chat,
  ChatSummary,
  Collection,
  CollectionSummary,
  SharedCollection,
  User,
} from './types.ts'

function readCookie(name: string): string | null {
  const match = document.cookie.split('; ').find((part) => part.startsWith(`${name}=`))
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null
}

// Yazan isteklerde Django CSRF başlığı; çerez `GET /api/auth/me` ile kurulur.
export function buildHeaders(method: string, extra: Record<string, string> = {}): Headers {
  const headers = new Headers(extra)
  if (method !== 'GET' && method !== 'HEAD') {
    const token = readCookie('csrftoken')
    if (token) headers.set('X-CSRFToken', token)
  }
  return headers
}

export async function errorFromResponse(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as { detail?: string; code?: string }
    return new ApiError(response.status, body.code ?? 'server_error', body.detail ?? '')
  } catch {
    return new ApiError(response.status, 'server_error', '')
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers = buildHeaders(method, body === undefined ? {} : { 'Content-Type': 'application/json' })
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers,
      credentials: 'same-origin',
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'network_error', '')
  }
  if (!response.ok) throw await errorFromResponse(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const me = () => request<User>('GET', '/auth/me')
export const login = (username: string, password: string) =>
  request<User>('POST', '/auth/login', { username, password })
export const logout = () => request<void>('POST', '/auth/logout')

export const listChats = () => request<ChatSummary[]>('GET', '/chats')
export const createChat = () => request<ChatSummary>('POST', '/chats')
export const getChat = (id: number) => request<Chat>('GET', `/chats/${id}`)

export const listCollections = () => request<CollectionSummary[]>('GET', '/collections')
export const getCollection = (id: number) => request<Collection>('GET', `/collections/${id}`)
export const updateCollection = (id: number, patch: { title?: string; description?: string }) =>
  request<Collection>('PATCH', `/collections/${id}`, patch)
export const removeFilm = (id: number, filmId: number) =>
  request<Collection>('DELETE', `/collections/${id}/films/${filmId}`)
export const approveCollection = (id: number) =>
  request<Collection>('POST', `/collections/${id}/approve`)
export const publishCollection = (id: number) =>
  request<Collection>('POST', `/collections/${id}/publish`)
export const getShared = (token: string) =>
  request<SharedCollection>('GET', `/share/${encodeURIComponent(token)}`)
