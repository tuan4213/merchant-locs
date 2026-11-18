# i18n.py
import json
import streamlit as st
from pathlib import Path

LOCALES_DIR = Path("locales")
LANG_PREFIX = "lang_"

def _file_path(code):
    return LOCALES_DIR / f"{LANG_PREFIX}{code}.json"

def _stem_to_code(stem):
    if LANG_PREFIX and stem.startswith(LANG_PREFIX):
        return stem[len(LANG_PREFIX):]
    return stem

LANG_NAMES = {
    "vi": "Tiếng Việt 🇻🇳",
    "en": "English 🇺🇸",
    "ja": "日本語 🇯🇵",
    "zh": "中文 🇨🇳",
    "fr": "Français 🇫🇷",
}
DEFAULT_LANG = "vi"

def get_available_langs():
    if not LOCALES_DIR.exists():
        return []
    pattern = f"{LANG_PREFIX}*.json" if LANG_PREFIX else "*.json"
    return sorted([_stem_to_code(f.stem) for f in LOCALES_DIR.glob(pattern) if _stem_to_code(f.stem)])

def _build_lang_labels():
    available = set(get_available_langs())
    if not available:
        return {name: code for code, name in LANG_NAMES.items()}
    labels = {name: code for code, name in LANG_NAMES.items() if code in available}
    for code in sorted(available - set(LANG_NAMES.keys())):
        labels[code] = code
    return labels

LANG_LABELS = _build_lang_labels()

VN_TIMEZONES = {
    "Asia/Ho_Chi_Minh", "Asia/Saigon", "Asia/Bangkok",
    "Asia/Phnom_Penh", "Asia/Vientiane", "Asia/Jakarta",
}

def detect_default_lang():
    try:
        tz = st.context.timezone or ""
        if tz in VN_TIMEZONES:
            return "vi"
        return "en"
    except Exception:
        return "vi"

def check_locales_errors():
    errors = []
    if not LOCALES_DIR.exists():
        return [f"Thư mục '{LOCALES_DIR}' không tồn tại."]
    pattern = f"{LANG_PREFIX}*.json" if LANG_PREFIX else "*.json"
    files = sorted(LOCALES_DIR.glob(pattern))
    if not files:
        return [f"Không có file {LANG_PREFIX}*.json trong '{LOCALES_DIR}'."]
    for f in files:
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
        except json.JSONDecodeError as e:
            errors.append(f"`{f.name}`: JSON lỗi — dòng {e.lineno}: {e.msg}")
            continue
        except Exception as e:
            errors.append(f"`{f.name}`: {e}")
            continue
        if not isinstance(data, dict):
            errors.append(f"`{f.name}`: root phải là dict")
            continue
        for key in ('ui', 'widget'):
            if key in data and not isinstance(data[key], dict):
                errors.append(f"`{f.name}`: '{key}' phải là dict")
        if 'ui' not in data:
            errors.append(f"`{f.name}`: thiếu key 'ui'")
    return errors

@st.cache_data(show_spinner=False)
def _load_lang_file(lang_code):
    file_path = _file_path(lang_code)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        st.error(f"⚠️ Lỗi load ngôn ngữ {lang_code}: {e}")
        return {"ui": {}, "widget": {}}

def get_translator(lang):
    data = _load_lang_file(lang)
    lang_dict = data.get('ui', {})
    def T(key, default=None, **kwargs):
        text = lang_dict.get(key)
        if text is None:
            text = default if default is not None else f"[{key}]"
        try:
            return text.format(**kwargs) if kwargs else text
        except KeyError:
            return text
    return T

def get_widget_text(lang):
    return _load_lang_file(lang).get('widget', {})
