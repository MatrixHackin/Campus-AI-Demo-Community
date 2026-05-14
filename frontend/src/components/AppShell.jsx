import { NavLink } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const navItems = [
  { to: '/dashboard', label: '工作台' },
  { to: '/community', label: '应用社区' },
  { to: '/my-apps', label: '我的应用' }
]

export default function AppShell({ children }) {
  const { user, logout } = useAuth()
  const displayName = user?.display_name || user?.username || '用户'

  return (
    <div className="site-shell app-shell">
      <header className="app-nav">
        <div className="site-brand" aria-label="Campus AI Community">
          <span className="site-brand__mark">C</span>
          <span>Campus AI Community</span>
        </div>

        <nav className="app-nav__links" aria-label="应用导航">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              className={({ isActive }) => `app-nav__link${isActive ? ' app-nav__link--active' : ''}`}
              to={item.to}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="app-nav__account">
          <span className="user-name">{displayName}</span>
          <button className="btn btn--secondary" onClick={logout}>
            退出
          </button>
        </div>
      </header>

      <main className="app-blank-main">{children}</main>
    </div>
  )
}
