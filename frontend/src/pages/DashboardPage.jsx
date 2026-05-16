import { useCallback, useEffect, useState } from 'react'
import { getMyHarborImages } from '../api/client'
import AppShell from '../components/AppShell'

function formatDateTime(value) {
  if (!value) return '未知'

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '未知'
  }

  return date.toLocaleString('zh-CN', {
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function imageShortName(repo) {
  return repo?.name || '未命名镜像'
}

function ImageList({ title, project, message, loading, limit, variant = 'private' }) {
  const repos = project?.repos || []
  const visibleRepos = repos.slice(0, limit)
  const countLabel = `${Math.min(repos.length, limit)}/${limit}`

  return (
    <section className={`image-section image-section--${variant}`} aria-labelledby={`${title}-title`}>
      <div className="image-section__heading">
        <h2 id={`${title}-title`}>{title}</h2>
        <span>{countLabel}</span>
      </div>

      {loading ? <div className="muted-card">正在加载…</div> : null}
      {!loading && message ? <div className="muted-card">{message}</div> : null}
      {!loading && !message && project?.exists && repos.length === 0 ? (
        <div className="muted-card">暂无镜像。</div>
      ) : null}

      {!loading && project?.exists ? (
        <div className={`image-button-grid image-button-grid--${variant}`}>
          {visibleRepos.map((repo) => (
            <button
              className="image-button"
              key={repo.full_name}
              type="button"
              title={`${repo.image}\nArtifacts ${repo.artifact_count || 0} · 拉取 ${repo.pull_count || 0} · 更新 ${formatDateTime(repo.update_time)}`}
            >
              <span className="image-button__thumb" aria-hidden="true">
                <span>{imageShortName(repo).slice(0, 1).toUpperCase()}</span>
              </span>
              <span className="image-button__name">{imageShortName(repo)}</span>
            </button>
          ))}
        </div>
      ) : null}
    </section>
  )
}

export default function DashboardPage() {
  const [harborInfo, setHarborInfo] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadHarborImages = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await getMyHarborImages()
      setHarborInfo(result)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadHarborImages()
  }, [loadHarborImages])

  const harborConfigured = harborInfo?.configured
  const privateMessage = !harborConfigured
    ? harborInfo?.message || 'Harbor 未配置'
    : harborInfo?.private_message
  const publicMessage = !harborConfigured
    ? harborInfo?.message || 'Harbor 未配置'
    : harborInfo?.public_message

  return (
    <AppShell>
      <div className="dashboard-layout">
        <section className="content-panel container-request-panel" aria-labelledby="container-request-title">
          <div className="dashboard-panel-heading">
            <h1 id="container-request-title">容器申请</h1>
            <p>这里预留给后续创建 container 的申请表单。</p>
          </div>
        </section>

        <aside className="image-repository-panel" aria-label="镜像仓库">
          <div className="image-repository-panel__header">
            <div>
              <h1>镜像仓库</h1>
            </div>
            <button className="btn btn--secondary" type="button" onClick={loadHarborImages} disabled={loading}>
              {loading ? '刷新中' : '刷新'}
            </button>
          </div>

          {error ? <div className="feedback feedback--error">{error}</div> : null}

          {!error ? (
            <>
              <ImageList
                title="我的镜像"
                project={harborInfo?.private_project}
                message={privateMessage}
                loading={loading}
                limit={3}
                variant="private"
              />
              <ImageList
                title="公有镜像"
                project={harborInfo?.public_project_info}
                message={publicMessage}
                loading={loading}
                limit={9}
                variant="public"
              />
            </>
          ) : null}
        </aside>
      </div>
    </AppShell>
  )
}
