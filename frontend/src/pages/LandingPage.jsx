import { Link } from 'react-router-dom'

export default function LandingPage() {
  return (
    <div className="site-shell landing-shell">
      <header className="site-header">
        <Link className="site-brand" to="/" aria-label="Campus AI Community 首页">
          <span className="site-brand__mark">C</span>
          <span>Campus AI Community</span>
        </Link>
        <nav className="site-nav" aria-label="主导航">
          <Link className="nav-link" to="/login">
            登录
          </Link>
        </nav>
      </header>

      <main className="landing-main">
        <section className="landing-hero" aria-labelledby="landing-title">
          <div className="landing-copy">
            <h1 id="landing-title">校园 AI 社区平台</h1>
            <p>面向校园用户的统一智能服务入口。</p>
            <div className="hero-actions">
              <Link className="btn btn--primary" to="/login">
                进入平台
              </Link>
            </div>
          </div>
          <div className="hero-visual" aria-hidden="true">
            <div className="hero-visual__panel">
              <span />
              <span />
              <span />
            </div>
          </div>
        </section>
      </main>
    </div>
  )
}
