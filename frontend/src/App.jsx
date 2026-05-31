import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import LandingPage from './pages/LandingPage'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import CommunityPage from './pages/CommunityPage'
import MyAppsPage from './pages/MyAppsPage'
import DeveloperManualPage from './pages/DeveloperManualPage'
import AdminPublicationReviewPage from './pages/AdminPublicationReviewPage'
import AdminNotificationsPage from './pages/AdminNotificationsPage'
import ProtectedRoute from './components/ProtectedRoute'

const WebSshPage = lazy(() => import('./pages/WebSshPage'))

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/dashboard"
        element={
          <ProtectedRoute>
            <DashboardPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/community"
        element={
          <ProtectedRoute>
            <CommunityPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/my-apps"
        element={
          <ProtectedRoute>
            <MyAppsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/manual"
        element={
          <ProtectedRoute>
            <DeveloperManualPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin/publication-review"
        element={
          <ProtectedRoute>
            <AdminPublicationReviewPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin/notifications"
        element={
          <ProtectedRoute>
            <AdminNotificationsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/ssh/:target"
        element={
          <ProtectedRoute>
            <Suspense fallback={null}>
              <WebSshPage />
            </Suspense>
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
