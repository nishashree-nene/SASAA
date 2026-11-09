"""
SASAA – Mock Telephony Adapter
================================
Used exclusively for automated tests. Never use in production.

The mock adapter:
  - Accepts any webhook payload without signature validation
  - Returns pre-configured recording info
  - Records method calls so tests can assert on them
  - Simulates configurable failures (timeout, auth error, etc.)

Usage in tests:
    from app.telephony.mock_adapter import MockTelephonyAdapter
    adapter = MockTelephonyAdapter()
    adapter.set_next_recording(RecordingInfo(...))
    # inject adapter into the voicemail service
"""

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Optional

from fastapi import Request

from app.telephony.provider_base import (
    InboundCallEvent,
    ProviderError,
    ProviderHealth,
    RecordingInfo,
    TelephonyProviderBase,
)


class MockTelephonyAdapter(TelephonyProviderBase):
    """Mock adapter for automated tests."""

    def __init__(self) -> None:
        self._recordings: dict[str, RecordingInfo] = {}
        self._call_details: dict[str, dict] = {}
        self._should_fail_signature = False
        self._should_fail_recording = False
        self._fail_after_n_attempts: Optional[int] = None
        self._download_attempts: int = 0
        self.validated_webhooks: list[dict] = []
        self.parsed_events: list[InboundCallEvent] = []
        self.downloaded_recordings: list[str] = []

    @property
    def provider_name(self) -> str:
        return "Mock"

    def set_fail_signature(self, fail: bool = True) -> None:
        """Make the next validate_webhook call return False."""
        self._should_fail_signature = fail

    def set_fail_recording(self, fail: bool = True) -> None:
        """Make get_recording raise ProviderError."""
        self._should_fail_recording = fail

    def set_next_recording(self, call_id: str, info: RecordingInfo) -> None:
        """Pre-configure a recording to return for a given call_id."""
        self._recordings[call_id] = info

    def set_call_details(self, call_id: str, details: dict) -> None:
        self._call_details[call_id] = details

    async def validate_webhook(self, request: Request) -> bool:
        body = await request.body()
        self.validated_webhooks.append({"body": body.decode("utf-8", errors="replace")})
        return not self._should_fail_signature

    async def parse_inbound_event(self, request: Request) -> InboundCallEvent:
        body = await request.body()
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            # Try form data fallback
            form = await request.form()
            payload = dict(form)

        event = InboundCallEvent(
            provider_call_id=str(payload.get("CallSid", payload.get("call_id", "mock-call-001"))),
            caller_number=str(payload.get("From", payload.get("caller_number", "+919876543210"))),
            called_number=str(payload.get("To", payload.get("called_number", "+911234567890"))),
            event_type=str(payload.get("CallStatus", payload.get("event_type", "no-answer"))),
            forward_reason=str(payload.get("forward_reason", "no_answer")),
            raw_payload=payload,
        )
        self.parsed_events.append(event)
        return event

    async def get_recording(self, provider_call_id: str) -> RecordingInfo:
        if self._should_fail_recording:
            raise ProviderError(
                f"Mock recording failure for call {provider_call_id}",
                provider="Mock",
                is_retryable=True,
            )

        if provider_call_id in self._recordings:
            return self._recordings[provider_call_id]

        # Default mock recording pointing to a sample file from the project
        sample_dir = Path(__file__).parent.parent.parent.parent / "sample"
        sample_files = list(sample_dir.glob("*.mp3")) + list(sample_dir.glob("*.ogg"))
        sample_path = str(sample_files[0]) if sample_files else ""

        return RecordingInfo(
            provider_recording_id=f"mock-rec-{provider_call_id}",
            provider_recording_url=f"file://{sample_path}",
            duration_seconds=5.0,
            mime_type="audio/mpeg",
            raw_payload={"mock": True},
        )

    async def download_recording(
        self,
        recording_url: str,
        destination_path: str,
    ) -> tuple[int, str]:
        self._download_attempts += 1
        self.downloaded_recordings.append(recording_url)

        dest = Path(destination_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        if recording_url.startswith("file://"):
            # Copy local sample file for tests
            source = Path(recording_url[7:])
            if source.exists():
                shutil.copy2(source, dest)
                size = dest.stat().st_size
                return size, "audio/mpeg"

        # Write a minimal valid WAV header + silence for tests without sample files
        silence_wav = (
            b"RIFF" + (36).to_bytes(4, "little") +
            b"WAVE" + b"fmt " + (16).to_bytes(4, "little") +
            (1).to_bytes(2, "little") +   # PCM
            (1).to_bytes(2, "little") +   # mono
            (8000).to_bytes(4, "little") + # sample rate
            (8000).to_bytes(4, "little") + # byte rate
            (1).to_bytes(2, "little") +   # block align
            (8).to_bytes(2, "little") +   # bits per sample
            b"data" + (0).to_bytes(4, "little")
        )
        dest.write_bytes(silence_wav)
        return len(silence_wav), "audio/wav"

    async def get_call_details(self, provider_call_id: str) -> dict:
        return self._call_details.get(provider_call_id, {
            "CallSid": provider_call_id,
            "From": "+919876543210",
            "To": "+911234567890",
            "Status": "completed",
            "Duration": "5",
            "mock": True,
        })

    async def get_provider_health(self) -> ProviderHealth:
        return ProviderHealth(
            is_healthy=True,
            provider_name="Mock",
            account_id="mock-acct",
            phone_numbers=["+911234567890"],
        )
