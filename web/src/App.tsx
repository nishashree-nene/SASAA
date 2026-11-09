import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './contexts/AuthContext'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import DashboardPage from './pages/DashboardPage'
import VoicemailInboxPage from './pages/VoicemailInboxPage'
import VoicemailDetailPage from './pages/VoicemailDetailPage'
import AnalyticsPage from './pages/AnalyticsPage'
import SettingsPage from './pages/SettingsPage'
import TelephonySetupPage from './pages/TelephonySetupPage'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth()
  if (isLoading) return <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#090811' }} />
  if (!user) return <Navigate to="/login" replace />
  return <Layout>{children}</Layout>
}

export default function App() {
  const { user, isLoading } = useAuth()

  if (isLoading) {
    return <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#090811', color: '#a49bb7' }}>Loading SASAA…</div>
  }

  return (
    <Routes>
      {/* Public routes */}
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage />} />
      <Route path="/register" element={user ? <Navigate to="/" replace /> : <RegisterPage />} />

      {/* Protected routes */}
      <Route path="/" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
      <Route path="/voicemails" element={<ProtectedRoute><VoicemailInboxPage /></ProtectedRoute>} />
      <Route path="/voicemails/:id" element={<ProtectedRoute><VoicemailDetailPage /></ProtectedRoute>} />
      <Route path="/analytics" element={<ProtectedRoute><AnalyticsPage /></ProtectedRoute>} />
      <Route path="/telephony" element={<ProtectedRoute><TelephonySetupPage /></ProtectedRoute>} />
      <Route path="/settings" element={<ProtectedRoute><SettingsPage /></ProtectedRoute>} />

      {/* Fallback */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
