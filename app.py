import streamlit as st
import streamlit.components.v1 as components
import csv, os, glob, subprocess, shutil, base64
from datetime import datetime, timedelta, timezone
from pathlib import Path

from i18n import (LANG_LABELS as LANG_OPTIONS, get_translator,
                  check_locales_errors, detect_default_lang)
import predictor

# [PATCH-LOCK] Serialize run_pipeline calls
import threading as _threading
_PIPELINE_LOCK = _threading.Lock()

# === CONFIG FLAGS (was missing after refactor) ===
# Bật/tắt UI nâng cao cho block 'Quét TRANS' (verify offsets động)
SHOW_ADVANCED_UI = True
# === END CONFIG FLAGS ===


st.set_page_config(page_title="Merchant Location", layout="wide")

components.html("""
<script>
(function() {
    let hiddenAt = null;
    let lastVisible = Date.now();
    let heartbeatStuckCount = 0;
    const HIDDEN_TIMEOUT_MS = 60 * 1000;
    const RENDER_GRACE_MS   = 1500;
    const HEARTBEAT_MS      = 30 * 1000;
    const FOCUS_GRACE_MS    = 1500;
    function isStuck() {
        const appRoot = document.querySelector('[data-testid="stAppViewContainer"]');
        const hasContent = appRoot && appRoot.children.length > 2;
        const hasSpinner = document.querySelector('[data-testid="stSpinner"], [data-testid="stStatusWidget"]');
        const hasError = document.querySelector('[data-testid="stException"]');
        const hasInteractive = document.querySelector('[data-testid="stFileUploader"], [data-testid="stButton"], iframe, [data-testid="stSlider"]');
        return (!hasContent) || hasSpinner || hasError || (!hasInteractive);
    }
    document.addEventListener('visibilitychange', function() {
        if (document.hidden) { hiddenAt = Date.now(); return; }
        lastVisible = Date.now();
        if (!hiddenAt) return;
        const hiddenMs = Date.now() - hiddenAt;
        hiddenAt = null;
        if (hiddenMs < HIDDEN_TIMEOUT_MS) {
            setTimeout(function() { if (isStuck()) window.location.reload(); }, FOCUS_GRACE_MS);
            return;
        }
        setTimeout(function() {
            if (isStuck()) { window.location.reload(); return; }
            setTimeout(function() { if (isStuck()) window.location.reload(); }, 2000);
        }, RENDER_GRACE_MS);
    });
    window.addEventListener('focus', function() {
        if (document.hidden) return;
        if (Date.now() - lastVisible < 2000) return;
        lastVisible = Date.now();
        setTimeout(function() { if (isStuck()) window.location.reload(); }, FOCUS_GRACE_MS);
    });
    setInterval(function() {
        if (document.hidden) { heartbeatStuckCount = 0; return; }
        if (isStuck()) {
            heartbeatStuckCount++;
            if (heartbeatStuckCount >= 2) window.location.reload();
        } else { heartbeatStuckCount = 0; }
    }, HEARTBEAT_MS);
})();
</script>
""", height=0)

st.markdown(T('csv_logic_cols_html', default="<div style=\"display:flex;flex-wrap:wrap;align-items:center;gap:6px;font-size:12.5px;line-height:1.55;color:#a8b0c4;margin:4px 0 8px 0;max-width:100%;overflow-wrap:anywhere;word-break:break-word;\"><span style=\"white-space:nowrap;\">📄 <b style=\"color:#e2e6f0;\">Cột logic CSV:</b></span><span style=\"display:inline-flex;align-items:center;gap:4px;flex-wrap:wrap;min-width:0;overflow-wrap:anywhere;\"><code style=\"color:#ffd166;background:rgba(255,209,102,.15);padding:1px 6px;border-radius:4px;font-weight:600;white-space:nowrap;\">ID</code><span style=\"color:#c8ccd8;\">(Snowflake ID nếu có — không dùng tính chu kỳ/slot)</span></span> <span style=\"color:#6c7288;margin:0 2px;\">·</span> <span style=\"display:inline-flex;align-items:center;gap:4px;flex-wrap:wrap;min-width:0;overflow-wrap:anywhere;\"><code style=\"color:#7ab7ff;background:rgba(122,183,255,.16);padding:1px 6px;border-radius:4px;font-weight:600;white-space:nowrap;\">Timestamp</code><span style=\"color:#c8ccd8;\">(mốc thời gian quy đổi slot 6h)</span></span> <span style=\"color:#6c7288;margin:0 2px;\">·</span> <span style=\"display:inline-flex;align-items:center;gap:4px;flex-wrap:wrap;min-width:0;overflow-wrap:anywhere;\"><code style=\"color:#90ee90;background:rgba(144,238,144,.15);padding:1px 6px;border-radius:4px;font-weight:600;white-space:nowrap;\">Content</code><span style=\"color:#c8ccd8;\">(nội dung pattern/vật phẩm)</span></span></div>") if not str(locals().get('lang', '')).lower().startswith('en') else "<div style=\"display:flex;flex-wrap:wrap;align-items:center;gap:6px;font-size:12.5px;line-height:1.55;color:#a8b0c4;margin:4px 0 8px 0;max-width:100%;overflow-wrap:anywhere;word-break:break-word;\"><span style=\"white-space:nowrap;\">📄 <b style=\"color:#e2e6f0;\">Logic CSV columns:</b></span><span style=\"display:inline-flex;align-items:center;gap:4px;flex-wrap:wrap;min-width:0;overflow-wrap:anywhere;\"><code style=\"color:#ffd166;background:rgba(255,209,102,.15);padding:1px 6px;border-radius:4px;font-weight:600;white-space:nowrap;\">ID</code><span style=\"color:#c8ccd8;\">(Snowflake ID if present — not used for cycle/slot)</span></span> <span style=\"color:#6c7288;margin:0 2px;\">·</span> <span style=\"display:inline-flex;align-items:center;gap:4px;flex-wrap:wrap;min-width:0;overflow-wrap:anywhere;\"><code style=\"color:#7ab7ff;background:rgba(122,183,255,.16);padding:1px 6px;border-radius:4px;font-weight:600;white-space:nowrap;\">Timestamp</code><span style=\"color:#c8ccd8;\">(timestamp mapped to 6h slot)</span></span> <span style=\"color:#6c7288;margin:0 2px;\">·</span> <span style=\"display:inline-flex;align-items:center;gap:4px;flex-wrap:wrap;min-width:0;overflow-wrap:anywhere;\"><code style=\"color:#90ee90;background:rgba(144,238,144,.15);padding:1px 6px;border-radius:4px;font-weight:600;white-space:nowrap;\">Content</code><span style=\"color:#c8ccd8;\">(pattern/item content)</span></span></div>", unsafe_allow_html=True)
uploaded = st.file_uploader(T("uploader", default="Upload CSV"), type=["csv"], accept_multiple_files=True)

# --- CẢNH BÁO TIMEZONE CSV ---
if uploaded:
    try:
        import io as _io, csv as _csv
        _sample_ts = []
        for _row in list(_csv.DictReader(_io.StringIO(uploaded[0].getvalue().decode('utf-8-sig', errors='replace'))))[:50]:
            _t = _row.get('Timestamp') or _row.get('timestamp') or ''
            if _t: _sample_ts.append(_t)
        _tz_formats = predictor._check_mixed_timezones(_sample_ts)
        if len(_tz_formats) > 1:
            st.warning(f"⚠️ **Cảnh báo:** File CSV chứa nhiều định dạng timezone: `{_tz_formats}`. App sẽ tự động convert.")
        elif _tz_formats and "Naive" not in _tz_formats:
            st.info(f"ℹ️ **Timezone:** File CSV đã có sẵn timezone `{_tz_formats[0]}`. App đã tự động convert về UTC+7.")
        else:
            st.info(f"ℹ️ **Timezone:** File CSV không có timezone. App giả định file đang ở **UTC+{st.session_state.utc_offset}** và tự động convert về UTC+7.")
    except Exception:
        pass

_has_something = uploaded or (use_default and bool(_default_files))

if _has_something:
    files_data = tuple((f.name, f.getvalue()) for f in (uploaded or []))
    _loaded = load_default_csv()
    default_rows = tuple(_loaded[0]) if use_default else tuple()
    used_files = tuple(_loaded[3]) if use_default else tuple()

    @st.cache_data(show_spinner=False)
    def _cached(files_tuple, default_rows_tuple, used_files_tuple, offset, use_def, lang_code, utc_off, trans_lookback, adaptive_state):
        # [PATCH-ISOLATION-v2] Lock + reload + deepcopy tránh race
        import importlib as _il
        import copy as _cp
        with _PIPELINE_LOCK:
            _il.reload(predictor)
            _res = predictor.run_pipeline(list(files_tuple), list(default_rows_tuple), list(used_files_tuple), offset, use_def, lang_code, utc_off, trans_lookback)
            return (_res[0], _res[1], _res[2], _cp.deepcopy(_res[3]))
    widget_html, log_text, trans_text, trans_stats = _cached(
        files_data, default_rows, used_files, offset_days, use_default, lang, st.session_state.utc_offset, trans_lookback_input, predictor.get_adaptive_offset_state()
    )
    
    if SHOW_ADVANCED_UI and trans_text:
        _stats_changed = st.session_state.get('trans_stats') != trans_stats
        _text_changed = st.session_state.get('trans_text') != trans_text
        st.session_state['trans_text'] = trans_text
        st.session_state['trans_stats'] = trans_stats
        if (_stats_changed or _text_changed) and not st.session_state.get('_skip_rerun_flag'):
            st.session_state['_skip_rerun_flag'] = True; st.rerun()
    else:
        st.session_state.pop('_skip_rerun_flag', None)

    if widget_html is None:
        st.error(T("failed", default="❌ Pipeline failed")); st.code(log_text, language="text")
    else:
        parts = ([T("part_default", default="{n} baseline", n=len(_default_files))] if use_default else []) + ([T("part_upload", default="{n} uploaded", n=len(uploaded))] if uploaded else [])
        st.success(T("success", default="✅ Processed: {parts}", parts=" + ".join(parts)))
        if trans_stats.get('total_missing_04', 0) > 0:
            c1, c2 = st.columns([4, 1])
            with c1: st.warning(T("gap_warning", default="⚠️ **Cảnh báo Gap:** Phát hiện **{n}** slot bị thiếu dữ liệu.", n=trans_stats['total_missing_04']))
            with c2:
                with st.popover(T("gap_detail_btn", default="🔍 Chi tiết"), use_container_width=True):
                    st.write(T("gap_list_title", default="**Các slot bị thiếu gần nhất:**"))
                    missing_str = format_missing_slots(trans_stats['missing_04'], st.session_state.utc_offset)
                    st.code(missing_str, language="text")
        components.html(widget_html, height=1100, scrolling=True)
        with st.expander(T("expander", default="📋 Log"), expanded=False):
            col_log_a, col_log_b = st.columns([4, 1])
            with col_log_b:
                st.download_button(T("log_download", default="💾 Tải log"), log_text, file_name=f"pipeline_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt", key="dl_log_btn", use_container_width=True)
            st.code(log_text, language="text")
else:
    st.info(T("upload_hint", default="👆 Upload CSV to start"))

with st.expander(T("predict_settings_title", default=T("predict_settings_title", default="⚙️ Predict Settings")), expanded=False):

    def calc_local_time(vn_hour, user_offset):
        local_hour = (vn_hour - 7) + user_offset
        day_shift = 0
        if local_hour < 0: local_hour += 24; day_shift = -1
        elif local_hour >= 24: local_hour -= 24; day_shift = 1
        hh, mm = int(local_hour), int((local_hour - int(local_hour)) * 60)
        time_str = f"{hh:02d}:{mm:02d}"
        if day_shift == -1: time_str += T("time_prev", default=" (Prev)")
        elif day_shift == 1: time_str += T("time_next", default=" (Next)")
        return time_str

    local_times = {k: calc_local_time(int(k), utc_offset) for k in ["04", "10", "16", "22"]}
    settings_text = T("predict_settings_md", default="")
    for k, v in local_times.items(): settings_text = settings_text.replace(f"{{t_{k}}}", v)
    st.markdown(settings_text)
    st.warning(T("timezone_warning", default="⚠️ Times based on VN timezone"))
    st.warning(T("gap_disabled_warning", default="⚠️ **Lưu ý:** Các tính năng xử lý gap (Bridge, Patch 1, Auto-Heal) đã bị vô hiệu hoá vĩnh viễn trong code để đảm bảo dữ liệu không bị nhiễu."))
    if trans_stats.get('total_missing_04', 0) > 0:
        st.error(T("gap_stats", default="⚠️ **Thống kê Gap:** {n} slot bị thiếu dữ liệu.", n=trans_stats['total_missing_04']))
        with st.popover(T("gap_detail_btn_settings", default="🔍 Xem chi tiết các slot gần nhất")):
            missing_str = format_missing_slots(trans_stats['missing_04'], st.session_state.utc_offset)
            st.code(missing_str, language="text")
    else:
        st.success(T("gap_none", default="✅ Dữ liệu đầy đủ, không phát hiện gap nào."))