import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  checkAppName,
  commitContainer,
  createDevboxContainer,
  deleteContainer,
  getK3sJobStatus,
  getMyContainers,
  getMyHarborImages,
  getMyPublicationStatuses,
  getPublicationSettings,
  publishApp,
  unpublishApp
} from '../api/client'
import AppShell from '../components/AppShell'

const APP_NAME_PATTERN = /^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/
const CONTAINER_REFRESH_INTERVAL_MS = 5000
const CONTAINER_REFRESH_MAX_ATTEMPTS = 12
const COVER_MAX_UPLOAD_BYTES = 512 * 1024
const COVER_CANVAS_WIDTH = 960
const COVER_CANVAS_HEIGHT = 540
const APP_DESCRIPTION_MAX_LENGTH = 40
const COMMIT_IMAGE_NAME_PATTERN = /^[a-z0-9][a-z0-9._-]*$/
const COMMIT_JOB_REFRESH_INTERVAL_MS = 5000
const COMMIT_JOB_MAX_ATTEMPTS = 200
const FALLBACK_DEVBOX_IMAGE = 'gpunion2.io/dev/devbox:latest'
const VISIBLE_REFRESH_MIN_INTERVAL_MS = 2000
const PUBLICATION_BUTTON_LABELS = {
  pending: '审核中',
  approved: '取消发布',
  rejected: '重新审核',
  unpublished: '发布'
}
const GPU_DEFAULT_RESOURCES = {
  gpuCount: '1',
  cpuCores: '8',
  memoryGb: '16',
  shmGb: '4'
}

function gpuResourceLimits(gpuCountValue) {
  const gpuCount = Number(gpuCountValue) || 1
  return {
    maxCpu: 16 * gpuCount,
    maxMemory: 32 * gpuCount,
    maxShm: 8 * gpuCount
  }
}

function clampIntegerInput(value, min, max) {
  const number = Number.parseInt(value, 10)
  if (!Number.isFinite(number)) return ''
  return String(Math.min(max, Math.max(min, number)))
}

function containerFromCreateResult(result) {
  return {
    name: result.pod_name,
    image: result.image,
    status: result.status === 'creating' ? 'Pending' : result.status,
    app_name: result.app_name,
    url: result.url,
    ssh_username: result.ssh_username,
    webssh_url: result.webssh_url,
    native_ssh_command: result.native_ssh_command,
    is_published: false,
    publication_status: 'unpublished',
    publication_submitted_at: null,
    publication_reviewed_at: null
  }
}

function publicationStateFromRecord(record) {
  const reviewStatus = record?.review_status || record?.publication_status || (
    record?.is_published ? 'approved' : 'unpublished'
  )
  return {
    is_published: Boolean(record?.is_published),
    publication_status: reviewStatus || 'unpublished',
    publication_submitted_at: record?.submitted_at || record?.publication_submitted_at || null,
    publication_reviewed_at: record?.reviewed_at || record?.publication_reviewed_at || null
  }
}

function mergePublicationStatuses(containers, statuses) {
  const statusByPodName = new Map((statuses || []).map((statusItem) => [statusItem.pod_name, statusItem]))
  return (containers || []).map((container) => ({
    ...container,
    ...publicationStateFromRecord(statusByPodName.get(container.name) || container)
  }))
}

function loadImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const image = new Image()
    image.onload = () => {
      URL.revokeObjectURL(url)
      resolve(image)
    }
    image.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('封面图片读取失败'))
    }
    image.src = url
  })
}

function canvasToBlob(canvas, type, quality) {
  return new Promise((resolve) => {
    canvas.toBlob(resolve, type, quality)
  })
}

async function compressCoverImage(file) {
  if (!file) return null
  if (!file.type.startsWith('image/')) {
    throw new Error('封面必须是图片文件')
  }

  const image = await loadImage(file)
  const scale = Math.min(COVER_CANVAS_WIDTH / image.width, COVER_CANVAS_HEIGHT / image.height)
  const width = Math.max(1, Math.round(image.width * scale))
  const height = Math.max(1, Math.round(image.height * scale))
  const offsetX = Math.round((COVER_CANVAS_WIDTH - width) / 2)
  const offsetY = Math.round((COVER_CANVAS_HEIGHT - height) / 2)
  const canvas = document.createElement('canvas')
  canvas.width = COVER_CANVAS_WIDTH
  canvas.height = COVER_CANVAS_HEIGHT
  const context = canvas.getContext('2d')
  if (!context) {
    throw new Error('当前浏览器不支持封面压缩')
  }
  context.fillStyle = '#f7faff'
  context.fillRect(0, 0, COVER_CANVAS_WIDTH, COVER_CANVAS_HEIGHT)
  context.drawImage(image, offsetX, offsetY, width, height)

  for (const quality of [0.78, 0.68, 0.58, 0.48]) {
    const blob = await canvasToBlob(canvas, 'image/webp', quality)
    if (blob && blob.size <= COVER_MAX_UPLOAD_BYTES) {
      return new File([blob], 'cover.webp', { type: 'image/webp' })
    }
  }

  throw new Error('封面压缩后仍过大，请更换更轻量的图片')
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
  return repo?.name || '未命名模板'
}

function imageNameFromRef(image) {
  if (!image) return '开发环境模板'
  const withoutDigest = image.split('@')[0]
  const lastPart = withoutDigest.split('/').pop() || withoutDigest
  return lastPart.split(':')[0] || '开发环境模板'
}

function allRepositoryImages(info) {
  return [
    defaultRepositoryImage(info),
    ...((info?.private_project?.repos || []).map((repo) => repo.image)),
    ...((info?.public_project_info?.repos || []).map((repo) => repo.image))
  ].filter(Boolean)
}

function defaultRepositoryImage(info) {
  const publicRepos = info?.public_project_info?.repos || []
  const privateRepos = info?.private_project?.repos || []
  const devboxRepo = publicRepos.find((repo) => (
    repo.name === 'devbox' || /(^|\/)devbox(?::|$)/.test(repo.image || '')
  ))
  if (devboxRepo?.image) return devboxRepo.image
  if (info?.registry && info?.public_project) {
    return `${info.registry.replace(/\/$/, '')}/${info.public_project}/devbox:latest`
  }
  return publicRepos[0]?.image || privateRepos[0]?.image || FALLBACK_DEVBOX_IMAGE
}


function sshTargetFromCommand(command) {
  if (!command) return null
  const normalized = command.trim().replace(/\s+/g, ' ')
  const portMatch = normalized.match(/(?:^|\s)-p\s+(\d+)(?:\s|$)/)
  const port = portMatch?.[1] || '22'

  const loginMatch = normalized.match(/(?:^|\s)-l\s+['"]?([^'"\s]+)['"]?\s+([^\s]+)/)
  if (loginMatch) {
    return { login: loginMatch[1], host: loginMatch[2], port }
  }

  const directMatch = normalized.match(/^ssh\s+(?!-)(.+?)@([^\s]+)(?:\s|$)/)
  if (directMatch) {
    return { login: directMatch[1], host: directMatch[2], port }
  }

  return null
}

function base64UrlEncode(value) {
  const bytes = new TextEncoder().encode(value)
  let binary = ''
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte)
  })
  return window.btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
}

function ideRemoteUri(protocol, container) {
  const target = sshTargetFromCommand(container?.native_ssh_command)
  if (!target || !container?.app_name || !container?.ssh_username) return ''
  const safeLogin = `${container.app_name}__${base64UrlEncode(container.ssh_username)}`
  const remotePath = `/home/${encodeURIComponent(container.ssh_username)}`
  return `${protocol}://vscode-remote/ssh-remote+${safeLogin}@${target.host}:${target.port}${remotePath}?windowId=_blank`
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

function ImageList({
  title,
  project,
  message,
  loading,
  limit,
  selectedImage,
  variant = 'private',
  onSelectImage
}) {
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
        <div className="muted-card">暂无模板。</div>
      ) : null}

      {!loading && project?.exists ? (
        <div className={`image-button-grid image-button-grid--${variant}`}>
          {visibleRepos.map((repo) => (
            <button
              className={`image-button${selectedImage === repo.image ? ' image-button--selected' : ''}`}
              key={repo.full_name}
              type="button"
              aria-pressed={selectedImage === repo.image}
              onClick={() => onSelectImage(repo.image)}
              title={`${repo.image}\n版本 ${repo.artifact_count || 0} · 拉取 ${repo.pull_count || 0} · 更新 ${formatDateTime(repo.update_time)}`}
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

function ContainerList({
  containers,
  deletingPodName,
  loading,
  publishingPodName,
  savingJobs,
  onCopySsh,
  onDelete,
  onOpenCursor,
  onOpenVSCode,
  onOpenApp,
  onOpenPublish,
  onOpenWebSsh,
  onSaveContainer,
  onUnpublish
}) {
  if (loading) {
    return <div className="muted-card">正在加载开发沙盒…</div>
  }

  if (!containers.length) {
    return <div className="muted-card">暂无开发沙盒。</div>
  }

  return (
    <div className="container-list" aria-label="我的开发沙盒">
      {containers.map((container) => {
        const imageName = imageNameFromRef(container.image)
        const displayName = container.app_name || container.name
        const saveState = savingJobs[container.name]
        const isSaving = saveState && !['Succeeded', 'Failed', 'NotFound', 'Error'].includes(saveState.status)
        const publicationStatus = container.publication_status || (container.is_published ? 'approved' : 'unpublished')
        const canUnpublish = publicationStatus === 'approved'
        const canPublish = ['unpublished', 'rejected'].includes(publicationStatus)
        const isPendingReview = publicationStatus === 'pending'
        const publicationButtonLabel = PUBLICATION_BUTTON_LABELS[publicationStatus] || '发布'
        return (
          <div className="container-row" key={container.name}>
            <span className="container-row__image" title={container.image || imageName} aria-hidden="true">
              <span>{imageName.slice(0, 1).toUpperCase()}</span>
            </span>
            <div className="container-row__main">
              <strong title={container.name}>{displayName}</strong>
              <span className={`container-status container-status--${container.status?.toLowerCase() || 'unknown'}`}>
                {statusText(container.status)}
              </span>
            </div>
            <div className="container-row__actions" aria-label={`${displayName} 操作`}>
              <div className="container-row__action-line">
                <button
                  className="container-action-button"
                  type="button"
                  onClick={() => onOpenApp(container)}
                  disabled={!container.url}
                >
                  访问应用
                </button>
                <button
                  className="container-action-button"
                  type="button"
                  title={saveState?.message || '保存当前开发沙盒为我的开发环境模板'}
                  onClick={() => onSaveContainer(container)}
                  disabled={isSaving || container.status !== 'Running'}
                >
                  {isSaving ? '保存中…' : '保存为我的模板'}
                </button>
                <button
                  className="container-delete-button"
                  type="button"
                  onClick={() => onDelete(container)}
                  disabled={deletingPodName === container.name || container.status === 'Terminating'}
                >
                  {deletingPodName === container.name ? '删除中…' : '删除沙盒'}
                </button>
              </div>
              <div className="container-row__action-line container-row__action-line--connection">
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
                  className="container-action-button"
                  type="button"
                  onClick={() => onOpenVSCode(container)}
                  disabled={!container.native_ssh_command}
                  title="使用本机 VS Code Remote SSH 打开"
                >
                  VSCode连接
                </button>
                <button
                  className="container-action-button"
                  type="button"
                  onClick={() => onOpenCursor(container)}
                  disabled={!container.native_ssh_command}
                  title="使用本机 Cursor Remote SSH 打开"
                >
                  Cursor连接
                </button>
              </div>
              <div className="container-row__action-line container-row__action-line--publication">
                <button
                  className={[
                    'container-publish-button',
                    `container-publish-button--${publicationStatus}`,
                    canUnpublish ? 'container-publish-button--published' : ''
                  ].filter(Boolean).join(' ')}
                  type="button"
                  onClick={() => (canUnpublish ? onUnpublish(container) : onOpenPublish(container))}
                  disabled={
                    publishingPodName === container.name
                    || !container.app_name
                    || isPendingReview
                    || (!canPublish && !canUnpublish)
                  }
                >
                  {publishingPodName === container.name ? '处理中…' : publicationButtonLabel}
                </button>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function PublishAppModal({
  app,
  description,
  coverFile,
  error,
  reviewSettings,
  responsibilityAck,
  submitting,
  onClose,
  onCoverChange,
  onDescriptionChange,
  onResponsibilityAckChange,
  onSubmit
}) {
  if (!app) return null
  if (typeof document === 'undefined') return null

  return createPortal(
    <div className="modal-backdrop modal-backdrop--dashboard" role="presentation">
      <div className="modal-card publish-modal-card" role="dialog" aria-modal="true" aria-labelledby="publish-title">
        <div className="modal-card__header">
          <div>
            <h2 id="publish-title">发布应用</h2>
            <p>
              {reviewSettings?.review_policy === 'require_review'
                ? '提交后将进入管理员审核，通过后展示在应用市场。'
                : '发布后将在应用市场展示为应用卡片。'}
            </p>
          </div>
        </div>

        <form className="modal-form" onSubmit={onSubmit}>
          <label>
            <span>应用名称</span>
            <input type="text" value={app.app_name || app.name} disabled />
          </label>

          <label>
            <span>应用简述</span>
            <textarea
              value={description}
              onChange={(event) => onDescriptionChange(event.target.value)}
              placeholder="用两行以内说明这个应用能做什么"
              maxLength={APP_DESCRIPTION_MAX_LENGTH}
              disabled={submitting}
              required
            />
            <small>{description.length}/{APP_DESCRIPTION_MAX_LENGTH}</small>
          </label>

          <label>
            <span>封面图片</span>
            <input type="file" accept="image/*" onChange={onCoverChange} disabled={submitting} />
            <small>上传后会自动压缩为适合展示的轻量图片。</small>
          </label>

          <p className="publish-cover-note">
            {coverFile
              ? `已选择封面，压缩后约 ${Math.max(1, Math.round(coverFile.size / 1024))} KB。`
              : '未上传封面时，应用市场会使用默认渐变封面。'}
          </p>

          <label className="publish-acknowledgement">
            <input
              type="checkbox"
              checked={responsibilityAck}
              onChange={(event) => onResponsibilityAckChange(event.target.checked)}
              disabled={submitting}
              required
            />
            <span>
              我已知悉并承诺：该应用的内容、数据处理、外部调用、生成内容和对外服务行为由我本人负责；不会发布违法违规、侵权、涉密、恶意或影响平台稳定性的内容。
            </span>
          </label>

          {error ? <div className="feedback feedback--error">{error}</div> : null}

          <div className="modal-actions">
            <button className="btn btn--ghost" type="button" onClick={onClose} disabled={submitting}>
              取消
            </button>
            <button className="btn btn--primary" type="submit" disabled={submitting || !responsibilityAck}>
              {submitting
                ? '提交中…'
                : reviewSettings?.review_policy === 'require_review'
                  ? '提交审核'
                  : '确认发布'}
            </button>
          </div>
        </form>
      </div>
    </div>,
    document.body
  )
}

function ContainerApplyModal({
  appName,
  appNameCheck,
  connectionPassword,
  error,
  gpuConfig,
  selectedImage,
  submitting,
  onAppNameChange,
  onConnectionPasswordChange,
  onGpuConfigChange,
  onClose,
  onSubmit
}) {
  if (typeof document === 'undefined') return null
  const gpuLimits = gpuResourceLimits(gpuConfig.gpuCount)

  return createPortal(
    <div className="modal-backdrop modal-backdrop--dashboard" role="presentation">
      <div className="modal-card dashboard-modal-card" role="dialog" aria-modal="true" aria-labelledby="container-apply-title">
        <div className="modal-card__header">
          <div>
            <h2 id="container-apply-title">创建开发沙盒</h2>
          </div>
        </div>

        <form className="modal-form" onSubmit={onSubmit}>
          <label>
            <span>使用开发环境模板</span>
            <input type="text" value={imageNameFromRef(selectedImage)} title={selectedImage} disabled />
            <small>开发沙盒将使用当前选中的开发环境模板，默认选中公有开发环境模板。</small>
          </label>

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
              placeholder="至少 6 位，用于 SSH 连接"
              autoComplete="new-password"
              minLength={6}
              disabled={submitting}
            />
          </label>

          <label className="gpu-option">
            <input
              type="checkbox"
              checked={gpuConfig.enabled}
              onChange={(event) => onGpuConfigChange((prev) => ({ ...prev, enabled: event.target.checked }))}
              disabled={submitting}
            />
            <span>
              <strong>需要 GPU 来部署私有模型</strong>
              <small>勾选后将申请 NVIDIA GPU，并按填写资源调度到可用 GPU 节点。</small>
            </span>
          </label>

          {gpuConfig.enabled ? (
            <div className="gpu-resource-grid">
              <label>
                <span>GPU 数量</span>
                <select
                  value={gpuConfig.gpuCount}
                  onChange={(event) => {
                    const gpuCount = event.target.value
                    const limits = gpuResourceLimits(gpuCount)
                    onGpuConfigChange((prev) => ({
                      ...prev,
                      gpuCount,
                      cpuCores: clampIntegerInput(prev.cpuCores || GPU_DEFAULT_RESOURCES.cpuCores, 1, limits.maxCpu),
                      memoryGb: clampIntegerInput(prev.memoryGb || GPU_DEFAULT_RESOURCES.memoryGb, 1, limits.maxMemory),
                      shmGb: clampIntegerInput(prev.shmGb || GPU_DEFAULT_RESOURCES.shmGb, 1, limits.maxShm)
                    }))
                  }}
                  disabled={submitting}
                >
                  <option value="1">1 张</option>
                  <option value="2">2 张</option>
                </select>
              </label>

              <label>
                <span>CPU 核数</span>
                <input
                  type="number"
                  min="1"
                  max={gpuLimits.maxCpu}
                  value={gpuConfig.cpuCores}
                  onChange={(event) => onGpuConfigChange((prev) => ({ ...prev, cpuCores: event.target.value }))}
                  onBlur={(event) => onGpuConfigChange((prev) => ({ ...prev, cpuCores: clampIntegerInput(event.target.value, 1, gpuLimits.maxCpu) }))}
                  disabled={submitting}
                />
                <small>最多 {gpuLimits.maxCpu} 核</small>
              </label>

              <label>
                <span>内存 GB</span>
                <input
                  type="number"
                  min="1"
                  max={gpuLimits.maxMemory}
                  value={gpuConfig.memoryGb}
                  onChange={(event) => onGpuConfigChange((prev) => ({ ...prev, memoryGb: event.target.value }))}
                  onBlur={(event) => onGpuConfigChange((prev) => ({ ...prev, memoryGb: clampIntegerInput(event.target.value, 1, gpuLimits.maxMemory) }))}
                  disabled={submitting}
                />
                <small>最多 {gpuLimits.maxMemory} GB</small>
              </label>

              <label>
                <span>/dev/shm GB</span>
                <input
                  type="number"
                  min="1"
                  max={gpuLimits.maxShm}
                  value={gpuConfig.shmGb}
                  onChange={(event) => onGpuConfigChange((prev) => ({ ...prev, shmGb: event.target.value }))}
                  onBlur={(event) => onGpuConfigChange((prev) => ({ ...prev, shmGb: clampIntegerInput(event.target.value, 1, gpuLimits.maxShm) }))}
                  disabled={submitting}
                />
                <small>最多 {gpuLimits.maxShm} GB</small>
              </label>
            </div>
          ) : null}

          {appNameCheck?.available ? (
            <div className="feedback feedback--success">应用名称可用：{appNameCheck.url}</div>
          ) : null}
          {error ? <div className="feedback feedback--error">{error}</div> : null}

          <div className="modal-actions">
            <button className="btn btn--ghost" type="button" onClick={onClose} disabled={submitting}>
              取消
            </button>
            <button className="btn btn--primary" type="submit" disabled={submitting}>
              {submitting ? '创建中…' : '确认创建'}
            </button>
          </div>
        </form>
      </div>
    </div>,
    document.body
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
  const [gpuConfig, setGpuConfig] = useState({ enabled: false, ...GPU_DEFAULT_RESOURCES })
  const [appNameCheck, setAppNameCheck] = useState(null)
  const [applyFormError, setApplyFormError] = useState('')
  const [publishTarget, setPublishTarget] = useState(null)
  const [publishDescription, setPublishDescription] = useState('')
  const [publishCoverFile, setPublishCoverFile] = useState(null)
  const [publishError, setPublishError] = useState('')
  const [publishReviewSettings, setPublishReviewSettings] = useState(null)
  const [responsibilityAck, setResponsibilityAck] = useState(false)
  const [publishingPodName, setPublishingPodName] = useState('')
  const [savingJobs, setSavingJobs] = useState({})
  const [selectedImage, setSelectedImage] = useState(FALLBACK_DEVBOX_IMAGE)
  const containerPollTimersRef = useRef([])
  const commitPollTimersRef = useRef([])
  const lastVisibleRefreshRef = useRef(0)

  const scheduleManagedTimeout = useCallback((timersRef, callback, delay) => {
    const timerId = window.setTimeout(() => {
      timersRef.current = timersRef.current.filter((id) => id !== timerId)
      callback()
    }, delay)
    timersRef.current.push(timerId)
  }, [])

  const clearManagedTimeouts = useCallback((timersRef) => {
    timersRef.current.forEach((timerId) => window.clearTimeout(timerId))
    timersRef.current = []
  }, [])

  useEffect(() => () => {
    clearManagedTimeouts(containerPollTimersRef)
    clearManagedTimeouts(commitPollTimersRef)
  }, [clearManagedTimeouts])

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

  const loadPublicationSettings = useCallback(async () => {
    try {
      const result = await getPublicationSettings()
      setPublishReviewSettings(result)
    } catch {
      setPublishReviewSettings({ review_policy: 'no_review', responsibility_ack_version: '' })
    }
  }, [])

  const loadContainers = useCallback(async ({ showLoading = true, silent = false } = {}) => {
    if (showLoading) {
      setContainersLoading(true)
    }
    if (!silent) {
      setContainersError('')
    }
    try {
      const result = await getMyContainers()
      const podNames = (result.containers || []).map((container) => container.name).filter(Boolean)
      const publicationStatuses = await getMyPublicationStatuses(podNames)
      const enrichedResult = {
        ...result,
        containers: mergePublicationStatuses(result.containers || [], publicationStatuses.statuses || [])
      }
      setContainersInfo(enrichedResult)
      setHiddenDeletingPods((prev) => {
        if (!prev.length) return prev
        const existingPodNames = new Set((enrichedResult.containers || []).map((container) => container.name))
        return prev.filter((podName) => existingPodNames.has(podName))
      })
      return enrichedResult
    } catch (err) {
      if (!silent) {
        setContainersError(err.message)
      }
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
    loadPublicationSettings()
  }, [loadHarborImages, loadContainers, loadPublicationSettings])

  useEffect(() => {
    const refreshVisibleContainers = () => {
      if (document.visibilityState === 'visible') {
        const now = Date.now()
        if (now - lastVisibleRefreshRef.current < VISIBLE_REFRESH_MIN_INTERVAL_MS) return
        lastVisibleRefreshRef.current = now
        loadContainers({ showLoading: false, silent: true })
      }
    }
    window.addEventListener('focus', refreshVisibleContainers)
    document.addEventListener('visibilitychange', refreshVisibleContainers)
    return () => {
      window.removeEventListener('focus', refreshVisibleContainers)
      document.removeEventListener('visibilitychange', refreshVisibleContainers)
    }
  }, [loadContainers])

  useEffect(() => {
    if (!harborInfo) return
    const images = allRepositoryImages(harborInfo)
    if (selectedImage && images.includes(selectedImage)) return
    setSelectedImage(defaultRepositoryImage(harborInfo))
  }, [harborInfo, selectedImage])

  const pollContainersUntil = useCallback((shouldContinue, attempt = 1) => {
    scheduleManagedTimeout(containerPollTimersRef, async () => {
      const result = await loadContainers({ showLoading: false })
      if (!result || attempt >= CONTAINER_REFRESH_MAX_ATTEMPTS) {
        return
      }
      if (shouldContinue(result)) {
        pollContainersUntil(shouldContinue, attempt + 1)
      }
    }, CONTAINER_REFRESH_INTERVAL_MS)
  }, [loadContainers, scheduleManagedTimeout])

  const resetApplyForm = useCallback(() => {
    setAppName('')
    setConnectionPassword('')
    setGpuConfig({ enabled: false, ...GPU_DEFAULT_RESOURCES })
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
    const gpuCount = Number.parseInt(gpuConfig.gpuCount, 10)
    const cpuCores = Number.parseInt(gpuConfig.cpuCores, 10)
    const memoryGb = Number.parseInt(gpuConfig.memoryGb, 10)
    const shmGb = Number.parseInt(gpuConfig.shmGb, 10)
    if (gpuConfig.enabled) {
      if (![1, 2].includes(gpuCount)) {
        setApplyFormError('GPU 数量必须为 1 到 2 张')
        return
      }
      const limits = gpuResourceLimits(gpuCount)
      if (!Number.isInteger(cpuCores) || cpuCores < 1 || cpuCores > limits.maxCpu) {
        setApplyFormError(`CPU 核数必须在 1 到 ${limits.maxCpu} 之间`)
        return
      }
      if (!Number.isInteger(memoryGb) || memoryGb < 1 || memoryGb > limits.maxMemory) {
        setApplyFormError(`内存必须在 1GB 到 ${limits.maxMemory}GB 之间`)
        return
      }
      if (!Number.isInteger(shmGb) || shmGb < 1 || shmGb > limits.maxShm) {
        setApplyFormError(`/dev/shm 必须在 1GB 到 ${limits.maxShm}GB 之间`)
        return
      }
    }
    const imageForContainer = selectedImage || defaultRepositoryImage(harborInfo)

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
        connection_password: connectionPassword,
        image: imageForContainer,
        needs_gpu: gpuConfig.enabled,
        gpu_count: gpuConfig.enabled ? gpuCount : 0,
        cpu_cores: gpuConfig.enabled ? cpuCores : null,
        memory_gb: gpuConfig.enabled ? memoryGb : null,
        shm_gb: gpuConfig.enabled ? shmGb : null
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
  }, [appName, connectionPassword, gpuConfig, harborInfo, pollContainersUntil, resetApplyForm, selectedImage])

  const handleDeleteContainer = useCallback(async (container) => {
    if (!container?.name) return
    const confirmed = window.confirm(`确定删除沙盒 ${container.name} 及其配套访问资源吗？`)
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

  const handleOpenApp = useCallback((container) => {
    if (!container?.url) return
    window.open(container.url, '_blank', 'noopener,noreferrer')
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

  const handleOpenVSCode = useCallback((container) => {
    const uri = ideRemoteUri('vscode', container)
    if (!uri) {
      setContainerError('无法生成 VSCode 连接地址，请先确认 SSH 命令已生成')
      return
    }
    setContainerError('')
    window.open(uri, '_blank', 'noopener,noreferrer')
  }, [])

  const handleOpenCursor = useCallback((container) => {
    const uri = ideRemoteUri('cursor', container)
    if (!uri) {
      setContainerError('无法生成 Cursor 连接地址，请先确认 SSH 命令已生成')
      return
    }
    setContainerError('')
    window.open(uri, '_blank', 'noopener,noreferrer')
  }, [])

  const updateSavingJob = useCallback((podName, patch) => {
    setSavingJobs((prev) => ({
      ...prev,
      [podName]: {
        ...(prev[podName] || {}),
        ...patch
      }
    }))
  }, [])

  const pollCommitJob = useCallback((podName, jobName, attempt = 1) => {
    scheduleManagedTimeout(commitPollTimersRef, async () => {
      try {
        const status = await getK3sJobStatus(jobName)
        updateSavingJob(podName, status)
        if (status.status === 'Succeeded') {
          loadHarborImages()
          window.alert(`模板保存成功：${status.image || ''}`)
          return
        }
        if (['Failed', 'NotFound', 'Error'].includes(status.status)) {
          setContainerError(status.message || '模板保存失败')
          return
        }
        if (attempt < COMMIT_JOB_MAX_ATTEMPTS) {
          pollCommitJob(podName, jobName, attempt + 1)
        } else {
          updateSavingJob(podName, {
            status: 'Error',
            message: '保存任务查询超时，请稍后刷新模板仓库确认结果'
          })
          setContainerError('保存任务查询超时，请稍后刷新模板仓库确认结果')
        }
      } catch (err) {
        updateSavingJob(podName, {
          status: 'Error',
          message: err.message
        })
        setContainerError(err.message)
      }
    }, COMMIT_JOB_REFRESH_INTERVAL_MS)
  }, [loadHarborImages, scheduleManagedTimeout, updateSavingJob])

  const handleSaveContainer = useCallback(async (container) => {
    if (!container?.name) return
    const imageName = window.prompt('请输入要保存的开发环境模板名称，例如 my-backup-v1：')
    if (!imageName) return

    const normalizedImageName = imageName.trim().toLowerCase()
    if (!COMMIT_IMAGE_NAME_PATTERN.test(normalizedImageName) || normalizedImageName.length > 80) {
      setContainerError('开发环境模板名称最多 80 个字符，只能包含小写字母、数字、点、下划线和中划线，且必须以字母或数字开头')
      return
    }

    setContainerError('')
    updateSavingJob(container.name, {
      status: 'Submitting',
      message: '正在提交保存任务'
    })
    try {
      const result = await commitContainer(container.name, normalizedImageName)
      updateSavingJob(container.name, result)
      pollCommitJob(container.name, result.job_name)
    } catch (err) {
      updateSavingJob(container.name, {
        status: 'Error',
        message: err.message
      })
      setContainerError(err.message)
    }
  }, [pollCommitJob, updateSavingJob])

  const handleOpenPublishModal = useCallback((container) => {
    setPublishTarget(container)
    setPublishDescription('')
    setPublishCoverFile(null)
    setPublishError('')
    setResponsibilityAck(false)
    loadPublicationSettings()
  }, [loadPublicationSettings])

  const handleClosePublishModal = useCallback(() => {
    if (publishingPodName) return
    setPublishTarget(null)
    setPublishDescription('')
    setPublishCoverFile(null)
    setPublishError('')
    setResponsibilityAck(false)
  }, [publishingPodName])

  const handlePublishCoverChange = useCallback(async (event) => {
    const file = event.target.files?.[0]
    setPublishError('')
    setPublishCoverFile(null)
    if (!file) return
    try {
      const compressed = await compressCoverImage(file)
      setPublishCoverFile(compressed)
    } catch (err) {
      setPublishError(err.message)
    }
  }, [])

  const updateContainerPublication = useCallback((podName, publication) => {
    setContainersInfo((prev) => ({
      ...prev,
      containers: (prev?.containers || []).map((container) => (
        container.name === podName
          ? {
              ...container,
              ...publicationStateFromRecord(publication)
            }
          : container
      ))
    }))
  }, [])

  const handlePublishSubmit = useCallback(async (event) => {
    event.preventDefault()
    if (!publishTarget?.name) return
    if (!publishDescription.trim()) {
      setPublishError('请填写应用简述')
      return
    }
    if (publishDescription.trim().length > APP_DESCRIPTION_MAX_LENGTH) {
      setPublishError(`应用简述最多 ${APP_DESCRIPTION_MAX_LENGTH} 个字符`)
      return
    }
    if (!responsibilityAck) {
      setPublishError('请先确认责任归属承诺知情书')
      return
    }

    setPublishingPodName(publishTarget.name)
    setPublishError('')
    try {
      const publication = await publishApp(publishTarget.name, {
        appDescription: publishDescription.trim(),
        cover: publishCoverFile,
        responsibilityAck
      })
      updateContainerPublication(publishTarget.name, publication)
      setPublishTarget(null)
      setPublishDescription('')
      setPublishCoverFile(null)
      setResponsibilityAck(false)
    } catch (err) {
      setPublishError(err.message)
    } finally {
      setPublishingPodName('')
    }
  }, [publishCoverFile, publishDescription, publishTarget, responsibilityAck, updateContainerPublication])

  const handleUnpublish = useCallback(async (container) => {
    if (!container?.name) return
    const confirmed = window.confirm(`确定取消发布应用 ${container.app_name || container.name} 吗？`)
    if (!confirmed) return

    setPublishingPodName(container.name)
    setContainerError('')
    try {
      await unpublishApp(container.name)
      updateContainerPublication(container.name, { is_published: false, review_status: 'unpublished' })
    } catch (err) {
      setContainerError(err.message)
    } finally {
      setPublishingPodName('')
    }
  }, [updateContainerPublication])

  const harborConfigured = harborInfo?.configured
  const privateMessage = !harborConfigured
    ? harborInfo?.message || '模板仓库暂不可用'
    : harborInfo?.private_message
  const publicMessage = !harborConfigured
    ? harborInfo?.message || '模板仓库暂不可用'
    : harborInfo?.public_message
  const visibleContainers = (containersInfo?.containers || []).filter(
    (container) => container.status !== 'Terminating' && !hiddenDeletingPods.includes(container.name)
  )

  return (
    <AppShell>
      <div className="dashboard-layout">
        <section className="content-panel container-request-panel" aria-labelledby="container-request-title">
          <div className="dashboard-panel-heading">
            <h1 id="container-request-title">开发沙盒</h1>
            <button
              className="btn btn--primary"
              type="button"
              onClick={handleOpenApplyModal}
              disabled={creatingContainer}
            >
              {creatingContainer ? '创建中…' : '创建开发沙盒'}
            </button>
          </div>

          {containerError ? <div className="feedback feedback--error">{containerError}</div> : null}
          {containersError ? <div className="feedback feedback--error">{containersError}</div> : null}
          {!containersError ? (
            <ContainerList
              containers={visibleContainers}
              deletingPodName={deletingPodName}
              loading={containersLoading}
              publishingPodName={publishingPodName}
              savingJobs={savingJobs}
              onCopySsh={handleCopySsh}
              onDelete={handleDeleteContainer}
              onOpenApp={handleOpenApp}
              onOpenCursor={handleOpenCursor}
              onOpenPublish={handleOpenPublishModal}
              onOpenVSCode={handleOpenVSCode}
              onOpenWebSsh={handleOpenWebSsh}
              onSaveContainer={handleSaveContainer}
              onUnpublish={handleUnpublish}
            />
          ) : null}
        </section>

        <aside className="image-repository-panel" aria-label="模板仓库">
          <div className="image-repository-panel__header">
            <div>
              <h1>模板仓库</h1>
            </div>
            <button className="btn btn--primary" type="button" onClick={loadHarborImages} disabled={loading}>
              {loading ? '刷新中' : '刷新'}
            </button>
          </div>

          {error ? <div className="feedback feedback--error">{error}</div> : null}

          {!error ? (
            <>
              <ImageList
                title="我的模板"
                project={harborInfo?.private_project}
                message={privateMessage}
                loading={loading}
                limit={3}
                selectedImage={selectedImage}
                variant="private"
                onSelectImage={setSelectedImage}
              />
              <ImageList
                title="公有模板"
                project={harborInfo?.public_project_info}
                message={publicMessage}
                loading={loading}
                limit={9}
                selectedImage={selectedImage}
                variant="public"
                onSelectImage={setSelectedImage}
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
          gpuConfig={gpuConfig}
          selectedImage={selectedImage}
          submitting={creatingContainer}
          onAppNameChange={handleAppNameChange}
          onConnectionPasswordChange={setConnectionPassword}
          onGpuConfigChange={setGpuConfig}
          onClose={handleCloseApplyModal}
          onSubmit={handleCreateContainer}
        />
      ) : null}
      <PublishAppModal
        app={publishTarget}
        description={publishDescription}
        coverFile={publishCoverFile}
        error={publishError}
        reviewSettings={publishReviewSettings}
        responsibilityAck={responsibilityAck}
        submitting={Boolean(publishingPodName)}
        onClose={handleClosePublishModal}
        onCoverChange={handlePublishCoverChange}
        onDescriptionChange={setPublishDescription}
        onResponsibilityAckChange={setResponsibilityAck}
        onSubmit={handlePublishSubmit}
      />
    </AppShell>
  )
}
