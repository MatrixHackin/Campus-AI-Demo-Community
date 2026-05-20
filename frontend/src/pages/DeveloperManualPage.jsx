import { useMemo } from 'react'
import AppShell from '../components/AppShell'
import MarkdownRenderer, { extractMarkdownHeadings } from '../components/MarkdownRenderer'
import manualMarkdown from '../content/developer-manual.md?raw'

export default function DeveloperManualPage() {
  const manualNavItems = useMemo(() => extractMarkdownHeadings(manualMarkdown), [])

  return (
    <AppShell>
      <div className="manual-layout">
        <aside className="manual-toc" aria-label="开发手册目录">
          <strong>目录</strong>
          <nav>
            {manualNavItems.map((item) => (
              <a className={`manual-toc__link manual-toc__link--level-${item.level}`} key={item.id} href={`#${item.id}`}>
                {item.text}
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
