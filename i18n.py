# i18n.py — Language support
LANG_LABELS = {
    "Tiếng Việt": "vi",
    "English": "en",
}

TRANSLATIONS_EN = {
    "title": "📍 Merchant Location",
    "loading": "Loading...",
    "passed": "Passed",
    "sidebar_config": "### ⚙️ Config",
    "sidebar_reload": "🔄 Reload config files",
    "sidebar_hint": "Edit config files → click Reload",
    "uploader": "Upload CSV",
    "use_default": "📚 Use default baseline",
    "slider_label": "🕰️ Time travel (days)",
    "reset_time_travel": "🔄 Reset Time Travel",
    "upload_hint": "👆 Upload CSV to start",
    "success": "✅ Processed: {parts}",
    "failed": "❌ Pipeline failed",
    "expander": "📋 Log",
    "log_download": "💾 Download log",
    "info_header": "📚 **Default baseline** ({n} file(s)):",
    "info_from": "- 🗓️ **From:** `{v}` (VN, UTC+7)",
    "info_to": "- 🗓️ **To:** `{v}` (VN, UTC+7)",
    "info_total": "- 📊 **Total:** `{n:,}` posts  ·  💾 `{mb:.1f} MB`",
    "no_valid": "⚠️ No valid rows",
    "read_error": "⚠️ Read error: `{e}`",
    "no_default": "ℹ️ No baseline CSV",
    "part_default": "{n} baseline",
    "part_upload": "{n} uploaded",
    "gap_warning": "⚠️ **Gap Warning:** Found **{n}** missing slots.",
    "gap_detail_btn": "🔍 Details",
    "gap_list_title": "**Missing slots (most recent):**",
    "err_widget_missing": "⚠️ Cannot find `widget_template.html`.",
    "err_lang_files": "⚠️ Language files error:",
    "predict_settings_title": "⚙️ Predict Settings",
    "utc_offset_label": "🌍 UTC Offset",
    "utc_reset_btn": "🔄 Reset",
    "timezone_warning": "⚠️ Times based on VN timezone",
    "gap_disabled_warning": "⚠️ **Note:** Gap handling features are disabled.",
    "gap_stats": "⚠️ **Gap Stats:** {n} missing slots.",
    "gap_detail_btn_settings": "🔍 Show recent missing slots",
    "gap_none": "✅ Data complete, no gaps detected.",
    "time_prev": " (Prev)",
    "time_next": " (Next)",
    "predict_settings_md": "",
    "trans_scan_title": "#### 🔍 TRANS Scan",
    "trans_scan_slots": "Slots to scan backwards",
    "adaptive_toggled": "✅ {status} adaptive offset",
    "trans_overridden": "🚀 Static TRANS overridden",
    "trans_using_static": "✅ Using static TRANS",
    "trans_scanned_caption": "📥 Scanned: **{used}** slots (requested: {req})",
    "trans_train_test": "📊 Train: {train} | Test: {test}",
    "trans_edit": "Edit content:",
}

WIDGET_TEXT = {
    "vi": {
        "title": "Vị trí Merchant", "loading": "Đang tải...", "passed": "Đã qua",
        "copied": "Đã sao chép", "copy_failed": "Lỗi",
        "no_cand": "Không có dự đoán",
        "src": "← nguồn", "src_actual": "← slot thật", "src_bridge": "← bridge từ",
        "actual_hint": "Pattern thật từ CSV", "bridge_hint": "Pattern dự đoán (lấp gap)",
        "fallback": "Dự phòng", "reinforced": "Được củng cố",
        "dup_hint": "Được xác nhận bởi nguồn khác", "check": "Kiểm tra",
        "real_badge": "THẬT", "bridge_badge": "BRIDGE",
        "real_prefix": "⏱ Thực: ",
        "missing_data_warn": "⚠️ <b>Dữ liệu gốc bị thiếu!</b> Dự đoán quy luật. Không có data tại ",
    },
    "en": {
        "title": "Merchant Location", "loading": "Loading...", "passed": "Passed",
        "copied": "Copied", "copy_failed": "Failed",
        "no_cand": "No prediction",
        "src": "← source", "src_actual": "← actual slot", "src_bridge": "← bridge from",
        "actual_hint": "Actual pattern from CSV", "bridge_hint": "Predicted pattern (gap fill)",
        "fallback": "Fallback", "reinforced": "Reinforced",
        "dup_hint": "Confirmed by other sources", "check": "Check",
        "real_badge": "ACTUAL", "bridge_badge": "BRIDGE",
        "real_prefix": "⏱ Real: ",
        "missing_data_warn": "⚠️ <b>Missing source data!</b> Predicting by rule. No data at ",
    }
}

def get_translator(lang):
    def translate(key, default=None, **kwargs):
        if lang == "en" and key in TRANSLATIONS_EN:
            text = TRANSLATIONS_EN[key]
        elif default is not None:
            text = default
        else:
            text = key
        if kwargs:
            try: text = text.format(**kwargs)
            except (KeyError, ValueError, IndexError): pass
        return text
    return translate

def get_widget_text(lang):
    return WIDGET_TEXT.get(lang, WIDGET_TEXT["en"])

def check_locales_errors():
    return []

def detect_default_lang():
    return "vi"
