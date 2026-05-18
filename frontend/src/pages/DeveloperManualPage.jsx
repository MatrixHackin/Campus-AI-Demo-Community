import AppShell from '../components/AppShell'
import MarkdownRenderer from '../components/MarkdownRenderer'
import manualMarkdown from '../content/developer-manual.md?raw'

const manualNavItems = [
  { href: '#平台应用访问路径规范', label: '应用访问路径' },
  { href: '#利用ide开始-vibecoding', label: 'IDE：VS Code / Cursor' },
  { href: '#利用cli开始-vibecoding', label: 'CLI：WebSSH / SSH' },
  { href: '#安全规范', label: '安全规范' },
  { href: '#排障清单', label: '排障清单' }
]

export default function DeveloperManualPage() {
  return (
    <AppShell>
      <div className="manual-layout">
        <aside className="manual-toc" aria-label="开发手册目录">
          <strong>目录</strong>
          <nav>
            {manualNavItems.map((item) => (
              <a key={item.href} href={item.href}>
                {item.label}
              </a>
            ))}
          </nav>
        </aside>

        <section className="manual-panel" aria-labelledby="manual-title">
          <div className="section-heading">
            <h1 id="manual-title">开发手册</h1>
            <p>请按手册完成开发环境连接、应用访问配置和安全设置。</p>
          </div>

          <MarkdownRenderer markdown={manualMarkdown} />
        </section>
      </div>
    </AppShell>
  )
}
