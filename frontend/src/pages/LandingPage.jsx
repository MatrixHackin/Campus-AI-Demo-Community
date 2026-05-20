import { Link } from 'react-router-dom'
import BrandLogo from '../components/BrandLogo'

export default function LandingPage() {
  return (
    <div className="site-shell landing-shell">
      <header className="site-header">
        <Link className="site-brand" to="/" aria-label="Campus AI Community 首页">
          <BrandLogo />
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
            <h1 id="landing-title" className="art-title">
              <span>校园AI+</span>
              <span>应用社区</span>
            </h1>
            <p>面向校园用户的统一智能服务入口。</p>
            <div className="hero-actions">
              <Link className="btn btn--primary" to="/login">
                进入平台
              </Link>
            </div>
          </div>
          <div className="hero-visual" aria-hidden="true">
            <div className="hero-visual__panel">
              <div className="gpunion-card">
                <div>
                  <strong>GPUnion</strong>
                  <span>AI Computing Platform</span>
                </div>
              </div>
              <div className="gpunion-orbit gpunion-orbit--one" />
              <div className="gpunion-orbit gpunion-orbit--two" />
              <div className="gpunion-node gpunion-node--one" />
              <div className="gpunion-node gpunion-node--two" />
            </div>
          </div>
        </section>
      </main>
    </div>
  )
}
