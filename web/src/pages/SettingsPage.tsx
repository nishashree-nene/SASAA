import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { User, Bell, Shield, Trash2, Save } from 'lucide-react'
import { users, type UserPreferences } from '../lib/api'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../components/Toast'

export default function SettingsPage() {
  const { user, logout } = useAuth()
  const { toast } = useToast()
  const [prefs, setPrefs] = useState<UserPreferences | null>(null)

  const { data: profile } = useQuery({
    queryKey: ['user', 'me'],
    queryFn: () => users.me(),
    enabled: !!user,
  })

  const { data: preferences } = useQuery({
    queryKey: ['user', 'preferences'],
    queryFn: () => users.preferences(),
    enabled: !!user,
    onSuccess: (data) => setPrefs(data),
  })

  const updatePrefs = useMutation({
    mutationFn: (updates: Partial<UserPreferences>) => users.updatePreferences(updates),
    onSuccess: (data) => {
      setPrefs(data)
      toast('Preferences updated.', 'success')
    },
    onError: (err) => toast(err instanceof Error ? err.message : 'Update failed', 'error'),
  })

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <p>Manage your account, preferences, and privacy.</p>
        </div>
      </div>

      {/* Profile */}
      <div className="form-section">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">PROFILE</span>
            <h3>Account information</h3>
          </div>
          <User size={18} color="#a49bb7" />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div>
            <label style={{ fontSize: 12, color: '#a49bb7', fontWeight: 600, marginBottom: 6, display: 'block' }}>Full name</label>
            <input value={profile?.full_name ?? ''} readOnly style={{ opacity: 0.7 }} />
          </div>
          <div>
            <label style={{ fontSize: 12, color: '#a49bb7', fontWeight: 600, marginBottom: 6, display: 'block' }}>Email</label>
            <input value={profile?.email ?? ''} readOnly style={{ opacity: 0.7 }} />
          </div>
          <div>
            <label style={{ fontSize: 12, color: '#a49bb7', fontWeight: 600, marginBottom: 6, display: 'block' }}>Phone</label>
            <input value={profile?.phone_number ?? ''} readOnly style={{ opacity: 0.7 }} />
          </div>
          <div>
            <label style={{ fontSize: 12, color: '#a49bb7', fontWeight: 600, marginBottom: 6, display: 'block' }}>Verified</label>
            <input value={profile?.is_verified ? 'Yes' : 'No'} readOnly style={{ opacity: 0.7 }} />
          </div>
        </div>
      </div>

      {/* Notification preferences */}
      <div className="form-section">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">NOTIFICATIONS</span>
            <h3>Notification preferences</h3>
          </div>
          <Bell size={18} color="#a49bb7" />
        </div>

        {prefs && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {[
              { key: 'notify_new_message', label: 'New voicemail notifications' },
              { key: 'notify_high_priority', label: 'High priority alerts' },
              { key: 'notify_emergency', label: 'Emergency alerts' },
              { key: 'notify_suspicious', label: 'Suspicious transcription warnings' },
              { key: 'notify_email', label: 'Email notifications' },
            ].map(({ key, label }) => (
              <label key={key} style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={(prefs as Record<string, unknown>)[key] as boolean}
                  onChange={(e) => {
                    const newPrefs = { ...prefs, [key]: e.target.checked }
                    setPrefs(newPrefs)
                  }}
                  style={{ width: 'auto' }}
                />
                <span style={{ fontSize: 13 }}>{label}</span>
              </label>
            ))}
            <button
              className="primary"
              onClick={() => updatePrefs.mutate(prefs)}
              disabled={updatePrefs.isPending}
              style={{ marginTop: 8, padding: '10px 16px', borderRadius: 8, fontSize: 12, fontWeight: 700, border: 0, cursor: 'pointer', color: 'white', background: 'linear-gradient(100deg, #a34fee, #6940dc)', width: 'fit-content' }}
            >
              <Save size={13} style={{ display: 'inline', marginRight: 5 }} />
              {updatePrefs.isPending ? 'Saving…' : 'Save preferences'}
            </button>
          </div>
        )}
      </div>

      {/* Language preferences */}
      <div className="form-section">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">LANGUAGE</span>
            <h3>Language preferences</h3>
          </div>
        </div>
        {prefs && (
          <div className="form-row">
            <div>
              <label style={{ fontSize: 12, color: '#a49bb7', fontWeight: 600, marginBottom: 6, display: 'block' }}>Interface language</label>
              <select
                value={prefs.interface_language}
                onChange={(e) => setPrefs({ ...prefs, interface_language: e.target.value })}
              >
                <option value="en-IN">English</option>
                <option value="ta-IN">Tamil</option>
                <option value="hi-IN">Hindi</option>
                <option value="te-IN">Telugu</option>
              </select>
            </div>
            <div>
              <label style={{ fontSize: 12, color: '#a49bb7', fontWeight: 600, marginBottom: 6, display: 'block' }}>Transcript language</label>
              <select
                value={prefs.transcript_language}
                onChange={(e) => setPrefs({ ...prefs, transcript_language: e.target.value })}
              >
                <option value="ta-IN">Tamil</option>
                <option value="en-IN">English</option>
                <option value="hi-IN">Hindi</option>
                <option value="te-IN">Telugu</option>
              </select>
            </div>
          </div>
        )}
      </div>

      {/* Security */}
      <div className="form-section">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">SECURITY</span>
            <h3>Account security</h3>
          </div>
          <Shield size={18} color="#a49bb7" />
        </div>
        <button
          className="secondary"
          onClick={logout}
          style={{ padding: '10px 16px', borderRadius: 8, fontSize: 12, fontWeight: 700, border: '1px solid #493568', background: '#2b203e', color: '#d9c7ff', cursor: 'pointer' }}
        >
          Sign out of all devices
        </button>
      </div>

      {/* Privacy */}
      <div className="form-section">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">PRIVACY</span>
            <h3>Data retention</h3>
          </div>
          <Trash2 size={18} color="#a49bb7" />
        </div>
        <p className="muted small" style={{ marginBottom: 14 }}>
          Audio recordings are retained according to your preference. Set to null to keep recordings until manually deleted.
        </p>
        {prefs && (
          <div>
            <label style={{ fontSize: 12, color: '#a49bb7', fontWeight: 600, marginBottom: 6, display: 'block' }}>Audio retention (days)</label>
            <input
              type="number"
              value={prefs.audio_retention_days ?? ''}
              onChange={(e) => setPrefs({ ...prefs, audio_retention_days: e.target.value ? parseInt(e.target.value) : null })}
              placeholder="e.g. 90 (leave empty for permanent)"
              style={{ maxWidth: 300 }}
            />
          </div>
        )}
      </div>
    </div>
  )
}
