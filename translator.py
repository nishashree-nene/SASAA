
from deep_translator import GoogleTranslator

def translate_to_english(original_text):
    try:
        translated_text = GoogleTranslator(
            source="auto",
            target="en"
        ).translate(original_text)

        return translated_text

    except Exception as error:
        print("Translation failed:", error)
        return None
