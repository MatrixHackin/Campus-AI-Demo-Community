export function getAppAccessUrl(app) {
  if (typeof window === 'undefined') {
    return app?.app_url || app?.url || ''
  }

  const name = String(app?.app_name || '').trim()
  if (name) {
    return `${window.location.origin}/apps/${name}/`
  }

  const raw = app?.app_url || app?.url || ''
  try {
    const parsed = new URL(raw, window.location.origin)
    if (parsed.pathname.startsWith('/apps/')) {
      return `${window.location.origin}${parsed.pathname}${parsed.search}`
    }
  } catch {
    return raw
  }

  return raw
}
