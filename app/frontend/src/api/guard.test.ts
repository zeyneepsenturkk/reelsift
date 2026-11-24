import { describe, expect, it, vi } from 'vitest'
import { ApiError } from './errors.ts'
import { guardApi } from './guard.ts'
import type { Api } from './index.ts'

const unauthorized = () => new ApiError(401, 'not_authenticated', '')

function fake(overrides: Partial<Record<keyof Api, unknown>> = {}): Api {
  const fail = () => Promise.reject(unauthorized())
  return {
    me: fail,
    login: fail,
    logout: fail,
    listChats: fail,
    createChat: fail,
    getChat: fail,
    streamMessage: async function* () {
      throw unauthorized()
    },
    listCollections: fail,
    getCollection: fail,
    updateCollection: fail,
    removeFilm: fail,
    approveCollection: fail,
    publishCollection: fail,
    getShared: fail,
    ...overrides,
  } as unknown as Api
}

describe('guardApi', () => {
  it('korumalı uçtan gelen 401 oturumu düşürür ve hatayı yine fırlatır', async () => {
    const onUnauthorized = vi.fn()
    const api = guardApi(fake(), onUnauthorized)
    await expect(api.listChats()).rejects.toBeInstanceOf(ApiError)
    await expect(api.removeFilm(1, 2)).rejects.toMatchObject({ status: 401 })
    expect(onUnauthorized).toHaveBeenCalledTimes(2)
  })

  it('yayın ucundaki 401 oturumu düşürür; yayın hataları düşürmez', async () => {
    const onUnauthorized = vi.fn()
    const expired = guardApi(fake(), onUnauthorized)
    await expect(expired.publishCollection(1)).rejects.toMatchObject({ status: 401 })
    expect(onUnauthorized).toHaveBeenCalledTimes(1)

    const failing = guardApi(
      fake({ publishCollection: () => Promise.reject(new ApiError(502, 'publish_unauthorized', '')) }),
      onUnauthorized,
    )
    await expect(failing.publishCollection(1)).rejects.toMatchObject({ code: 'publish_unauthorized' })
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
  })

  it('akış başlamadan gelen 401 de oturumu düşürür', async () => {
    const onUnauthorized = vi.fn()
    const api = guardApi(fake(), onUnauthorized)
    const run = async () => {
      for await (const event of api.streamMessage(1, { text: 'x' }, new AbortController().signal)) void event
    }
    await expect(run()).rejects.toMatchObject({ status: 401 })
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
  })

  it('me, login ve paylaşım uçlarındaki 401 oturumu düşürmez', async () => {
    const onUnauthorized = vi.fn()
    const api = guardApi(fake(), onUnauthorized)
    await expect(api.me()).rejects.toBeInstanceOf(ApiError)
    await expect(api.login('a', 'b')).rejects.toBeInstanceOf(ApiError)
    await expect(api.getShared('t')).rejects.toBeInstanceOf(ApiError)
    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it('401 dışındaki hatalar (404, invalid_credentials) oturumu düşürmez', async () => {
    const onUnauthorized = vi.fn()
    const api = guardApi(
      fake({
        getChat: () => Promise.reject(new ApiError(404, 'not_found', '')),
        listChats: () => Promise.reject(new ApiError(401, 'invalid_credentials', '')),
      }),
      onUnauthorized,
    )
    await expect(api.getChat(9)).rejects.toMatchObject({ status: 404 })
    await expect(api.listChats()).rejects.toMatchObject({ code: 'invalid_credentials' })
    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it('başarılı çağrıyı olduğu gibi geçirir', async () => {
    const api = guardApi(fake({ listChats: () => Promise.resolve([{ id: 1 }]) }), vi.fn())
    await expect(api.listChats()).resolves.toEqual([{ id: 1 }])
  })
})
