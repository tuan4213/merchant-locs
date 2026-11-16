import streamlit as st
import streamlit.components.v1 as components
import csv, os, glob, subprocess, shutil, base64
from datetime import datetime, timedelta, timezone
from pathlib import Path

from i18n import (LANG_LABELS as LANG_OPTIONS, get_translator,
                  check_locales_errors, detect_default_lang)
import predictor

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

st.markdown("""
<style>
div[data-testid="stCode"] pre, div[data-testid="stCode"] code, .stCode pre, .stCode code {
    white-space: pre-wrap !important;
    word-wrap: break-word !important;
    overflow-wrap: break-word !important;
}
</style>
""", unsafe_allow_html=True)

REPO_NAME = predictor.REPO_NAME

def format_missing_slots(missing_data, utc_off):
    res = []
    for m in missing_data:
        try:
            dt = datetime.strptime(m['iso'].split('+')[0], '%Y-%m-%dT%H:%M:%S')
            dt_local = dt - timedelta(hours=7) + timedelta(hours=utc_off)
            res.append((m['slot'], f"{m['slot']} ({dt_local.strftime('%Y/%m/%d %H:%M')})"))
        except: res.append((m['slot'], str(m['slot'])))
    res.sort(key=lambda x: x[0])
    return "\n".join(r[1] for r in res)

def list_default_files():
    found = set()
    for pat in ["*.csv", "data/*.csv", "csv/*.csv", "data/**/*.csv", "csv/**/*.csv"]:
        for f in glob.glob(pat, recursive=True):
            if os.path.isfile(f) and os.path.getsize(f) > 0: found.add(f.replace('\\', '/').lstrip('./'))
    sf = sorted(found)
    if 'data.csv' in sf: sf.remove('data.csv'); sf.append('data.csv')
    return sf

_DATA_BRANCH = "main"

@st.cache_data(ttl=60, show_spinner=False)
def _get_main_sha():
    try:
        try: token = st.secrets.get("GITHUB_TOKEN")
        except Exception: token = os.getenv("GITHUB_TOKEN")
        url = (f"https://{token}@github.com/{REPO_NAME}.git" if token else f"https://github.com/{REPO_NAME}.git")
        r = subprocess.run(["git", "ls-remote", url, f"refs/heads/{_DATA_BRANCH}"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip(): return r.stdout.strip().split()[0]
    except Exception: pass
    return None

@st.cache_data(ttl=3600, show_spinner="⏳ Đang tải data mới...")
def _load_at_sha(sha):
    try:
        try: token = st.secrets.get("GITHUB_TOKEN")
        except Exception: token = os.getenv("GITHUB_TOKEN")
        repo_url = (f"https://{token}@github.com/{REPO_NAME}.git" if token else f"https://github.com/{REPO_NAME}.git")
        
        target_dir = "/tmp/main_repo_data_v1220"
        if os.path.exists(target_dir): shutil.rmtree(target_dir, ignore_errors=True)
        
        cmd = ["git"]
        if token:
            auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            cmd.extend(["-c", f"http.extraheader=AUTHORIZATION: basic {auth}"])
        cmd.extend(["clone", "--depth", "1", "-b", _DATA_BRANCH, repo_url, target_dir])
        
        r = subprocess.run(cmd, capture_output=True, timeout=30)
        if r.returncode != 0: return None
        
        csv_files = glob.glob(f"{target_dir}/**/*.csv", recursive=True)
        csv_files.sort(key=lambda x: x.endswith('data.csv'))
        rows, used_files = [], []
        for path in csv_files:
            try:
                with open(path, "r", encoding="utf-8-sig") as fh:
                    reader = csv.DictReader(fh)
                    if not reader.fieldnames: continue
                    cols = {c.strip().lower(): c for c in reader.fieldnames}
                    col_ts = cols.get("timestamp"); col_ct = cols.get("content"); col_us = cols.get("username")
                    if not col_ts: continue
                    n = 0
                    for row in reader:
                        dt = predictor.parse_ts(row.get(col_ts, ""))
                        if dt is None: continue
                        rows.append((dt, row.get(col_ct, "") if col_ct else "", row.get(col_us, "?") if col_us else "?"))
                        n += 1
                    if n: used_files.append((os.path.basename(path), n))
            except Exception: pass
        
        if not rows: return None
        
        seen = {(r[0], r[2], r[1]): r for r in rows}
        rows = list(seen.values())
        dts = [r[0] for r in rows]
        return rows, min(dts), max(dts), used_files
    except Exception as e: return None

def load_default_csv():
    sha = _get_main_sha()
    if sha:
        result = _load_at_sha(sha)
        if result: return result
    return [], None, None, []

_detected_lang = detect_default_lang()
if "app_lang" not in st.session_state: st.session_state.app_lang = _detected_lang

def _set_lang(l_code):
    st.session_state.app_lang = l_code; st.rerun()

col_vi, col_en, col_other, _ = st.columns([1.2, 1.2, 2.5, 5])
with col_vi:
    st.button("🇻🇳 Tiếng Việt", on_click=_set_lang, args=("vi",), use_container_width=True, type="primary" if st.session_state.app_lang == "vi" else "secondary")
with col_en:
    st.button("🇺🇸 English", on_click=_set_lang, args=("en",), use_container_width=True, type="primary" if st.session_state.app_lang == "en" else "secondary")

lang = st.session_state.app_lang
T = get_translator(lang)

try: predictor.set_secrets(dict(st.secrets))
except Exception: pass

with st.sidebar:
    st.markdown(T("sidebar_config", default="### ⚙️ Config"))
    if st.button(T("sidebar_reload", default="🔄 Reload config files"), use_container_width=True, key="btn_reload_sidebar"):
        st.cache_data.clear(); st.rerun()
    st.caption(T("sidebar_hint", default="Sửa config files → bấm Reload"))
    
    _current_sha = _get_main_sha()
    if _current_sha: st.caption(f"🟢 GitHub: `{_current_sha[:7]}`")
    else: st.caption("🔴 GitHub: Offline")

st.title(T("title", default="📍 Merchant Location"))
_default_files = list_default_files()

if _default_files:
    try:
        _d_rows, _d_min, _d_max, _used = load_default_csv()
        if _d_rows:
            info_text = T("info_header", default="📚 **Default baseline** ({n} file(s)):", n=len(_used)) + "\n\n"
            info_text += T("info_total", default="- 📊 **Total:** `{n:,}` posts", n=len(_d_rows)) + "\n\n"
            st.info(info_text)
    except Exception as e: st.warning(T("read_error", default="⚠️ Read error: `{e}`", e=e))

if "utc_offset" not in st.session_state: st.session_state.utc_offset = 7.0
if "time_travel_slider" not in st.session_state: st.session_state.time_travel_slider = 0
def reset_time_travel(): st.session_state.time_travel_slider = 0

offset_days = st.slider(T("slider_label", default="🕰️ Time travel (days)"), min_value=-7, max_value=30, step=1, key="time_travel_slider")
st.button(T("reset_time_travel", default="🔄 Reset Time Travel"), on_click=reset_time_travel)

use_default = st.checkbox(T("use_default", default="📚 Use default baseline"), value=True)
uploaded = st.file_uploader(T("uploader", default="Upload CSV"), type=["csv"], accept_multiple_files=True)
_has_something = uploaded or (use_default and bool(_default_files))

if _has_something:
    files_data = tuple((f.name, f.getvalue()) for f in (uploaded or []))
    _loaded = load_default_csv()
    default_rows = tuple(_loaded[0]) if use_default else tuple()
    used_files = tuple(_loaded[3]) if use_default else tuple()

    @st.cache_data(show_spinner=False)
    def _cached(files_tuple, default_rows_tuple, used_files_tuple, offset, use_def, lang_code, utc_off, trans_lookback, adaptive_state):
        return predictor.run_pipeline(list(files_tuple), list(default_rows_tuple), list(used_files_tuple), offset, use_def, lang_code, utc_off, trans_lookback)

    widget_html, log_text, trans_text, trans_stats = _cached(
        files_data, default_rows, used_files, offset_days, use_default, lang, st.session_state.utc_offset, predictor.TRANS_ADAPTIVE_LOOKBACK, predictor.get_adaptive_offset_state())

    if widget_html is None:
        st.error(T("failed", default="❌ Pipeline failed")); st.code(log_text, language="text")
    else:
        st.success(T("success", default="✅ Processed successfully!"))
        if trans_stats.get('total_missing_04', 0) > 0:
            st.warning(T("gap_warning", default="⚠️ **Cảnh báo Gap:** Phát hiện **{n}** slot bị thiếu dữ liệu.", n=trans_stats['total_missing_04']))
        components.html(widget_html, height=1100, scrolling=True)
        with st.expander(T("expander", default="📋 Log"), expanded=False):
            st.download_button(T("log_download", default="💾 Tải log"), log_text, file_name=f"pipeline_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt", key="dl_log_btn")
            st.code(log_text, language="text")
else:
    st.info(T("upload_hint", default="👆 Upload CSV to start"))
