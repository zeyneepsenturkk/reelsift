import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/errors.ts'
import type { Collection } from '../api/types.ts'
import { acceptIncoming, withoutFilm } from './collection.ts'
import { newPending, runOptimistic } from './optimistic.ts'

const film = (id: number) => ({
  film_id: id,
  position: id,
  title: `F${id}`,
  title_tr: null,
  year: 2020,
  countries: [],
  vote_count: 1,
  directors: [],
  actors: [],
  poster_url: null,
  rationale: '',
  source_quote: '',
  quote_source: null,
  sources: [],
})

const base = (patch: Partial<Collection> = {}): Collection => ({
  id: 1,
  chat_id: 1,
  title: 'Eski',
  description: '',
  status: 'draft',
  version: 3,
  films: [film(1), film(2), film(3)],
  stats: { film_count: 3, year_min: 2020, year_max: 2020, country_count: 0, avg_vote_count: 1 },
  share_url: null,
  published_url: null,
  publish_enabled: false,
  approved_at: null,
  updated_at: 'x',
  ...patch,
})

const ids = (collection: Collection) => collection.films.map((f) => f.film_id)
const networkError = () => new ApiError(0, 'network_error', '')

// Gerçek `runOptimistic` çağrılır; yalnız `call` ve `resync` sahtelenir.
function setup(initial: Collection) {
  const state = { screen: initial }
  const pending = newPending<Collection>()
  const onError = vi.fn()
  const run = (
    optimistic: (from: Collection) => Collection,
    call: () => Promise<Collection>,
    resync?: () => Promise<Collection>,
  ) => {
    const before = state.screen
    return runOptimistic({
      before,
      optimistic: optimistic(before),
      call,
      set: (next) => (state.screen = next),
      accept: acceptIncoming,
      current: () => state.screen,
      pending,
      onError,
      resync,
    })
  }
  return { state, pending, onError, run }
}

function deferred() {
  let resolve!: (value: Collection) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<Collection>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('runOptimistic: tek işlem', () => {
  it('ağ hatasında film çıkarma eski hale döner, bir kez bildirir', async () => {
    const s0 = base()
    const { state, run, onError, pending } = setup(s0)
    const ok = await run((c) => withoutFilm(c, 1), () => Promise.reject(networkError()))
    expect(ok).toBe(false)
    expect(state.screen).toBe(s0)
    expect(onError).toHaveBeenCalledTimes(1)
    expect(pending.count).toBe(0)
  })

  it('ağ hatasında başlık düzenleme eski başlığa döner; yeniden çekme de düşse geri alma kalır', async () => {
    const s0 = base()
    const { state, run, onError } = setup(s0)
    const resync = vi.fn().mockRejectedValue(networkError())
    await run((c) => ({ ...c, title: 'Yeni' }), () => Promise.reject(networkError()), resync)
    await Promise.resolve()
    expect(resync).toHaveBeenCalled()
    expect(state.screen.title).toBe('Eski')
    expect(onError).toHaveBeenCalled()
  })

  it('başarıda sunucu cevabı uygulanır', async () => {
    const { state, run } = setup(base())
    const server = base({ title: 'Yeni', version: 4 })
    expect(await run((c) => ({ ...c, title: 'Yeni' }), () => Promise.resolve(server))).toBe(true)
    expect(state.screen).toBe(server)
  })

  it('geç dönen eski cevap (daha düşük sürüm) ekranı geri çevirmez', async () => {
    const { state, run } = setup(base({ version: 5 }))
    await run((c) => ({ ...c, title: 'Y' }), () => Promise.resolve(base({ version: 4 })))
    expect(state.screen.version).toBe(5)
  })
})

describe('runOptimistic: art arda iki işlem (A, sonra B)', () => {
  const start = async (outcome: { a: 'fail' | 'ok'; b: 'fail' | 'ok' }, order: 'ab' | 'ba' = 'ab', resync?: () => Promise<Collection>) => {
    const s0 = base({ version: 3 })
    const ctx = setup(s0)
    const a = deferred()
    const b = deferred()
    const pa = ctx.run((c) => withoutFilm(c, 1), () => a.promise, resync)
    const pb = ctx.run((c) => withoutFilm(c, 2), () => b.promise, resync)
    const serverA = base({ version: 4, films: [film(2), film(3)] }) // yalnız A uygulanmış
    const serverB = base({ version: 5, films: [film(3)] }) // A ve B uygulanmış
    const serverBOnly = base({ version: 4, films: [film(1), film(3)] }) // A düşmüş, yalnız B uygulanmış
    const settle = {
      a: () => (outcome.a === 'ok' ? a.resolve(serverA) : a.reject(networkError())),
      b: () => (outcome.b === 'ok' ? b.resolve(outcome.a === 'ok' ? serverB : serverBOnly) : b.reject(networkError())),
    }
    if (order === 'ab') {
      settle.a()
      settle.b()
    } else {
      settle.b()
      settle.a()
    }
    await Promise.all([pa, pb])
    return { ...ctx, s0, serverA, serverB, serverBOnly }
  }

  it('ikisi de düşer: ekran S0\'a döner, tek toast', async () => {
    const r = await start({ a: 'fail', b: 'fail' })
    expect(r.state.screen).toBe(r.s0)
    expect(r.onError).toHaveBeenCalledTimes(1)
    expect(r.pending.count).toBe(0)
  })

  it('A düşer, B başarılı: sunucunun B cevabı (A geri gelmiş, B çıkmış)', async () => {
    const r = await start({ a: 'fail', b: 'ok' })
    expect(r.state.screen).toBe(r.serverBOnly)
    expect(ids(r.state.screen)).toEqual([1, 3])
    expect(r.onError).toHaveBeenCalledTimes(1)
  })

  it('A başarılı, B düşer: ekran A\'nın cevabında kalır', async () => {
    const r = await start({ a: 'ok', b: 'fail' })
    expect(r.state.screen).toBe(r.serverA)
    expect(ids(r.state.screen)).toEqual([2, 3])
    expect(r.onError).toHaveBeenCalledTimes(1)
  })

  it('ikisi de başarılı: son cevap, hata bildirimi yok', async () => {
    const r = await start({ a: 'ok', b: 'ok' })
    expect(r.state.screen).toBe(r.serverB)
    expect(r.onError).not.toHaveBeenCalled()
  })

  it('cevaplar ters sırada dönerse (B önce, A sonra) sürümü yüksek olan kalır', async () => {
    const r = await start({ a: 'ok', b: 'ok' }, 'ba')
    expect(r.state.screen).toBe(r.serverB)
    expect(r.state.screen.version).toBe(5)
  })

  it('hepsi düşer ve resync de düşer: S0 kalır', async () => {
    const resync = vi.fn().mockRejectedValue(networkError())
    const r = await start({ a: 'fail', b: 'fail' }, 'ab', resync)
    await Promise.resolve()
    expect(resync).toHaveBeenCalled()
    expect(r.state.screen).toBe(r.s0)
  })

  it('bekleyen varken ara hallere dokunulmaz (düşen A ekranı hemen geri sarmaz)', async () => {
    const s0 = base()
    const { state, run } = setup(s0)
    const a = deferred()
    const b = deferred()
    const pa = run((c) => withoutFilm(c, 1), () => a.promise)
    const pb = run((c) => withoutFilm(c, 2), () => b.promise)
    a.reject(networkError())
    await pa
    expect(ids(state.screen)).toEqual([3]) // B hâlâ bekliyor: iyimser görünüm duruyor
    b.reject(networkError())
    await pb
    expect(state.screen).toBe(s0)
  })

  it('sürerken onaylanan (approved) hal, geç dönen taslak cevabıyla geri çevrilmez', async () => {
    const s0 = base()
    const { state, run } = setup(s0)
    const a = deferred()
    const pa = run((c) => withoutFilm(c, 1), () => a.promise)
    state.screen = base({ status: 'approved', version: 9 }) // onay cevabı araya girdi
    a.resolve(base({ version: 4, films: [film(2), film(3)] }))
    await pa
    expect(state.screen.status).toBe('approved')
  })
})

describe('koleksiyon değişince', () => {
  it('uçuştaki eski koleksiyon işlemi (düşse de, başarılı da olsa) yeni koleksiyonu ezmez', async () => {
    for (const outcome of ['fail', 'ok'] as const) {
      const old = base({ id: 1 })
      const { state, run } = setup(old)
      const a = deferred()
      const p = run((c) => withoutFilm(c, 1), () => a.promise)
      const other = base({ id: 2, title: 'Başka seçki', version: 1 })
      state.screen = other // panel bu arada başka seçkiye geçti
      if (outcome === 'fail') a.reject(networkError())
      else a.resolve(base({ id: 1, version: 4, films: [film(2), film(3)] }))
      await p
      expect(state.screen).toBe(other)
    }
  })

  it('yeni koleksiyonda yeni bir pending ile başlanınca eski kayıt onu etkilemez', async () => {
    const first = setup(base({ id: 1 }))
    const stuck = deferred()
    void first.run((c) => withoutFilm(c, 1), () => stuck.promise)
    // Yeni koleksiyon: taze pending (hook'un yaptığı gibi)
    const second = setup(base({ id: 2 }))
    const s2 = second.state.screen
    await second.run((c) => withoutFilm(c, 2), () => Promise.reject(networkError()))
    expect(second.state.screen).toBe(s2)
    expect(second.onError).toHaveBeenCalledTimes(1)
  })
})

describe('acceptIncoming', () => {
  it('farklı kimlikli cevabı reddeder', () => {
    expect(acceptIncoming({ id: 1, version: 3, status: 'draft' }, { id: 2, version: 9, status: 'draft' })).toBe(false)
    expect(acceptIncoming({ id: 1, version: 3, status: 'draft' }, { id: 1, version: 4, status: 'draft' })).toBe(true)
  })
  it('aynı ya da yeni sürümü kabul eder', () => {
    expect(acceptIncoming({ version: 3, status: 'draft' }, { version: 3, status: 'draft' })).toBe(true)
    expect(acceptIncoming({ version: 3, status: 'draft' }, { version: 4, status: 'draft' })).toBe(true)
  })
  it('eski sürümü reddeder', () => {
    expect(acceptIncoming({ version: 4, status: 'draft' }, { version: 3, status: 'draft' })).toBe(false)
  })
  it('onaylı hali taslağa çeviren cevabı sürümü yüksek olsa da reddeder', () => {
    expect(acceptIncoming({ version: 4, status: 'approved' }, { version: 9, status: 'draft' })).toBe(false)
  })
})
