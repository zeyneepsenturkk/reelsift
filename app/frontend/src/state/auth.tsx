import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '../api/index.ts'
import { setUnauthorizedHandler } from '../api/session.ts'
import type { User } from '../api/types.ts'

type AuthValue = {
  status: 'loading' | 'authed' | 'anon'
  user: User | null
  signIn: (username: string, password: string) => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ status: AuthValue['status']; user: User | null }>({
    status: 'loading',
    user: null,
  })

  // `me` aynı zamanda CSRF çerezini kurar; girişsizse 401 gelir ve giriş ekranına yönlendirilir.
  useEffect(() => {
    let cancelled = false
    api
      .me()
      .then((user) => !cancelled && setState({ status: 'authed', user }))
      .catch(() => !cancelled && setState({ status: 'anon', user: null }))
    return () => {
      cancelled = true
    }
  }, [])

  // Oturum ortada düşerse (herhangi bir uçtan 401) giriş ekranına dönülür.
  useEffect(() => {
    setUnauthorizedHandler(() => setState({ status: 'anon', user: null }))
    return () => setUnauthorizedHandler(null)
  }, [])

  const signIn = useCallback(async (username: string, password: string) => {
    const user = await api.login(username, password)
    setState({ status: 'authed', user })
  }, [])

  const signOut = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      setState({ status: 'anon', user: null })
    }
  }, [])

  const value = useMemo(() => ({ ...state, signIn, signOut }), [state, signIn, signOut])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('AuthProvider eksik')
  return value
}
