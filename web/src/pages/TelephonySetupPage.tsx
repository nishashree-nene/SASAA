import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Phone, ShieldCheck, AlertCircle, CheckCircle, Loader, Server, PhoneForwarded } from 'lucide-react'
import { apiFetch } from '../lib/api'

interface TelephonyConfig {
  provider: string
  is_live_provider: boolean
  is_configured: boolean
  health: {
    is_healthy: boolean
    provider_name: string
    account_id_masked: string | null
    phone_numbers: string[]
    error: string | null
  }
  webhook_url: string
  forwarding_instructions: {
    overview: string
    conditions: Array<{ condition: string; description: string; note: string }>
    carrier_instructions: Record<string, string>
    important_notes: string[]
  }
  dev_note?: string
}

export default function TelephonySetupPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['telephony', 'config'],
    queryFn: () => apiFetch<TelephonyConfig>('/telephony/configuration'),
  })

  const { data: testData, refetch: refetchTest } = useQuery({
    queryKey: ['telephony', 'test-result'],
    queryFn: async () => {
      const result = await apiFetch<{ test_id: string; voicemail_id: string; status: string }>(
        '/telephony/test',
        { method: 'POST' },
      )
      return result
    },
    enabled: false,
  })

  if (isLoading) {
    return <div style={{ padding: 40, color: '#a49bb7' }}>Loading configuration…</div>
  }

  const config = data
  const isMock = config?.provider === 'mock'

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Telephony Setup</h1>
          <p>Configure missed-call voicemail using your existing mobile number.</p>
        </div>
      </div>

      {/* Provider status */}
      <div className="panel" style={{ padding: 22, marginBottom: 16 }}>
        <div className="panel-heading">
          <div>
            <span className="eyebrow">PROVIDER</span>
            <h3>Connection status</h3>
          </div>
          <Server size={18} color="#a49bb7" />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <div style={{ padding: 14, background: '#1b1729', borderRadius: 10, border: '1px solid #30283f' }}>
            <span style={{ fontSize: 11, color: '#a49bb7' }}>Provider</span>
            <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 8 }}>
              <strong style={{ fontSize: 16 }}>{config?.provider?.toUpperCase()}</strong>
              <span className={`pill ${isMock ? 'neutral' : config?.is_configured ? 'success' : 'warning'}`}>
                {isMock ? 'Mock (dev)' : config?.is_configured ? 'Configured' : 'Not configured'}
              </span>
            </div>
          </div>
          <div style={{ padding: 14, background: '#1b1729', borderRadius: 10, border: '1px solid #30283f' }}>
            <span style={{ fontSize: 11, color: '#a49bb7' }}>Health</span>
            <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 8 }}>
              {config?.health?.is_healthy ? (
                <CheckCircle size={16} color="#22c55e" />
              ) : (
                <AlertCircle size={16} color="#f59e0b" />
              )}
              <span style={{ fontSize: 13 }}>{config?.health?.is_healthy ? 'Healthy' : config?.health?.error ?? 'Unknown'}</span>
            </div>
          </div>
        </div>

        {config?.health?.account_id_masked && (
          <div style={{ marginTop: 12, fontSize: 12, color: '#a49bb7' }}>
            Account: {config.health.account_id_masked}
          </div>
        )}
      </div>

      {/* Webhook URL */}
      <div className="panel" style={{ padding: 22, marginBottom: 16 }}>
        <div className="panel-heading">
          <div>
            <span className="eyebrow">WEBHOOK</span>
            <h3>Inbound webhook URL</h3>
          </div>
          <PhoneForwarded size={18} color="#a49bb7" />
        </div>
        <p className="muted small" style={{ marginBottom: 10 }}>
          Configure this URL in your Exotel call flow (Passthru applet) to receive inbound call events.
        </p>
        <div style={{ padding: 12, background: '#0f0d1a', borderRadius: 8, border: '1px solid #2b2240', fontFamily: 'monospace', fontSize: 12, color: '#a77af5', wordBreak: 'break-all' }}>
          {config?.webhook_url}
        </div>
      </div>

      {/* Test button */}
      <div className="panel" style={{ padding: 22, marginBottom: 16 }}>
        <div className="panel-heading">
          <div>
            <span className="eyebrow">TEST</span>
            <h3>Simulate a missed call</h3>
          </div>
          <Phone size={18} color="#a49bb7" />
        </div>
        <p className="muted small" style={{ marginBottom: 14 }}>
          Trigger a test voicemail using the mock provider. This creates a real voicemail record and runs it through the full pipeline.
        </p>
        <button
          className="primary"
          onClick={() => refetchTest()}
          style={{ padding: '10px 18px', borderRadius: 8, fontSize: 12, fontWeight: 700, border: 0, cursor: 'pointer', color: 'white', background: 'linear-gradient(100deg, #a34fee, #6940dc)' }}
        >
          Trigger test voicemail
        </button>
        {testData && (
          <div style={{ marginTop: 14, padding: 12, background: '#0f0d1a', borderRadius: 8, border: '1px solid #2b2240' }}>
            <span style={{ fontSize: 12 }}>Test voicemail created: </span>
            <Link to={`/voicemails/${testData.voicemail_id}`} style={{ color: '#a77af5', fontSize: 12, textDecoration: 'none' }}>
              View voicemail →
            </Link>
          </div>
        )}
      </div>

      {/* Forwarding instructions */}
      <div className="panel" style={{ padding: 22 }}>
        <div className="panel-heading">
          <div>
            <span className="eyebrow">FORWARDING</span>
            <h3>Carrier call forwarding setup</h3>
          </div>
          <ShieldCheck size={18} color="#a49bb7" />
        </div>

        <p className="muted" style={{ marginBottom: 16 }}>
          {config?.forwarding_instructions?.overview}
        </p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
          {config?.forwarding_instructions?.conditions?.map((cond, i) => (
            <div key={i} style={{ padding: 14, background: '#1b1729', borderRadius: 10, border: '1px solid #30283f' }}>
              <strong style={{ fontSize: 13, color: '#c4aeff' }}>{cond.condition}</strong>
              <p style={{ margin: '4px 0 0', fontSize: 12, color: '#a49bb7' }}>{cond.description}</p>
              <p style={{ margin: '4px 0 0', fontSize: 11, color: '#7d7589' }}>{cond.note}</p>
            </div>
          ))}
        </div>

        {config?.dev_note && (
          <div className="alert" style={{ background: '#1d1830', border: '1px solid #30283f', borderRadius: 10, padding: '12px 16px', color: '#a77af5', fontSize: 12 }}>
            {config.dev_note}
          </div>
        )}

        <div style={{ marginTop: 16 }}>
          <span className="eyebrow" style={{ marginBottom: 10 }}>IMPORTANT NOTES</span>
          <ul style={{ paddingLeft: 20, margin: 0 }}>
            {config?.forwarding_instructions?.important_notes?.map((note, i) => (
              <li key={i} style={{ fontSize: 12, color: '#a49bb7', marginBottom: 6, lineHeight: 1.6 }}>{note}</li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}
