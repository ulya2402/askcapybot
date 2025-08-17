import json
from pathlib import Path

class Translator:
    def __init__(self, path: str):
        self.translations = {}
        locales_path = Path(path)
        if not locales_path.is_dir():
            print(f"Error: Locales directory not found at '{path}'")
            return
            
        for file in locales_path.glob("*.json"):
            lang_code = file.stem
            with open(file, "r", encoding="utf-8") as f:
                self.translations[lang_code] = json.load(f)
        
        if self.translations:
            print(f"Loaded languages: {list(self.translations.keys())}")
        else:
            print("Warning: No language files were loaded.")

    def get_text(self, key: str, lang_code: str = "en"):
        # Fallback to English if the user's language isn't loaded
        effective_lang_code = lang_code if lang_code in self.translations else "en"
        
        # Get the dictionary for the effective language, or the English one as a fallback
        lang_dict = self.translations.get(effective_lang_code, self.translations.get("en", {}))
        
        return lang_dict.get(key, f"<{key}>")

translator_instance = Translator(path="locales")
