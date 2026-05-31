import { useCallback, useEffect, useState } from 'react'
import {
  approvePublicationReview,
  getAdminPublicationSettings,
  getPublicationReviewItems,
  rejectPublicationReview,
  updateAdminPublicationSettings
} from '../api/client'
import AppShell from '../components/AppShell'

const STATUS_OPTIONS = [
  { value: 'pending', label: '待审核' },
  { value: 'approved', label: '已通过' },
  { value: 'rejected', label: '已拒绝' },
  { value: 'all', label: '全部' }
]

const STATUS_LABELS = {
  pending: '待审核',
  approved: '已通过',
  rejected: '已拒绝',
  unpublished: '已下架'
}

function formatDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', { hour12: false })
}

export default function AdminPublicationReviewPage() {
  const [settings, setSettings] = useState({ review_policy: 'no_review', responsibility_ack_version: '' })
  const [status, setStatus] = useState('pending')
  const [apps, setApps] = useState([])
  const [loading, setLoading] = useState(true)
  const [savingSettings, setSavingSettings] = useState(false)
  const [processingId, setProcessingId] = useState(null)
  const [error, setError] = useState('')

  const loadSettings = useCallback(async () => {
    const result = await getAdminPublicationSettings()
    setSettings(result)
  }, [])

  const loadItems = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await getPublicationReviewItems(status)
      setApps(result.apps || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [status])

  useEffect(() => {
    loadSettings().catch((err) => setError(err.message))
  }, [loadSettings])

  useEffect(() => {
    loadItems()
  }, [loadItems])

  const handleSaveSettings = useCallback(async (event) => {
    event.preventDefault()
    setSavingSettings(true)
    setError('')
    try {
      const result = await updateAdminPublicationSettings(settings)
      setSettings(result)
    } catch (err) {
      setError(err.message)
    } finally {
      setSavingSettings(false)
    }
  }, [settings])

  const handleApprove = useCallback(async (app) => {
    setProcessingId(app.id)
    setError('')
    try {
      await approvePublicationReview(app.id)
      await loadItems()
    } catch (err) {
      setError(err.message)
    } finally {
      setProcessingId(null)
    }
  }, [loadItems])

  const handleReject = useCallback(async (app) => {
    const reason = window.prompt(`请输入拒绝 ${app.app_name} 的原因：`)
    if (!reason) return
    setProcessingId(app.id)
    setError('')
    try {
      await rejectPublicationReview(app.id, { rejectReason: reason.trim() })
      await loadItems()
    } catch (err) {
      setError(err.message)
    } finally {
      setProcessingId(null)
    }
  }, [loadItems])

  return (
    <AppShell>
      <section className="admin-review-panel" aria-label="应用发布审核">
        <div className="admin-review-panel__head">
          <div>
            <h1>应用发布审核</h1>
            <p>控制应用市场发布策略，并处理待审核应用。</p>
          </div>
          <button className="btn btn--secondary" type="button" onClick={loadItems} disabled={loading}>
            {loading ? '刷新中…' : '刷新'}
          </button>
        </div>

        {error ? <div className="feedback feedback--error">{error}</div> : null}

        <form className="admin-review-settings" onSubmit={handleSaveSettings}>
          <label>
            <span>审核策略</span>
            <select
              value={settings.review_policy}
              onChange={(event) => setSettings((prev) => ({ ...prev, review_policy: event.target.value }))}
              disabled={savingSettings}
            >
              <option value="no_review">不审核，用户提交后直接展示</option>
              <option value="require_review">都要审核，通过后展示</option>
            </select>
          </label>
          <label>
            <span>责任承诺版本</span>
            <input
              type="text"
              value={settings.responsibility_ack_version || ''}
              maxLength={32}
              onChange={(event) => setSettings((prev) => ({ ...prev, responsibility_ack_version: event.target.value }))}
              disabled={savingSettings}
            />
          </label>
          <button className="btn btn--primary" type="submit" disabled={savingSettings}>
            {savingSettings ? '保存中…' : '保存策略'}
          </button>
        </form>

        <div className="admin-review-tabs" role="tablist" aria-label="审核状态">
          {STATUS_OPTIONS.map((option) => (
            <button
              key={option.value}
              className={`admin-review-tab${status === option.value ? ' admin-review-tab--active' : ''}`}
              type="button"
              onClick={() => setStatus(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>

        {loading ? <div className="muted-card">正在加载审核列表…</div> : null}
        {!loading && apps.length === 0 ? <div className="muted-card">当前没有应用。</div> : null}

        <div className="admin-review-list">
          {apps.map((app) => (
            <article className="admin-review-item" key={app.id}>
              <div className="admin-review-item__main">
                <div className="admin-review-item__title">
                  <h2>{app.app_name}</h2>
                  <span>{STATUS_LABELS[app.review_status] || app.review_status}</span>
                </div>
                <p>{app.app_description || '未填写应用简述'}</p>
                <div className="admin-review-item__meta">
                  <span>作者：{app.owner_display_name || app.owner_username}</span>
                  <span>提交：{formatDateTime(app.submitted_at)}</span>
                  <span>承诺：{app.responsibility_ack ? app.responsibility_ack_version || '已确认' : '未确认'}</span>
                </div>
                {app.reject_reason ? <div className="feedback feedback--error">{app.reject_reason}</div> : null}
              </div>
              <div className="admin-review-item__actions">
                <button className="btn btn--secondary" type="button" onClick={() => window.open(app.app_url, '_blank', 'noopener,noreferrer')}>
                  打开应用
                </button>
                <button
                  className="btn btn--primary"
                  type="button"
                  onClick={() => handleApprove(app)}
                  disabled={processingId === app.id || app.review_status === 'approved'}
                >
                  通过
                </button>
                <button
                  className="btn btn--ghost"
                  type="button"
                  onClick={() => handleReject(app)}
                  disabled={processingId === app.id || app.review_status === 'rejected'}
                >
                  拒绝
                </button>
              </div>
            </article>
          ))}
        </div>
      </section>
    </AppShell>
  )
}
