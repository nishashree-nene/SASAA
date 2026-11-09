import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  AlertTriangle, Inbox, Phone, ShieldCheck, Activity,
  Clock, CheckCircle, Loader, PhoneIncoming
} from 'lucide-react'
import { analytics, messages } from '../lib/api'
import { useAuth } from '../contexts/AuthContext'

export default function DashboardPage() {
  const { user } = useAuth()
  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['dashboard'],
    queryFn: () => analytics.dashboard(),
  })
  const { data: msgData } = useQuery({
    queryKey: ['messages', 'recent'],
    queryFn: () => messages.list({ page: 1, page_size: 5 }),
  })

  const recentMessages = msgData?.items ?? []

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Welcome back, {user?.full_name?.split(' ')[0] ?? 'there'}</h1>
          <p>Your voice messages and voicemail analysis at a glance.</p>
        </div>
        <Link to="/voicemails" className="secondary" style={{ textDecoration: 'none', padding: '10px 18px', borderRadius: 10, fontSize: 12, fontWeight: 800 }}>
          View all voicemails
        </Link>
      </div>

      <section className="stats-grid">
        <StatCard icon={<Inbox size={18} />} label="Total messages" value={stats?.total_messages} loading={statsLoading} />
        <StatCard icon={<Clock size={18} />} label="Unread" value={stats?.unread_messages} loading={statsLoading} />
        <StatCard icon={<ShieldCheck size={18} />} label="Needs verification" value={stats?.messages_needing_verification} loading={statsLoading} />
        <StatCard icon={<AlertTriangle size={18} />} label="High priority" value={stats?.high_priority_messages} loading={statsLoading} />
      </section>

      <div className="divider" />

      <div className="panel" style={{ padding: 22 }}>
        <div className="panel-heading">
          <div>
            <span className="eyebrow">RECENT ACTIVITY</span>
            <h3>Recent voice messages</h3>
          </div>
          <PhoneIncoming size={18} color="#a49bb7" />
        </div>

        {recentMessages.length === 0 ? (
          <div className="empty-state">
            <Inbox size={40} color="#4a4458" />
            <strong>No messages yet</strong>
            <p>Create a message and upload audio to get started with SASAA.</p>
          </div>
        ) : (
          <div className="message-list">
            {recentMessages.map((msg) => (
              <Link key={msg.id} to={`/voicemails/${msg.id}`} style={{ textDecoration: 'none', color: 'inherit' }}>
                <div className="message-item" style={{ display: 'flex', alignItems: 'center', gap: 12, padding: 14, border: '1px solid #30283f', borderRadius: 10, background: '#1b1729', marginBottom: 8 }}>
                  <div className="message-avatar" style={{ width: 36, height: 36, borderRadius: 10, background: '#2b2040', display: 'grid', placeItems: 'center' }}>
                    <Phone size={16} color="#a77af5" />
                  </div>
                  <div className="message-info" style={{ flex: 1, minWidth: 0 }}>
                    <strong style={{ fontSize: 13 }}>{msg.caller_name || msg.caller_phone || 'Unknown caller'}</strong>
                    <span style={{ display: 'block', fontSize: 11, color: '#a49bb7', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {msg.transcript_preview || msg.caller_phone || 'No transcript yet'}
                    </span>
                  </div>
                  <span className={`pill ${msg.status === 'COMPLETED' ? 'success' : msg.status === 'FAILED' ? 'danger' : 'info'}`}>
                    {msg.status.toLowerCase().replace(/_/g, ' ')}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function StatCard({ icon, label, value, loading }: { icon: React.ReactNode; label: string; value?: number; loading?: boolean }) {
  return (
    <div className="stat-card" style={{ padding: 19 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <span style={{ color: '#a49bb7', fontSize: 11 }}>{label}</span>
        <div style={{ color: '#9253f4' }}>{icon}</div>
      </div>
      <strong style={{ display: 'block', marginTop: 12, fontSize: 27 }}>
        {loading ? <span className="skeleton skeleton-title" style={{ display: 'inline-block', width: 40 }} /> : (value ?? '—')}
      </strong>
    </div>
  )
}
