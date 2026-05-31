import { useCallback, useEffect, useState } from 'react'
import {
  createAdminNotification,
  deleteAdminNotification,
  getAdminNotifications
} from '../api/client'
import AppShell from '../components/AppShell'

const notificationTypeOptions = [
  { value: 'system_announcement', label: '系统公告' },
  { value: 'admin_message', label: '管理员通知' }
]

const notificationScopeOptions = [
  { value: 'all', label: '全员' },
  { value: 'user', label: '指定用户' }
]

const notificationTypeLabels = {
  system_announcement: '系统公告',
  admin_message: '管理员通知',
  review_rejected: '审核通知',
  review_approved: '审核通知'
}

function formatDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', { hour12: false })
}

const initialForm = {
  title: '',
  content: '',
  type: 'system_announcement',
  scope: 'all',
  recipient_username: '',
  expires_at: ''
}

export default function AdminNotificationsPage() {
  const [form, setForm] = useState(initialForm)
  const [notifications, setNotifications] = useState([])
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [deletingId, setDeletingId] = useState(null)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const loadNotifications = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await getAdminNotifications()
      setNotifications(result.notifications || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadNotifications()
  }, [loadNotifications])

  const handleSubmit = useCallback(async (event) => {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    setSuccess('')
    try {
      await createAdminNotification({
        title: form.title.trim(),
        content: form.content.trim(),
        type: form.type,
        scope: form.scope,
        recipient_username: form.scope === 'user' ? form.recipient_username.trim() : null,
        expires_at: form.expires_at || null
      })
      setForm(initialForm)
      setSuccess('通知已发送')
      await loadNotifications()
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }, [form, loadNotifications])

  const handleDelete = useCallback(async (notification) => {
    const confirmed = window.confirm(`确定删除通知「${notification.title}」吗？`)
    if (!confirmed) return
    setDeletingId(notification.id)
    setError('')
    setSuccess('')
    try {
      await deleteAdminNotification(notification.id)
      setSuccess('通知已删除')
      await loadNotifications()
    } catch (err) {
      setError(err.message)
    } finally {
      setDeletingId(null)
    }
  }, [loadNotifications])

  return (
    <AppShell>
      <section className="admin-notification-panel" aria-label="系统通知">
        <div className="admin-review-panel__head">
          <div>
            <h1>系统通知</h1>
            <p>向所有用户发送公告，或向指定用户推送消息。</p>
          </div>
          <button className="btn btn--secondary" type="button" onClick={loadNotifications} disabled={loading}>
            {loading ? '刷新中…' : '刷新'}
          </button>
        </div>

        {error ? <div className="feedback feedback--error">{error}</div> : null}
        {success ? <div className="feedback feedback--success">{success}</div> : null}

        <form className="admin-notification-form" onSubmit={handleSubmit}>
          <div className="admin-notification-form__row">
            <label>
              <span>类型</span>
              <select
                value={form.type}
                onChange={(event) => setForm((prev) => ({ ...prev, type: event.target.value }))}
                disabled={submitting}
              >
                {notificationTypeOptions.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label>
              <span>范围</span>
              <select
                value={form.scope}
                onChange={(event) => setForm((prev) => ({ ...prev, scope: event.target.value }))}
                disabled={submitting}
              >
                {notificationScopeOptions.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label>
              <span>接收用户名</span>
              <input
                type="text"
                value={form.recipient_username}
                onChange={(event) => setForm((prev) => ({ ...prev, recipient_username: event.target.value }))}
                disabled={submitting || form.scope === 'all'}
                placeholder={form.scope === 'all' ? '全员通知无需填写' : '例如 dylanhemuliu'}
              />
            </label>
            <label>
              <span>过期时间</span>
              <input
                type="datetime-local"
                value={form.expires_at}
                onChange={(event) => setForm((prev) => ({ ...prev, expires_at: event.target.value }))}
                disabled={submitting}
              />
            </label>
          </div>

          <label>
            <span>标题</span>
            <input
              type="text"
              value={form.title}
              maxLength={120}
              onChange={(event) => setForm((prev) => ({ ...prev, title: event.target.value }))}
              disabled={submitting}
              required
            />
          </label>

          <label>
            <span>内容</span>
            <textarea
              value={form.content}
              maxLength={2000}
              rows={5}
              onChange={(event) => setForm((prev) => ({ ...prev, content: event.target.value }))}
              disabled={submitting}
              required
            />
          </label>

          <div className="admin-notification-form__actions">
            <button className="btn btn--primary" type="submit" disabled={submitting}>
              {submitting ? '发送中…' : '发送通知'}
            </button>
          </div>
        </form>

        {loading ? <div className="muted-card">正在加载通知…</div> : null}
        {!loading && notifications.length === 0 ? <div className="muted-card">暂无通知。</div> : null}

        <div className="admin-notification-list">
          {notifications.map((notification) => (
            <article className="admin-notification-item" key={notification.id}>
              <div className="admin-notification-item__main">
                <div className="admin-review-item__title">
                  <h2>{notification.title}</h2>
                  <span>{notificationTypeLabels[notification.type] || notification.type}</span>
                </div>
                <p>{notification.content}</p>
                <div className="admin-review-item__meta">
                  <span>范围：{notification.scope === 'all' ? '全员' : notification.recipient_username}</span>
                  <span>发送：{formatDateTime(notification.created_at)}</span>
                  <span>过期：{formatDateTime(notification.expires_at)}</span>
                </div>
              </div>
              <div className="admin-review-item__actions">
                <button
                  className="btn btn--ghost"
                  type="button"
                  onClick={() => handleDelete(notification)}
                  disabled={deletingId === notification.id}
                >
                  {deletingId === notification.id ? '删除中…' : '删除'}
                </button>
              </div>
            </article>
          ))}
        </div>
      </section>
    </AppShell>
  )
}
