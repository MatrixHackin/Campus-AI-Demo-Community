const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim()
const fallbackBaseUrl = `${window.location.protocol}//${window.location.hostname}:8000/api/v1`
const API_BASE_URL = configuredBaseUrl || fallbackBaseUrl

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
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

export async function login(payload) {
  return request('/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export async function createSandbox(token, payload = {}) {
  return request('/sandboxes', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`
    },
    body: JSON.stringify(payload)
  })
}

export async function getMySandboxes(token) {
  return request('/sandboxes/me', {
    headers: {
      Authorization: `Bearer ${token}`
    }
  })
}
