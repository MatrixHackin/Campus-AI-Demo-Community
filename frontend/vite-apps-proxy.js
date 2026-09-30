import http from 'node:http'

const TRAEFIK_HOST = 'gpunion.hkust-gz.edu.cn'
const TRAEFIK_PORT = 80
const TRAEFIK_HOSTNAME = '127.0.0.1'
const MAX_REDIRECTS = 5
const HOP_BY_HOP = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'proxy-connection',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
])

function appNameFromPath(pathname) {
  const match = pathname.match(/^\/apps\/([^/]+)/)
  return match ? match[1] : ''
}

function copyRequestHeaders(req, incomingHost) {
  const headers = {}
  for (const [key, value] of Object.entries(req.headers)) {
    if (value == null || HOP_BY_HOP.has(key.toLowerCase())) continue
    headers[key] = value
  }
  headers.host = TRAEFIK_HOST
  headers['x-forwarded-host'] = incomingHost
  headers['x-forwarded-proto'] = 'http'
  headers['accept-encoding'] = 'identity'
  return headers
}

function copyResponseHeaders(source) {
  const headers = {}
  for (const [key, value] of Object.entries(source)) {
    if (value == null || HOP_BY_HOP.has(key.toLowerCase())) continue
    headers[key] = value
  }
  return headers
}

function resolveLocation(location, currentPath) {
  return new URL(location, `http://${TRAEFIK_HOST}${currentPath}`)
}

function shouldFollowRedirect(statusCode, locationUrl, appName) {
  if (![301, 302, 303, 307, 308].includes(statusCode) || !appName) return false
  const prefix = `/apps/${appName}`
  return locationUrl.pathname === prefix || locationUrl.pathname.startsWith(`${prefix}/`)
}

function rewriteLocation(location, currentPath, incomingHost) {
  const url = resolveLocation(location, currentPath)
  const internalHost = url.hostname === TRAEFIK_HOST
    || url.hostname === '127.0.0.1'
    || url.hostname === 'localhost'
    || url.hostname.startsWith('10.43.')
  if (!internalHost) return location
  return `${url.pathname}${url.search}`
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

function proxyOnce(req, path, incomingHost) {
  return new Promise((resolve, reject) => {
    const request = http.request(
      {
        hostname: TRAEFIK_HOSTNAME,
        port: TRAEFIK_PORT,
        path,
        method: req.method,
        headers: copyRequestHeaders(req, incomingHost),
      },
      (upstream) => {
        const chunks = []
        upstream.on('data', (chunk) => chunks.push(chunk))
        upstream.on('end', () => {
          resolve({
            statusCode: upstream.statusCode || 502,
            headers: upstream.headers,
            body: Buffer.concat(chunks),
          })
        })
      },
    )
    request.on('error', reject)
    if (req.method === 'GET' || req.method === 'HEAD') {
      request.end()
      return
    }
    req.pipe(request)
  })
}

async function proxyApps(req, res) {
  const incomingHost = req.headers.host || ''
  let path = req.url || '/'
  const appName = appNameFromPath(path.split('?')[0] || '')
  let response = await proxyOnce(req, path, incomingHost)

  for (let hop = 0; hop < MAX_REDIRECTS; hop += 1) {
    const location = response.headers.location
    if (!location) break
    const locationUrl = resolveLocation(location, path)
    if (!shouldFollowRedirect(response.statusCode, locationUrl, appName)) {
      response.headers.location = rewriteLocation(location, path, incomingHost)
      break
    }
    path = `${locationUrl.pathname}${locationUrl.search}`
    response = await proxyOnce(req, path, incomingHost)
  }

  const headers = copyResponseHeaders(response.headers)
  headers['x-campus-app-proxy'] = '1'
  if (headers.location) {
    headers.location = rewriteLocation(String(headers.location), path, incomingHost)
  }

  const contentType = String(headers['content-type'] || '')
  if (appName && response.statusCode === 200 && contentType.includes('text/html')) {
    const html = injectAppBase(response.body.toString('utf8'), appName)
    const body = Buffer.from(html)
    headers['content-length'] = String(body.length)
    delete headers['content-encoding']
    res.writeHead(response.statusCode, headers)
    res.end(body)
    return
  }

  res.writeHead(response.statusCode, headers)
  res.end(response.body)
}

function requestPath(req) {
  const raw = req.originalUrl || req.url || '/'
  if (raw.startsWith('http://') || raw.startsWith('https://')) {
    const url = new URL(raw)
    return `${url.pathname}${url.search}`
  }
  return raw
}

export function campusAppsProxy() {
  return {
    name: 'campus-apps-proxy',
    configureServer(server) {
      const handler = (req, res, next) => {
        const path = requestPath(req)
        if (!path.startsWith('/apps/')) {
          next()
          return
        }
        if (String(req.headers.upgrade || '').toLowerCase() === 'websocket') {
          next()
          return
        }
        req.url = path
        proxyApps(req, res).catch((error) => {
          if (!res.headersSent) {
            res.writeHead(502, { 'content-type': 'text/plain; charset=utf-8' })
          }
          res.end(`应用代理失败：${error.message}`)
        })
      }

      // 插到栈顶，避免 Vite 自带 /apps 代理或 SPA fallback 先处理。
      const install = () => {
        server.middlewares.stack.unshift({ route: '', handle: handler })
      }
      install()
      return install
    },
  }
}
