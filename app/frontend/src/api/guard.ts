import { ApiError } from './errors.ts'
import type { Api } from './index.ts'

// Girişsiz de çağrılabilen uçlar: bunlardaki 401 oturum düştü demek değildir.
const PUBLIC: ReadonlySet<keyof Api> = new Set<keyof Api>(['me', 'login', 'getShared'])

const isUnauthorized = (error: unknown): boolean =>
  error instanceof ApiError && error.status === 401 && error.code === 'not_authenticated'

// Her uç fonksiyonunu sarar: korumalı uçtan 401 gelirse `onUnauthorized` çağrılır, hata yine de fırlatılır.
export function guardApi(api: Api, onUnauthorized: () => void): Api {
  const wrapped: Record<string, unknown> = {}
  for (const name of Object.keys(api) as (keyof Api)[]) {
    if (PUBLIC.has(name)) {
      wrapped[name] = api[name]
    } else if (name === 'streamMessage') {
      wrapped[name] = async function* (...args: Parameters<Api['streamMessage']>) {
        try {
          yield* api.streamMessage(...args)
        } catch (error) {
          if (isUnauthorized(error)) onUnauthorized()
          throw error
        }
      }
    } else {
      const call = api[name] as (...args: unknown[]) => Promise<unknown>
      wrapped[name] = async (...args: unknown[]) => {
        try {
          return await call(...args)
        } catch (error) {
          if (isUnauthorized(error)) onUnauthorized()
          throw error
        }
      }
    }
  }
  return wrapped as Api
}
