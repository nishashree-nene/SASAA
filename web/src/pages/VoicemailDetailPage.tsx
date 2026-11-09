import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, Play, Save, RefreshCw, ShieldCheck, AlertTriangle, Clock, Loader } from 'lucide-react'
import { messages, transcription, verification, audio as audioApi } from '../lib/api'
import { useToast } from '../components/Toast'

export default function VoicemailDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { toast } = useToast()
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [editedText, setEditedText] = useState('')
  const [saving, setSaving] = useState(false)

  // Load message
  const { data: msg, refetch } = useQuery({
    queryKey: ['message', id],
    queryFn: () => messages.get(id!),
    enabled: !!id,
    refetchInterval: (data) => data?.status === 'TRANSCRIBING' || data?.status === 'PROCESSING' ? 3000 : false,
  })

  // Load transcript
  const { data: transcriptData, refetch: refetchTranscript } = useQuery({
    queryKey: ['transcript', id],
    queryFn: () => transcription.get(id!),
    enabled: !!id,
    refetchInterval: (data) => data?.status === 'TRANSCRIBING' || data?.status === 'PROCESSING' ? 3000 : false,
  })

  // Load verification
  const { data: verificationData } = useQuery({
    queryKey: ['verification', id],
    queryFn: () => verification.get(id!),
    enabled: !!id,
  })

  // Load audio blob
  useEffect(() => {
    if (!id) return
    audioApi.fetchBlob(id).then(setAudioUrl).catch(() => setAudioUrl(null))
    return () => { if (audioUrl) URL.revokeObjectURL(audioUrl) }
  }, [id])

  // Sync transcript text to editor
  useEffect(() => {
    if (transcriptData?.has_transcript && transcriptData.transcript) {
      setEditedText(transcriptData.transcript.raw_text)
    }
  }, [transcriptData])

  const entities = verificationData?.entities ?? []

  async function handleSaveCorrection() {
    if (!id || !editedText.trim()) return
    setSaving(true)
    try {
      await verification.saveCorrection(id, editedText, 'User correction from web interface')
      toast('Correction saved as a new version. Original transcript preserved.', 'success')
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Failed to save correction', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleReprocess() {
    if (!id) return
    try {
      await messages.update(id, { is_read: true })
      toast('Message marked as read.', 'info')
    } catch {
      // ignore
    }
  }

  const status = msg?.status ?? 'UPLOADED'
  const isProcessing = ['TRANSCRIBING', 'PROCESSING', 'ANALYZING', 'VALIDATING'].includes(status)

  return (
    <div>
      <div className="page-header">
        <div>
          <Link to="/voicemails" style={{ color: '#a49bb7', fontSize: 12, textDecoration: 'none' }}>
            <ArrowLeft size={14} style={{ display: 'inline', marginRight: 6 }} />
            Back to inbox
          </Link>
          <h1 style={{ marginTop: 6 }}>{msg?.caller_name || msg?.caller_phone || 'Voicemail'}</h1>
          <p style={{ fontSize: 12, color: '#a49bb7' }}>
            {msg?.caller_phone && `From: ${msg.caller_phone}`}
            {msg?.created_at && ` · ${new Date(msg.created_at).toLocaleString()}`}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {status === 'FAILED' && (
            <button className="secondary" onClick={handleReprocess} style={{ padding: '8px 14px', borderRadius: 8, fontSize: 11, border: 0, cursor: 'pointer' }}>
              <RefreshCw size={13} style={{ marginRight: 5, display: 'inline' }} />
              Reprocess
            </button>
          )}
        </div>
      </div>

      {/* Status banner */}
      {isProcessing && (
        <div className="alert" style={{ background: '#141b3b', border: '1px solid #2a2f6b', borderRadius: 10, padding: '10px 16px', marginBottom: 16, color: '#818cf8', fontSize: 13 }}>
          <Loader size={14} style={{ display: 'inline', marginRight: 8, animation: 'spin 1s linear infinite' }} />
          Processing in progress — status: {status.toLowerCase()}
        </div>
      )}
      {status === 'FAILED' && msg?.error_message && (
        <div className="alert" style={{ background: '#2d0a0a', border: '1px solid #5c1010', borderRadius: 10, padding: '10px 16px', marginBottom: 16, color: '#f87171', fontSize: 13 }}>
          <AlertTriangle size={14} style={{ display: 'inline', marginRight: 8 }} />
          {msg.error_message}
        </div>
      )}

      <div className="content-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 16, alignItems: 'start' }}>
        {/* Left column: Audio + Transcript */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Audio player */}
          <div className="panel" style={{ padding: 22 }}>
            <div className="panel-heading">
              <div>
                <span className="eyebrow">AUDIO</span>
                <h3>Original recording</h3>
              </div>
              <Play size={18} color="#a49bb7" />
            </div>
            {audioUrl ? (
              <div className="audio-player">
                <div className="audio-label">
                  <ShieldCheck size={12} style={{ display: 'inline', marginRight: 6 }} />
                  Authenticated playback
                </div>
                <audio controls src={audioUrl} style={{ width: '100%', height: 38, accentColor: '#9253f4' }} />
              </div>
            ) : (
              <p className="muted small">
                {status === 'UPLOADED' ? 'Audio uploaded. Start transcription to process.' :
                 isProcessing ? 'Audio is being processed…' :
                 'Audio file not available.'}
              </p>
            )}
          </div>

          {/* Transcript */}
          <div className="panel" style={{ padding: 22 }}>
            <div className="panel-heading">
              <div>
                <span className="eyebrow">TRANSCRIPT</span>
                <h3>Transcription {transcriptData?.has_transcript && `· ${transcriptData.transcript?.detected_language ?? ''}`}</h3>
              </div>
              {transcriptData?.has_transcript && (
                <span className="pill success">Complete</span>
              )}
            </div>

            {transcriptData?.has_transcript && transcriptData.transcript ? (
              <>
                <label style={{ fontSize: 12, color: '#a49bb7', fontWeight: 600, marginBottom: 8, display: 'block' }}>
                  Editable transcript (original is preserved)
                </label>
                <textarea
                  value={editedText}
                  onChange={(e) => setEditedText(e.target.value)}
                  rows={8}
                  placeholder="Transcript will appear here after processing…"
                  style={{ width: '100%', background: '#100e19', border: '1px solid #393147', borderRadius: 10, padding: 14, color: '#f5f2ff', fontSize: 13, lineHeight: 1.6, resize: 'vertical', minHeight: 120 }}
                />
                {transcriptData.transcript.english_translation && (
                  <div style={{ marginTop: 12, padding: 12, background: '#0f0d1a', borderRadius: 8, border: '1px solid #2b2240' }}>
                    <span className="eyebrow" style={{ marginBottom: 6 }}>ENGLISH TRANSLATION</span>
                    <p style={{ fontSize: 12, color: '#a49bb7', margin: 0, lineHeight: 1.6 }}>{transcriptData.transcript.english_translation}</p>
                  </div>
                )}
                <div className="action-row" style={{ marginTop: 14, display: 'flex', gap: 10 }}>
                  <button
                    className="primary"
                    onClick={handleSaveCorrection}
                    disabled={saving || !editedText.trim()}
                    style={{ padding: '10px 16px', borderRadius: 8, fontSize: 12, fontWeight: 700, border: 0, cursor: 'pointer' }}
                  >
                    <Save size={13} style={{ display: 'inline', marginRight: 5 }} />
                    {saving ? 'Saving…' : 'Save correction'}
                  </button>
                </div>
              </>
            ) : isProcessing ? (
              <div className="empty-state" style={{ padding: 30 }}>
                <Loader size={28} color="#818cf8" style={{ animation: 'spin 1s linear infinite' }} />
                <strong>Transcribing…</strong>
                <p>The transcript will appear here once Gnani AI completes processing.</p>
              </div>
            ) : (
              <div className="empty-state" style={{ padding: 30 }}>
                <Clock size={28} color="#4a4458" />
                <strong>No transcript yet</strong>
                <p>Start transcription to generate the text from this audio.</p>
              </div>
            )}
          </div>
        </div>

        {/* Right column: Verification findings */}
        <div className="panel" style={{ padding: 22, position: 'sticky', top: 16 }}>
          <div className="panel-heading">
            <div>
              <span className="eyebrow">VERIFICATION</span>
              <h3>Findings</h3>
            </div>
            <span className="count" style={{ fontSize: 11, color: '#a49bb7' }}>{entities.length} items</span>
          </div>

          {entities.length === 0 ? (
            <p className="muted small" style={{ textAlign: 'center', padding: '20px 0' }}>
              No entities detected or verification not yet run.
            </p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {entities.map((entity, i) => (
                <div key={i} className="entity-card">
                  <div className="entity-card-header">
                    <span className="entity-card-type">{entity.entity_type.replace(/_/g, ' ')}</span>
                    <span className={`pill ${entity.risk_level === 'CRITICAL' ? 'danger' : entity.risk_level === 'HIGH' ? 'warning' : entity.risk_level === 'MEDIUM' ? 'info' : 'neutral'}`}>
                      {entity.risk_level?.toLowerCase() ?? 'low'}
                    </span>
                  </div>
                  <div className="entity-card-value">{entity.raw_value}</div>
                  {entity.normalized_value && (
                    <div style={{ fontSize: 11, color: '#a49bb7', marginBottom: 4 }}>→ {entity.normalized_value}</div>
                  )}
                  {entity.reason && (
                    <div className="entity-card-reason">{entity.reason}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Responsive: stack on mobile */}
      <style>{`
        @media (max-width: 768px) {
          .content-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  )
}
