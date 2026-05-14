import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { createSandbox, getMySandboxes } from '../api/client'
import { useAuth } from '../context/AuthContext'

function formatDateTime(value) {
  if (!value) return ''

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return ''
  }

  return date.toLocaleString('zh-CN', {
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function normalizeStatus(status) {
  if (!status) return ''
  if (status === 'creating') return '创建中'
  if (status === 'Running') return '运行中'
  if (status === 'Pending') return '创建中'
  if (status === 'Succeeded') return '已完成'
  if (status === 'Failed') return '异常'
  return '已创建'
}

export default function DashboardPage() {
  const { user, token, logout } = useAuth()
  const displayName = user?.display_name || user?.username || '用户'
  const [sandboxes, setSandboxes] = useState([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [image, setImage] = useState('')

  const loadSandboxes = useCallback(async () => {
    try {
      const result = await getMySandboxes(token)
      setSandboxes(result.items ?? [])
    } catch (err) {
      setError(err.message)
    }
  }, [token])

  useEffect(() => {
    loadSandboxes()
  }, [loadSandboxes])

  const onCreateSandbox = async () => {
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await createSandbox(token, image.trim() ? { image: image.trim() } : {})
      setMessage('创建请求已提交')
      setImage('')
      await loadSandboxes()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="site-shell app-shell">
      <header className="site-header app-header">
        <Link className="site-brand" to="/" aria-label="Campus AI Community 首页">
          <span className="site-brand__mark">C</span>
          <span>Campus AI Community</span>
        </Link>
        <div className="app-header__actions">
          <span className="user-name">{displayName}</span>
          <button className="btn btn--secondary" onClick={logout}>
            退出
          </button>
        </div>
      </header>

      <main className="app-main">
        <section className="workspace-panel" aria-labelledby="workspace-title">
          <div className="section-heading">
            <h1 id="workspace-title">工作台</h1>
          </div>

          <div className="create-card">
            <label>
              <span>容器镜像</span>
              <input value={image} onChange={(event) => setImage(event.target.value)} />
            </label>
            <button className="btn btn--primary" onClick={onCreateSandbox} disabled={busy}>
              {busy ? '提交中' : '创建'}
            </button>
          </div>

          {message ? <div className="feedback feedback--success">{message}</div> : null}
          {error ? <div className="feedback feedback--error">{error}</div> : null}
        </section>

        <section className="workspace-panel" aria-labelledby="sandbox-title">
          <div className="section-heading section-heading--row">
            <h2 id="sandbox-title">我的环境</h2>
            <button className="text-button" onClick={loadSandboxes} type="button">
              刷新
            </button>
          </div>

          <div className="sandbox-list">
            {sandboxes.length === 0 ? (
              <div className="empty-state" aria-label="暂无内容" />
            ) : (
              sandboxes.map((item) => (
                <article key={item.sandbox_id} className="sandbox-row">
                  <div>
                    <strong>{item.pod_name}</strong>
                    <span>{item.image}</span>
                  </div>
                  <div className="sandbox-row__meta">
                    <em>{normalizeStatus(item.status)}</em>
                    <small>{formatDateTime(item.created_at)}</small>
                  </div>
                </article>
              ))
            )}
          </div>
        </section>
      </main>
    </div>
  )
}
