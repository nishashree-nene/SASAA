
import os
import requests
from dotenv import load_dotenv

# Load API key from .env
load_dotenv()

API_KEY = os.getenv("GNANI_API_KEY")

API_URL = "https://api.vachana.ai/stt/v3"

# Check API key
if not API_KEY:
    print("API key not found. Check your .env file.")
    raise SystemExit(1)

# Audio file location
audio_path = "sample/test.wav.mp3"

if not os.path.exists(audio_path):
    print("Audio file not found:", audio_path)
    raise SystemExit(1)

# Send audio to Gnani Prisma
try:
    with open(audio_path, "rb") as audio:
        response = requests.post(
            API_URL,
            headers={
                "X-API-Key-ID": API_KEY
            },
            files={
                "audio_file": ("test.wav.mp3", audio, "audio/mpeg")
            },
            data={
                "model": "prisma-v3.0",
                "language_code": "ta-IN",
                "format": "verbatim"
            },
            timeout=60
        )

    response.raise_for_status()
    result = response.json()

    if result.get("success"):
        print("\nTranscription successful!")
        print("Transcript:", result.get("transcript"))
        print("Language:", result.get("detected_language_code"))
        print("Latency:", result.get("end_to_end_latency"))
    else:
        print("Transcription failed:", result)

except requests.exceptions.RequestException as error:
    print("API request error:", error)
