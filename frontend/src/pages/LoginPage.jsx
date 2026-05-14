import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function LoginPage() {
  const navigate = useNavigate()
  const { login, isAuthenticated, isLoading } = useAuth()
  const [form, setForm] = useState({ username: '', password: '' })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  if (!isLoading && isAuthenticated) {
    return <Navigate to="/dashboard" replace />
  }

  const onSubmit = async (event) => {
    event.preventDefault()
    setLoading(true)
    setError('')
    try {
      await login(form)
      navigate('/dashboard')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="site-shell auth-shell">
      <header className="site-header">
        <Link className="site-brand" to="/" aria-label="Campus AI Community 首页">
          <span className="site-brand__mark">C</span>
          <span>Campus AI Community</span>
        </Link>
      </header>

      <main className="auth-main">
        <section className="auth-panel" aria-labelledby="login-title">
          <div className="auth-copy">
            <h1 id="login-title">登录</h1>
            <p>请输入账号信息进入平台。</p>
          </div>

          <form className="form-grid" onSubmit={onSubmit}>
            <a className="btn btn--sso btn--full" href="/auth/sso/login">
              校园 SSO 认证登录
            </a>

            <div className="form-separator" aria-hidden="true" />

            <label>
              <span>用户名</span>
              <input
                type="text"
                value={form.username}
                onChange={(event) => setForm((prev) => ({ ...prev, username: event.target.value }))}
                autoComplete="username"
                required
              />
            </label>
            <label>
              <span>密码</span>
              <input
                type="password"
                value={form.password}
                onChange={(event) => setForm((prev) => ({ ...prev, password: event.target.value }))}
                autoComplete="current-password"
                required
              />
            </label>

            {error ? <div className="form-error" role="alert">{error}</div> : null}

            <button className="btn btn--primary btn--full" type="submit" disabled={loading}>
              {loading ? '登录中' : '登录'}
            </button>
          </form>
        </section>
      </main>
    </div>
  )
}
