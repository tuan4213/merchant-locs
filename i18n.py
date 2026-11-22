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
    w = dict(_load_lang_file(lang).get('widget', {}))
    if not w.get('top2_label'):
        fb = (w.get('fallback') or '').strip()
        if str(lang).lower().startswith('vi'):
            w['top2_label'] = f"🥈 TOP 2 ({fb})" if fb else "🥈 TOP 2 (Dự phòng)"
        else:
            w['top2_label'] = f"🥈 TOP 2 ({fb})" if fb else "🥈 TOP 2 (Fallback)"
    return w

# === STATIC_ISO639_LABELS_START ===
def _cc_flag(cc: str) -> str:
    cc = (cc or "").strip().upper()
    if len(cc) == 2 and cc.isalpha():
        return chr(0x1F1E6 + ord(cc[0]) - 65) + chr(0x1F1E6 + ord(cc[1]) - 65)
    return "🌐"

# (Tên ngôn ngữ, mã quốc gia 2 chữ cái để render cờ)
_ISO639_STATIC_META = {
    "aa": ("Afar", "ET"), "ab": ("Abkhazian", "GE"), "ae": ("Avestan", "IR"), "af": ("Afrikaans", "ZA"),
    "ak": ("Akan", "GH"), "am": ("Amharic", "ET"), "an": ("Aragonese", "ES"), "ar": ("العربية", "SA"),
    "as": ("Assamese", "IN"), "av": ("Avaric", "RU"), "ay": ("Aymara", "BO"), "az": ("Azərbaycan", "AZ"),
    "ba": ("Bashkir", "RU"), "be": ("Беларуская", "BY"), "bg": ("Български", "BG"), "bh": ("Bhojpuri", "IN"),
    "bi": ("Bislama", "VU"), "bm": ("Bambara", "ML"), "bn": ("বাংলা", "BD"), "bo": ("བོད་སྐད", "CN"),
    "br": ("Brezhoneg", "FR"), "bs": ("Bosanski", "BA"), "ca": ("Català", "ES"), "ce": ("Нохчийн", "RU"),
    "ch": ("Chamoru", "GU"), "co": ("Corsu", "FR"), "cr": ("Nēhiyawēwin", "CA"), "cs": ("Čeština", "CZ"),
    "cu": ("Church Slavic", "BG"), "cv": ("Чӑвашла", "RU"), "cy": ("Cymraeg", "GB"), "da": ("Dansk", "DK"),
    "de": ("Deutsch", "DE"), "dv": ("Divehi", "MV"), "dz": ("རྫོང་ཁ", "BT"), "ee": ("Eʋegbe", "GH"),
    "el": ("Ελληνικά", "GR"), "en": ("English", "US"), "eo": ("Esperanto", "UN"), "es": ("Español", "ES"),
    "et": ("Eesti", "EE"), "eu": ("Euskara", "ES"), "fa": ("فارسی", "IR"), "ff": ("Fulfulde", "SN"),
    "fi": ("Suomi", "FI"), "fj": ("Na Vosa Vakaviti", "FJ"), "fo": ("Føroyskt", "FO"), "fr": ("Français", "FR"),
    "fy": ("Frysk", "NL"), "ga": ("Gaeilge", "IE"), "gd": ("Gàidhlig", "GB"), "gl": ("Galego", "ES"),
    "gn": ("Avañe'ẽ", "PY"), "gu": ("ગુજરાતી", "IN"), "gv": ("Gaelg", "IM"), "ha": ("Hausa", "NG"),
    "he": ("עברית", "IL"), "hi": ("हिन्दी", "IN"), "ho": ("Hiri Motu", "PG"), "hr": ("Hrvatski", "HR"),
    "ht": ("Kreyòl Ayisyen", "HT"), "hu": ("Magyar", "HU"), "hy": ("Հայերեն", "AM"), "hz": ("Otjiherero", "NA"),
    "ia": ("Interlingua", "UN"), "id": ("Bahasa Indonesia", "ID"), "ie": ("Interlingue", "UN"),
    "ig": ("Igbo", "NG"), "ii": ("ꆈꌠꉙ", "CN"), "ik": ("Iñupiaq", "US"), "io": ("Ido", "UN"),
    "is": ("Íslenska", "IS"), "it": ("Italiano", "IT"), "iu": ("ᐃᓄᒃᑎᑐᑦ", "CA"), "ja": ("日本語", "JP"),
    "jv": ("Basa Jawa", "ID"), "ka": ("ქართული", "GE"), "kg": ("Kikongo", "CD"), "ki": ("Gĩkũyũ", "KE"),
    "kj": ("Kwanyama", "NA"), "kk": ("Қазақ тілі", "KZ"), "kl": ("Kalaallisut", "GL"), "km": ("ខ្មែរ", "KH"),
    "kn": ("ಕನ್ನಡ", "IN"), "ko": ("한국어", "KR"), "kr": ("Kanuri", "NG"), "ks": ("कॉशुर", "IN"),
    "ku": ("Kurdî", "IQ"), "kv": ("Коми", "RU"), "kw": ("Kernewek", "GB"), "ky": ("Кыргызча", "KG"),
    "la": ("Latina", "VA"), "lb": ("Lëtzebuergesch", "LU"), "lg": ("Luganda", "UG"), "li": ("Limburgs", "NL"),
    "ln": ("Lingála", "CD"), "lo": ("ລາວ", "LA"), "lt": ("Lietuvių", "LT"), "lu": ("Kiluba", "CD"),
    "lv": ("Latviešu", "LV"), "mg": ("Malagasy", "MG"), "mh": ("Kajin M̧ajeļ", "MH"), "mi": ("Te Reo Māori", "NZ"),
    "mk": ("Македонски", "MK"), "ml": ("മലയാളം", "IN"), "mn": ("Монгол", "MN"), "mr": ("मराठी", "IN"),
    "ms": ("Bahasa Melayu", "MY"), "mt": ("Malti", "MT"), "my": ("မြန်မာ", "MM"), "na": ("Dorerin Naoero", "NR"),
    "nb": ("Norsk bokmål", "NO"), "nd": ("isiNdebele", "ZW"), "ne": ("नेपाली", "NP"), "ng": ("Owambo", "NA"),
    "nl": ("Nederlands", "NL"), "nn": ("Norsk nynorsk", "NO"), "no": ("Norsk", "NO"), "nr": ("isiNdebele", "ZA"),
    "nv": ("Diné bizaad", "US"), "ny": ("Chichewa", "MW"), "oc": ("Occitan", "FR"), "oj": ("ᐊᓂᔑᓈᐯᒧᐎᓐ", "CA"),
    "om": ("Afaan Oromoo", "ET"), "or": ("ଓଡ଼ିଆ", "IN"), "os": ("Ирон", "GE"), "pa": ("ਪੰਜਾਬੀ", "IN"),
    "pi": ("Pāli", "IN"), "pl": ("Polski", "PL"), "ps": ("پښتو", "AF"), "pt": ("Português", "PT"),
    "qu": ("Runasimi", "PE"), "rm": ("Rumantsch", "CH"), "rn": ("Ikirundi", "BI"), "ro": ("Română", "RO"),
    "ru": ("Русский", "RU"), "rw": ("Ikinyarwanda", "RW"), "sa": ("संस्कृतम्", "IN"), "sc": ("Sardu", "IT"),
    "sd": ("سنڌي", "PK"), "se": ("Davvisámegiella", "NO"), "sg": ("Sängö", "CF"), "si": ("සිංහල", "LK"),
    "sk": ("Slovenčina", "SK"), "sl": ("Slovenščina", "SI"), "sm": ("Gagana Samoa", "WS"), "sn": ("chiShona", "ZW"),
    "so": ("Soomaali", "SO"), "sq": ("Shqip", "AL"), "sr": ("Српски", "RS"), "ss": ("SiSwati", "SZ"),
    "st": ("Sesotho", "LS"), "su": ("Basa Sunda", "ID"), "sv": ("Svenska", "SE"), "sw": ("Kiswahili", "KE"),
    "ta": ("தமிழ்", "IN"), "te": ("తెలుగు", "IN"), "tg": ("Тоҷикӣ", "TJ"), "th": ("ไทย", "TH"),
    "ti": ("ትግርኛ", "ER"), "tk": ("Türkmen", "TM"), "tl": ("Tagalog", "PH"), "tn": ("Setswana", "BW"),
    "to": ("Lea fakatonga", "TO"), "tr": ("Türkçe", "TR"), "ts": ("Xitsonga", "ZA"), "tt": ("Татарча", "RU"),
    "tw": ("Twi", "GH"), "ty": "Tahitian", "ug": ("ئۇيغۇرچە", "CN"), "uk": ("Українська", "UA"),
    "ur": ("اردو", "PK"), "uz": ("Oʻzbek", "UZ"), "ve": ("Tshivenḓa", "ZA"), "vi": ("Tiếng Việt", "VN"),
    "vo": ("Volapük", "UN"), "wa": ("Walon", "BE"), "wo": ("Wolof", "SN"), "xh": ("isiXhosa", "ZA"),
    "yi": ("ייִדיש", "IL"), "yo": ("Yoruba", "NG"), "za": ("Saɯ cueŋƅ", "CN"), "zh": ("中文", "CN"),
    "zh-cn": ("简体中文", "CN"), "zh-tw": ("繁體中文", "TW"), "zu": ("isiZulu", "ZA"),
}

def _build_static_label(code: str) -> str:
    c = (code or "").strip().lower()
    meta = _ISO639_STATIC_META.get(c) or _ISO639_STATIC_META.get(c.split("-")[0])
    if isinstance(meta, tuple) and len(meta) == 2:
        name, cc = meta
        return f"{name} {_cc_flag(cc)}".strip()
    if isinstance(meta, str):
        return f"{meta} {_cc_flag(c[:2])}".strip()
    return f"{c.upper()} 🌐" if c else "🌐"

if isinstance(globals().get("LANG_LABELS"), dict):
    _codes_in_order = []
    _seen_codes = set()
    for _lbl, _cd in LANG_LABELS.items():
        _c = str(_cd).strip().lower()
        if _c and _c not in _seen_codes:
            _seen_codes.add(_c)
            _codes_in_order.append(_c)
    _new_map = {_build_static_label(_c): _c for _c in _codes_in_order}
    LANG_LABELS.clear()
    LANG_LABELS.update(_new_map)
# === STATIC_ISO639_LABELS_END ===
