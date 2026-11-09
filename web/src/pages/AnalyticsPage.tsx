import { useQuery } from '@tanstack/react-query'
import { BarChart3, Inbox, ShieldCheck, AlertTriangle, Activity } from 'lucide-react'
import { analytics } from '../lib/api'

export default function AnalyticsPage() {
  const { data: stats, isLoading } = useQuery({
    queryKey: ['analytics', 'dashboard'],
    queryFn: () => analytics.dashboard(),
  })

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Analytics</h1>
          <p>Processing activity and verification statistics.</p>
        </div>
      </div>

      <section className="stats-grid">
        <StatCard icon={<Inbox size={18} />} label="Total" value={stats?.total_messages} loading={isLoading} />
        <StatCard icon={<Activity size={18} />} label="Today" value={stats?.messages_today} loading={isLoading} />
        <StatCard icon={<ShieldCheck size={18} />} label="Needs verification" value={stats?.messages_needing_verification} loading={isLoading} />
        <StatCard icon={<AlertTriangle size={18} />} label="High priority" value={stats?.high_priority_messages} loading={isLoading} />
      </section>

      <div className="divider" />

      <div className="chart-container" style={{ marginBottom: 20 }}>
        <div className="chart-title">Message distribution</div>
        <div className="bar-chart" style={{ height: 140 }}>
          {[
            { label: 'Total', value: stats?.total_messages ?? 0, max: stats?.total_messages ?? 1 },
            { label: 'Unread', value: stats?.unread_messages ?? 0, max: stats?.total_messages ?? 1 },
            { label: 'Verify', value: stats?.messages_needing_verification ?? 0, max: stats?.total_messages ?? 1 },
            { label: 'High', value: stats?.high_priority_messages ?? 0, max: stats?.total_messages ?? 1 },
            { label: 'Today', value: stats?.messages_today ?? 0, max: Math.max(stats?.messages_today ?? 1, stats?.total_messages ?? 1) },
            { label: 'Week', value: stats?.messages_this_week ?? 0, max: Math.max(stats?.messages_this_week ?? 1, stats?.total_messages ?? 1) },
          ].map((bar) => (
            <div key={bar.label} className="bar-col">
              <div className="bar-fill" style={{ height: `${Math.max(2, (bar.value / bar.max) * 100)}%` }} />
              <div className="bar-label">{bar.label}<br />{bar.value}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="panel" style={{ padding: 22 }}>
        <div className="panel-heading">
          <div>
            <span className="eyebrow">SYSTEM STATUS</span>
            <h3>Guardian status</h3>
          </div>
          <BarChart3 size={18} color="#a49bb7" />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <div style={{ padding: 14, background: '#1b1729', borderRadius: 10, border: '1px solid #30283f' }}>
            <span style={{ fontSize: 11, color: '#a49bb7' }}>Guardian</span>
            <div style={{ marginTop: 6 }}>
              <span className={`pill ${stats?.guardian_active ? 'success' : 'danger'}`}>
                {stats?.guardian_active ? 'Active' : 'Inactive'}
              </span>
            </div>
          </div>
          <div style={{ padding: 14, background: '#1b1729', borderRadius: 10, border: '1px solid #30283f' }}>
            <span style={{ fontSize: 11, color: '#a49bb7' }}>Emergency messages</span>
            <strong style={{ display: 'block', marginTop: 6, fontSize: 22 }}>{stats?.emergency_messages ?? 0}</strong>
          </div>
        </div>
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
        {loading ? '—' : (value ?? 0)}
      </strong>
    </div>
  )
}
