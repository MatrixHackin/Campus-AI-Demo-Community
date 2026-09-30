const APP_PATH_PATTERN = /^\/apps\/([^/]+)/
const REDIRECT_STATUSES = new Set([301, 302, 303, 307, 308])

function appNameFromPath(pathname) {
  const match = pathname.match(APP_PATH_PATTERN)
  return match ? match[1] : ''
}

function injectAppBase(html, appName) {
  const baseTag = `<base href="/apps/${appName}/">`
  if (/<base\b[^>]*>/i.test(html)) {
    return html.replace(/<base\b[^>]*>/i, baseTag)
  }
  if (/<head\b[^>]*>/i.test(html)) {
    return html.replace(/<head\b[^>]*>/i, (openTag) => `${openTag}${baseTag}`)
  }
  return html
}

function isSameAppRedirect(requestUrl, location, appName) {
  if (!appName || !location) return false
  const nextUrl = new URL(location, requestUrl)
  const prefix = `/apps/${appName}`
  return nextUrl.pathname === prefix || nextUrl.pathname.startsWith(`${prefix}/`)
}

async function handleAppRequest(request) {
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return fetch(request)
  }

  const originalUrl = new URL(request.url)
  const appName = appNameFromPath(originalUrl.pathname)
  if (!appName) return fetch(request)

  let currentUrl = originalUrl.href
  let response = await fetch(currentUrl, {
    method: request.method,
    headers: request.headers,
    redirect: 'manual',
    cache: 'no-store',
    credentials: 'include',
  })

  for (let hop = 0; hop < 5; hop += 1) {
    if (!REDIRECT_STATUSES.has(response.status)) break
    const location = response.headers.get('Location')
    if (!isSameAppRedirect(currentUrl, location, appName)) break
    currentUrl = new URL(location, currentUrl).href
    response = await fetch(currentUrl, {
      method: 'GET',
      redirect: 'manual',
      cache: 'no-store',
      credentials: 'include',
    })
  }

  const contentType = response.headers.get('content-type') || ''
  if (request.method !== 'GET' || !contentType.includes('text/html') || response.status !== 200) {
    return response
  }

  const html = injectAppBase(await response.text(), appName)
  const headers = new Headers(response.headers)
  headers.delete('content-length')
  headers.set('cache-control', 'no-store')
  return new Response(html, {
    status: 200,
    statusText: response.statusText,
    headers,
  })
}

self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting())
})

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim())
})

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url)
  if (url.origin !== self.location.origin || !url.pathname.startsWith('/apps/')) {
    return
  }
  event.respondWith(handleAppRequest(event.request))
})
