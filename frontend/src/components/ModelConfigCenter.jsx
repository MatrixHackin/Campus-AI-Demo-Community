import { useEffect } from 'react'
import { createPortal } from 'react-dom'

const EMPTY_DRAFT = {
  api_base: 'https://api.deepseek.com/v1',
  model_name: '',
  api_key: ''
}

export { EMPTY_DRAFT }

export default function ModelConfigCenter({
  configs,
  loading,
  error,
  draft,
  editingId,
  saving,
  open,
  onDraftChange,
  onAdd,
  onEdit,
  onClose,
  onSave,
  onDelete
}) {
  return (
    <aside className="model-config-panel" aria-label="模型配置中心">
      <div className="model-config-panel__header">
        <h1>模型配置中心</h1>
        <button className="btn btn--primary" type="button" onClick={onAdd} disabled={saving}>
          添加配置
        </button>
      </div>
      <p className="model-config-panel__lead">保存多组模型接口、模型名称和 API Key。开始开发时从这里选择一组。</p>

      {error && !open ? <div className="feedback feedback--error">{error}</div> : null}
      {loading ? <div className="muted-card">正在加载模型配置…</div> : null}

      {!loading ? (
        <div className="model-config-list" aria-label="已保存的模型配置">
          {configs.length === 0 ? (
            <div className="muted-card">还没有模型配置。点击「添加配置」，填写接口、模型名称和 API Key。</div>
          ) : configs.map((config) => (
            <article className={`model-config-card${editingId === config.id ? ' model-config-card--active' : ''}`} key={config.id}>
              <div>
                <strong>{config.model_name}</strong>
                <span>{config.api_base}</span>
                <small>{config.api_key_hint || '未保存 API Key'}</small>
              </div>
              <div className="model-config-card__actions">
                <button className="container-action-button" type="button" onClick={() => onEdit(config)} disabled={saving}>
                  编辑
                </button>
                <button className="container-delete-button" type="button" onClick={() => onDelete(config)} disabled={saving}>
                  删除
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : null}

      {open ? (
        <ModelConfigFormModal
          draft={draft}
          editing={Boolean(editingId)}
          error={error}
          saving={saving}
          onClose={onClose}
          onDraftChange={onDraftChange}
          onSave={onSave}
        />
      ) : null}
    </aside>
  )
}

function ModelConfigFormModal({ draft, editing, error, saving, onClose, onDraftChange, onSave }) {
  useEffect(() => {
    function onKeyDown(event) {
      if (event.key === 'Escape' && !saving) onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose, saving])

  if (typeof document === 'undefined') return null

  return createPortal(
    <div
      className="modal-backdrop modal-backdrop--dashboard"
      role="presentation"
      onClick={() => {
        if (!saving) onClose()
      }}
    >
      <div
        className="modal-card dashboard-modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="model-config-form-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-card__header">
          <div>
            <h2 id="model-config-form-title">{editing ? '编辑配置' : '添加配置'}</h2>
            <p>填写模型接口、模型名称和 API Key。Key 只保存在当前账号下。</p>
          </div>
          <button className="modal-close" type="button" onClick={onClose} disabled={saving} aria-label="关闭配置表单">
            ×
          </button>
        </div>
        <form className="modal-form" onSubmit={onSave}>
          <label>
            <span>接口</span>
            <input
              type="url"
              value={draft.api_base}
              onChange={(event) => onDraftChange({ ...draft, api_base: event.target.value })}
              placeholder="https://api.deepseek.com/v1"
              disabled={saving}
              autoFocus
              required
            />
          </label>
          <label>
            <span>模型名称</span>
            <input
              type="text"
              value={draft.model_name}
              onChange={(event) => onDraftChange({ ...draft, model_name: event.target.value })}
              placeholder="例如 deepseek-chat"
              disabled={saving}
              required
            />
          </label>
          <label>
            <span>API Key</span>
            <input
              type="password"
              value={draft.api_key}
              onChange={(event) => onDraftChange({ ...draft, api_key: event.target.value })}
              placeholder={editing ? '留空则保留已保存的 Key' : '只保存在你的账号下'}
              autoComplete="off"
              disabled={saving}
              required={!editing}
            />
          </label>
          {error ? <div className="feedback feedback--error">{error}</div> : null}
          <div className="modal-actions">
            <button className="btn btn--ghost" type="button" onClick={onClose} disabled={saving}>
              取消
            </button>
            <button className="btn btn--primary" type="submit" disabled={saving}>
              {saving ? '保存中…' : '保存'}
            </button>
          </div>
        </form>
      </div>
    </div>,
    document.body
  )
}

export function ModelConfigPicker({ appName, configs, loading, onClose, onSelect }) {
  if (typeof document === 'undefined') return null

  return createPortal(
    <div className="modal-backdrop modal-backdrop--dashboard" role="presentation">
      <div className="modal-card dashboard-modal-card" role="dialog" aria-modal="true" aria-labelledby="model-picker-title">
        <div className="modal-card__header">
          <div>
            <h2 id="model-picker-title">选择模型配置</h2>
            <p>为 {appName || '当前沙盒'} 选择一组已保存的配置，随后会打开新的开发页面。</p>
          </div>
          <button className="modal-close" type="button" onClick={onClose} aria-label="关闭模型配置选择">
            ×
          </button>
        </div>
        {loading ? <div className="muted-card">正在加载模型配置…</div> : null}
        {!loading && configs.length === 0 ? (
          <div className="muted-card">还没有可用的模型配置。请先在右侧模型配置中心点击「添加配置」。</div>
        ) : null}
        {!loading && configs.length > 0 ? (
          <div className="model-config-picker" role="list">
            {configs.map((config) => (
              <button
                className="model-config-picker__item"
                key={config.id}
                type="button"
                onClick={() => onSelect(config)}
              >
                <strong>{config.model_name}</strong>
                <span>{config.api_base}</span>
                <small>{config.api_key_hint || '未保存 API Key'}</small>
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </div>,
    document.body
  )
}
