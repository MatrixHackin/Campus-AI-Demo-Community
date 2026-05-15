import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { getCurrentUser, login as loginApi } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [session, setSession] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let ignore = false

    async function syncCookieSession() {
      try {
        const result = await getCurrentUser()
        if (!ignore) {
          setSession({
            user: result.user,
            expiresAt: result.expires_at,
            authProvider: result.auth_provider
          })
        }
      } catch {
        if (!ignore) {
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
  }, [])

  const login = async (credentials) => {
    const result = await loginApi(credentials)
    const nextSession = {
      user: result.user,
      expiresAt: result.expires_at,
      authProvider: result.auth_provider || 'local'
    }
    setSession(nextSession)
    return result
  }

  const logout = () => {
    setSession(null)
    window.location.href = '/auth/logout'
  }

  const value = useMemo(
    () => ({
      session,
      user: session?.user || null,
      isLoading: loading,
      isAuthenticated: Boolean(session?.user),
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
