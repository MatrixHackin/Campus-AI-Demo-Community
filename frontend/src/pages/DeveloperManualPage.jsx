import AppShell from '../components/AppShell'
import MarkdownRenderer from '../components/MarkdownRenderer'
import manualMarkdown from '../content/developer-manual.md?raw'

const manualNavItems = [
  { href: '#方式一-ai-ide---trae', label: 'AI IDE：Trae' },
  { href: '#方式二-vs-code-插件---cline--deepseek', label: 'VS Code：Cline + DeepSeek' },
  { href: '#方式三-终端-agent---codex--阿里云百炼', label: '终端 Agent：Codex + 百炼' },
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
            <p>渲染本地 Markdown：frontend/src/content/developer-manual.md</p>
          </div>

          <MarkdownRenderer markdown={manualMarkdown} />
        </section>
      </div>
    </AppShell>
  )
}
