# SASAA Implementation Audit
**Generated:** Phase 1 Repository Audit
**Project:** SASAA – AI Voice Note Guardian
**Goal:** Missed-call voicemail pipeline using the owner's existing mobile number

---

## 1. Existing Architecture

```
backend/          FastAPI + SQLAlchemy + PostgreSQL + Alembic
  app/
    api/v1/       11 route files, 41 total routes (27 implemented, 8 = 501 stubs)
    ai/           Gnani STT client (working, live key), transcription + audio services
    models/       16 database tables (all migrated, HEAD = 8fe1db1e0b9f)
    verification/ Full entity-detection pipeline (phone, amount, time, negation, etc.)
    services/     user_service.py (complete), message_service.py (stub), alert_service.py (complete)
    workers/      audio_processor.py (STUB — 1 comment line)
    notifications/ fcm_service.py, email_service.py, web_push_service.py (all stubs)

web/              React 19 + TypeScript + Vite
  App.tsx         Monolithic single-component app (350 lines) — live, working
  lib/api.ts      Complete typed API client — built but NEVER imported by App.tsx
  lib/auth.ts     Token storage — built but NEVER imported by App.tsx
  contexts/       AuthContext.tsx — built but NEVER mounted in main.tsx
  pages/          LoginPage.tsx, RegisterPage.tsx — built but never routed
  (router)        React Router v7 installed in package.json but NOT configured
```

---

## 2. Existing Functionality (Working)

| Feature | Status |
|---------|--------|
| Email + password authentication (JWT) | ✅ Working |
| User profile and preferences | ✅ Working |
| Manual message creation + audio upload | ✅ Working |
| Gnani STT transcription (async background) | ✅ Working with live key |
| Entity extraction (10 types) | ✅ Working |
| Verification engine + risk scoring | ✅ Working |
| Guardian alerts | ✅ Working |
| Transcript corrections (immutable versioning) | ✅ Working |
| Dashboard analytics (live DB counts) | ✅ Working |
| Language endpoint (11 Indian languages) | ✅ Working |
| Audio streaming (authenticated FileResponse) | ✅ Working |
| All automated tests | ✅ 39/39 corrections, 67/67 auth, 31/31 audio, 31/31 transcription |

---

## 3. Missing Functionality (For Voicemail Pipeline)

| Feature | Status |
|---------|--------|
| Telephony webhook receiver | ❌ MISSING — no inbound call handler |
| Provider adapter interface | ❌ MISSING |
| Exotel/Twilio adapter | ❌ MISSING |
| Voicemail recording retrieval | ❌ MISSING |
| Auto-message creation from webhook | ❌ MISSING |
| Voicemail database tables | ❌ MISSING |
| Processing job queue (fault-tolerant) | ❌ MISSING — uses BackgroundTasks only |
| Voicemail-specific API endpoints | ❌ MISSING |
| Android app | ❌ MISSING — no Android code anywhere |
| Push notification delivery | ❌ MISSING — FCM service is a stub |
| Telephony configuration screen | ❌ MISSING |
| Web frontend routing | ❌ NOT CONFIGURED (React Router installed but unused) |
| AuthContext wired to main.tsx | ❌ NOT MOUNTED |

---

## 4. Critical Bugs in Existing Code

| Bug | File | Impact |
|-----|------|--------|
| Token key mismatch: App.tsx stores `sasaa_token`, auth.ts reads `sasaa_access_token` | App.tsx + auth.ts | Session lost on refactor |
| Audio element has no auth header | App.tsx line ~230 | Audio always returns 401 |
| API hardcoded to 127.0.0.1:8000 | App.tsx line 3 | Ignores VITE_API_URL |
| api.ts never imported by App.tsx | App.tsx | Dead code, no benefit |
| AuthContext never mounted | main.tsx | Context unavailable |
| LoginPage/RegisterPage never routed | main.tsx | Pages unreachable |

---

## 5. Files to Create

### Backend
```
backend/app/models/voicemail.py           — 6 new ORM models
backend/app/telephony/__init__.py         — package
backend/app/telephony/provider_base.py    — abstract provider interface
backend/app/telephony/mock_adapter.py     — test adapter
backend/app/telephony/exotel_adapter.py   — Exotel production adapter
backend/app/telephony/webhook_router.py   — inbound webhook FastAPI router
backend/app/services/voicemail_service.py — voicemail business logic
backend/app/workers/voicemail_processor.py— background processing
backend/alembic/versions/XXXXX_voicemail_tables.py — migration
```

### Frontend
```
web/src/pages/DashboardPage.tsx
web/src/pages/MessagesPage.tsx
web/src/pages/MessageDetailPage.tsx
web/src/pages/AnalyticsPage.tsx
web/src/pages/AlertsPage.tsx
web/src/pages/SettingsPage.tsx
web/src/pages/TelephonySetupPage.tsx
web/src/components/AudioPlayer.tsx
web/src/components/EntityCard.tsx
web/src/components/StatusBadge.tsx
```

---

## 6. Files to Modify

| File | Change |
|------|--------|
| `web/src/main.tsx` | Add BrowserRouter + AuthProvider + QueryClientProvider |
| `web/src/App.tsx` | Replace with route definitions |
| `backend/app/api/v1/router.py` | Register telephony webhook router |
| `backend/app/models/__init__.py` | Register voicemail models |
| `.env` | Add telephony provider variables |
| `.env.example` | Document new variables |

---

## 7. Database Migration Plan

New tables:
1. `voicemails` — core voicemail record (provider, caller, status, timing)
2. `voicemail_recordings` — audio file metadata (storage_key, checksum, retention)
3. `processing_jobs` — job queue (status, attempts, retry backoff)
4. `telephony_events` — webhook idempotency log
5. `voicemail_reports` — accuracy analysis output

The existing `messages` and `message_audio` tables will be REUSED for voicemail records — a `voicemail_id` foreign key links them. This avoids duplicating the full transcription pipeline.

---

## 8. API Integration Plan

### Telephony Provider Evaluation: Exotel

Exotel is an India-focused CPaaS provider. Based on their published documentation:
- **Inbound voice numbers:** Available for Indian DID numbers (requires business KYC)
- **Call forwarding model:** The user's mobile carrier uses conditional forwarding (busy/no-answer/unreachable) to route to an Exotel ExoPhone number
- **Original caller ID:** Preserved via the `From` / `CallFrom` field in webhooks
- **Recording:** Exotel records calls automatically when enabled on the flow
- **Recording retrieval:** Via `GET /v1/Accounts/{SID}/Calls/{CallSid}/Recordings`
- **Webhook format:** HTTP POST with form-encoded fields (Twilio-compatible subset)
- **Webhook authentication:** Exotel sends an HMAC-SHA1 signature in `X-Exotel-Signature` header
- **Call flow:** XML/JSON passthrough — `play greeting → record → hangup`

**Required Exotel credentials:** `EXOTEL_SID`, `EXOTEL_TOKEN`, `EXOTEL_API_KEY`, `EXOTEL_API_SECRET`, `EXOTEL_PHONE_NUMBER`, `EXOTEL_WEBHOOK_SECRET`

---

## 9. Security Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Live Gnani API key in .env | HIGH | Key is not in source code ✅ — .env is in .gitignore |
| GNANI_VERIFY_SSL=False | MEDIUM | Acceptable for dev; set True in production |
| Audio files served without token | HIGH | Already fixed: FileResponse uses auth dependency |
| Webhook without signature validation | CRITICAL | Must validate HMAC before processing |
| Replay attacks on webhooks | HIGH | `telephony_events` idempotency table prevents |
| Private audio URLs exposed | MEDIUM | Never return storage_path in API responses |

---

## 10. Implementation Order

1. **Database models + migration** (voicemail tables)
2. **Provider base interface** (abstract telephony contract)
3. **Mock adapter** (for automated tests)
4. **Exotel adapter** (production provider)
5. **Webhook router** (inbound call handler + recording download + message creation)
6. **Voicemail service** (business logic layer)
7. **Background worker** (fault-tolerant processing job)
8. **Voicemail API endpoints** (inbox, detail, audio, report, reprocess)
9. **Frontend routing fix** (wire up React Router + AuthContext)
10. **Voicemail frontend screens** (inbox, detail, report, setup)
11. **Push notifications** (FCM implementation)
12. **Automated tests** (webhook, idempotency, transcription, report)
