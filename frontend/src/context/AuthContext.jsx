import { createContext, useContext, useMemo, useState } from 'react'
import { login as loginApi } from '../api/client'

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
  }

  const value = useMemo(
    () => ({
      session,
      user: session?.user || null,
      token: session?.token || null,
      isAuthenticated: Boolean(session?.token),
      login,
      logout
    }),
    [session]
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
