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

export async function publishApp(podName, { appDescription, cover }) {
  const formData = new FormData()
  formData.append('app_description', appDescription)
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

export function getWebSshSocketUrl(appName, sshUsername) {
  const baseUrl = new URL(API_BASE_URL, window.location.origin)
  baseUrl.protocol = baseUrl.protocol === 'https:' ? 'wss:' : 'ws:'
  baseUrl.pathname = `${baseUrl.pathname.replace(/\/$/, '')}/ssh/ws/${encodeURIComponent(appName)}/${encodeURIComponent(sshUsername)}`
  baseUrl.search = ''
  return baseUrl.toString()
}
