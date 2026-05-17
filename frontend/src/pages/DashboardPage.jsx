import { useCallback, useEffect, useState } from 'react'
import {
  checkAppName,
  createDevboxContainer,
  deleteContainer,
  getMyContainers,
  getMyHarborImages
} from '../api/client'
import AppShell from '../components/AppShell'

const APP_NAME_PATTERN = /^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/
const CONTAINER_REFRESH_INTERVAL_MS = 5000
const CONTAINER_REFRESH_MAX_ATTEMPTS = 12

function containerFromCreateResult(result) {
  return {
    name: result.pod_name,
    image: result.image,
    status: result.status === 'creating' ? 'Pending' : result.status,
    app_name: result.app_name,
    url: result.url,
    ssh_username: result.ssh_username,
    webssh_url: result.webssh_url,
    native_ssh_command: result.native_ssh_command
  }
}

function formatDateTime(value) {
  if (!value) return '未知'

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '未知'
  }

  return date.toLocaleString('zh-CN', {
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function imageShortName(repo) {
  return repo?.name || '未命名镜像'
}

function imageNameFromRef(image) {
  if (!image) return '镜像'
  const withoutDigest = image.split('@')[0]
  const lastPart = withoutDigest.split('/').pop() || withoutDigest
  return lastPart.split(':')[0] || '镜像'
}

function statusText(status) {
  const statusMap = {
    Running: '运行中',
    Pending: '创建中',
    Succeeded: '已完成',
    Failed: '失败',
    Terminating: '删除中',
    Unknown: '未知'
  }
  return statusMap[status] || status || '未知'
}

function ImageList({ title, project, message, loading, limit, variant = 'private' }) {
  const repos = project?.repos || []
  const visibleRepos = repos.slice(0, limit)
  const countLabel = `${Math.min(repos.length, limit)}/${limit}`

  return (
    <section className={`image-section image-section--${variant}`} aria-labelledby={`${title}-title`}>
      <div className="image-section__heading">
        <h2 id={`${title}-title`}>{title}</h2>
        <span>{countLabel}</span>
      </div>

      {loading ? <div className="muted-card">正在加载…</div> : null}
      {!loading && message ? <div className="muted-card">{message}</div> : null}
      {!loading && !message && project?.exists && repos.length === 0 ? (
        <div className="muted-card">暂无镜像。</div>
      ) : null}

      {!loading && project?.exists ? (
        <div className={`image-button-grid image-button-grid--${variant}`}>
          {visibleRepos.map((repo) => (
            <button
              className="image-button"
              key={repo.full_name}
              type="button"
              title={`${repo.image}\nArtifacts ${repo.artifact_count || 0} · 拉取 ${repo.pull_count || 0} · 更新 ${formatDateTime(repo.update_time)}`}
            >
              <span className="image-button__thumb" aria-hidden="true">
                <span>{imageShortName(repo).slice(0, 1).toUpperCase()}</span>
              </span>
              <span className="image-button__name">{imageShortName(repo)}</span>
            </button>
          ))}
        </div>
      ) : null}
    </section>
  )
}

function ContainerList({ containers, deletingPodName, loading, onCopySsh, onDelete, onOpenWebSsh }) {
  if (loading) {
    return <div className="muted-card">正在加载容器…</div>
  }

  if (!containers.length) {
    return <div className="muted-card">暂无容器。</div>
  }

  return (
    <div className="container-list" aria-label="我的容器">
      {containers.map((container) => {
        const imageName = imageNameFromRef(container.image)
        return (
          <div className="container-row" key={container.name}>
            <span className="container-row__image" title={container.image || imageName} aria-hidden="true">
              <span>{imageName.slice(0, 1).toUpperCase()}</span>
            </span>
            <div className="container-row__main">
              <strong>{container.name}</strong>
              <span className={`container-status container-status--${container.status?.toLowerCase() || 'unknown'}`}>
                {statusText(container.status)}
              </span>
            </div>
            <div className="container-row__actions">
              <button
                className="container-action-button"
                type="button"
                onClick={() => onOpenWebSsh(container)}
                disabled={!container.webssh_url}
              >
                WebSSH
              </button>
              <button
                className="container-action-button"
                type="button"
                onClick={() => onCopySsh(container)}
                disabled={!container.native_ssh_command}
              >
                复制 SSH
              </button>
              <button
                className="container-delete-button"
                type="button"
                onClick={() => onDelete(container)}
                disabled={deletingPodName === container.name || container.status === 'Terminating'}
              >
                {deletingPodName === container.name ? '删除中…' : '删除'}
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function ContainerApplyModal({
  appName,
  appNameCheck,
  connectionPassword,
  error,
  submitting,
  onAppNameChange,
  onConnectionPasswordChange,
  onClose,
  onSubmit
}) {
  return (
    <div className="modal-backdrop" role="presentation">
      <div className="modal-card" role="dialog" aria-modal="true" aria-labelledby="container-apply-title">
        <div className="modal-card__header">
          <div>
            <h2 id="container-apply-title">申请容器</h2>
          </div>
        </div>

        <form className="modal-form" onSubmit={onSubmit}>
          <label>
            <span>app_name</span>
            <input
              type="text"
              value={appName}
              onChange={(event) => onAppNameChange(event.target.value)}
              placeholder="例如 demo-app"
              autoComplete="off"
              maxLength={40}
              disabled={submitting}
            />
            <small>仅允许小写字母、数字和中划线；访问路径为 /apps/app_name。</small>
          </label>

          <label>
            <span>连接密码</span>
            <input
              type="password"
              value={connectionPassword}
              onChange={(event) => onConnectionPasswordChange(event.target.value)}
              placeholder="至少 6 位，后续用于 SSH 连接"
              autoComplete="new-password"
              minLength={6}
              disabled={submitting}
            />
          </label>

          {appNameCheck?.available ? (
            <div className="feedback feedback--success">应用名称可用：{appNameCheck.url}</div>
          ) : null}
          {error ? <div className="feedback feedback--error">{error}</div> : null}

          <div className="modal-actions">
            <button className="btn btn--ghost" type="button" onClick={onClose} disabled={submitting}>
              取消
            </button>
            <button className="btn btn--primary" type="submit" disabled={submitting}>
              {submitting ? '申请中…' : '确认申请'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function DashboardPage() {
  const [harborInfo, setHarborInfo] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [containersInfo, setContainersInfo] = useState({ containers: [] })
  const [containersLoading, setContainersLoading] = useState(true)
  const [containersError, setContainersError] = useState('')
  const [creatingContainer, setCreatingContainer] = useState(false)
  const [containerError, setContainerError] = useState('')
  const [deletingPodName, setDeletingPodName] = useState('')
  const [hiddenDeletingPods, setHiddenDeletingPods] = useState([])
  const [isApplyModalOpen, setIsApplyModalOpen] = useState(false)
  const [appName, setAppName] = useState('')
  const [connectionPassword, setConnectionPassword] = useState('')
  const [appNameCheck, setAppNameCheck] = useState(null)
  const [applyFormError, setApplyFormError] = useState('')

  const loadHarborImages = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await getMyHarborImages()
      setHarborInfo(result)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  const loadContainers = useCallback(async ({ showLoading = true } = {}) => {
    if (showLoading) {
      setContainersLoading(true)
    }
    setContainersError('')
    try {
      const result = await getMyContainers()
      setContainersInfo(result)
      setHiddenDeletingPods((prev) => {
        if (!prev.length) return prev
        const existingPodNames = new Set((result.containers || []).map((container) => container.name))
        return prev.filter((podName) => existingPodNames.has(podName))
      })
      return result
    } catch (err) {
      setContainersError(err.message)
      return null
    } finally {
      if (showLoading) {
        setContainersLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    loadHarborImages()
    loadContainers()
  }, [loadHarborImages, loadContainers])

  const pollContainersUntil = useCallback((shouldContinue, attempt = 1) => {
    window.setTimeout(async () => {
      const result = await loadContainers({ showLoading: false })
      if (!result || attempt >= CONTAINER_REFRESH_MAX_ATTEMPTS) {
        return
      }
      if (shouldContinue(result)) {
        pollContainersUntil(shouldContinue, attempt + 1)
      }
    }, CONTAINER_REFRESH_INTERVAL_MS)
  }, [loadContainers])

  const resetApplyForm = useCallback(() => {
    setAppName('')
    setConnectionPassword('')
    setAppNameCheck(null)
    setApplyFormError('')
  }, [])

  const handleOpenApplyModal = useCallback(() => {
    setContainerError('')
    resetApplyForm()
    setIsApplyModalOpen(true)
  }, [resetApplyForm])

  const handleCloseApplyModal = useCallback(() => {
    if (creatingContainer) return
    setIsApplyModalOpen(false)
    resetApplyForm()
  }, [creatingContainer, resetApplyForm])

  const handleAppNameChange = useCallback((value) => {
    setAppName(value.trim().toLowerCase())
    setAppNameCheck(null)
    setApplyFormError('')
  }, [])

  const handleCreateContainer = useCallback(async (event) => {
    event.preventDefault()
    const normalizedAppName = appName.trim().toLowerCase()
    if (!APP_NAME_PATTERN.test(normalizedAppName)) {
      setApplyFormError('app_name 只允许小写字母、数字和中划线，且必须以字母或数字开头结尾')
      return
    }
    if (connectionPassword.trim().length < 6) {
      setApplyFormError('连接密码至少需要 6 位')
      return
    }

    setCreatingContainer(true)
    setContainerError('')
    setApplyFormError('')
    try {
      const availability = await checkAppName(normalizedAppName)
      setAppNameCheck(availability)
      if (!availability.available) {
        setApplyFormError(availability.message || '该应用名称已被使用')
        return
      }
      const createdContainer = await createDevboxContainer({
        app_name: normalizedAppName,
        connection_password: connectionPassword
      })
      setContainersInfo((prev) => ({
        namespace: createdContainer.namespace || prev?.namespace,
        containers: [
          containerFromCreateResult(createdContainer),
          ...(prev?.containers || []).filter((container) => container.name !== createdContainer.pod_name)
        ]
      }))
      setIsApplyModalOpen(false)
      resetApplyForm()
      pollContainersUntil((result) => {
        const current = (result.containers || []).find((container) => container.name === createdContainer.pod_name)
        return Boolean(current && ['Pending', 'Unknown'].includes(current.status))
      })
    } catch (err) {
      setApplyFormError(err.message)
    } finally {
      setCreatingContainer(false)
    }
  }, [appName, connectionPassword, pollContainersUntil, resetApplyForm])

  const handleDeleteContainer = useCallback(async (container) => {
    if (!container?.name) return
    const confirmed = window.confirm(`确定删除容器 ${container.name} 及其配套访问资源吗？`)
    if (!confirmed) return

    let previousContainersInfo = null
    setDeletingPodName(container.name)
    setContainerError('')
    setHiddenDeletingPods((prev) => (prev.includes(container.name) ? prev : [...prev, container.name]))
    setContainersInfo((prev) => {
      previousContainersInfo = prev
      return {
        ...prev,
        containers: (prev?.containers || []).filter((item) => item.name !== container.name)
      }
    })
    try {
      await deleteContainer(container.name)
    } catch (err) {
      setHiddenDeletingPods((prev) => prev.filter((podName) => podName !== container.name))
      if (previousContainersInfo) {
        setContainersInfo(previousContainersInfo)
      }
      setContainerError(err.message)
    } finally {
      setDeletingPodName('')
    }
  }, [])

  const handleOpenWebSsh = useCallback((container) => {
    if (!container?.webssh_url) return
    window.open(container.webssh_url, '_blank', 'noopener,noreferrer')
  }, [])

  const handleCopySsh = useCallback(async (container) => {
    if (!container?.native_ssh_command) return
    setContainerError('')
    try {
      await navigator.clipboard.writeText(container.native_ssh_command)
    } catch {
      setContainerError(`复制失败，请手动复制：${container.native_ssh_command}`)
    }
  }, [])

  const harborConfigured = harborInfo?.configured
  const privateMessage = !harborConfigured
    ? harborInfo?.message || 'Harbor 未配置'
    : harborInfo?.private_message
  const publicMessage = !harborConfigured
    ? harborInfo?.message || 'Harbor 未配置'
    : harborInfo?.public_message
  const visibleContainers = (containersInfo?.containers || []).filter(
    (container) => !hiddenDeletingPods.includes(container.name)
  )

  return (
    <AppShell>
      <div className="dashboard-layout">
        <section className="content-panel container-request-panel" aria-labelledby="container-request-title">
          <div className="dashboard-panel-heading">
            <h1 id="container-request-title">容器申请</h1>
            <button
              className="btn btn--primary"
              type="button"
              onClick={handleOpenApplyModal}
              disabled={creatingContainer}
            >
              {creatingContainer ? '申请中…' : '申请容器'}
            </button>
          </div>

          {containerError ? <div className="feedback feedback--error">{containerError}</div> : null}
          {containersError ? <div className="feedback feedback--error">{containersError}</div> : null}
          {!containersError ? (
            <ContainerList
              containers={visibleContainers}
              deletingPodName={deletingPodName}
              loading={containersLoading}
              onCopySsh={handleCopySsh}
              onDelete={handleDeleteContainer}
              onOpenWebSsh={handleOpenWebSsh}
            />
          ) : null}
        </section>

        <aside className="image-repository-panel" aria-label="镜像仓库">
          <div className="image-repository-panel__header">
            <div>
              <h1>镜像仓库</h1>
            </div>
            <button className="btn btn--primary" type="button" onClick={loadHarborImages} disabled={loading}>
              {loading ? '刷新中' : '刷新'}
            </button>
          </div>

          {error ? <div className="feedback feedback--error">{error}</div> : null}

          {!error ? (
            <>
              <ImageList
                title="我的镜像"
                project={harborInfo?.private_project}
                message={privateMessage}
                loading={loading}
                limit={3}
                variant="private"
              />
              <ImageList
                title="公有镜像"
                project={harborInfo?.public_project_info}
                message={publicMessage}
                loading={loading}
                limit={9}
                variant="public"
              />
            </>
          ) : null}
        </aside>
      </div>

      {isApplyModalOpen ? (
        <ContainerApplyModal
          appName={appName}
          appNameCheck={appNameCheck}
          connectionPassword={connectionPassword}
          error={applyFormError}
          submitting={creatingContainer}
          onAppNameChange={handleAppNameChange}
          onConnectionPasswordChange={setConnectionPassword}
          onClose={handleCloseApplyModal}
          onSubmit={handleCreateContainer}
        />
      ) : null}
    </AppShell>
  )
}
