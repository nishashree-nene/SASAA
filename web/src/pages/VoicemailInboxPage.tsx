import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Inbox, Phone, Search, Play, CheckCircle, Clock, AlertTriangle } from 'lucide-react'
import { messages, type MessageStatus } from '../lib/api'

const STATUS_ICONS: Record<string, React.ReactNode> = {
  COMPLETED: <CheckCircle size={14} color="#22c55e" />,
  TRANSCRIBING: <Clock size={14} color="#818cf8" />,
  ANALYZING: <Clock size={14} color="#818cf8" />,
  PROCESSING: <Clock size={14} color="#818cf8" />,
  VALIDATING: <Clock size={14} color="#818cf8" />,
  UPLOADED: <Inbox size={14} color="#a49bb7" />,
  NEEDS_VERIFICATION: <AlertTriangle size={14} color="#f59e0b" />,
  FAILED: <AlertTriangle size={14} color="#ef4444" />,
}

export default function VoicemailInboxPage() {
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['messages', 'inbox', page, search, statusFilter],
    queryFn: () => messages.list({
      page,
      page_size: 20,
      search: search || undefined,
      status: statusFilter || undefined,
    }),
  })

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const totalPages = data?.total_pages ?? 0

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Voicemail Inbox</h1>
          <p>{total} message{total !== 1 ? 's' : ''} total</p>
        </div>
      </div>

      <div className="filter-row">
        <div className="search-bar">
          <Search size={15} />
          <input
            type="text"
            placeholder="Search by caller number…"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1) }}
          />
        </div>
        <select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }} style={{ width: 'auto' }}>
          <option value="">All statuses</option>
          <option value="UPLOADED">Uploaded</option>
          <option value="TRANSCRIBING">Transcribing</option>
          <option value="COMPLETED">Completed</option>
          <option value="NEEDS_VERIFICATION">Needs verification</option>
          <option value="FAILED">Failed</option>
        </select>
      </div>

      <div className="panel" style={{ padding: 0, overflow: 'hidden' }}>
        {isLoading ? (
          <div style={{ padding: 24 }}>
            {[1, 2, 3].map(i => (
              <div key={i} style={{ marginBottom: 12 }}>
                <div className="skeleton skeleton-text" style={{ width: '60%' }} />
                <div className="skeleton skeleton-text" style={{ width: '40%' }} />
              </div>
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="empty-state">
            <Inbox size={40} color="#4a4458" />
            <strong>No voicemails found</strong>
            <p>Missed calls forwarded to SASAA will appear here automatically.</p>
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Caller</th>
                <th>Phone</th>
                <th>Preview</th>
                <th>Status</th>
                <th>Date</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((msg) => (
                <tr key={msg.id} onClick={() => window.location.href = `/voicemails/${msg.id}`}>
                  <td style={{ fontWeight: 600 }}>{msg.caller_name || 'Unknown'}</td>
                  <td style={{ color: '#a49bb7', fontSize: 12 }}>{msg.caller_phone || '—'}</td>
                  <td style={{ color: '#a49bb7', fontSize: 12, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {msg.transcript_preview || '—'}
                  </td>
                  <td>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11 }}>
                      {STATUS_ICONS[msg.status] || <Clock size={14} />}
                      {msg.status.toLowerCase().replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td style={{ color: '#a49bb7', fontSize: 11 }}>
                    {new Date(msg.created_at).toLocaleDateString()}
                  </td>
                  <td>
                    <Link to={`/voicemails/${msg.id}`} style={{ color: '#9253f4', textDecoration: 'none', fontSize: 12 }}>
                      View →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {totalPages > 1 && (
        <div className="pagination">
          <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1}>←</button>
          <span className="page-info">{page} / {totalPages}</span>
          <button onClick={() => setPage(p => p + 1)} disabled={page >= totalPages}>→</button>
        </div>
      )}
    </div>
  )
}
