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

# === ISO639_NAME_MAP_PATCH_START ===
def _flag_from_cc(cc: str) -> str:
    cc = (cc or "").strip().upper()
    if len(cc) == 2 and cc.isalpha():
        return chr(0x1F1E6 + ord(cc[0]) - 65) + chr(0x1F1E6 + ord(cc[1]) - 65)
    return "🌐"

_LANG_TO_CC = {
    "aa": "ET", "ab": "GE", "ae": "IR", "af": "ZA", "ak": "GH", "am": "ET", "an": "ES", "ar": "SA",
    "as": "IN", "av": "RU", "ay": "BO", "az": "AZ", "ba": "RU", "be": "BY", "bg": "BG", "bh": "IN",
    "bi": "VU", "bm": "ML", "bn": "BD", "bo": "CN", "br": "FR", "bs": "BA", "ca": "ES", "ce": "RU",
    "ch": "GU", "co": "FR", "cr": "CA", "cs": "CZ", "cu": "BG", "cv": "RU", "cy": "GB", "da": "DK",
    "de": "DE", "dv": "MV", "dz": "BT", "ee": "GH", "el": "GR", "en": "US", "eo": "UN", "es": "ES",
    "et": "EE", "eu": "ES", "fa": "IR", "ff": "SN", "fi": "FI", "fj": "FJ", "fo": "FO", "fr": "FR",
    "fy": "NL", "ga": "IE", "gd": "GB", "gl": "ES", "gn": "PY", "gu": "IN", "gv": "IM", "ha": "NG",
    "he": "IL", "hi": "IN", "ho": "PG", "hr": "HR", "ht": "HT", "hu": "HU", "hy": "AM", "hz": "NA",
    "ia": "UN", "id": "ID", "ie": "UN", "ig": "NG", "ii": "CN", "ik": "US", "io": "UN", "is": "IS",
    "it": "IT", "iu": "CA", "ja": "JP", "jv": "ID", "ka": "GE", "kg": "CD", "ki": "KE", "kj": "NA",
    "kk": "KZ", "kl": "GL", "km": "KH", "kn": "IN", "ko": "KR", "kr": "NG", "ks": "IN", "ku": "IQ",
    "kv": "RU", "kw": "GB", "ky": "KG", "la": "VA", "lb": "LU", "lg": "UG", "li": "NL", "ln": "CD",
    "lo": "LA", "lt": "LT", "lu": "CD", "lv": "LV", "mg": "MG", "mh": "MH", "mi": "NZ", "mk": "MK",
    "ml": "IN", "mn": "MN", "mr": "IN", "ms": "MY", "mt": "MT", "my": "MM", "na": "NR", "nb": "NO",
    "nd": "ZW", "ne": "NP", "ng": "NA", "nl": "NL", "nn": "NO", "no": "NO", "nr": "ZA", "nv": "US",
    "ny": "MW", "oc": "FR", "oj": "CA", "om": "ET", "or": "IN", "os": "GE", "pa": "IN", "pi": "IN",
    "pl": "PL", "ps": "AF", "pt": "PT", "qu": "PE", "rm": "CH", "rn": "BI", "ro": "RO", "ru": "RU",
    "rw": "RW", "sa": "IN", "sc": "IT", "sd": "PK", "se": "NO", "sg": "CF", "si": "LK", "sk": "SK",
    "sl": "SI", "sm": "WS", "sn": "ZW", "so": "SO", "sq": "AL", "sr": "RS", "ss": "SZ", "st": "LS",
    "su": "ID", "sv": "SE", "sw": "KE", "ta": "IN", "te": "IN", "tg": "TJ", "th": "TH", "ti": "ER",
    "tk": "TM", "tl": "PH", "tn": "BW", "to": "TO", "tr": "TR", "ts": "ZA", "tt": "RU", "tw": "GH",
    "ty": "PF", "ug": "CN", "uk": "UA", "ur": "PK", "uz": "UZ", "ve": "ZA", "vi": "VN", "vo": "UN",
    "wa": "BE", "wo": "SN", "xh": "ZA", "yi": "IL", "yo": "Yoruba", "za": "CN", "zh": "CN", "zh-cn": "CN",
    "zh-tw": "TW", "zu": "ZA",
}

_CUSTOM_LANG_NAMES = {
    "vi": "Tiếng Việt",
    "en": "English",
    "ja": "日本語",
    "zh": "中文",
    "zh-cn": "简体中文",
    "zh-tw": "繁體中文",
    "fr": "Français",
    "ko": "한국어",
    "th": "ไทย",
    "id": "Bahasa Indonesia",
    "ms": "Bahasa Melayu",
    "de": "Deutsch",
    "es": "Español",
    "pt": "Português",
    "ru": "Русский",
    "ar": "العربية",
    "hi": "हिन्दी",
    "it": "Italiano",
    "nl": "Nederlands",
    "pl": "Polski",
    "tr": "Türkçe",
    "uk": "Українська",
    "af": "Afrikaans",
    "am": "Amharic",
    "az": "Azərbaycan",
    "bg": "Български",
    "bn": "বাংলা",
    "bs": "Bosanski",
    "ca": "Català",
    "cs": "Čeština",
    "cy": "Cymraeg",
    "da": "Dansk",
    "el": "Ελληνικά",
    "et": "Eesti",
    "eu": "Euskara",
    "fa": "فارسی",
    "fi": "Suomi",
    "ga": "Gaeilge",
    "gl": "Galego",
    "gu": "ગુજરાતી",
    "he": "עברית",
    "hr": "Hrvatski",
    "hu": "Magyar",
    "hy": "Հայերեն",
    "is": "Íslenska",
    "ka": "ქართული",
    "kk": "Қазақ тілі",
    "km": "ខ្មែរ",
    "kn": "ಕನ್ನಡ",
    "lo": "ລາວ",
    "lt": "Lietuvių",
    "lv": "Latviešu",
    "mk": "Македонски",
    "ml": "മലയാളം",
    "mn": "Монгол",
    "mr": "मराठी",
    "mt": "Malti",
    "my": "မြန်မာ",
    "ne": "नेपाली",
    "no": "Norsk",
    "pa": "ਪੰਜਾਬੀ",
    "ps": "پښتو",
    "ro": "Română",
    "si": "සිංහල",
    "sk": "Slovenčina",
    "sl": "Slovenščina",
    "so": "Soomaali",
    "sq": "Shqip",
    "sr": "Српски",
    "sv": "Svenska",
    "sw": "Kiswahili",
    "ta": "தமிழ்",
    "te": "తెలుగు",
    "tl": "Tagalog",
    "ur": "اردو",
    "uz": "Oʻzbek",
    "zu": "isiZulu",
}

def _format_lang_with_flag(code: str, existing_label: str = "") -> str:
    c = (code or "").strip().lower()
    flag = _flag_from_cc(_LANG_TO_CC.get(c, c[:2]))
    name = _CUSTOM_LANG_NAMES.get(c)
    if not name:
        try:
            import pycountry
            lang_obj = pycountry.languages.get(alpha_2=c[:2])
            if lang_obj and getattr(lang_obj, "name", None):
                name = lang_obj.name
        except Exception:
            pass
    if not name and existing_label and existing_label.strip().lower() != c:
        cleaned = re.sub(r"[🇦-🇿]2|\🌐", "", existing_label).strip()
        if cleaned and not cleaned.lower().startswith("language ("):
            name = cleaned
    if not name:
        name = f"Lang {c.upper()}" if c else "Unknown"
    return f"{name} {flag}".strip()

try:
    if isinstance(LANG_LABELS, dict):
        _rebuilt = {}
        for _lbl, _code in LANG_LABELS.items():
            _c = str(_code).strip().lower()
            _formatted = _format_lang_with_flag(_c, str(_lbl or ""))
            _rebuilt[_formatted] = _c
        LANG_LABELS.clear()
        LANG_LABELS.update(_rebuilt)
except Exception:
    pass
# === ISO639_NAME_MAP_PATCH_END ===
