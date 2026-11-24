import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './errors.ts'
import * as client from './client.ts'
import { streamMessage } from './stream.ts'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

describe('istemci', () => {
  beforeEach(() => {
    vi.stubGlobal('document', { cookie: 'foo=1; csrftoken=abc%20def' })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('yazan isteğe CSRF başlığı ve çerezi ekler, okuyan isteğe eklemez', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(json({ id: 1 })))
    vi.stubGlobal('fetch', fetchMock)
    await client.updateCollection(5, { title: 'x' })
    await client.getCollection(5)
    const [, post] = fetchMock.mock.calls[0]
    const [, get] = fetchMock.mock.calls[1]
    expect((post.headers as Headers).get('X-CSRFToken')).toBe('abc def')
    expect(post.credentials).toBe('same-origin')
    expect(post.method).toBe('PATCH')
    expect(post.body).toBe('{"title":"x"}')
    expect((get.headers as Headers).get('X-CSRFToken')).toBeNull()
  })

  it('{detail, code} cevabını ApiError olarak fırlatır', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ detail: 'Kilitli.', code: 'collection_locked' }, 409)))
    const error = await client.removeFilm(1, 2).catch((caught: unknown) => caught)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 409, code: 'collection_locked' })
  })

  it('gövdesi JSON olmayan hata cevabında genel koda düşer', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>', { status: 502 })))
    await expect(client.me()).rejects.toMatchObject({ status: 502, code: 'server_error' })
  })

  it('ağ kopmasını network_error olarak bildirir', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('fail')))
    await expect(client.listChats()).rejects.toMatchObject({ status: 0, code: 'network_error' })
  })

  it('204 cevabında boş döner', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
    await expect(client.logout()).resolves.toBeUndefined()
  })
})

describe('streamMessage', () => {
  beforeEach(() => {
    vi.stubGlobal('document', { cookie: 'csrftoken=tok' })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('POST gövdesiyle olayları sırayla verir', async () => {
    const body = new Response('event: text.delta\ndata: {"delta":"a"}\n\nevent: message.done\ndata: {"message":{},"chat":{}}\n\n')
    const fetchMock = vi.fn().mockResolvedValue(body)
    vi.stubGlobal('fetch', fetchMock)
    const names: string[] = []
    for await (const event of streamMessage(3, { text: 'merhaba', action: { type: 'research' } }, new AbortController().signal)) {
      names.push(event.event)
    }
    expect(names).toEqual(['text.delta', 'message.done'])
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/chats/3/messages/stream')
    expect(init.body).toBe('{"text":"merhaba","action":{"type":"research"}}')
    expect((init.headers as Headers).get('X-CSRFToken')).toBe('tok')
  })

  it('akış başlamadan gelen JSON hatasını ApiError yapar', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ detail: 'Yok.', code: 'not_found' }, 404)))
    const run = async () => {
      for await (const event of streamMessage(9, { text: 'x' }, new AbortController().signal)) void event
    }
    await expect(run()).rejects.toMatchObject({ status: 404, code: 'not_found' })
  })

  it('iptal edilen istekte AbortError olduğu gibi geçer', async () => {
    const controller = new AbortController()
    controller.abort()
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new DOMException('Aborted', 'AbortError')))
    const run = async () => {
      for await (const event of streamMessage(1, { text: 'x' }, controller.signal)) void event
    }
    await expect(run()).rejects.toMatchObject({ name: 'AbortError' })
  })
})
