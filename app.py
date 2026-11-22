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
        git_url = f"https://github.com/{REPO_NAME}.git"
        cmd = ["git"]
        if token:
            auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            cmd.extend(["-c", f"http.extraheader=AUTHORIZATION: basic {auth}"])
        cmd.extend(["ls-remote", git_url, f"refs/heads/{_DATA_BRANCH}"])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip(): return r.stdout.strip().split()[0]
    except Exception: pass
    return None

@st.cache_data(ttl=3600, show_spinner="⏳ Đang tải data mới...")
def _load_at_sha(sha):
    try:
        try: token = st.secrets.get("GITHUB_TOKEN")
        except Exception: token = os.getenv("GITHUB_TOKEN")
        git_url = f"https://github.com/{REPO_NAME}.git"
        target_dir = "/tmp/main_repo_data_v1220"
        if os.path.exists(target_dir): shutil.rmtree(target_dir, ignore_errors=True)
        cmd = ["git"]
        if token:
            auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            cmd.extend(["-c", f"http.extraheader=AUTHORIZATION: basic {auth}"])
        cmd.extend(["clone", "--depth", "1", "-b", _DATA_BRANCH, git_url, target_dir])
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

def _load_local_csv_v1220():
    files = list_default_files()
    if not files: return [], None, None, []
    rows, used_files = [], []
    for path in files:
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
                if n: used_files.append((path, n))
        except Exception: pass
    if not rows: return [], None, None, used_files
    seen = {(r[0], r[2], r[1]): r for r in rows}
    rows = list(seen.values())
    dts = [r[0] for r in rows]
    return rows, min(dts), max(dts), used_files

def load_default_csv():
    sha = _get_main_sha()
    if sha:
        result = _load_at_sha(sha)
        if result: return result
    return _load_local_csv_v1220()

# === LANG_BAR_PATCH_START ===
_detected_lang = detect_default_lang()
if "app_lang" not in st.session_state:
    st.session_state.app_lang = _detected_lang


def _set_lang(l_code):
    st.session_state.app_lang = l_code
    st.rerun()


st.markdown(
    """
    <style>
    .lang-bar-wrap div[data-testid="stButton"] > button {
        min-height: 48px !important;
        padding: 8px 16px !important;
        font-size: 15px !important;
        font-weight: 700 !important;
        border-radius: 10px !important;
        white-space: nowrap !important;
    }
    @media (max-width: 768px) {
        .lang-bar-wrap div[data-testid="stButton"] > button {
            min-height: 42px !important;
            padding: 6px 8px !important;
            font-size: 13.5px !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="lang-bar-wrap">', unsafe_allow_html=True)
col_vi, col_en, col_other = st.columns([1.35, 1.35, 3.3], vertical_alignment="bottom")

with col_vi:
    st.button(
        "🇻🇳 VI",
        on_click=_set_lang,
        args=("vi",),
        use_container_width=True,
        type="primary" if st.session_state.app_lang == "vi" else "secondary",
    )

with col_en:
    st.button(
        "🇺🇸 EN",
        on_click=_set_lang,
        args=("en",),
        use_container_width=True,
        type="primary" if st.session_state.app_lang == "en" else "secondary",
    )

with col_other:
    _other_langs = {k: v for k, v in LANG_OPTIONS.items() if v not in ("vi", "en")}
    if _other_langs:
        _options = ["🌐 Ngôn ngữ khác / Others"] + list(_other_langs.keys())
        _cur_other_key = next((k for k, v in _other_langs.items() if v == st.session_state.app_lang), None)
        _idx = _options.index(_cur_other_key) if _cur_other_key in _options else 0
        _sel = st.selectbox(
            "🌐 Ngôn ngữ / Language",
            _options,
            index=_idx,
            label_visibility="collapsed",
            key="lang_other_select",
        )
        if _sel != _options[0] and st.session_state.app_lang != _other_langs[_sel]:
            _set_lang(_other_langs[_sel])
st.markdown("</div>", unsafe_allow_html=True)

lang = st.session_state.app_lang
# === LANG_BAR_PATCH_END ===

# ==========================================

T = get_translator(lang)

# === PRED_SETTINGS_WITH_TZ_START ===
try:
    from zoneinfo import ZoneInfo
    system_tz_name = st.context.timezone or "Asia/Ho_Chi_Minh"
    vn_tz = ZoneInfo("Asia/Ho_Chi_Minh")
    sample = datetime(2025, 1, 1, 12, 0, tzinfo=vn_tz).astimezone(ZoneInfo(system_tz_name))
    system_offset = sample.utcoffset().total_seconds() / 3600
except Exception:
    system_tz_name, system_offset = "Asia/Ho_Chi_Minh", 7.0

if "utc_offset" not in st.session_state:
    st.session_state.utc_offset = system_offset

def reset_utc():
    st.session_state.utc_offset = system_offset

with st.expander(T("predict_settings_title", default="⚙️ Predict Settings"), expanded=False):
    if lang == "vi":
        st.caption(f"🌍 Hệ thống tự nhận diện: **{system_tz_name}** (UTC{system_offset:+.1f})")
    else:
        st.caption(f"🌍 System auto-detected: **{system_tz_name}** (UTC{system_offset:+.1f})")

    col_tz, col_tz_btn = st.columns([3, 1])
    with col_tz:
        utc_offset = st.slider(
            T("utc_offset_label", default="🌍 UTC Offset"),
            min_value=-12.0,
            max_value=14.0,
            step=0.5,
            key="utc_offset",
        )
    with col_tz_btn:
        st.write("")
        st.write("")
        st.button(T("utc_reset_btn", default="🔄 Reset"), on_click=reset_utc)

    _now_local = datetime.now(timezone.utc) + timedelta(hours=utc_offset)
    _now_str = _now_local.strftime('%Y-%m-%d %H:%M:%S')
    if lang == "vi":
        st.caption(f"🕐 **Giờ hiện tại (theo offset trên):** `{_now_str}` — UTC{utc_offset:+.1f}")
    else:
        st.caption(f"🕐 **Current time (per offset above):** `{_now_str}` — UTC{utc_offset:+.1f}")

    st.markdown("---")

    def calc_local_time(vn_hour, user_offset):
        local_hour = (vn_hour - 7) + user_offset
        day_shift = 0
        if local_hour < 0:
            local_hour += 24
            day_shift = -1
        elif local_hour >= 24:
            local_hour -= 24
            day_shift = 1
        hh, mm = int(local_hour), int((local_hour - int(local_hour)) * 60)
        time_str = f"{hh:02d}:{mm:02d}"
        if day_shift == -1:
            time_str += T("time_prev", default=" (Prev)")
        elif day_shift == 1:
            time_str += T("time_next", default=" (Next)")
        return time_str

    local_times = {k: calc_local_time(int(k), utc_offset) for k in ["04", "10", "16", "22"]}
    settings_text = T("predict_settings_md", default="")
    for k, v in local_times.items():
        settings_text = settings_text.replace(f"{{t_{k}}}", v)
    if settings_text:
        st.markdown(settings_text)
    st.warning(T("timezone_warning", default="⚠️ Times based on VN timezone"))
    st.warning(T("gap_disabled_warning", default="⚠️ **Lưu ý:** Các tính năng xử lý gap (Bridge, Patch 1, Auto-Heal) đã bị vô hiệu hoá vĩnh viễn trong code để đảm bảo dữ liệu không bị nhiễu."))
    _stats_for_settings = locals().get("trans_stats") or st.session_state.get("trans_stats", {})
    if _stats_for_settings.get("total_missing_04", 0) > 0:
        st.error(T("gap_stats", default="⚠️ **Thống kê Gap:** {n} slot bị thiếu dữ liệu.", n=_stats_for_settings["total_missing_04"]))
        with st.popover(T("gap_detail_btn_settings", default="🔍 Xem chi tiết các slot gần nhất")):
            missing_str = format_missing_slots(_stats_for_settings["missing_04"], st.session_state.utc_offset)
            st.code(missing_str, language="text")
    else:
        st.success(T("gap_none", default="✅ Dữ liệu đầy đủ, không phát hiện gap nào."))
# === PRED_SETTINGS_WITH_TZ_END ===


try:
    from zoneinfo import ZoneInfo
    system_tz_name = st.context.timezone or "Asia/Ho_Chi_Minh"
    vn_tz = ZoneInfo("Asia/Ho_Chi_Minh")
    sample = datetime(2025, 1, 1, 12, 0, tzinfo=vn_tz).astimezone(ZoneInfo(system_tz_name))
    system_offset = sample.utcoffset().total_seconds() / 3600
except Exception:
    system_tz_name, system_offset = "Asia/Ho_Chi_Minh", 7.0

if "utc_offset" not in st.session_state:
    st.session_state.utc_offset = system_offset

def reset_utc():
    st.session_state.utc_offset = system_offset

if lang == "vi": st.caption(f"🌍 Hệ thống tự nhận diện: **{system_tz_name}** (UTC{system_offset:+.1f})")
else: st.caption(f"🌍 System auto-detected: **{system_tz_name}** (UTC{system_offset:+.1f})")

col_tz, col_tz_btn = st.columns([3, 1])
with col_tz: 
    utc_offset = st.slider(T("utc_offset_label", default="🌍 UTC Offset"), min_value=-12.0, max_value=14.0, step=0.5, key="utc_offset")
with col_tz_btn: 
    st.write("")
    st.write("")
    st.button(T("utc_reset_btn", default="🔄 Reset"), on_click=reset_utc)

_now_local = datetime.now(timezone.utc) + timedelta(hours=utc_offset)
_now_str = _now_local.strftime('%Y-%m-%d %H:%M:%S')
if lang == "vi": st.caption(f"🕐 **Giờ hiện tại (theo offset trên):** `{_now_str}` — UTC{utc_offset:+.1f}")
else: st.caption(f"🕐 **Current time (per offset above):** `{_now_str}` — UTC{utc_offset:+.1f}")
# ==========================================


if predictor._WIDGET_TEMPLATE is None:
    st.error(T("err_widget_missing", default="⚠️ Không tìm thấy file `widget_template.html`."))
    st.stop()

_lang_errs = check_locales_errors()
if _lang_errs:
    st.error(T("err_lang_files", default="⚠️ Language files error:\n\n") + "\n\n".join(f"- {e}" for e in _lang_errs))
    st.stop()

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
    
    trans_lookback_input = predictor.TRANS_ADAPTIVE_LOOKBACK
    if SHOW_ADVANCED_UI:
        st.markdown(T("trans_scan_title", default="#### 🔍 Quét TRANS"))
        trans_lookback_input = st.number_input(
            T("trans_scan_slots", default="Số slot quét ngược"), min_value=40, max_value=5000,
            value=predictor.TRANS_ADAPTIVE_LOOKBACK, step=10, key="trans_lookback_input"
        )
        st.markdown("---")
        trans_text_ss = st.session_state.get('trans_text', '')
        if trans_text_ss:
            with st.expander("📊 TRANS động", expanded=False):
                stats = st.session_state.get('trans_stats', {})
                _s_acc = stats.get('static_acc', 0); _a_acc = stats.get('adaptive_acc', 0); _delta = _a_acc - _s_acc
                _d_icon = '🟢' if _delta > 0 else ('⚪' if _delta == 0 else '🔴')
                st.caption(f'Static: **{_s_acc:.1f}%** | Adaptive: **{_a_acc:.1f}%** | Delta: {_d_icon} {_delta:+.1f}%')
                _curr = predictor.get_adaptive_offset_state()
                _tog = st.toggle('🚀 Bật Adaptive Offset (override TRANS)', value=_curr, key='adaptive_offset_toggle')
                if _tog != _curr:
                    predictor.set_adaptive_offset_state(_tog)
                    st.success(T("adaptive_toggled", default="✅ Đã {status} adaptive offset", status="BẬT" if _tog else "TẮT"))
                    st.rerun()
                if stats.get('was_overridden', False): st.success(T('trans_overridden', default='🚀 Đã ghi đè TRANS tĩnh'))
                else: st.info(T('trans_using_static', default='✅ Đang dùng TRANS tĩnh'))
                st.caption(T('trans_scanned_caption', default="📥 Đã quét: **{used}** slot (yêu cầu: {req})", used=stats.get('lookback_used', 0), req=stats.get('lookback_requested', 0)))
                st.caption(T('trans_train_test', default="📊 Train: {train} | Test: {test}", train=stats.get('train_size', 0), test=stats.get('test_size', 0)))
                edited = st.text_area(T('trans_edit', default='Sửa nội dung:'), value=trans_text_ss, height=200, key='trans_editor_v5')
                st.markdown("**🎯 Auto-detected Offsets:**")
                _current_offsets = predictor.ADAPTIVE_CANDIDATE_OFFSETS
                if _current_offsets: st.code(", ".join(map(str, _current_offsets)), language="text")
                else: st.caption("Chưa có (bấm nút bên dưới để quét)")
                if st.button("🔍 Chạy thử (Verify Offsets mới)", key="btn_verify_offsets", use_container_width=True):
                    with st.spinner("Đang quét và tính toán..."):
                        _old_offsets = list(predictor.ADAPTIVE_CANDIDATE_OFFSETS) if predictor.ADAPTIVE_CANDIDATE_OFFSETS else []
                        _new_offsets, _old_acc, _new_acc = predictor._auto_detect_offsets()
                        st.session_state['offset_verify_result'] = {'old_offsets': _old_offsets, 'new_offsets': _new_offsets, 'old_acc': _old_acc, 'new_acc': _new_acc}
                    st.rerun()
                if 'offset_verify_result' in st.session_state:
                    res = st.session_state['offset_verify_result']
                    st.markdown("**📊 Kết quả kiểm tra:**")
                    st.write(f"- Bộ cũ: `Accuracy {res['old_acc']:.1f}%`")
                    st.write(f"- Bộ mới: `Accuracy {res['new_acc']:.1f}%`")
                    if res['new_acc'] >= res['old_acc']:
                        st.success(f"✅ Bộ mới tốt hơn/ngang bằng (+{res['new_acc']-res['old_acc']:.1f}%)")
                        if st.button("🚀 Áp dụng Bộ Mới", type="primary", key="btn_apply_new", use_container_width=True):
                            predictor.ADAPTIVE_CANDIDATE_OFFSETS = res['new_offsets']
                            predictor._build_context_offset_cache(); st.cache_data.clear(); del st.session_state['offset_verify_result']
                            st.success("Đã áp dụng Offsets mới thành công!"); st.rerun()
                    else:
                        st.error(f"❌ Bộ mới KÉM HƠN ({res['new_acc']-res['old_acc']:.1f}%)")
                        if st.button("⚠️ Vẫn áp dụng (Không khuyến khích)", key="btn_apply_force", use_container_width=True):
                            predictor.ADAPTIVE_CANDIDATE_OFFSETS = res['new_offsets']
                            predictor._build_context_offset_cache(); st.cache_data.clear(); del st.session_state['offset_verify_result']
                            st.warning("Đã áp dụng Offsets mới (dù kém hơn)."); st.rerun()
                    if st.button("🗑️ Bỏ qua / Hủy kết quả", key="btn_discard_verify", use_container_width=True):
                        del st.session_state['offset_verify_result']; st.rerun()

st.title(T("title", default="📍 Merchant Location"))
_default_files = list_default_files()

if _default_files:
    try:
        _d_rows, _d_min, _d_max, _used = load_default_csv()
        if _d_rows:
            total_mb = sum(os.path.getsize(f) for f in _default_files) / 1024 / 1024
            shown = ", ".join(f"`{f}` ({n:,})" for f, n in _used[:5]) + (f" … (+{len(_used)-5})" if len(_used) > 5 else "")
            info_text = T("info_header", default="📚 **Default baseline** ({n} file(s)):", n=len(_used)) + "\n\n" + f"- 📁 {shown}\n"
            info_text += T("info_from", default="- 🗓️ **From:** `{v}` (VN, UTC+7)", v=_d_min.strftime('%Y-%m-%d %H:%M')) + "\n"
            info_text += T("info_to", default="- 🗓️ **To:** `{v}` (VN, UTC+7)", v=_d_max.strftime('%Y-%m-%d %H:%M')) + "\n"
            info_text += T("info_total", default="- 📊 **Total:** `{n:,}` posts  ·  💾 `{mb:.1f} MB`", n=len(_d_rows), mb=total_mb) + "\n\n"
            st.info(info_text)
        else: st.warning(T("no_valid", default="⚠️ No valid rows"))
    except Exception as e: st.warning(T("read_error", default="⚠️ Read error: `{e}`", e=e))
else: st.caption(T("no_default", default="ℹ️ No baseline CSV"))

if "time_travel_slider" not in st.session_state: st.session_state.time_travel_slider = 0
def reset_time_travel(): st.session_state.time_travel_slider = 0

offset_days = st.slider(T("slider_label", default="🕰️ Time travel (days)"), min_value=-7, max_value=30, step=1, key="time_travel_slider")
st.button(T("reset_time_travel", default="🔄 Reset Time Travel"), on_click=reset_time_travel)

use_default = st.checkbox(T("use_default", default="📚 Use default baseline"), value=True)
st.markdown(T('csv_logic_cols_html', default="<div style=\"display:flex;flex-wrap:wrap;align-items:center;gap:6px;font-size:12.5px;line-height:1.55;color:#a8b0c4;margin:4px 0 8px 0;max-width:100%;overflow-wrap:anywhere;word-break:break-word;\"><span style=\"white-space:nowrap;\">📄 <b style=\"color:#e2e6f0;\">Cột logic CSV:</b></span> <span style=\"display:inline-flex;align-items:center;gap:4px;flex-wrap:wrap;min-width:0;overflow-wrap:anywhere;\"><code style=\"color:#ffd166;background:rgba(255,209,102,.15);padding:1px 6px;border-radius:4px;font-weight:600;white-space:nowrap;\">ID</code><span style=\"color:#c8ccd8;\">(Snowflake ID nếu có — không dùng tính chu kỳ/slot)</span></span> <span style=\"color:#6c7288;margin:0 2px;\">·</span> <span style=\"display:inline-flex;align-items:center;gap:4px;flex-wrap:wrap;min-width:0;overflow-wrap:anywhere;\"><code style=\"color:#7ab7ff;background:rgba(122,183,255,.16);padding:1px 6px;border-radius:4px;font-weight:600;white-space:nowrap;\">Timestamp</code><span style=\"color:#c8ccd8;\">(mốc thời gian quy đổi slot 6h)</span></span> <span style=\"color:#6c7288;margin:0 2px;\">·</span> <span style=\"display:inline-flex;align-items:center;gap:4px;flex-wrap:wrap;min-width:0;overflow-wrap:anywhere;\"><code style=\"color:#90ee90;background:rgba(144,238,144,.15);padding:1px 6px;border-radius:4px;font-weight:600;white-space:nowrap;\">Content</code><span style=\"color:#c8ccd8;\">(nội dung pattern/vật phẩm)</span></span></div>") if not str(locals().get('lang', '')).lower().startswith('en') else "<div style=\"display:flex;flex-wrap:wrap;align-items:center;gap:6px;font-size:12.5px;line-height:1.55;color:#a8b0c4;margin:4px 0 8px 0;max-width:100%;overflow-wrap:anywhere;word-break:break-word;\"><span style=\"white-space:nowrap;\">📄 <b style=\"color:#e2e6f0;\">Logic CSV columns:</b></span> <span style=\"display:inline-flex;align-items:center;gap:4px;flex-wrap:wrap;min-width:0;overflow-wrap:anywhere;\"><code style=\"color:#ffd166;background:rgba(255,209,102,.15);padding:1px 6px;border-radius:4px;font-weight:600;white-space:nowrap;\">ID</code><span style=\"color:#c8ccd8;\">(Snowflake ID if present — not used for cycle/slot)</span></span> <span style=\"color:#6c7288;margin:0 2px;\">·</span> <span style=\"display:inline-flex;align-items:center;gap:4px;flex-wrap:wrap;min-width:0;overflow-wrap:anywhere;\"><code style=\"color:#7ab7ff;background:rgba(122,183,255,.16);padding:1px 6px;border-radius:4px;font-weight:600;white-space:nowrap;\">Timestamp</code><span style=\"color:#c8ccd8;\">(timestamp mapped to 6h slot)</span></span> <span style=\"color:#6c7288;margin:0 2px;\">·</span> <span style=\"display:inline-flex;align-items:center;gap:4px;flex-wrap:wrap;min-width:0;overflow-wrap:anywhere;\"><code style=\"color:#90ee90;background:rgba(144,238,144,.15);padding:1px 6px;border-radius:4px;font-weight:600;white-space:nowrap;\">Content</code><span style=\"color:#c8ccd8;\">(pattern/item content)</span></span></div>", unsafe_allow_html=True)
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