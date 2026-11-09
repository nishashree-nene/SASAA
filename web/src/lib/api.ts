/**
 * SASAA – Centralised API Client
 *
 * All backend calls go through this module.
 * - Base URL driven by Vite environment variable (falls back to localhost:8000)
 * - Automatically attaches the Bearer token
 * - Normalises error messages from FastAPI's error shape
 * - Handles 401 → clears tokens → reloads to login
 */

import { clearTokens, getAccessToken } from './auth';

export const API_BASE =
  (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://127.0.0.1:8000/api/v1';

// ── Types mirroring backend Pydantic schemas ──────────────────────────────────

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface UserProfile {
  id: string;
  email: string;
  full_name: string | null;
  phone_number: string | null;
  profile_picture_url: string | null;
  is_verified: boolean;
  created_at: string;
}

export interface UserPreferences {
  interface_language: string;
  transcript_language: string;
  auto_translate: boolean;
  theme: string;
  notify_new_message: boolean;
  notify_high_priority: boolean;
  notify_emergency: boolean;
  notify_suspicious: boolean;
  notify_email: boolean;
  audio_retention_days: number | null;
}

export type MessageStatus =
  | 'UPLOADED'
  | 'VALIDATING'
  | 'PROCESSING'
  | 'TRANSCRIBING'
  | 'ANALYZING'
  | 'COMPLETED'
  | 'NEEDS_VERIFICATION'
  | 'FAILED';

export type MessagePriority = 'NORMAL' | 'IMPORTANT' | 'HIGH' | 'EMERGENCY';

export interface Message {
  id: string;
  caller_name: string | null;
  caller_phone: string | null;
  status: MessageStatus;
  priority: MessagePriority;
  detected_language: string | null;
  is_read: boolean;
  is_archived: boolean;
  duration_seconds: number | null;
  transcript_preview: string | null;
  created_at: string;
  updated_at: string;
  // detail fields
  original_filename?: string | null;
  mime_type?: string | null;
  file_size_bytes?: number | null;
  error_message?: string | null;
}

export interface PaginatedMessages {
  items: Message[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

export interface TranscriptData {
  id: string;
  message_id: string;
  raw_text: string;
  detected_language: string | null;
  provider_confidence: number | null;
  processing_latency_ms: number | null;
  english_translation: string | null;
  translation_source: string | null;
  created_at: string;
  updated_at: string;
}

export interface TranscriptionStatus {
  message_id: string;
  status: string;
  has_transcript: boolean;
  transcript: TranscriptData | null;
  audio_duration_seconds: number | null;
  error_message: string | null;
  message: string | null;
}

export interface ExtractedEntity {
  id: string;
  entity_type: string;
  raw_value: string;
  normalized_value: string | null;
  suggested_interpretation: string | null;
  has_ambiguity: boolean;
  ambiguity_reason: string | null;
  extraction_confidence: number | null;
  char_start: number | null;
  char_end: number | null;
  verification_status: string | null;
  risk_level: string | null;
  reason: string | null;
  evidence: Record<string, unknown> | null;
  user_decision: string | null;
  user_correction: string | null;
  user_decided_at: string | null;
}

export interface VerificationResult {
  message_id: string;
  status: string;
  has_results: boolean;
  entities: ExtractedEntity[];
  total_entities: number;
  flagged_count: number;
  needs_review_count: number;
  verified_count: number;
  critical_risk_count: number;
  high_risk_count: number;
  message: string | null;
}

export interface CorrectionVersion {
  id: string;
  transcript_id: string;
  version_number: number;
  corrected_text: string;
  change_summary: string | null;
  created_at: string;
}

export interface Alert {
  id: string;
  message_id: string;
  alert_type: string;
  severity: string;
  title: string;
  reason: string;
  related_transcript_segment: string | null;
  suggested_action: string | null;
  is_read: boolean;
  is_acknowledged: boolean;
  is_dismissed: boolean;
  created_at: string;
}

export interface AlertList {
  items: Alert[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

export interface DashboardStats {
  total_messages: number;
  unread_messages: number;
  messages_needing_verification: number;
  high_priority_messages: number;
  emergency_messages: number;
  messages_today: number;
  messages_this_week: number;
  guardian_active: boolean;
}

export interface LanguageInfo {
  code: string;
  name: string;
  native_name: string;
  stt_supported: boolean;
  translation_supported: boolean;
  code_switching: string | null;
  notes: string | null;
}

// ── Error handling ─────────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public detail?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function extractMessage(data: unknown, status: number): string {
  if (!data || typeof data !== 'object') return `Request failed (${status})`;
  const d = data as Record<string, unknown>;
  if (typeof d.detail === 'string') return d.detail;
  if (Array.isArray(d.detail)) {
    return (d.detail as Array<{ msg?: string }>)
      .map((item) => item.msg ?? 'Validation error')
      .join(', ');
  }
  if (typeof d.message === 'string') return d.message;
  if (typeof d.error === 'string') return d.error;
  return `Request failed (${status})`;
}

// ── Core request function ─────────────────────────────────────────────────────

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  skipAuth = false,
): Promise<T> {
  const headers = new Headers(options.headers);

  if (!skipAuth) {
    const token = getAccessToken();
    if (token) headers.set('Authorization', `Bearer ${token}`);
  }

  // Only set Content-Type for non-FormData bodies
  if (options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (response.status === 401 && !skipAuth) {
    // Token expired — clear and reload to login
    clearTokens();
    window.location.href = '/login';
    throw new ApiError('Session expired. Please sign in again.', 401);
  }

  let data: unknown;
  const contentType = response.headers.get('content-type') ?? '';
  if (contentType.includes('application/json')) {
    data = await response.json();
  } else if (contentType.startsWith('audio/') || contentType.startsWith('video/')) {
    // For audio streaming responses, return the response itself as the "data"
    return response as unknown as T;
  } else {
    data = await response.text();
  }

  if (!response.ok) {
    throw new ApiError(extractMessage(data, response.status), response.status, data);
  }

  return data as T;
}

// ── Auth endpoints ─────────────────────────────────────────────────────────────

export const auth = {
  register: (email: string, password: string, fullName: string) =>
    apiFetch<TokenResponse>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password, full_name: fullName }),
    }, true),

  login: (email: string, password: string) =>
    apiFetch<TokenResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }, true),

  logout: (refreshToken: string) =>
    apiFetch<{ success: boolean; message: string }>('/auth/logout', {
      method: 'POST',
      body: JSON.stringify({ refresh_token: refreshToken }),
    }),
};

// ── User endpoints ─────────────────────────────────────────────────────────────

export const users = {
  me: () => apiFetch<UserProfile>('/users/me'),
  updateMe: (data: Partial<UserProfile>) =>
    apiFetch<UserProfile>('/users/me', { method: 'PATCH', body: JSON.stringify(data) }),
  preferences: () => apiFetch<UserPreferences>('/users/preferences'),
  updatePreferences: (data: Partial<UserPreferences>) =>
    apiFetch<UserPreferences>('/users/preferences', { method: 'PATCH', body: JSON.stringify(data) }),
};

// ── Messages ───────────────────────────────────────────────────────────────────

export const messages = {
  list: (params: {
    page?: number;
    page_size?: number;
    search?: string;
    status?: string;
    priority?: string;
    is_archived?: boolean;
  } = {}) => {
    const qs = new URLSearchParams();
    if (params.page) qs.set('page', String(params.page));
    if (params.page_size) qs.set('page_size', String(params.page_size));
    if (params.search) qs.set('search', params.search);
    if (params.status) qs.set('status', params.status);
    if (params.priority) qs.set('priority', params.priority);
    if (params.is_archived !== undefined) qs.set('is_archived', String(params.is_archived));
    return apiFetch<PaginatedMessages>(`/messages?${qs}`);
  },

  create: (data: { caller_name?: string; caller_phone?: string }) =>
    apiFetch<Message>('/messages', { method: 'POST', body: JSON.stringify(data) }),

  get: (id: string) => apiFetch<Message>(`/messages/${id}`),

  update: (id: string, data: { is_read?: boolean; is_archived?: boolean; priority?: string }) =>
    apiFetch<Message>(`/messages/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  delete: (id: string) =>
    apiFetch<{ success: boolean; message: string }>(`/messages/${id}`, { method: 'DELETE' }),
};

// ── Audio ─────────────────────────────────────────────────────────────────────

export const audio = {
  upload: (messageId: string, file: File) => {
    const form = new FormData();
    form.append('audio_file', file);
    return apiFetch<{ success: boolean; message: string }>(
      `/messages/${messageId}/audio`,
      { method: 'POST', body: form },
    );
  },

  /** Returns the streaming URL. The component must add the auth header separately
   *  using a blob URL trick since <audio src> can't set custom headers. */
  streamUrl: (messageId: string) => `${API_BASE}/messages/${messageId}/audio`,

  /** Fetch audio as a Blob and create an object URL for <audio> */
  fetchBlob: async (messageId: string): Promise<string> => {
    const response = await apiFetch<Response>(`/messages/${messageId}/audio`);
    const blob = await response.blob();
    return URL.createObjectURL(blob);
  },
};

// ── Transcription ──────────────────────────────────────────────────────────────

export const transcription = {
  trigger: (messageId: string, languageCode = 'ta-IN') =>
    apiFetch<{ success: boolean; message: string }>(
      `/messages/${messageId}/transcribe`,
      { method: 'POST', body: JSON.stringify({ language_code: languageCode }) },
    ),

  get: (messageId: string) =>
    apiFetch<TranscriptionStatus>(`/messages/${messageId}/transcription`),
};

// ── Verification ───────────────────────────────────────────────────────────────

export const verification = {
  run: (messageId: string) =>
    apiFetch<{ success: boolean; message: string }>(
      `/messages/${messageId}/verify`,
      { method: 'POST' },
    ),

  get: (messageId: string) =>
    apiFetch<VerificationResult>(`/messages/${messageId}/verification`),

  saveCorrection: (
    messageId: string,
    correctedText: string,
    changeSummary?: string,
    corrections?: Array<Record<string, unknown>>,
  ) =>
    apiFetch<CorrectionVersion>(
      `/messages/${messageId}/corrections`,
      {
        method: 'POST',
        body: JSON.stringify({
          corrected_text: correctedText,
          change_summary: changeSummary,
          corrections,
        }),
      },
    ),
};

// ── Alerts ─────────────────────────────────────────────────────────────────────

export const alerts = {
  list: (params: { page?: number; is_dismissed?: boolean } = {}) => {
    const qs = new URLSearchParams();
    if (params.page) qs.set('page', String(params.page));
    if (params.is_dismissed !== undefined) qs.set('is_dismissed', String(params.is_dismissed));
    return apiFetch<AlertList>(`/alerts?${qs}`);
  },

  acknowledge: (alertId: string) =>
    apiFetch<{ success: boolean; message: string }>(
      `/alerts/${alertId}/acknowledge`,
      { method: 'PATCH' },
    ),

  dismiss: (alertId: string) =>
    apiFetch<{ success: boolean; message: string }>(
      `/alerts/${alertId}/dismiss`,
      { method: 'PATCH' },
    ),
};

// ── Analytics ─────────────────────────────────────────────────────────────────

export const analytics = {
  dashboard: () => apiFetch<DashboardStats>('/analytics/dashboard'),
};

// ── Languages ─────────────────────────────────────────────────────────────────

export const languages = {
  list: () => apiFetch<LanguageInfo[]>('/languages'),
};
