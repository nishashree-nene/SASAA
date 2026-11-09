
import os
import re
import time
import requests

from pathlib import Path
from dotenv import load_dotenv
from translator import translate_to_english


# --------------------------------
# 1. LOAD API CONFIGURATION
# --------------------------------

load_dotenv()

API_KEY = os.getenv("GNANI_API_KEY")
API_URL = "https://api.vachana.ai/stt/v3"

audio_path = Path("sample/time_test.wav.ogg")


# --------------------------------
# 2. CHECK API KEY AND AUDIO FILE
# --------------------------------

if not API_KEY:
    print("ERROR: GNANI_API_KEY not found in .env")
    raise SystemExit(1)

if not audio_path.exists():
    print("ERROR: Audio file not found:", audio_path)
    raise SystemExit(1)


# --------------------------------
# 3. CHECK IMPORTANT TIME
# --------------------------------

def check_time(transcript):

    pattern = (
        r"\b(1[0-2]|0?[1-9])"
        r"(?::([0-5]\d))?"
        r"\s*(AM|PM)\b"
    )

    match = re.search(pattern, transcript, re.IGNORECASE)

    if match:

        hour = match.group(1)
        minute = match.group(2) or "00"
        period = match.group(3).upper()

        detected_time = f"{hour}:{minute} {period}"

        print("\nTIME DETECTED:", detected_time)
        print("AM/PM information is present.")

    else:

        number_pattern = (
            r"\b(1[0-2]|0?[1-9])"
            r"(?::([0-5]\d))?\b"
        )

        number_match = re.search(number_pattern, transcript)

        if number_match:
            print("\nWARNING: Time detected, but AM/PM is missing.")
            print("Manual verification required.")

        else:
            print("\nNo recognizable time found in transcript.")


# --------------------------------
# 4. GNANI SPEECH-TO-TEXT API
# --------------------------------

def transcribe_audio():

    for attempt in range(3):

        response = None

        try:

            print(f"\nAPI Attempt {attempt + 1}/3")

            with audio_path.open("rb") as audio:

                response = requests.post(

                    API_URL,

                    headers={
                        "X-API-Key-ID": API_KEY
                    },

                    files={
                        "audio_file": (
                            audio_path.name,
                            audio,
                            "audio/ogg"
                        )
                    },

                    data={
                        "language_code": "ta-IN",
                        "format": "verbatim"
                    },

                    timeout=120
                )

            print("Status:", response.status_code)

            if response.status_code == 504:

                print("Server gateway timeout.")

                if attempt < 2:
                    print("Retrying in 5 seconds...")
                    time.sleep(5)
                    continue

                return None

            response.raise_for_status()

            result = response.json()

            transcript = result.get("transcript", "")

            if transcript:

                print("\nTRANSCRIPTION SUCCESSFUL!")

                return transcript

            print("No transcript received.")
            print("API response:", result)

            return None

        except requests.exceptions.Timeout:

            print("Request timed out.")

            if attempt < 2:
                print("Retrying in 5 seconds...")
                time.sleep(5)

        except requests.exceptions.RequestException as error:

            print("API request failed:", error)

            if response is not None:
                print("API response:", response.text[:1000])

            return None

        except ValueError:

            print("API returned invalid JSON.")
            return None

    print("\nAll API attempts failed.")

    return None


# --------------------------------
# 5. MAIN PROGRAM
# --------------------------------

def main():

    print("\nVOICE NOTE GUARDIAN")
    print("-------------------")

    # Get original transcript
    transcript = transcribe_audio()

    if not transcript:

        print("\nTranscription failed.")
        print("Translation unavailable.")
        return

    # Display original transcript
    print("\nORIGINAL TRANSCRIPT:")
    print(transcript)

    # Translate original transcript into English
    print("\nTRANSLATING INTO ENGLISH...")

    english_translation = translate_to_english(transcript)

    if english_translation:

        print("\nENGLISH TRANSLATION:")
        print(english_translation)

    else:

        print("\nEnglish translation unavailable.")

    # Check time in original transcript
    print("\nCHECKING IMPORTANT TIME INFORMATION...")

    check_time(transcript)


# --------------------------------
# 6. PROGRAM START
# --------------------------------

if __name__ == "__main__":
    main()
