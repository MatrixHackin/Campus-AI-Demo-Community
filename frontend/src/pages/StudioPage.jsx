import { useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { listAgentConfigs, streamAgentTurn } from '../api/client'
import AppShell from '../components/AppShell'

const storageVersion = 'v1'
const titlebarHeight = 28
const phoneBezel = 12
const viewports = {
  desktop: { width: 1280, height: 800 },
  mobile: { width: 390, height: 844 }
}

function storageKey(appName) {
  return `studioTranscript:${storageVersion}:${appName}`
}

function loadEntries(appName) {
  try {
    const raw = localStorage.getItem(storageKey(appName))
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.slice(-40).map((item) => (
      item.status === 'pending' && !item.runId
        ? { ...item, status: 'failed', error: item.error || '这一轮在页面刷新前没有返回' }
        : item
    ))
  } catch {
    return []
  }
}

function saveEntries(appName, entries) {
  try {
    localStorage.setItem(storageKey(appName), JSON.stringify(entries.slice(-40)))
  } catch {
    // 隐私模式或配额用尽时，这一次对话仍留在当前页面。
  }
}

function clock(value) {
  return new Date(value).toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit' })
}

function usePreviewScale(frame) {
  const ref = useRef(null)
  const [scale, setScale] = useState(1)
  const viewport = viewports[frame]

  useEffect(() => {
    const el = ref.current
    if (!el) return undefined
    const update = () => {
      const width = el.clientWidth
      const height = el.clientHeight
      if (width <= 0 || height <= 0) return
      const extraWidth = frame === 'mobile' ? phoneBezel * 2 : 0
      const extraHeight = frame === 'mobile' ? phoneBezel * 2 : titlebarHeight
      const next = Math.min((width - extraWidth) / viewport.width, (height - extraHeight) / viewport.height, 1)
      const safe = next > 0.05 ? next : 0.05
      setScale((current) => (Math.abs(current - safe) < 0.005 ? current : safe))
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(el)
    return () => observer.disconnect()
  }, [frame, viewport.width, viewport.height])

  return { ref, scale, viewport }
}

function DesktopIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true">
      <rect x="1.5" y="2.5" width="13" height="8.5" rx="1.2" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path d="M5.5 13.5h5M8 11v2.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  )
}

function PhoneIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true">
      <rect x="4.25" y="1.5" width="7.5" height="13" rx="1.6" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path d="M7 12.75h2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  )
}

function PreviewPane({ appName, frame, previewKey, previewUrl, onFrame, onRefresh }) {
  const { ref, scale, viewport } = usePreviewScale(frame)
  const screenWidth = viewport.width * scale
  const screenHeight = viewport.height * scale
  const preview = (
    <iframe
      key={previewKey}
      title={`${appName} 预览`}
      src={previewUrl}
      style={{ width: viewport.width, height: viewport.height, transform: `scale(${scale})` }}
    />
  )

  return (
    <section className="studio-preview" aria-label="网站预览">
      <div className="preview-toolbar">
        <button className="btn btn--secondary preview-refresh" type="button" onClick={onRefresh}>
          刷新预览
        </button>
        <div className="preview-switch" role="group" aria-label="预览宽度">
          <button
            className={frame === 'desktop' ? 'preview-switch__btn is-on' : 'preview-switch__btn'}
            type="button"
            aria-pressed={frame === 'desktop'}
            aria-label="电脑预览"
            onClick={() => onFrame('desktop')}
          >
            <DesktopIcon />
          </button>
          <button
            className={frame === 'mobile' ? 'preview-switch__btn is-on' : 'preview-switch__btn'}
            type="button"
            aria-pressed={frame === 'mobile'}
            aria-label="手机预览"
            onClick={() => onFrame('mobile')}
          >
            <PhoneIcon />
          </button>
        </div>
      </div>
      <div className="preview-stage" ref={ref}>
        {frame === 'mobile' ? (
          <div className="phone-device" style={{ width: screenWidth + phoneBezel * 2, height: screenHeight + phoneBezel * 2 }}>
            <div className="phone-device__screen" style={{ width: screenWidth, height: screenHeight }}>
              {preview}
            </div>
          </div>
        ) : (
          <div className="mac-browser" style={{ width: screenWidth, height: screenHeight + titlebarHeight }}>
            <div className="mac-browser__chrome">
              <span className="mac-dots" aria-hidden="true">
                <i className="mac-dot mac-dot--close" />
                <i className="mac-dot mac-dot--min" />
                <i className="mac-dot mac-dot--zoom" />
              </span>
              <span className="mac-browser__url">{`/apps/${appName}/`}</span>
            </div>
            <div className="mac-browser__screen" style={{ width: screenWidth, height: screenHeight }}>
              {preview}
            </div>
          </div>
        )}
      </div>
    </section>
  )
}

function PendingProgress({ startedAt, steps }) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const seconds = Math.max(0, Math.floor((now - startedAt) / 1000))
  const phase = steps?.length
    ? '开发环境正在继续'
    : (seconds < 2 ? '正在发送这一轮' : '开发环境正在处理')

  return (
    <div className="studio-progress" role="status">
      <span className="studio-progress__phase">{phase}</span>
      <span className="studio-progress__time">已进行 {seconds} 秒</span>
      <ol>
        <li>这一轮已进入对话</li>
        <li>请求已交给开发环境</li>
        <li>
          {steps?.length
            ? `已完成 ${steps.length} 个工具步骤，后续步骤会继续出现在这里`
            : (seconds < 8 ? '等待模型开始工具步骤' : '工具步骤仍在进行，结束后会显示结果')}
        </li>
      </ol>
    </div>
  )
}

function StepList({ steps }) {
  if (!steps?.length) return null
  return (
    <ul className="studio-steps">
      {steps.map((step, index) => (
        <li key={`${step.tool}-${index}`} className={step.ok === false ? 'studio-steps__item--failed' : ''}>
          {step.summary || step.tool}
        </li>
      ))}
    </ul>
  )
}

export function StudioWorkspace({
  appName,
  configLabel,
  entries,
  pending,
  composerDisabled,
  error,
  prompt,
  frame,
  previewUrl,
  previewKey,
  onPrompt,
  onSubmit,
  onFrame,
  onRefresh,
  onThreadScroll,
  threadRef,
  contentRef
}) {
  return (
    <div className="studio-layout">
      <section className="content-panel studio-panel studio-chat" aria-labelledby="studio-title">
        <div className="dashboard-panel-heading">
          <div>
            <p><Link to="/dashboard">返回工作台</Link></p>
            <h1 id="studio-title" translate="no">{appName}</h1>
            {configLabel ? <p>{configLabel}</p> : null}
          </div>
        </div>
        <div className="studio-thread" ref={threadRef} onScroll={onThreadScroll} aria-label="对话记录">
          <div className="studio-thread__content" ref={contentRef}>
            {entries.length === 0 ? (
              <div className="muted-card">还没有对话。写下要做的事，发送后会留在这里，进行中的步骤和用时也会显示。</div>
            ) : null}
            {entries.map((entry) => (
              <article className={`studio-msg studio-msg--${entry.role}`} key={entry.id}>
                <div className="studio-msg__meta">
                  {entry.role === 'user' ? '你' : '开发环境'} · {clock(entry.startedAt)}
                  {entry.role === 'assistant' && entry.status === 'pending' ? ' · 进行中' : null}
                  {entry.role === 'assistant' && entry.status === 'done' ? ` · 已结束 · ${entry.steps?.length || 0} 个工具步骤` : null}
                  {entry.role === 'assistant' && entry.status === 'failed' ? ' · 失败' : null}
                </div>
                <div className="studio-msg__body">
                  {entry.role === 'assistant' && entry.status === 'pending' ? (
                    <PendingProgress startedAt={entry.startedAt} steps={entry.steps} />
                  ) : null}
                  {entry.text ? entry.text : null}
                  <StepList steps={entry.steps} />
                  {entry.error ? <div className="feedback feedback--error">{entry.error}</div> : null}
                  {entry.role === 'assistant' && entry.status === 'done' && !entry.text ? <span>这一轮没有文字说明。</span> : null}
                  {entry.role === 'assistant' && entry.status === 'done' ? (
                    <div className="studio-turn-done" role="status">
                      <strong>这一轮已完成</strong>
                      {(entry.configLabel || configLabel) ? <span>{entry.configLabel || configLabel}</span> : null}
                    </div>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        </div>
        {error ? <div className="feedback feedback--error" role="alert">{error}</div> : null}
        <form className="studio-composer" onSubmit={onSubmit}>
          <label>
            <span className="studio-sr">这一轮</span>
            <textarea
              name="prompt"
              value={prompt}
              onChange={(event) => onPrompt(event.target.value)}
              rows={3}
              autoComplete="off"
              placeholder="写下要让开发环境做的事"
              disabled={composerDisabled}
            />
          </label>
          <button className="btn btn--primary" type="submit" disabled={composerDisabled || prompt.trim() === ''}>
            {pending ? '进行中' : '发送'}
          </button>
        </form>
      </section>
      <PreviewPane
        appName={appName}
        frame={frame}
        previewKey={previewKey}
        previewUrl={previewUrl}
        onFrame={onFrame}
        onRefresh={onRefresh}
      />
    </div>
  )
}

export default function StudioPage() {
  const { appName = '' } = useParams()
  const [searchParams] = useSearchParams()
  const podName = searchParams.get('pod') || ''
  const configId = Number(searchParams.get('config'))
  const configReady = Number.isInteger(configId) && configId > 0
  const [prompt, setPrompt] = useState('')
  const [pending, setPending] = useState(false)
  const [entries, setEntries] = useState(() => loadEntries(appName))
  const [error, setError] = useState('')
  const [frame, setFrame] = useState('desktop')
  const [previewKey, setPreviewKey] = useState(0)
  const [configLabel, setConfigLabel] = useState('')
  const [configState, setConfigState] = useState('loading')
  const threadRef = useRef(null)
  const contentRef = useRef(null)
  const stickRef = useRef(true)
  const loadedFor = useRef(null)

  useEffect(() => {
    document.title = appName ? `${appName} · 开发` : '开发'
  }, [appName])

  useEffect(() => {
    if (loadedFor.current !== appName) return
    saveEntries(appName, entries)
  }, [entries, appName])

  useEffect(() => {
    loadedFor.current = appName
    const loaded = loadEntries(appName)
    setEntries(loaded)
    setPrompt('')
    setError('')
    const pendingItem = loaded.find((item) => item.status === 'pending' && item.runId)
    if (!pendingItem) {
      setPending(false)
      return undefined
    }
    let cancelled = false
    const name = appName
    const assistantId = pendingItem.id
    setPending(true)
    streamAgentTurn({}, {
      runId: pendingItem.runId,
      seen: pendingItem.steps?.length || 0,
      onStep: (step) => {
        if (cancelled || loadedFor.current !== name) return
        setEntries((curr) => curr.map((item) => (
          item.id === assistantId ? { ...item, steps: [...(item.steps || []), step] } : item
        )))
      }
    }).then((next) => {
      if (cancelled || loadedFor.current !== name) return
      setEntries((curr) => curr.map((item) => (
        item.id === assistantId
          ? { ...item, status: 'done', text: next.reply || '', steps: next.steps || item.steps || [] }
          : item
      )))
      setPreviewKey((value) => value + 1)
    }).catch((err) => {
      if (cancelled || loadedFor.current !== name) return
      const message = err instanceof Error ? err.message : '发送失败'
      setError(message)
      setEntries((curr) => curr.map((item) => (
        item.id === assistantId ? { ...item, status: 'failed', error: message } : item
      )))
    }).finally(() => {
      if (!cancelled && loadedFor.current === name) setPending(false)
    })
    return () => {
      cancelled = true
    }
  }, [appName])

  useEffect(() => {
    if (!podName || !configReady) {
      setConfigState('missing')
      setConfigLabel('')
      setError('开发页面缺少沙盒或模型配置。')
      return undefined
    }
    let cancelled = false
    setConfigState('loading')
    listAgentConfigs()
      .then((result) => {
        if (cancelled) return
        const match = (result.configs || []).find((item) => item.id === configId)
        setConfigState(match ? 'ready' : 'missing')
        setConfigLabel(match ? `${match.model_name} · ${match.api_base}` : '')
        if (!match) setError('这组模型配置已不存在，请回到工作台重新选择。')
      })
      .catch((err) => {
        if (cancelled) return
        setConfigState('missing')
        setError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [configId, configReady, podName])

  useEffect(() => {
    const content = contentRef.current
    const thread = threadRef.current
    if (!content || !thread) return undefined
    const observer = new ResizeObserver(() => {
      if (stickRef.current) thread.scrollTop = thread.scrollHeight
    })
    observer.observe(content)
    return () => observer.disconnect()
  }, [])

  function onThreadScroll() {
    const thread = threadRef.current
    if (!thread) return
    stickRef.current = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 48
  }

  async function submit(event) {
    event.preventDefault()
    const text = prompt.trim()
    if (!text || pending) return
    if (!podName || !configReady || configState !== 'ready') {
      setError('请从工作台选择一组已保存的模型配置后再开始')
      return
    }
    const name = appName
    const startedAt = Date.now()
    const assistantId = `${startedAt}-assistant`
    const priorHistory = entries
      .filter((item) => item.status === 'done' && item.text && (item.role === 'user' || item.role === 'assistant'))
      .slice(-12)
      .map((item) => ({ role: item.role, content: item.text }))
    stickRef.current = true
    setPrompt('')
    setError('')
    setPending(true)
    setEntries((curr) => [
      ...curr,
      { id: `${startedAt}-user`, role: 'user', text, status: 'done', startedAt },
      { id: assistantId, role: 'assistant', text: '', status: 'pending', steps: [], startedAt, configLabel }
    ])
    try {
      const next = await streamAgentTurn({
        pod_name: podName,
        config_id: configId,
        message: text,
        history: priorHistory
      }, {
        onRunId: (runId) => {
          if (loadedFor.current !== name) return
          setEntries((curr) => curr.map((item) => (
            item.id === assistantId ? { ...item, runId } : item
          )))
        },
        onStep: (step) => {
          if (loadedFor.current !== name) return
          setEntries((curr) => curr.map((item) => (
            item.id === assistantId ? { ...item, steps: [...(item.steps || []), step] } : item
          )))
        }
      })
      if (loadedFor.current !== name) return
      setEntries((curr) => curr.map((item) => (
        item.id === assistantId
          ? { ...item, status: 'done', text: next.reply || '', steps: next.steps || item.steps || [] }
          : item
      )))
      setPreviewKey((value) => value + 1)
    } catch (err) {
      if (loadedFor.current !== name) return
      const message = err instanceof Error ? err.message : '发送失败'
      setError(message)
      setEntries((curr) => curr.map((item) => (
        item.id === assistantId ? { ...item, status: 'failed', error: message } : item
      )))
    } finally {
      if (loadedFor.current === name) setPending(false)
    }
  }

  const previewUrl = appName ? `/apps/${encodeURIComponent(appName)}/` : 'about:blank'

  return (
    <AppShell fill>
      <StudioWorkspace
        appName={appName}
        configLabel={configLabel}
        entries={entries}
        pending={pending}
        composerDisabled={pending || configState !== 'ready'}
        error={error}
        prompt={prompt}
        frame={frame}
        previewUrl={previewUrl}
        previewKey={previewKey}
        onPrompt={setPrompt}
        onSubmit={submit}
        onFrame={setFrame}
        onRefresh={() => setPreviewKey((value) => value + 1)}
        onThreadScroll={onThreadScroll}
        threadRef={threadRef}
        contentRef={contentRef}
      />
    </AppShell>
  )
}
