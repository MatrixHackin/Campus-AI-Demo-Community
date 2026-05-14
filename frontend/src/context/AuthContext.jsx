import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { getCurrentUser, login as loginApi } from '../api/client'

const AuthContext = createContext(null)
const STORAGE_KEY = 'campus-ai-auth'

export function AuthProvider({ children }) {
  const [session, setSession] = useState(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      return raw ? JSON.parse(raw) : null
    } catch {
      localStorage.removeItem(STORAGE_KEY)
      return null
    }
  })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let ignore = false

    async function syncCookieSession() {
      try {
        const result = await getCurrentUser()
        if (!ignore) {
          setSession((current) => ({
            token: current?.token || null,
            user: result.user,
            expiresAt: result.expires_at,
            authProvider: result.auth_provider
          }))
        }
      } catch {
        if (!ignore && !session?.token) {
          setSession(null)
        }
      } finally {
        if (!ignore) {
          setLoading(false)
        }
      }
    }

    syncCookieSession()
    return () => {
      ignore = true
    }
    // only run once on app startup
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const login = async (credentials) => {
    const result = await loginApi(credentials)
    const nextSession = {
      token: result.access_token,
      user: result.user,
      expiresAt: result.expires_at
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(nextSession))
    setSession(nextSession)
    return result
  }

  const logout = () => {
    localStorage.removeItem(STORAGE_KEY)
    setSession(null)
    window.location.href = '/auth/logout'
  }

  const value = useMemo(
    () => ({
      session,
      user: session?.user || null,
      token: session?.token || null,
      isLoading: loading,
      isAuthenticated: Boolean(session?.token || session?.user),
      login,
      logout
    }),
    [loading, session]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth 必须在 AuthProvider 内使用')
  }
  return context
}
