import { useCallback, useEffect, useState } from 'react'
import { getPublishedApps } from '../api/client'
import AppShell from '../components/AppShell'

function AppCover({ app }) {
  if (app.cover_url) {
    return <img src={app.cover_url} alt={`${app.app_name} 封面`} />
  }

  return (
    <div className="market-app-card__cover-fallback" aria-hidden="true">
      <span>{app.app_name.slice(0, 1).toUpperCase()}</span>
    </div>
  )
}

export default function CommunityPage() {
  const [apps, setApps] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadApps = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await getPublishedApps()
      setApps(result.apps || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadApps()
  }, [loadApps])

  const handleOpenApp = useCallback((app) => {
    if (!app?.app_url) return
    window.open(app.app_url, '_blank', 'noopener,noreferrer')
  }, [])

  return (
    <AppShell>
      <section className="market-panel" aria-labelledby="market-title">
        <div className="section-heading section-heading--split">
          <div>
            <h1 id="market-title">应用市场</h1>
            <p>浏览由用户发布的应用，点击访问即可打开对应服务。</p>
          </div>
          <button className="btn btn--primary" type="button" onClick={loadApps} disabled={loading}>
            {loading ? '刷新中…' : '刷新'}
          </button>
        </div>

        {error ? <div className="feedback feedback--error">{error}</div> : null}
        {loading ? <div className="muted-card">正在加载应用市场…</div> : null}
        {!loading && !error && apps.length === 0 ? <div className="muted-card">暂无已发布应用。</div> : null}

        {!loading && !error && apps.length > 0 ? (
          <div className="market-app-grid">
            {apps.map((app) => (
              <article className="market-app-card" key={app.id}>
                <div className="market-app-card__cover">
                  <AppCover app={app} />
                </div>
                <div className="market-app-card__body">
                  <div>
                    <h2>{app.app_name}</h2>
                    <p>{app.app_description}</p>
                  </div>
                  <div className="market-app-card__footer">
                    <span>发布者：{app.owner_display_name || app.owner_username}</span>
                    <button className="btn btn--primary" type="button" onClick={() => handleOpenApp(app)}>
                      访问应用
                    </button>
                  </div>
                </div>
              </article>
            ))}
          </div>
        ) : null}
      </section>
    </AppShell>
  )
}
