const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim()
const fallbackBaseUrl = `${window.location.protocol}//${window.location.hostname}:8000/api/v1`
const API_BASE_URL = configuredBaseUrl || fallbackBaseUrl

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {})
    },
    ...options
  })

  const data = await response.json().catch(() => ({}))

  if (!response.ok) {
    throw new Error(data.detail || '请求失败，请稍后重试')
  }

  return data
}

async function requestForm(path, formData, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: 'include',
    ...options,
    body: formData
  })

  const data = await response.json().catch(() => ({}))

  if (!response.ok) {
    throw new Error(data.detail || '请求失败，请稍后重试')
  }

  return data
}

export async function login(payload) {
  return request('/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export async function getCurrentUser() {
  return request('/auth/me')
}

export async function getNotifications({ unreadOnly = false, limit = 50, offset = 0 } = {}) {
  const query = new URLSearchParams({
    unread_only: unreadOnly ? 'true' : 'false',
    limit: String(limit),
    offset: String(offset)
  }).toString()
  return request(`/notifications?${query}`)
}

export async function getNotificationUnreadCount() {
  return request('/notifications/unread-count')
}

export async function markNotificationRead(notificationId) {
  return request(`/notifications/${encodeURIComponent(notificationId)}/read`, {
    method: 'POST'
  })
}

export async function markAllNotificationsRead() {
  return request('/notifications/read-all', {
    method: 'POST'
  })
}

export async function dismissNotification(notificationId) {
  return request(`/notifications/${encodeURIComponent(notificationId)}/dismiss`, {
    method: 'POST'
  })
}

export async function getMyHarborImages({ includeTags = false } = {}) {
  const query = includeTags ? '?include_tags=true' : ''
  return request(`/harbor/me${query}`)
}

export async function createDevboxContainer(payload) {
  return request('/k3s/devbox', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export async function getMyContainers() {
  return request('/k3s/containers')
}

export async function getMyAppsUsage() {
  return request('/k3s/my-apps/usage')
}

export async function getContainerUsageTrend(podName) {
  return request(`/k3s/containers/${encodeURIComponent(podName)}/usage-trend`)
}

export async function deleteContainer(podName) {
  return request(`/k3s/containers/${encodeURIComponent(podName)}`, {
    method: 'DELETE'
  })
}

export async function commitContainer(podName, imageName) {
  return request(`/k3s/containers/${encodeURIComponent(podName)}/commit`, {
    method: 'POST',
    body: JSON.stringify({ image_name: imageName })
  })
}

export async function getK3sJobStatus(jobName) {
  return request(`/k3s/jobs/${encodeURIComponent(jobName)}`)
}

export async function checkAppName(appName) {
  const query = new URLSearchParams({ app_name: appName }).toString()
  return request(`/k3s/apps/check-name?${query}`)
}

export async function getPublishedApps() {
  return request('/community/apps')
}

export async function getPublicationSettings() {
  return request('/community/publication-settings')
}

export async function getMyPublicationStatuses(podNames) {
  if (!podNames.length) {
    return { statuses: [] }
  }
  const query = new URLSearchParams()
  podNames.forEach((podName) => query.append('pod_names', podName))
  return request(`/community/publication-status?${query.toString()}`)
}

export async function recordAppVisit(publicationId) {
  return request(`/community/apps/${encodeURIComponent(publicationId)}/visit`, {
    method: 'POST'
  })
}

export async function toggleAppLike(publicationId) {
  return request(`/community/apps/${encodeURIComponent(publicationId)}/like`, {
    method: 'POST'
  })
}

export async function getAppReviews(publicationId, { offset = 0, limit = 10, sort = 'desc' } = {}) {
  const query = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
    sort
  }).toString()
  return request(`/community/apps/${encodeURIComponent(publicationId)}/reviews?${query}`)
}

export async function submitAppReview(publicationId, { rating, comment }) {
  return request(`/community/apps/${encodeURIComponent(publicationId)}/review`, {
    method: 'POST',
    body: JSON.stringify({ rating, comment })
  })
}

export async function deleteAppReview(publicationId) {
  return request(`/community/apps/${encodeURIComponent(publicationId)}/review`, {
    method: 'DELETE'
  })
}

export async function publishApp(podName, { appDescription, cover, responsibilityAck }) {
  const formData = new FormData()
  formData.append('app_description', appDescription)
  formData.append('responsibility_ack', responsibilityAck ? 'true' : 'false')
  if (cover) {
    formData.append('cover', cover, cover.name || 'cover.webp')
  }
  return requestForm(`/community/apps/${encodeURIComponent(podName)}/publish`, formData, {
    method: 'POST'
  })
}

export async function unpublishApp(podName) {
  return request(`/community/apps/${encodeURIComponent(podName)}/publish`, {
    method: 'DELETE'
  })
}

export async function getAdminPublicationSettings() {
  return request('/admin/publication/settings')
}

export async function updateAdminPublicationSettings(payload) {
  return request('/admin/publication/settings', {
    method: 'PUT',
    body: JSON.stringify(payload)
  })
}

export async function getPublicationReviewItems(status = 'pending') {
  const query = new URLSearchParams({ status }).toString()
  return request(`/admin/publication/reviews?${query}`)
}

export async function approvePublicationReview(publicationId, { reviewNote } = {}) {
  return request(`/admin/publication/reviews/${encodeURIComponent(publicationId)}/approve`, {
    method: 'POST',
    body: JSON.stringify({ review_note: reviewNote || null })
  })
}

export async function rejectPublicationReview(publicationId, { rejectReason, reviewNote } = {}) {
  return request(`/admin/publication/reviews/${encodeURIComponent(publicationId)}/reject`, {
    method: 'POST',
    body: JSON.stringify({
      reject_reason: rejectReason,
      review_note: reviewNote || null
    })
  })
}

export async function getAdminNotifications() {
  return request('/admin/notifications')
}

export async function createAdminNotification(payload) {
  return request('/admin/notifications', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export async function deleteAdminNotification(notificationId) {
  return request(`/admin/notifications/${encodeURIComponent(notificationId)}`, {
    method: 'DELETE'
  })
}

export function getNotificationEventUrl() {
  const baseUrl = new URL(API_BASE_URL, window.location.origin)
  baseUrl.pathname = `${baseUrl.pathname.replace(/\/$/, '')}/notifications/events`
  baseUrl.search = ''
  return baseUrl.toString()
}

export function getWebSshSocketUrl(appName, sshUsername) {
  const baseUrl = new URL(API_BASE_URL, window.location.origin)
  baseUrl.protocol = baseUrl.protocol === 'https:' ? 'wss:' : 'ws:'
  baseUrl.pathname = `${baseUrl.pathname.replace(/\/$/, '')}/ssh/ws/${encodeURIComponent(appName)}/${encodeURIComponent(sshUsername)}`
  baseUrl.search = ''
  return baseUrl.toString()
}
