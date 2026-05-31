import { useCallback, useEffect, useRef, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import {
  dismissNotification,
  getNotificationEventUrl,
  getNotificationUnreadCount,
  getNotifications,
  markAllNotificationsRead,
  markNotificationRead
} from '../api/client'
import { useAuth } from '../context/AuthContext'
import BrandLogo from './BrandLogo'
import SiteFooter from './SiteFooter'

const navItems = [
  { to: '/dashboard', label: '工作台' },
  { to: '/community', label: '应用市场' },
  { to: '/my-apps', label: '我的应用' },
  { to: '/manual', label: '开发手册' }
]

const adminNavItems = [
  { to: '/admin/publication-review', label: '发布审核' },
  { to: '/admin/notifications', label: '系统通知' }
]

const notificationTypeLabels = {
  system_announcement: '系统公告',
  admin_message: '管理员通知',
  review_rejected: '审核通知',
  review_approved: '审核通知'
}

function formatNotificationTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function NotificationDrawer({
  open,
  notifications,
  loading,
  error,
  unreadCount,
  onClose,
  onRefresh,
  onRead,
  onReadAll,
  onDismiss
}) {
  if (!open) return null

  return (
    <div className="notification-layer" role="presentation">
      <aside className="notification-drawer" role="dialog" aria-modal="true" aria-label="消息窗口">
        <div className="notification-drawer__head">
          <div>
            <h2>消息</h2>
            <p>{unreadCount > 0 ? `${unreadCount} 条未读` : '暂无未读消息'}</p>
          </div>
          <button className="modal-close" type="button" onClick={onClose} aria-label="关闭消息窗口">
            ×
          </button>
        </div>

        <div className="notification-drawer__toolbar">
          <button className="btn btn--secondary" type="button" onClick={onRefresh} disabled={loading}>
            {loading ? '刷新中…' : '刷新'}
          </button>
          <button className="btn btn--primary" type="button" onClick={onReadAll} disabled={loading || unreadCount === 0}>
            全部已读
          </button>
        </div>

        {error ? <div className="feedback feedback--error">{error}</div> : null}
        {loading ? <div className="muted-card muted-card--compact">正在加载消息…</div> : null}
        {!loading && notifications.length === 0 ? <div className="muted-card muted-card--compact">暂无消息。</div> : null}

        <div className="notification-list">
          {notifications.map((notification) => {
            const unread = !notification.read_at
            return (
              <article
                className={`notification-item${unread ? ' notification-item--unread' : ''}`}
                key={notification.id}
              >
                <div className="notification-item__title">
                  <h3>{notification.title}</h3>
                  <span>{notificationTypeLabels[notification.type] || notification.type}</span>
                </div>
                <p>{notification.content}</p>
                <div className="notification-item__meta">
                  <span>{formatNotificationTime(notification.created_at)}</span>
                  {notification.sender_username ? <span>来自：{notification.sender_username}</span> : null}
                </div>
                <div className="notification-item__actions">
                  <button
                    className="btn btn--secondary"
                    type="button"
                    onClick={() => onRead(notification)}
                    disabled={!unread}
                  >
                    标为已读
                  </button>
                  <button className="btn btn--ghost" type="button" onClick={() => onDismiss(notification)}>
                    移除
                  </button>
                </div>
              </article>
            )
          })}
        </div>
      </aside>
    </div>
  )
}

export default function AppShell({ children }) {
  const { user, logout } = useAuth()
  const location = useLocation()
  const displayName = user?.display_name || user?.username || '用户'
  const [notificationOpen, setNotificationOpen] = useState(false)
  const [notifications, setNotifications] = useState([])
  const [notificationsLoading, setNotificationsLoading] = useState(false)
  const [notificationsError, setNotificationsError] = useState('')
  const [unreadCount, setUnreadCount] = useState(0)
  const notificationOpenRef = useRef(false)
  const navLinksRef = useRef(null)

  useEffect(() => {
    notificationOpenRef.current = notificationOpen
  }, [notificationOpen])

  const loadUnreadCount = useCallback(async () => {
    try {
      const result = await getNotificationUnreadCount()
      setUnreadCount(result.unread_count || 0)
    } catch {
      setUnreadCount(0)
    }
  }, [])

  const loadNotifications = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setNotificationsLoading(true)
      setNotificationsError('')
    }
    try {
      const result = await getNotifications()
      setNotifications(result.notifications || [])
      setUnreadCount(result.unread_count || 0)
    } catch (err) {
      if (!silent) {
        setNotificationsError(err.message)
      }
    } finally {
      if (!silent) {
        setNotificationsLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    loadUnreadCount()
  }, [loadUnreadCount, user?.username])

  useEffect(() => {
    const refreshWhenVisible = () => {
      if (document.visibilityState === 'visible') {
        loadUnreadCount()
        if (notificationOpenRef.current) {
          loadNotifications({ silent: true })
        }
      }
    }
    window.addEventListener('focus', refreshWhenVisible)
    document.addEventListener('visibilitychange', refreshWhenVisible)
    return () => {
      window.removeEventListener('focus', refreshWhenVisible)
      document.removeEventListener('visibilitychange', refreshWhenVisible)
    }
  }, [loadNotifications, loadUnreadCount])

  useEffect(() => {
    const source = new EventSource(getNotificationEventUrl(), { withCredentials: true })
    source.addEventListener('notification.changed', (event) => {
      try {
        const payload = JSON.parse(event.data)
        if (typeof payload.unread_count === 'number') {
          setUnreadCount(payload.unread_count)
        } else {
          loadUnreadCount()
        }
      } catch {
        loadUnreadCount()
      }
      if (notificationOpenRef.current) {
        loadNotifications({ silent: true })
      }
    })
    source.onerror = () => {}
    return () => {
      source.close()
    }
  }, [loadNotifications, loadUnreadCount, user?.username])

  useEffect(() => {
    const activeLink = navLinksRef.current?.querySelector('.app-nav__link--active')
    activeLink?.scrollIntoView({ block: 'nearest', inline: 'center' })
  }, [location.pathname, user?.is_admin])

  const handleOpenNotifications = useCallback(() => {
    setNotificationOpen(true)
    loadNotifications()
  }, [loadNotifications])

  const handleMarkRead = useCallback(async (notification) => {
    setNotificationsError('')
    try {
      await markNotificationRead(notification.id)
      await loadNotifications({ silent: true })
    } catch (err) {
      setNotificationsError(err.message)
    }
  }, [loadNotifications])

  const handleMarkAllRead = useCallback(async () => {
    setNotificationsError('')
    try {
      const result = await markAllNotificationsRead()
      setUnreadCount(result.unread_count || 0)
      await loadNotifications({ silent: true })
    } catch (err) {
      setNotificationsError(err.message)
    }
  }, [loadNotifications])

  const handleDismiss = useCallback(async (notification) => {
    setNotificationsError('')
    try {
      const result = await dismissNotification(notification.id)
      setUnreadCount(result.unread_count || 0)
      await loadNotifications({ silent: true })
    } catch (err) {
      setNotificationsError(err.message)
    }
  }, [loadNotifications])

  return (
    <div className="site-shell app-shell">
      <header className="app-nav">
        <div className="site-brand" aria-label="Campus AI Community">
          <BrandLogo />
          <span>Campus AI Community</span>
        </div>

        <nav className="app-nav__links" aria-label="应用导航" ref={navLinksRef}>
          {[...navItems, ...(user?.is_admin ? adminNavItems : [])].map((item) => (
            <NavLink
              key={item.to}
              className={({ isActive }) => `app-nav__link${isActive ? ' app-nav__link--active' : ''}`}
              to={item.to}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="app-nav__account">
          <button className="notification-button" type="button" onClick={handleOpenNotifications}>
            消息
            {unreadCount > 0 ? <span>{unreadCount > 99 ? '99+' : unreadCount}</span> : null}
          </button>
          <span className="user-name">{displayName}</span>
          <button className="btn btn--secondary" onClick={logout}>
            退出
          </button>
        </div>
      </header>

      <main className="app-blank-main">{children}</main>
      <NotificationDrawer
        open={notificationOpen}
        notifications={notifications}
        loading={notificationsLoading}
        error={notificationsError}
        unreadCount={unreadCount}
        onClose={() => setNotificationOpen(false)}
        onRefresh={() => loadNotifications()}
        onRead={handleMarkRead}
        onReadAll={handleMarkAllRead}
        onDismiss={handleDismiss}
      />
      <SiteFooter />
    </div>
  )
}
