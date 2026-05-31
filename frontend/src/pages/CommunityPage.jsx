import { useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  deleteAppReview,
  getAppReviews,
  getPublishedApps,
  recordAppVisit,
  submitAppReview,
  toggleAppLike
} from '../api/client'
import AppShell from '../components/AppShell'

const REVIEW_COMMENT_MAX_LENGTH = 240
const SHARE_POSTER_WIDTH = 1080
const SHARE_POSTER_HEIGHT = 1440
const MARKET_SORT_OPTIONS = [
  { key: 'visit_count', label: '访问量' },
  { key: 'like_count', label: '点赞数' },
  { key: 'rating_avg', label: '评分' }
]

function appSortValue(app, key) {
  return Number(app?.[key] || 0)
}

function sortMarketApps(apps, sortKey) {
  return [...apps].sort((left, right) => {
    const primary = appSortValue(right, sortKey) - appSortValue(left, sortKey)
    if (primary !== 0) return primary

    if (sortKey === 'rating_avg') {
      const reviewTieBreak = appSortValue(right, 'review_count') - appSortValue(left, 'review_count')
      if (reviewTieBreak !== 0) return reviewTieBreak
    }

    const visitTieBreak = appSortValue(right, 'visit_count') - appSortValue(left, 'visit_count')
    if (visitTieBreak !== 0) return visitTieBreak

    return Number(right?.id || 0) - Number(left?.id || 0)
  })
}

function getAbsoluteUrl(value) {
  if (!value || typeof window === 'undefined') return ''
  return new URL(value, window.location.origin).toString()
}

function getShareTargetUrl(app) {
  return app?.share_url || app?.app_url || ''
}

function getShareText(app) {
  const publisher = app.owner_display_name || app.owner_username || '用户'
  return [
    `推荐应用：${app.app_name}`,
    app.app_description || '欢迎体验这个应用。',
    `发布者：${publisher}`,
    `访问地址：${getAbsoluteUrl(getShareTargetUrl(app))}`
  ].join('\n')
}

async function copyText(value) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value)
    return
  }

  const textarea = document.createElement('textarea')
  textarea.value = value
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  const copied = document.execCommand('copy')
  textarea.remove()
  if (!copied) throw new Error('复制失败')
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.crossOrigin = 'anonymous'
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('图片加载失败'))
    image.src = src
  })
}

function fillRoundedRect(context, x, y, width, height, radius, fillStyle) {
  context.beginPath()
  context.roundRect(x, y, width, height, radius)
  context.fillStyle = fillStyle
  context.fill()
}

function drawContainedImage(context, image, x, y, width, height) {
  const scale = Math.min(width / image.width, height / image.height)
  const drawWidth = image.width * scale
  const drawHeight = image.height * scale
  context.drawImage(
    image,
    x + (width - drawWidth) / 2,
    y + (height - drawHeight) / 2,
    drawWidth,
    drawHeight
  )
}

function drawWrappedText(context, text, x, y, maxWidth, lineHeight, maxLines) {
  const characters = [...text]
  const lines = []
  let currentLine = ''

  characters.forEach((character) => {
    const nextLine = `${currentLine}${character}`
    if (currentLine && context.measureText(nextLine).width > maxWidth) {
      lines.push(currentLine)
      currentLine = character
    } else {
      currentLine = nextLine
    }
  })
  if (currentLine) lines.push(currentLine)

  const visibleLines = lines.slice(0, maxLines)
  if (lines.length > maxLines) {
    let lastLine = visibleLines[maxLines - 1]
    while (lastLine && context.measureText(`${lastLine}…`).width > maxWidth) {
      lastLine = lastLine.slice(0, -1)
    }
    visibleLines[maxLines - 1] = `${lastLine}…`
  }

  visibleLines.forEach((line, index) => {
    context.fillText(line, x, y + index * lineHeight)
  })
}

function canvasToBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) {
        resolve(blob)
      } else {
        reject(new Error('海报生成失败'))
      }
    }, 'image/png')
  })
}

async function createSharePoster(app, qrDataUrl) {
  const canvas = document.createElement('canvas')
  canvas.width = SHARE_POSTER_WIDTH
  canvas.height = SHARE_POSTER_HEIGHT
  const context = canvas.getContext('2d')
  const publisher = app.owner_display_name || app.owner_username || '用户'
  const description = app.app_description || '欢迎体验这个应用。'

  context.fillStyle = '#edf4ff'
  context.fillRect(0, 0, canvas.width, canvas.height)
  fillRoundedRect(context, 54, 54, 972, 1332, 40, '#ffffff')

  context.fillStyle = '#173b78'
  context.font = '700 34px sans-serif'
  context.fillText('Campus AI Community', 100, 132)
  context.fillStyle = '#607089'
  context.font = '400 25px sans-serif'
  context.fillText('应用市场', 100, 178)

  fillRoundedRect(context, 100, 232, 880, 495, 28, '#f3f7fd')
  try {
    if (app.cover_url) {
      const coverImage = await loadImage(getAbsoluteUrl(app.cover_url))
      drawContainedImage(context, coverImage, 100, 232, 880, 495)
    } else {
      throw new Error('没有封面')
    }
  } catch {
    context.fillStyle = '#173b78'
    context.font = '800 148px sans-serif'
    context.textAlign = 'center'
    context.textBaseline = 'middle'
    context.fillText(app.app_name.slice(0, 1).toUpperCase(), 540, 480)
    context.textAlign = 'start'
    context.textBaseline = 'alphabetic'
  }

  context.fillStyle = '#102033'
  context.font = '800 62px sans-serif'
  drawWrappedText(context, app.app_name, 100, 824, 880, 78, 2)

  context.fillStyle = '#52647b'
  context.font = '400 32px sans-serif'
  drawWrappedText(context, description, 100, 976, 880, 48, 3)

  context.fillStyle = '#405269'
  context.font = '600 27px sans-serif'
  context.fillText(`发布者：${publisher}`, 100, 1150)

  const qrImage = await loadImage(qrDataUrl)
  fillRoundedRect(context, 710, 1114, 258, 258, 20, '#ffffff')
  context.drawImage(qrImage, 728, 1132, 222, 222)

  context.fillStyle = '#173b78'
  context.font = '700 33px sans-serif'
  context.fillText('扫码访问应用', 100, 1250)
  context.fillStyle = '#68758a'
  context.font = '400 23px sans-serif'
  context.fillText('Campus AI Community', 100, 1300)

  return canvasToBlob(canvas)
}

function AppCover({ app }) {
  if (app.cover_url) {
    return <img src={app.cover_url} alt={`${app.app_name} 封面`} />
  }

  return (
    <div className="market-app-card__cover-fallback" aria-hidden="true">
      <span>{app.app_name.slice(0, 1).toUpperCase()}</span>
    </div>
  )
}

function StarRating({ value, onChange, disabled = false, label = '评分' }) {
  return (
    <div className="star-rating" role="group" aria-label={label}>
      {[1, 2, 3, 4, 5].map((star) => (
        <button
          key={star}
          type="button"
          className={`star-rating__star${value >= star ? ' star-rating__star--active' : ''}`}
          onClick={() => onChange?.(star)}
          disabled={disabled}
          aria-label={`${star} 星`}
        >
          ★
        </button>
      ))}
      <span className="star-rating__value">{value} 星</span>
      <button
        type="button"
        className="star-rating__clear"
        onClick={() => onChange?.(0)}
        disabled={disabled}
      >
        清零
      </button>
    </div>
  )
}

function ReadonlyStars({ value }) {
  const rounded = Math.round(Number(value || 0))
  return (
    <span className="readonly-stars" aria-label={`${Number(value || 0).toFixed(1)} 星`}>
      {[1, 2, 3, 4, 5].map((star) => (
        <span key={star} className={rounded >= star ? 'readonly-stars__star--active' : ''}>★</span>
      ))}
    </span>
  )
}

function ReviewModal({
  app,
  form,
  reviews,
  loading,
  submitting,
  error,
  sort,
  hasMore,
  onClose,
  onChangeForm,
  onSubmit,
  onDelete,
  onToggleSort,
  onLoadMore
}) {
  if (!app) return null
  const remaining = REVIEW_COMMENT_MAX_LENGTH - form.comment.length

  if (typeof document === 'undefined') return null

  return createPortal(
    <div className="modal-backdrop modal-backdrop--review" role="presentation">
      <section className="modal-card review-modal-card" role="dialog" aria-modal="true" aria-labelledby="review-title">
        <div className="modal-card__header">
          <div>
            <h2 id="review-title">评价 {app.app_name}</h2>
            <p>评分和评论会帮助应用开发者改进体验。</p>
          </div>
          <button className="modal-close" type="button" onClick={onClose} disabled={submitting} aria-label="关闭">
            ×
          </button>
        </div>

        <form className="modal-form" onSubmit={onSubmit}>
          <label>
            <span>你的评分</span>
            <StarRating
              value={form.rating}
              onChange={(rating) => onChangeForm((prev) => ({ ...prev, rating }))}
              disabled={submitting}
            />
          </label>

          <label>
            <span>评论</span>
            <textarea
              value={form.comment}
              maxLength={REVIEW_COMMENT_MAX_LENGTH}
              rows={3}
              onChange={(event) => onChangeForm((prev) => ({ ...prev, comment: event.target.value }))}
              placeholder="写下你的体验、建议或问题。"
              disabled={submitting}
            />
            <small>{remaining} 字剩余</small>
          </label>

          {error ? <div className="feedback feedback--error">{error}</div> : null}

          <div className={`modal-actions review-modal-actions${form.hasReview ? ' review-modal-actions--split' : ''}`}>
            {form.hasReview ? (
              <button className="btn btn--ghost" type="button" onClick={onDelete} disabled={submitting}>
                删除我的评价
              </button>
            ) : null}
            <button className="btn btn--primary" type="submit" disabled={submitting}>
              {submitting ? '提交中…' : '提交评价'}
            </button>
          </div>
        </form>

        <div className="review-list">
          <div className="review-list__header">
            <div>
              <h3>最近评价</h3>
              <span>{app.review_count || 0} 条</span>
            </div>
            <button className="review-sort-button" type="button" onClick={onToggleSort} disabled={loading}>
              {sort === 'desc' ? '高分优先' : '低分优先'}
            </button>
          </div>
          <div
            className="review-list__scroll"
            onScroll={(event) => {
              const target = event.currentTarget
              if (hasMore && !loading && target.scrollTop + target.clientHeight >= target.scrollHeight - 24) {
                onLoadMore?.()
              }
            }}
          >
            {loading && reviews.length === 0 ? <div className="review-list__empty">正在加载评价…</div> : null}
            {!loading && reviews.length === 0 ? <div className="review-list__empty">暂无评价。</div> : null}
            {reviews.length > 0 ? (
              <div className="review-list__items">
                {reviews.map((review) => (
                  <article className="review-item" key={review.id}>
                    <div className="review-item__topline">
                      <strong>{review.display_name || review.username || '用户'}</strong>
                      <ReadonlyStars value={review.rating} />
                    </div>
                    {review.comment ? <p>{review.comment}</p> : <p className="review-item__empty">未填写评论</p>}
                  </article>
                ))}
              </div>
            ) : null}
            {hasMore ? (
              <button className="review-load-more" type="button" onClick={onLoadMore} disabled={loading}>
                {loading ? '加载中…' : '加载更多'}
              </button>
            ) : null}
          </div>
        </div>
      </section>
    </div>,
    document.body
  )
}

function ShareModal({ app, onClose }) {
  const [qrDataUrl, setQrDataUrl] = useState('')
  const [qrError, setQrError] = useState('')
  const [posterBlob, setPosterBlob] = useState(null)
  const [posterUrl, setPosterUrl] = useState('')
  const [posterError, setPosterError] = useState('')
  const [feedback, setFeedback] = useState('')

  useEffect(() => {
    const targetUrl = getShareTargetUrl(app)
    if (!targetUrl) return undefined
    let active = true
    setQrDataUrl('')
    setQrError('')
    setPosterBlob(null)
    setPosterUrl('')
    setPosterError('')
    setFeedback('')

    import('qrcode')
      .then((module) => {
        const qrCode = module.default || module
        return qrCode.toDataURL(getAbsoluteUrl(targetUrl), {
          width: 260,
          margin: 1,
          color: {
            dark: '#102033',
            light: '#ffffff'
          }
        })
      })
      .then((url) => {
        if (active) setQrDataUrl(url)
      })
      .catch(() => {
        if (active) setQrError('二维码生成失败，请直接复制应用链接。')
      })

    return () => {
      active = false
    }
  }, [app])

  useEffect(() => {
    if (!app || !qrDataUrl) return undefined
    let active = true
    let objectUrl = ''
    setPosterBlob(null)
    setPosterUrl('')
    setPosterError('')

    createSharePoster(app, qrDataUrl)
      .then((blob) => {
        if (!active) return
        objectUrl = URL.createObjectURL(blob)
        setPosterBlob(blob)
        setPosterUrl(objectUrl)
      })
      .catch(() => {
        if (active) setPosterError('海报生成失败，请使用复制文本或复制链接。')
      })

    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [app, qrDataUrl])

  if (!app || typeof document === 'undefined') return null

  const shareUrl = getAbsoluteUrl(getShareTargetUrl(app))
  const shareText = getShareText(app)
  const canNativeShare = typeof navigator.share === 'function'
  const canCopyImage = Boolean(navigator.clipboard?.write && window.ClipboardItem)

  const handleCopy = async (value, successMessage) => {
    try {
      await copyText(value)
      setFeedback(successMessage)
    } catch {
      setFeedback('复制失败，请手动选择内容复制。')
    }
  }

  const handleNativeShare = async () => {
    try {
      await navigator.share({
        title: app.app_name,
        text: `${app.app_name} - ${app.app_description || '欢迎体验这个应用。'}`,
        url: shareUrl
      })
      setFeedback('已打开系统分享。')
    } catch (error) {
      if (error?.name !== 'AbortError') setFeedback('系统分享暂不可用，请复制链接分享。')
    }
  }

  const handleCopyPoster = async () => {
    try {
      await navigator.clipboard.write([
        new ClipboardItem({ 'image/png': posterBlob })
      ])
      setFeedback('海报图片已复制。')
    } catch {
      setFeedback('当前浏览器无法复制图片，请下载海报。')
    }
  }

  const handleSharePoster = async () => {
    const file = new File([posterBlob], `${app.app_name}-分享海报.png`, { type: 'image/png' })
    try {
      if (!navigator.canShare?.({ files: [file] })) {
        setFeedback('当前浏览器无法直接分享图片，请下载海报。')
        return
      }
      await navigator.share({
        title: app.app_name,
        text: `${app.app_name} - ${app.app_description || '欢迎体验这个应用。'}`,
        files: [file]
      })
      setFeedback('已打开系统分享。')
    } catch (error) {
      if (error?.name !== 'AbortError') setFeedback('当前浏览器无法直接分享图片，请下载海报。')
    }
  }

  return createPortal(
    <div className="modal-backdrop modal-backdrop--share" role="presentation">
      <section className="modal-card share-modal-card" role="dialog" aria-modal="true" aria-labelledby="share-title">
        <div className="modal-card__header">
          <div>
            <h2 id="share-title">分享应用</h2>
            <p>将 {app.app_name} 分享给更多用户。</p>
          </div>
          <button className="modal-close" type="button" onClick={onClose} aria-label="关闭分享窗口">
            ×
          </button>
        </div>

        <div className="share-modal-layout">
          <section className="share-action-section share-action-section--quick" aria-label="快捷分享">
            <h3>快捷分享</h3>
            <div className="share-action-stack">
              <button className="btn btn--secondary" type="button" onClick={() => handleCopy(shareText, '分享文本已复制。')}>
                复制分享文本
              </button>
              <button className="btn btn--secondary" type="button" onClick={() => handleCopy(shareUrl, '应用链接已复制。')}>
                复制链接
              </button>
              <button
                className="btn btn--primary"
                type="button"
                onClick={handleNativeShare}
                disabled={!canNativeShare}
                title={canNativeShare ? '打开系统分享' : '当前浏览器不支持系统分享'}
              >
                系统分享
              </button>
            </div>
          </section>

          <section className="share-poster-section" aria-label="分享海报">
            <h3>分享海报</h3>
            <div className="share-poster-preview">
              {posterUrl ? <img src={posterUrl} alt={`${app.app_name} 分享海报`} /> : null}
              {!posterUrl && !qrError && !posterError ? <span>正在生成海报…</span> : null}
              {qrError || posterError ? <span>{qrError || posterError}</span> : null}
            </div>
          </section>

          <section className="share-action-section share-action-section--poster" aria-label="海报操作">
            <h3>海报操作</h3>
            <div className="share-action-stack">
              <button
                className="btn btn--secondary"
                type="button"
                onClick={handleCopyPoster}
                disabled={!canCopyImage || !posterBlob}
                title={canCopyImage ? '复制海报图片' : '当前浏览器不支持复制图片'}
              >
                复制图片
              </button>
              <a
                className={`btn btn--secondary${posterUrl ? '' : ' btn--disabled'}`}
                href={posterUrl || undefined}
                download={`${app.app_name}-分享海报.png`}
                aria-disabled={!posterUrl}
              >
                下载图片
              </a>
              <button
                className="btn btn--primary"
                type="button"
                onClick={handleSharePoster}
                disabled={!canNativeShare || !posterBlob}
                title={canNativeShare ? '打开系统分享' : '当前浏览器不支持系统分享'}
              >
                分享图片
              </button>
            </div>
          </section>
        </div>

        {feedback ? <div className="feedback feedback--success share-feedback">{feedback}</div> : null}
      </section>
    </div>,
    document.body
  )
}

export default function CommunityPage() {
  const [apps, setApps] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [likingAppIds, setLikingAppIds] = useState([])
  const [reviewModalApp, setReviewModalApp] = useState(null)
  const [reviewForm, setReviewForm] = useState({ rating: 5, comment: '', hasReview: false })
  const [reviews, setReviews] = useState([])
  const [reviewLoading, setReviewLoading] = useState(false)
  const [reviewSubmitting, setReviewSubmitting] = useState(false)
  const [reviewError, setReviewError] = useState('')
  const [reviewSort, setReviewSort] = useState('desc')
  const [reviewNextOffset, setReviewNextOffset] = useState(null)
  const [reviewHasMore, setReviewHasMore] = useState(false)
  const [shareModalApp, setShareModalApp] = useState(null)
  const [marketSortKey, setMarketSortKey] = useState('visit_count')
  const sortedApps = useMemo(() => sortMarketApps(apps, marketSortKey), [apps, marketSortKey])

  const updateAppReviewSummary = useCallback((appId, reviewPayload) => {
    setApps((prev) => prev.map((item) => (
      item.id === appId
        ? {
            ...item,
            rating_avg: reviewPayload.summary?.rating_avg ?? item.rating_avg,
            rating_sum: reviewPayload.summary?.rating_sum ?? item.rating_sum,
            review_count: reviewPayload.summary?.review_count ?? item.review_count,
            my_review: reviewPayload.my_review || null
          }
        : item
    )))
    setReviewModalApp((prev) => (
      prev?.id === appId
        ? {
            ...prev,
            rating_avg: reviewPayload.summary?.rating_avg ?? prev.rating_avg,
            rating_sum: reviewPayload.summary?.rating_sum ?? prev.rating_sum,
            review_count: reviewPayload.summary?.review_count ?? prev.review_count,
            my_review: reviewPayload.my_review || null
          }
        : prev
    ))
  }, [])

  const loadApps = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await getPublishedApps()
      setApps(result.apps || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadApps()
  }, [loadApps])

  const handleOpenApp = useCallback((app) => {
    if (!app?.app_url) return
    window.open(app.app_url, '_blank', 'noopener,noreferrer')
    setApps((prev) => prev.map((item) => (
      item.id === app.id ? { ...item, visit_count: (item.visit_count || 0) + 1 } : item
    )))
    recordAppVisit(app.id)
      .then((updated) => {
        setApps((prev) => prev.map((item) => (
          item.id === updated.id ? { ...item, visit_count: updated.visit_count } : item
        )))
      })
      .catch(() => {
        // 访问应用不应被计数失败阻塞，刷新应用市场时会重新同步后端计数。
      })
  }, [])

  const handleToggleLike = useCallback(async (app) => {
    if (!app?.id) return

    const previousApp = app
    const nextLiked = !app.is_liked
    setError('')
    let shouldSubmit = true
    setLikingAppIds((prev) => {
      if (prev.includes(app.id)) {
        shouldSubmit = false
        return prev
      }
      return [...prev, app.id]
    })
    if (!shouldSubmit) return
    setApps((prev) => prev.map((item) => (
      item.id === app.id
        ? {
            ...item,
            is_liked: nextLiked,
            like_count: Math.max(0, (item.like_count || 0) + (nextLiked ? 1 : -1))
          }
        : item
    )))

    try {
      const updated = await toggleAppLike(app.id)
      setApps((prev) => prev.map((item) => (
        item.id === updated.id
          ? {
              ...item,
              like_count: updated.like_count,
              is_liked: updated.is_liked
            }
          : item
      )))
    } catch (err) {
      setApps((prev) => prev.map((item) => (item.id === previousApp.id ? previousApp : item)))
      setError(err.message)
    } finally {
      setLikingAppIds((prev) => prev.filter((id) => id !== app.id))
    }
  }, [])

  const loadReviewsPage = useCallback(async ({ appId, sort = 'desc', offset = 0, append = false }) => {
    setReviewLoading(true)
    setReviewError('')
    try {
      const result = await getAppReviews(appId, { offset, limit: 10, sort })
      setReviews((prev) => {
        if (!append) return result.reviews || []
        const seen = new Set(prev.map((review) => review.id))
        return [
          ...prev,
          ...(result.reviews || []).filter((review) => !seen.has(review.id))
        ]
      })
      setReviewNextOffset(result.next_offset ?? null)
      setReviewHasMore(Boolean(result.has_more))
      setReviewSort(result.sort || sort)
      setReviewForm({
        rating: result.my_review?.rating ?? 5,
        comment: result.my_review?.comment || '',
        hasReview: Boolean(result.my_review)
      })
      updateAppReviewSummary(appId, result)
      return result
    } catch (err) {
      setReviewError(err.message)
      return null
    } finally {
      setReviewLoading(false)
    }
  }, [updateAppReviewSummary])

  const openReviewModal = useCallback(async (app) => {
    if (!app?.id) return
    setReviewModalApp(app)
    setReviews([])
    setReviewError('')
    setReviewSort('desc')
    setReviewNextOffset(null)
    setReviewHasMore(false)
    setReviewForm({
      rating: app.my_review?.rating ?? 5,
      comment: app.my_review?.comment || '',
      hasReview: Boolean(app.my_review)
    })
    await loadReviewsPage({ appId: app.id, sort: 'desc', offset: 0, append: false })
  }, [loadReviewsPage])

  const closeReviewModal = useCallback(() => {
    if (reviewSubmitting) return
    setReviewModalApp(null)
    setReviews([])
    setReviewError('')
    setReviewNextOffset(null)
    setReviewHasMore(false)
  }, [reviewSubmitting])

  const handleSubmitReview = useCallback(async (event) => {
    event.preventDefault()
    if (!reviewModalApp?.id) return
    setReviewSubmitting(true)
    setReviewError('')
    try {
      const result = await submitAppReview(reviewModalApp.id, {
        rating: reviewForm.rating,
        comment: reviewForm.comment
      })
      setReviewForm({
        rating: result.my_review?.rating ?? reviewForm.rating,
        comment: result.my_review?.comment || '',
        hasReview: Boolean(result.my_review)
      })
      updateAppReviewSummary(reviewModalApp.id, result)
      await loadReviewsPage({ appId: reviewModalApp.id, sort: reviewSort, offset: 0, append: false })
    } catch (err) {
      setReviewError(err.message)
    } finally {
      setReviewSubmitting(false)
    }
  }, [loadReviewsPage, reviewForm.comment, reviewForm.rating, reviewModalApp, reviewSort, updateAppReviewSummary])

  const handleDeleteReview = useCallback(async () => {
    if (!reviewModalApp?.id) return
    setReviewSubmitting(true)
    setReviewError('')
    try {
      const result = await deleteAppReview(reviewModalApp.id)
      setReviewForm({ rating: 5, comment: '', hasReview: false })
      updateAppReviewSummary(reviewModalApp.id, result)
      await loadReviewsPage({ appId: reviewModalApp.id, sort: reviewSort, offset: 0, append: false })
    } catch (err) {
      setReviewError(err.message)
    } finally {
      setReviewSubmitting(false)
    }
  }, [loadReviewsPage, reviewModalApp, reviewSort, updateAppReviewSummary])

  const handleToggleReviewSort = useCallback(() => {
    if (!reviewModalApp?.id) return
    const nextSort = reviewSort === 'desc' ? 'asc' : 'desc'
    setReviews([])
    setReviewNextOffset(null)
    setReviewHasMore(false)
    loadReviewsPage({ appId: reviewModalApp.id, sort: nextSort, offset: 0, append: false })
  }, [loadReviewsPage, reviewModalApp, reviewSort])

  const handleLoadMoreReviews = useCallback(() => {
    if (!reviewModalApp?.id || !reviewHasMore || reviewNextOffset == null || reviewLoading) return
    loadReviewsPage({
      appId: reviewModalApp.id,
      sort: reviewSort,
      offset: reviewNextOffset,
      append: true
    })
  }, [loadReviewsPage, reviewHasMore, reviewLoading, reviewModalApp, reviewNextOffset, reviewSort])

  return (
    <AppShell>
      <section className="market-panel" aria-label="应用市场">
        <div className="market-panel__toolbar">
          <div className="market-sort-control" role="group" aria-label="应用排序方式">
            <span>排序</span>
            <div className="market-sort-control__options">
              {MARKET_SORT_OPTIONS.map((option) => (
                <button
                  key={option.key}
                  className={`market-sort-button${marketSortKey === option.key ? ' market-sort-button--active' : ''}`}
                  type="button"
                  onClick={() => setMarketSortKey(option.key)}
                  aria-pressed={marketSortKey === option.key}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
          <button className="btn btn--primary" type="button" onClick={loadApps} disabled={loading}>
            {loading ? '刷新中…' : '刷新'}
          </button>
        </div>

        {error ? <div className="feedback feedback--error">{error}</div> : null}
        {loading ? <div className="muted-card">正在加载应用市场…</div> : null}
        {!loading && !error && apps.length === 0 ? <div className="muted-card">暂无已发布应用。</div> : null}

        {!loading && !error && apps.length > 0 ? (
          <div className="market-app-grid">
            {sortedApps.map((app) => (
              <article className="market-app-card" key={app.id}>
                <div className="market-app-card__cover">
                  <AppCover app={app} />
                </div>
                <div className="market-app-card__body">
                  <div>
                    <div className="market-app-card__title-row">
                      <h2>{app.app_name}</h2>
                      <span className="market-rating-pill">
                        {app.review_count ? (
                          <>
                            <ReadonlyStars value={app.rating_avg} />
                            {Number(app.rating_avg || 0).toFixed(1)}
                          </>
                        ) : '暂无评分'}
                      </span>
                    </div>
                    <p>{app.app_description}</p>
                  </div>
                  <div className="market-app-card__footer">
                    <div className="market-app-card__meta">
                      <span>发布者：{app.owner_display_name || app.owner_username}</span>
                      <span>访问量：{app.visit_count || 0} · 评价：{app.review_count || 0} 条</span>
                    </div>
                    <div className="market-app-card__actions">
                      <button
                        className={`market-like-button${app.is_liked ? ' market-like-button--active' : ''}`}
                        type="button"
                        onClick={() => handleToggleLike(app)}
                        disabled={likingAppIds.includes(app.id)}
                        aria-pressed={app.is_liked}
                        title={app.is_liked ? '取消点赞' : '点赞'}
                      >
                        <span aria-hidden="true">{app.is_liked ? '♥' : '♡'}</span>
                        {app.like_count || 0}
                      </button>
                      <button className="btn btn--primary" type="button" onClick={() => handleOpenApp(app)}>
                        访问应用
                      </button>
                      <button className="btn btn--ghost" type="button" onClick={() => openReviewModal(app)}>
                        评价
                      </button>
                      <button className="btn btn--ghost" type="button" onClick={() => setShareModalApp(app)}>
                        分享
                      </button>
                    </div>
                  </div>
                </div>
              </article>
            ))}
          </div>
        ) : null}
      </section>
      <ReviewModal
        app={reviewModalApp}
        form={reviewForm}
        reviews={reviews}
        loading={reviewLoading}
        submitting={reviewSubmitting}
        error={reviewError}
        sort={reviewSort}
        hasMore={reviewHasMore}
        onClose={closeReviewModal}
        onChangeForm={setReviewForm}
        onSubmit={handleSubmitReview}
        onDelete={handleDeleteReview}
        onToggleSort={handleToggleReviewSort}
        onLoadMore={handleLoadMoreReviews}
      />
      <ShareModal app={shareModalApp} onClose={() => setShareModalApp(null)} />
    </AppShell>
  )
}
