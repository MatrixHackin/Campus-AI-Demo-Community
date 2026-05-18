import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getContainerUsageTrend, getMyContainers } from '../api/client'
import AppShell from '../components/AppShell'

const MONITOR_REFRESH_MS = 30000
const MONITOR_AUTO_COLLAPSE_MS = 3 * 60 * 1000

function formatBytes(value, fractionDigits = 1) {
  const number = Number(value || 0)
  if (number < 1024) return `${number.toFixed(0)} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let current = number / 1024
  for (const unit of units) {
    if (current < 1024 || unit === units[units.length - 1]) {
      return `${current.toFixed(fractionDigits)} ${unit}`
    }
    current /= 1024
  }
  return `${number.toFixed(0)} B`
}

function formatDuration(seconds) {
  const value = Math.max(0, Number(seconds || 0))
  const days = Math.floor(value / 86400)
  const hours = Math.floor((value % 86400) / 3600)
  const minutes = Math.floor((value % 3600) / 60)
  if (days > 0) return `${days}天 ${hours}小时`
  if (hours > 0) return `${hours}小时 ${minutes}分钟`
  return `${minutes}分钟`
}

function formatMetricValue(value, unit) {
  const number = Number(value || 0)
  if (unit === 'bytes') return formatBytes(number)
  if (unit === 'bytes/s') return `${formatBytes(number)}/s`
  if (unit === 'cores') return `${number.toFixed(3)} 核`
  return number.toFixed(2)
}

function formatSampleTime(timestamp) {
  const date = new Date(Number(timestamp || 0) * 1000)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleTimeString('zh-CN', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

function runningSeconds(app, now) {
  if (app.start_time) {
    const start = new Date(app.start_time).getTime()
    if (Number.isFinite(start)) {
      return Math.max(0, Math.floor((now - start) / 1000))
    }
  }
  return app.duration || 0
}

function TrendChart({ series }) {
  const [activePoint, setActivePoint] = useState(null)
  const points = series.points || []
  const current = Number(series.current_value ?? (points.length > 0 ? points[points.length - 1].value : 0))
  const chart = useMemo(() => {
    if (points.length === 0) {
      return { polyline: '', points: [] }
    }
    const values = points.map((point) => Number(point.value || 0))
    const max = Math.max(...values)
    const min = Math.min(...values)
    const span = max - min
    const isFlat = span <= Math.max(1e-12, Math.abs(max) * 1e-6)
    const timestamps = points.map((point) => Number(point.timestamp || 0)).filter((timestamp) => Number.isFinite(timestamp))
    const firstTimestamp = timestamps.length ? Math.min(...timestamps) : 0
    const lastTimestamp = timestamps.length ? Math.max(...timestamps) : firstTimestamp
    const timeSpan = lastTimestamp - firstTimestamp
    const chartPoints = points.map((point) => {
      const timestamp = Number(point.timestamp || 0)
      const x = timeSpan > 0 ? ((timestamp - firstTimestamp) / timeSpan) * 120 : 60
      const y = isFlat
        ? (max > 0 ? 27 : 44)
        : 44 - ((Number(point.value || 0) - min) / span) * 34
      return {
        x,
        y,
        timestamp,
        value: Number(point.value || 0)
      }
    })
    const polyline = chartPoints
      .map((point) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`)
      .join(' ')
    return { polyline, points: chartPoints }
  }, [points])

  return (
    <div className="usage-trend-card">
      <div className="usage-trend-card__head">
        <span>{series.label}</span>
        <strong>{formatMetricValue(current, series.unit)}</strong>
      </div>
      <svg className="usage-trend-card__chart" viewBox="0 0 120 48" preserveAspectRatio="none" role="img" aria-label={`${series.label} 资源趋势`}>
        <line x1="0" y1="44" x2="120" y2="44" />
        <line x1="0" y1="27" x2="120" y2="27" />
        <line x1="0" y1="10" x2="120" y2="10" />
        {chart.polyline ? <polyline points={chart.polyline} /> : null}
        {chart.points.map((point) => (
          <g
            className="usage-trend-point"
            key={`${point.timestamp}-${point.value}`}
            onMouseEnter={() => setActivePoint(point)}
            onMouseLeave={() => setActivePoint(null)}
            onFocus={() => setActivePoint(point)}
            onBlur={() => setActivePoint(null)}
            tabIndex={0}
          >
            <circle className="usage-trend-point__hit" cx={point.x} cy={point.y} r="5.8" />
            <circle className="usage-trend-point__dot" cx={point.x} cy={point.y} r="1.6" />
          </g>
        ))}
      </svg>
      {activePoint ? (
        <div
          className="usage-trend-tooltip"
          style={{ left: `${Math.min(96, Math.max(4, (activePoint.x / 120) * 100))}%` }}
        >
          <strong>{formatMetricValue(activePoint.value, series.unit)}</strong>
          <span>{formatSampleTime(activePoint.timestamp)}</span>
        </div>
      ) : null}
    </div>
  )
}

function AppCard({ app, now }) {
  const [expanded, setExpanded] = useState(false)
  const [trend, setTrend] = useState(null)
  const [loadingTrend, setLoadingTrend] = useState(false)
  const [trendError, setTrendError] = useState('')
  const refreshTimerRef = useRef(null)
  const collapseTimerRef = useRef(null)

  const clearMonitorTimers = useCallback(() => {
    if (refreshTimerRef.current) {
      window.clearInterval(refreshTimerRef.current)
      refreshTimerRef.current = null
    }
    if (collapseTimerRef.current) {
      window.clearTimeout(collapseTimerRef.current)
      collapseTimerRef.current = null
    }
  }, [])

  const closeMonitor = useCallback(() => {
    clearMonitorTimers()
    setExpanded(false)
    setTrend(null)
    setTrendError('')
    setLoadingTrend(false)
  }, [clearMonitorTimers])

  const loadTrend = useCallback(async ({ showLoading = false } = {}) => {
    if (showLoading) setLoadingTrend(true)
    setTrendError('')
    try {
      const result = await getContainerUsageTrend(app.name)
      setTrend(result)
    } catch (err) {
      setTrendError(err.message)
    } finally {
      if (showLoading) setLoadingTrend(false)
    }
  }, [app.name])

  const openMonitor = useCallback(() => {
    clearMonitorTimers()
    setExpanded(true)
    loadTrend({ showLoading: true })
    refreshTimerRef.current = window.setInterval(() => {
      loadTrend()
    }, MONITOR_REFRESH_MS)
    collapseTimerRef.current = window.setTimeout(() => {
      closeMonitor()
    }, MONITOR_AUTO_COLLAPSE_MS)
  }, [clearMonitorTimers, closeMonitor, loadTrend])

  useEffect(() => clearMonitorTimers, [clearMonitorTimers])

  return (
    <article className="my-app-card my-app-card--compact">
      <div className="my-app-card__header">
        <div>
          <h2>{app.app_name || app.name}</h2>
          <div className="my-app-card__meta my-app-card__meta--single">
            <span>运行：{formatDuration(runningSeconds(app, now))}</span>
          </div>
        </div>
        <span className={`container-status container-status--${app.status?.toLowerCase() || 'unknown'}`}>
          {app.status || 'Unknown'}
        </span>
      </div>

      <div className="my-app-card__actions">
        <button className="btn btn--primary" type="button" onClick={expanded ? closeMonitor : openMonitor} disabled={loadingTrend}>
          {expanded ? '收起资源消耗' : '查看资源消耗'}
        </button>
      </div>

      {expanded ? (
        <div className="usage-trends-panel">
          {trendError ? <div className="feedback feedback--error">{trendError}</div> : null}
          {loadingTrend && !trend ? <div className="muted-card muted-card--compact">正在获取监控数据…</div> : null}
          {trend?.series?.length ? (
            <div className="usage-trends-grid">
              {trend.series.map((series) => (
                <TrendChart key={series.key} series={series} />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  )
}

export default function MyAppsPage() {
  const [appsInfo, setAppsInfo] = useState({ containers: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [now, setNow] = useState(Date.now())

  const loadApps = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await getMyContainers()
      setAppsInfo(result)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadApps()
  }, [loadApps])

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60000)
    return () => window.clearInterval(timer)
  }, [])

  const apps = appsInfo.containers || []

  return (
    <AppShell>
      <section className="my-apps-panel" aria-label="我的应用">
        {error ? <div className="feedback feedback--error">{error}</div> : null}
        {loading ? <div className="muted-card">正在加载应用…</div> : null}
        {!loading && !error && apps.length === 0 ? <div className="muted-card">暂无运行中的应用。</div> : null}
        {!loading && !error && apps.length > 0 ? (
          <div className="my-apps-grid">
            {apps.map((app) => (
              <AppCard app={app} key={app.name} now={now} />
            ))}
          </div>
        ) : null}
      </section>
    </AppShell>
  )
}
