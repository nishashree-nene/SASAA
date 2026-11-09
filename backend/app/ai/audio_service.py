"""
SASAA – Audio Service
======================
Handles everything that needs to happen to an audio file BEFORE it is
sent to the Gnani STT API:

  1. Validate the file format and size
  2. Extract audio metadata (duration, sample rate, channels)
  3. Convert to a Gnani-compatible format if needed

WHY AUDIO PREPARATION MATTERS:
  Gnani's STT API accepts specific audio formats. If we send an unsupported
  format, the API returns an error. Rather than silently failing, we:
  - Check the format first
  - Convert if needed (using pydub)
  - Store both the original and converted files

IMPORTANT: pydub requires ffmpeg for most format conversions.
  Install ffmpeg: https://ffmpeg.org/download.html
  Without ffmpeg, only WAV files can be processed by pydub.
  .ogg and .mp3 files from your sample/ folder require ffmpeg.

  For the MVP, we attempt conversion and fall back to using the
  original file if conversion fails, letting Gnani decide.
"""

import asyncio
import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import aiofiles
import structlog
from fastapi import UploadFile

from app.core.config import settings

logger = structlog.get_logger(__name__)

# ── Supported audio formats ─────────────────────────────────────────────────
# These are the MIME types we accept for upload.
# Gnani compatibility is verified at transcription time.
ACCEPTED_MIME_TYPES: set[str] = {
    "audio/ogg",
    "audio/mpeg",        # .mp3
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/mp4",
    "audio/x-m4a",
    "audio/m4a",
    "audio/webm",        # Chrome/Firefox recording format
    "audio/aac",
    "audio/flac",
}

# File extensions we accept (as fallback when MIME type isn't set correctly)
ACCEPTED_EXTENSIONS: set[str] = {
    ".ogg", ".mp3", ".wav", ".m4a", ".mp4", ".webm", ".aac", ".flac"
}

# Gnani prefers these formats (from the working main.py and guardian.py)
GNANI_PREFERRED_MIME = "audio/wav"
GNANI_PREFERRED_EXT = ".wav"


@dataclass
class AudioMetadata:
    """
    Everything we know about an audio file after validation.
    Stored in the message_audio table.
    """
    original_filename: str
    storage_path: str               # Path where we saved the original
    converted_path: Optional[str]   # Path to converted file (if conversion ran)
    mime_type: str
    file_size_bytes: int
    duration_seconds: Optional[float]
    is_valid: bool
    validation_error: Optional[str] = None


@dataclass
class AudioValidationError(Exception):
    """Raised when an uploaded audio file fails validation."""
    reason: str
    user_message: str   # Safe to show to the user


def _get_storage_dir(user_id: str) -> Path:
    """
    Return (and create) the storage directory for a user's audio files.
    Each user gets their own subdirectory so files are isolated.

    Structure:
        audio_storage/
            {user_id}/
                {message_id}_{filename}
    """
    base = Path(settings.audio_storage_path)
    user_dir = base / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def _safe_filename(original_name: str, message_id: str) -> str:
    """
    Generate a safe, unique filename to prevent path traversal attacks.

    Original: "../../etc/passwd.mp3"
    Safe:     "{message_id}_etcpasswd.mp3"
    """
    # Keep only the base name, strip any directory components
    base = Path(original_name).name
    # Remove any characters that could be dangerous in a file path
    safe_chars = "".join(
        c for c in base if c.isalnum() or c in "._- "
    ).strip()
    if not safe_chars:
        safe_chars = "audio"
    return f"{message_id}_{safe_chars}"


def _detect_mime_from_extension(filename: str) -> Optional[str]:
    """
    Guess MIME type from file extension when the upload doesn't set one.
    """
    ext = Path(filename).suffix.lower()
    ext_to_mime = {
        ".ogg": "audio/ogg",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/x-m4a",
        ".mp4": "audio/mp4",
        ".webm": "audio/webm",
        ".aac": "audio/aac",
        ".flac": "audio/flac",
    }
    return ext_to_mime.get(ext)


async def save_uploaded_audio(
    upload: UploadFile,
    user_id: str,
    message_id: str,
) -> AudioMetadata:
    """
    Save an uploaded audio file to disk and validate it.

    Steps:
      1. Check MIME type and extension
      2. Check file size (read in chunks to avoid loading entire file into RAM)
      3. Save to user's storage directory
      4. Extract duration if possible

    Args:
        upload:     The FastAPI UploadFile from the request
        user_id:    The authenticated user's ID (for directory isolation)
        message_id: The message this audio belongs to

    Returns:
        AudioMetadata with all file details

    Raises:
        AudioValidationError if the file is invalid
    """
    # ── Step 1: Validate MIME type ─────────────────────────────────────────
    mime_type = upload.content_type or ""

    # If the browser didn't set a MIME type, try to detect from extension
    if not mime_type or mime_type == "application/octet-stream":
        detected = _detect_mime_from_extension(upload.filename or "")
        if detected:
            mime_type = detected
            logger.info(
                "MIME type detected from extension",
                filename=upload.filename,
                detected_mime=mime_type,
            )

    if mime_type not in ACCEPTED_MIME_TYPES:
        ext = Path(upload.filename or "").suffix.lower()
        if ext not in ACCEPTED_EXTENSIONS:
            raise AudioValidationError(
                reason=f"Unsupported MIME type: {mime_type}",
                user_message=(
                    f"Audio format not supported. "
                    f"Please upload an OGG, MP3, WAV, or M4A file."
                ),
            )
        # Extension is valid even if MIME was unrecognised — proceed
        mime_type = _detect_mime_from_extension(upload.filename) or mime_type

    # ── Step 2: Read file and check size ───────────────────────────────────
    max_bytes = settings.max_audio_size_bytes
    chunks = []
    total_size = 0
    chunk_size = 1024 * 1024  # Read 1 MB at a time

    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > max_bytes:
            raise AudioValidationError(
                reason=f"File size {total_size} exceeds limit {max_bytes}",
                user_message=(
                    f"File is too large. Maximum size is "
                    f"{settings.max_audio_size_mb} MB."
                ),
            )
        chunks.append(chunk)

    if total_size == 0:
        raise AudioValidationError(
            reason="Empty audio file",
            user_message="The audio file is empty. Please record or upload a valid voice message.",
        )

    audio_bytes = b"".join(chunks)

    # ── Step 3: Save to disk ───────────────────────────────────────────────
    storage_dir = _get_storage_dir(user_id)
    safe_name = _safe_filename(upload.filename or "audio.ogg", message_id)
    storage_path = storage_dir / safe_name

    async with aiofiles.open(storage_path, "wb") as f:
        await f.write(audio_bytes)

    logger.info(
        "Audio file saved",
        path=str(storage_path),
        size_bytes=total_size,
        mime_type=mime_type,
    )

    # ── Step 4: Extract duration ───────────────────────────────────────────
    duration = await _extract_duration(storage_path)

    return AudioMetadata(
        original_filename=upload.filename or safe_name,
        storage_path=str(storage_path),
        converted_path=None,
        mime_type=mime_type,
        file_size_bytes=total_size,
        duration_seconds=duration,
        is_valid=True,
    )


async def _extract_duration(audio_path: Path) -> Optional[float]:
    """
    Extract the duration of an audio file using pydub.
    Returns None if pydub can't read the file (e.g. ffmpeg not installed).
    This is non-critical — duration is displayed in the UI but doesn't
    affect transcription.
    """
    try:
        # Run in a thread pool so it doesn't block the async event loop
        loop = asyncio.get_event_loop()
        duration = await loop.run_in_executor(None, _read_duration_sync, audio_path)
        return duration
    except Exception as e:
        logger.warning(
            "Could not extract audio duration",
            path=str(audio_path),
            error=str(e),
            hint="Install ffmpeg for full audio format support",
        )
        return None


def _read_duration_sync(audio_path: Path) -> Optional[float]:
    """Synchronous duration extraction — called from thread pool."""
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(str(audio_path))
        return len(audio) / 1000.0  # pydub duration is in milliseconds
    except Exception:
        return None


async def prepare_for_gnani(audio_path: str) -> tuple[str, str]:
    """
    Prepare an audio file for the Gnani STT API.

    Gnani works best with WAV files. If the file is already WAV, return it
    directly. Otherwise, attempt conversion using pydub + ffmpeg.

    Args:
        audio_path: Path to the original audio file

    Returns:
        Tuple of (file_path_to_send, mime_type_to_use)
        If conversion fails, returns the original path so Gnani can try it.
    """
    path = Path(audio_path)
    ext = path.suffix.lower()

    # Already in a good format — Gnani accepts ogg and mp3 directly
    # (confirmed from guardian.py and main.py tests)
    if ext in {".wav", ".ogg", ".mp3"}:
        mime_map = {
            ".wav": "audio/wav",
            ".ogg": "audio/ogg",
            ".mp3": "audio/mpeg",
        }
        return audio_path, mime_map[ext]

    # Try converting to WAV via pydub
    try:
        loop = asyncio.get_event_loop()
        converted_path = await loop.run_in_executor(
            None, _convert_to_wav_sync, path
        )
        if converted_path:
            logger.info("Audio converted to WAV", original=audio_path, converted=converted_path)
            return str(converted_path), "audio/wav"
    except Exception as e:
        logger.warning(
            "Audio conversion failed, using original",
            path=audio_path,
            error=str(e),
        )

    # Fallback: send original and let Gnani decide
    return audio_path, "audio/octet-stream"


def _convert_to_wav_sync(audio_path: Path) -> Optional[str]:
    """Synchronous WAV conversion — called from thread pool."""
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(str(audio_path))
        wav_path = audio_path.with_suffix(".wav")
        audio.export(str(wav_path), format="wav")
        return str(wav_path)
    except Exception:
        return None
