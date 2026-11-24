import { useState, type FormEvent } from 'react'
import { Navigate, useLocation } from 'react-router'
import { ApiError } from '../api/errors.ts'
import { Brand } from '../components/Brand.tsx'
import { useAuth } from '../state/auth.tsx'

// Hesabın var olup olmadığını sızdırmamak için sunucu tek mesaj döner; arayüz de tek mesaj gösterir.
function loginErrorText(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Giriş yapılamadı, bir daha dener misin?'
  if (error.code === 'invalid_credentials') return 'Kullanıcı adı ya da şifre yanlış.'
  if (error.code === 'rate_limited') return 'Çok fazla deneme yaptın. Biraz bekleyip tekrar dene.'
  return 'Giriş yapılamadı, bir daha dener misin?'
}

export default function LoginPage() {
  const { status, signIn } = useAuth()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (status === 'loading') return <div className="login" aria-busy="true" />
  // Girişli kullanıcı buraya gelirse ana ekrana ya da gitmek istediği yere döner.
  if (status === 'authed') {
    const from = (location.state as { from?: string } | null)?.from
    return <Navigate to={from ?? '/'} replace />
  }

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (submitting) return
    setSubmitting(true)
    setError(null)
    try {
      await signIn(username.trim(), password)
    } catch (caught) {
      setError(loginErrorText(caught))
      setSubmitting(false)
    }
  }

  return (
    <div className="login">
      <div className="login-col">
        <div className="login-head">
          <img className="login-mark" src="/favicon.svg" alt="" />
          <Brand big />
          <span className="label">kürasyon masası</span>
        </div>
        <form onSubmit={onSubmit}>
          <label className="field">
            <span className="label">Kullanıcı adı</span>
            <span className="box">
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                required
                autoFocus
              />
            </span>
          </label>
          <label className="field">
            <span className="label">Şifre</span>
            <span className="box">
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                required
              />
            </span>
          </label>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button className="btn primary wide" type="submit" disabled={submitting}>
            {submitting ? 'Giriş yapılıyor…' : 'Giriş yap'}
          </button>
        </form>
      </div>
    </div>
  )
}
