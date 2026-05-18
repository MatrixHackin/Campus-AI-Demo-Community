import { useCallback, useEffect, useState } from 'react'
import { getPublishedApps, recordAppVisit, toggleAppLike } from '../api/client'
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
  const [likingAppIds, setLikingAppIds] = useState([])

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
    setApps((prev) => prev.map((item) => (
      item.id === app.id ? { ...item, visit_count: (item.visit_count || 0) + 1 } : item
    )))
    recordAppVisit(app.id)
      .then((updated) => {
        setApps((prev) => prev.map((item) => (
          item.id === updated.id ? { ...item, visit_count: updated.visit_count } : item
        )))
      })
      .catch(() => {
        // 访问应用不应被计数失败阻塞，刷新应用市场时会重新同步后端计数。
      })
  }, [])

  const handleToggleLike = useCallback(async (app) => {
    if (!app?.id) return

    const previousApp = app
    const nextLiked = !app.is_liked
    setError('')
    let shouldSubmit = true
    setLikingAppIds((prev) => {
      if (prev.includes(app.id)) {
        shouldSubmit = false
        return prev
      }
      return [...prev, app.id]
    })
    if (!shouldSubmit) return
    setApps((prev) => prev.map((item) => (
      item.id === app.id
        ? {
            ...item,
            is_liked: nextLiked,
            like_count: Math.max(0, (item.like_count || 0) + (nextLiked ? 1 : -1))
          }
        : item
    )))

    try {
      const updated = await toggleAppLike(app.id)
      setApps((prev) => prev.map((item) => (
        item.id === updated.id
          ? {
              ...item,
              like_count: updated.like_count,
              is_liked: updated.is_liked
            }
          : item
      )))
    } catch (err) {
      setApps((prev) => prev.map((item) => (item.id === previousApp.id ? previousApp : item)))
      setError(err.message)
    } finally {
      setLikingAppIds((prev) => prev.filter((id) => id !== app.id))
    }
  }, [])

  return (
    <AppShell>
      <section className="market-panel" aria-label="应用市场">
        <div className="market-panel__toolbar">
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
                    <div className="market-app-card__meta">
                      <span>发布者：{app.owner_display_name || app.owner_username}</span>
                      <span>访问量：{app.visit_count || 0}</span>
                    </div>
                    <div className="market-app-card__actions">
                      <button
                        className={`market-like-button${app.is_liked ? ' market-like-button--active' : ''}`}
                        type="button"
                        onClick={() => handleToggleLike(app)}
                        disabled={likingAppIds.includes(app.id)}
                        aria-pressed={app.is_liked}
                        title={app.is_liked ? '取消点赞' : '点赞'}
                      >
                        <span aria-hidden="true">{app.is_liked ? '♥' : '♡'}</span>
                        {app.like_count || 0}
                      </button>
                      <button className="btn btn--primary" type="button" onClick={() => handleOpenApp(app)}>
                        访问应用
                      </button>
                    </div>
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
