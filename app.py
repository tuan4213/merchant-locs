import streamlit as st
import time
import json
import hashlib

# --- ✨ Accent UI: Pill Time, Shift Badges, Rule Tags & Time Machine Banner ---
st.markdown(
    """
    <style>
    *, *::before, *::after {
        box-sizing: border-box;
    }
    .stMarkdown, .stMarkdown p, .stMarkdown div, .stMarkdown li, .stMarkdown span,
    .stSelectbox, .stSelectbox label, .stSelectbox div[data-baseweb="select"],
    .stSelectbox div[data-baseweb="select"] span,
    div[data-baseweb="popover"] li, div[data-baseweb="menu"] div,
    .mc-accent-wrap, .mc-accent-wrap * {
        white-space: normal !important;
        word-break: normal !important;
        overflow-wrap: break-word !important;
        max-width: 100% !important;
    }
    .mc-tz-header {
        margin: 8px 0 8px 0;
        padding: 8px 10px;
        border-radius: 8px;
        background: linear-gradient(90deg, rgba(56, 189, 248, 0.12), rgba(148, 163, 184, 0.04));
        border-left: 3px solid #38bdf8;
        font-size: 12.5px;
        line-height: 1.48;
        color: #e2e8f0;
    }
    .mc-table-frame {
        width: 100%;
        overflow-x: auto;
        border-radius: 10px;
        border: 1px solid rgba(148, 163, 184, 0.34);
        margin-bottom: 10px;
        background: rgba(15, 23, 42, 0.22);
    }
    table.mc-grid-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 12px;
        line-height: 1.45;
    }
    table.mc-grid-table th,
    table.mc-grid-table td {
        border: 1px solid rgba(148, 163, 184, 0.26);
        padding: 7px 8px;
        text-align: left;
        vertical-align: top;
    }
    table.mc-grid-table th {
        background: rgba(30, 41, 59, 0.72);
        color: #f8fafc;
        font-weight: 700;
        letter-spacing: 0.01em;
    }
    table.mc-grid-table tr.mc-row-anchor td {
        background: rgba(56, 189, 248, 0.05);
    }
    .mc-m-name {
        font-weight: 700;
        color: #f8fafc;
        display: block;
    }
    .mc-vn-time {
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 11.5px;
        color: #cbd5e1;
        background: rgba(148, 163, 184, 0.14);
        padding: 2px 6px;
        border-radius: 6px;
        display: inline-block;
    }
    .mc-target-pill {
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 12px;
        font-weight: 700;
        color: #7dd3fc;
        background: rgba(14, 165, 233, 0.16);
        border: 1px solid rgba(56, 189, 248, 0.35);
        padding: 2px 7px;
        border-radius: 6px;
        display: inline-block;
    }
    .mc-badge {
        display: inline-block;
        margin-top: 4px;
        padding: 1px 7px;
        border-radius: 999px;
        font-size: 10.5px;
        font-weight: 700;
    }
    .mc-badge-prev {
        background: rgba(251, 146, 60, 0.16);
        color: #fdba74;
        border: 1px solid rgba(251, 146, 60, 0.35);
    }
    .mc-badge-next {
        background: rgba(167, 139, 250, 0.16);
        color: #c4b5fd;
        border: 1px solid rgba(167, 139, 250, 0.35);
    }
    .mc-badge-same {
        background: rgba(52, 211, 153, 0.14);
        color: #6ee7b7;
        border: 1px solid rgba(52, 211, 153, 0.32);
    }
    .mc-rule-chip {
        display: inline-block;
        font-size: 10.5px;
        font-weight: 700;
        padding: 1px 6px;
        border-radius: 5px;
        margin-right: 4px;
        margin-bottom: 3px;
        background: rgba(250, 204, 21, 0.14);
        color: #fde047;
        border: 1px solid rgba(250, 204, 21, 0.28);
    }
    .mc-tm-banner {
        margin: 8px 0 10px 0;
        padding: 9px 11px;
        border-radius: 10px;
        background: linear-gradient(120deg, rgba(168, 85, 247, 0.12), rgba(56, 189, 248, 0.08));
        border: 1px solid rgba(192, 132, 252, 0.28);
        border-left: 3px solid #c084fc;
        font-size: 12.5px;
        line-height: 1.5;
        color: #f1f5f9;
    }
    .mc-tm-tag {
        display: inline-block;
        font-size: 10.5px;
        font-weight: 700;
        padding: 1px 7px;
        border-radius: 999px;
        margin-bottom: 4px;
        background: rgba(192, 132, 252, 0.18);
        color: #e9d5ff;
        border: 1px solid rgba(192, 132, 252, 0.35);
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _fmt_utc_offset(utc_offset) -> str:
    val = float(utc_offset)
    sign = "+" if val >= 0 else "-"
    abs_val = abs(val)
    if abs_val.is_integer():
        return f"{sign}{int(abs_val)}"
    return f"{sign}{abs_val:g}"


def _t_locale(key: str, vi_default: str, en_default: str) -> str:
    cur_lang = str(
        st.session_state.get("app_lang")
        or st.session_state.get("lang")
        or globals().get("lang")
        or "vi"
    ).strip().lower()
    is_vi = cur_lang == "vi" or cur_lang.startswith("vi")
    fallback = vi_default if is_vi else en_default
    try:
        tr_fn = globals().get("T")
        if callable(tr_fn):
            val = tr_fn(key, default=fallback)
        else:
            from i18n import get_translator
            val = get_translator(cur_lang or "vi")(key, default=fallback)
        if not isinstance(val, str) or not val.strip():
            return fallback
        if is_vi and val.strip() == en_default.strip() and vi_default != en_default:
            return vi_default
        if (not is_vi) and cur_lang != "en" and val.strip() == vi_default.strip() and vi_default != en_default:
            return en_default
        return val
    except Exception:
        return fallback


def _render_tz_milestone_table(utc_offset):
    from datetime import datetime, timezone, timedelta
    off_val = float(utc_offset)
    tz_str = _fmt_utc_offset(off_val)
    tz_cur = timezone(timedelta(hours=off_val))
    tz_vn = timezone(timedelta(hours=7))
    is_vi = str(st.session_state.get("app_lang") or "vi").lower().startswith("vi")

    day_prev = _t_locale("tz_day_prev", "Hôm trước", "Prev day")
    day_same = _t_locale("tz_day_same", "Cùng ngày", "Same day")
    day_next = _t_locale("tz_day_next", "Hôm sau", "Next day")

    m_first = _t_locale("tz_m_first", "First Merchant", "First Merchant")
    m_second = _t_locale("tz_m_second", "Merchant 2", "Merchant 2")
    m_third = _t_locale("tz_m_third", "Merchant 3", "Merchant 3")
    m_last = _t_locale("tz_m_last", "Last Merchant", "Last Merchant")

    r_first = _t_locale(
        "tz_rule_first",
        "Mốc gốc 04:00 VN: dò chuỗi pha A1–A4/B3/C7 & cụm lệch k*119 + p*j (j ∈ ±6, ±12) / k*119 + jitter theo k, p; ghép MarkovB2 & TRANS, thiếu thì bù tiến +4.",
        "04:00 VN base: reads A1–A4/B3/C7 chains & k*119 + p*j clusters (j ∈ ±6, ±12) / k*119 + jitter across k, p; pairs MarkovB2 & TRANS, forward-filling +4 if missing.",
    )
    r_mid = _t_locale(
        "tz_rule_mid",
        "Mặc định nhịp 119 (k*119 + jitter); khi lệch gap 16 / 116 / 132 hoặc chu kỳ 1072 (mẫu 14 bước) sẽ xét k*116 + p*16 theo k, p để chuyển sang pha A (A4 / A3).",
        "Defaults to 119 (k*119 + jitter); on gaps 16 / 116 / 132 or cycle 1072 (14-step pattern), uses k*116 + p*16 across k, p to pick Phase A (A4 / A3).",
    )
    r_last = _t_locale(
        "tz_rule_last",
        "Chốt ca theo nhịp 119 (k*119 + jitter); khi lệch gap 16 / 116 / 132 hoặc chu kỳ 1072 (dùng k*116 + p*16 theo k, p) sẽ ưu tiên pha điều chỉnh A2 / C7.",
        "Wraps along 119 (k*119 + jitter); when gaps 16 / 116 / 132 or cycle 1072 hit (k*116 + p*16 across k, p), favors adjusted phase A2 / C7.",
    )
    merchants = [
        (m_first, 4, 0, ["04:00 Base", "Phase A1–A4/B3/C7", "k, p · MarkovB2"], r_first, True),
        (m_second, 10, 0, ["Cycle 119", "Gap 16/116/132", "Macro 1072 → A4"], r_mid, False),
        (m_third, 16, 0, ["Cycle 119", "Gap 16/116/132", "Macro 1072 → A3"], r_mid, False),
        (m_last, 22, 0, ["Cycle 119", "Gap 16/116/132", "Macro 1072 → A2"], r_last, True),
    ]

    rows_html = []
    for m_label, vn_h, vn_m, chips, rule_desc, is_anchor in merchants:
        dt_vn = datetime(2026, 5, 10, vn_h, vn_m, tzinfo=tz_vn)
        dt_cur = dt_vn.astimezone(tz_cur)
        day_delta = (dt_cur.date() - dt_vn.date()).days
        if day_delta < 0:
            day_badge = day_prev
            badge_cls = "mc-badge mc-badge-prev"
        elif day_delta > 0:
            day_badge = day_next
            badge_cls = "mc-badge mc-badge-next"
        else:
            day_badge = day_same
            badge_cls = "mc-badge mc-badge-same"

        chips_html = "".join(f"<span class='mc-rule-chip'>{c}</span>" for c in chips)
        row_cls = " class='mc-row-anchor'" if is_anchor else ""
        rows_html.append(
            f"<tr{row_cls}>"
            f"<td><span class='mc-m-name'>{m_label}</span></td>"
            f"<td><span class='mc-vn-time'>{dt_vn.strftime('%H:%M')}</span></td>"
            f"<td><span class='mc-target-pill'>{dt_cur.strftime('%H:%M')}</span><br><span class='{badge_cls}'>{day_badge}</span></td>"
            f"<td><div>{chips_html}</div><div>{rule_desc}</div></td>"
            f"</tr>"
        )

    guide_txt = _t_locale(
        "tz_milestone_guide",
        "Mốc giờ & quy đổi (UTC{tz_str}): Thanh trượt chỉnh múi giờ hiển thị; đổi UTC có thể đẩy mốc sang ngày hôm trước hoặc ngày hôm sau.",
        "Timezone & conversion (UTC{tz_str}): Slider adjusts display timezone; shifting UTC may move a merchant into the previous or next day.",
    ).format(tz_str=tz_str)
    col_m = _t_locale("tz_col_merchant", "Merchant", "Merchant")
    col_vn = _t_locale("tz_col_vn", "VN (UTC+7)", "VN (UTC+7)")
    col_target = _t_locale("tz_col_target", "UTC{tz_str} & Lệch ngày", "UTC{tz_str} & Shift").format(tz_str=tz_str)
    col_rule = _t_locale("tz_col_rule", "Tóm tắt quy tắc đoán", "Prediction Rule Summary")
    hdr_badge = "🧭 Mốc & Lệch ngày" if is_vi else "🧭 Milestones & Shift"

    html = (
        f"<div class='mc-accent-wrap'>"
        f"<div class='mc-tz-header'><span class='mc-tm-tag'>{hdr_badge}</span><br>{guide_txt}</div>"
        f"<div class='mc-table-frame'>"
        f"<table class='mc-grid-table'>"
        f"<colgroup>"
        f"<col style='width: 20%;'>"
        f"<col style='width: 14%;'>"
        f"<col style='width: 22%;'>"
        f"<col style='width: 44%;'>"
        f"</colgroup>"
        f"<thead><tr><th>{col_m}</th><th>{col_vn}</th><th>{col_target}</th><th>{col_rule}</th></tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        f"</table>"
        f"</div>"
        f"</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def _render_time_machine_guide():
    is_vi = str(st.session_state.get("app_lang") or "vi").lower().startswith("vi")
    chip_lbl = "🕰️ Time Machine · Chỉ xem" if is_vi else "🕰️ Time Machine · View-Only"
    tm_txt = _t_locale(
        "time_machine_guide",
        "Lùi hoặc tiến số ngày trên thanh trượt để xem dữ liệu/dự đoán ở quá khứ hoặc tương lai, đối chiếu lịch sử và mô phỏng kịch bản. Chỉ đổi góc nhìn hiển thị, không sửa dữ liệu gốc.",
        "Shift days backward or forward on the slider to inspect past or future data/predictions, compare history, and simulate scenarios. View-only; source data is untouched.",
    )
    html = (
        f"<div class='mc-accent-wrap mc-tm-banner'>"
        f"<span class='mc-tm-tag'>{chip_lbl}</span><br>{tm_txt}"
        f"</div>"
    )
    st.markdown(html, unsafe_allow_html=True)

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
_SYNC_WATCH_LOCK = _threading.Lock()
_AUTO_APPLY_TIMEOUT_SEC = 30.0

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

def _get_local_runtime_commit() -> str:
    for env_key in ("GIT_COMMIT_SHA", "STREAMLIT_GIT_COMMIT", "COMMIT_SHA", "GITHUB_SHA"):
        val = (os.getenv(env_key) or "").strip()
        if val:
            return val[:12]
    try:
        r = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return "unknown"


@st.cache_resource(show_spinner=False)
def _get_sync_watch_store():
    return {
        "active_sig": None,
        "last_files": {},
        "pending_sig": None,
        "detected_at": None,
        "changed_parts": [],
    }


def _compute_local_watch_sig():
    parts_hash = {}
    watch_files = ["predictor.py", "widget_template.html"] + list_default_files()
    for rel in sorted(set(watch_files)):
        p = Path(rel)
        if p.exists() and p.is_file():
            parts_hash[rel] = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
    return parts_hash


def _build_three_parts_sig(parts_hash: dict) -> str:
    grouped = {
        "data": {k: v for k, v in sorted(parts_hash.items()) if k.endswith(".csv")},
        "widget_template.html": parts_hash.get("widget_template.html"),
        "predictor.py": parts_hash.get("predictor.py"),
    }
    return hashlib.sha256(json.dumps(grouped, sort_keys=True).encode("utf-8")).hexdigest()


def _evaluate_watch_changes():
    store = _get_sync_watch_store()
    local_map = _compute_local_watch_sig()
    sig_str = _build_three_parts_sig(local_map)

    with _SYNC_WATCH_LOCK:
        if store["active_sig"] is None:
            store["active_sig"] = sig_str
            store["last_files"] = local_map
            store["pending_sig"] = None
            store["detected_at"] = None
            store["changed_parts"] = []
            return sig_str, False, []

        if sig_str == store["active_sig"]:
            store["pending_sig"] = None
            store["detected_at"] = None
            store["changed_parts"] = []
            return sig_str, False, []

        prev_files = store.get("last_files") or {}
        changed = []
        if {k: v for k, v in prev_files.items() if k.endswith(".csv")} != {k: v for k, v in local_map.items() if k.endswith(".csv")}:
            changed.append("data")
        if prev_files.get("widget_template.html") != local_map.get("widget_template.html"):
            changed.append("widget html")
        if prev_files.get("predictor.py") != local_map.get("predictor.py"):
            changed.append("predictor")

        if not changed:
            store["active_sig"] = sig_str
            store["last_files"] = local_map
            return sig_str, False, []

        if store["pending_sig"] != sig_str:
            store["pending_sig"] = sig_str
            store["detected_at"] = time.time()
            store["changed_parts"] = changed

        return sig_str, True, list(store["changed_parts"])


def _apply_sync_update():
    store = _get_sync_watch_store()
    st.cache_data.clear()
    local_map = _compute_local_watch_sig()
    sig_str = _build_three_parts_sig(local_map)
    with _SYNC_WATCH_LOCK:
        store["active_sig"] = sig_str
        store["last_files"] = local_map
        store["pending_sig"] = None
        store["detected_at"] = None
        store["changed_parts"] = []
    st.session_state.pop("user_postponed_sig", None)
    st.rerun()


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
def _is_vn_timezone():
    try:
        from zoneinfo import ZoneInfo
        tz_name = (getattr(st.context, "timezone", None) or "").strip()
        if tz_name.lower() in ("asia/ho_chi_minh", "asia/saigon", "vietnam", "etc/gmt-7"):
            return True
        if tz_name:
            off = datetime.now(ZoneInfo(tz_name)).utcoffset()
            if off is not None and off.total_seconds() == 7 * 3600:
                return True
    except Exception:
        pass
    try:
        loc_off = datetime.now().astimezone().utcoffset()
        if loc_off is not None and loc_off.total_seconds() == 7 * 3600:
            return True
    except Exception:
        pass
    return False

if "app_lang" not in st.session_state:
    st.session_state.app_lang = "vi" if _is_vn_timezone() else detect_default_lang()

def _set_lang(l_code):
    st.session_state.app_lang = l_code
    if l_code in ("vi", "en") and "lang_other_select" in st.session_state:
        st.session_state.lang_other_select = None

def _on_other_lang_change():
    sel = st.session_state.get("lang_other_select")
    if sel and sel in LANG_OPTIONS:
        st.session_state.app_lang = LANG_OPTIONS[sel]

_other_placeholder = get_translator(st.session_state.app_lang)("other_languages_placeholder", default="🌐 Ngôn ngữ khác" if st.session_state.app_lang == "vi" else "🌐 Other languages")

st.markdown(
    """
    <style>
    .lang-bar-wrap div[data-testid="stButton"] > button {
        min-height: 48px !important;
        height: auto !important;
        padding: 8px 14px !important;
        font-size: 14.5px !important;
        font-weight: 700 !important;
        border-radius: 10px !important;
        white-space: normal !important;
        word-break: break-word !important;
        overflow-wrap: break-word !important;
        line-height: 1.3 !important;
    }
    .lang-bar-wrap div[data-testid="stSelectbox"],
    .lang-bar-wrap div[data-testid="stSelectbox"] > div,
    .lang-bar-wrap div[data-baseweb="select"],
    .lang-bar-wrap div[data-baseweb="select"] > div,
    .lang-bar-wrap div[data-baseweb="select"] > div > div {
        height: auto !important;
        min-height: 48px !important;
        max-height: none !important;
        max-width: 100% !important;
        min-width: 0 !important;
        flex: 1 1 auto !important;
        flex-wrap: wrap !important;
        align-items: center !important;
        overflow: visible !important;
    }
    .lang-bar-wrap div[data-baseweb="select"] > div > div {
        padding-top: 6px !important;
        padding-bottom: 6px !important;
    }
    .lang-bar-wrap div[data-testid="stSelectbox"] * {
        white-space: normal !important;
        word-break: break-word !important;
        overflow-wrap: anywhere !important;
        text-overflow: clip !important;
        line-height: 1.35 !important;
        max-width: 100% !important;
        min-width: 0 !important;
    }
    .lang-bar-wrap div[data-baseweb="select"] input {
        width: auto !important;
        flex: 1 1 80px !important;
    }
    @media (max-width: 768px) {
        .lang-bar-wrap div[data-testid="stButton"] > button {
            min-height: 42px !important;
            padding: 6px 8px !important;
            font-size: 13px !important;
        }
        .lang-bar-wrap div[data-testid="stSelectbox"],
        .lang-bar-wrap div[data-testid="stSelectbox"] > div,
        .lang-bar-wrap div[data-baseweb="select"],
        .lang-bar-wrap div[data-baseweb="select"] > div,
        .lang-bar-wrap div[data-baseweb="select"] > div > div {
            min-height: 42px !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="lang-bar-wrap">', unsafe_allow_html=True)
col_vi, col_en, col_other = st.columns([1.45, 1.45, 3.1], vertical_alignment="bottom")

with col_vi:
    st.button(
        "🇻🇳 Tiếng Việt",
        on_click=_set_lang,
        args=("vi",),
        use_container_width=True,
        type="primary" if st.session_state.app_lang == "vi" else "secondary",
    )

with col_en:
    st.button(
        "🇺🇸 English",
        on_click=_set_lang,
        args=("en",),
        use_container_width=True,
        type="primary" if st.session_state.app_lang == "en" else "secondary",
    )

with col_other:
    _other_langs = {k: v for k, v in LANG_OPTIONS.items() if v not in ("vi", "en")}
    if _other_langs:
        _other_keys = list(_other_langs.keys())
        _cur_other_key = next((k for k, v in _other_langs.items() if v == st.session_state.app_lang), None)
        if _cur_other_key is None and st.session_state.get("lang_other_select") is not None:
            st.session_state.lang_other_select = None
        st.selectbox(
            _other_placeholder,
            _other_keys,
            index=_other_keys.index(_cur_other_key) if _cur_other_key in _other_keys else None,
            placeholder=_other_placeholder,
            label_visibility="collapsed",
            key="lang_other_select",
            on_change=_on_other_lang_change,
        )
st.markdown("</div>", unsafe_allow_html=True)

lang = st.session_state.app_lang
# === LANG_BAR_PATCH_END ===

# ==========================================

T = get_translator(lang)

if "user_adaptive_enabled" not in st.session_state:
    try:
        st.session_state["user_adaptive_enabled"] = bool(predictor.get_adaptive_offset_state())
    except Exception:
        st.session_state["user_adaptive_enabled"] = False

if "user_candidate_offsets" not in st.session_state:
    try:
        cur_off = getattr(predictor, "ADAPTIVE_CANDIDATE_OFFSETS", None)
        st.session_state["user_candidate_offsets"] = tuple(cur_off) if cur_off else tuple()
    except Exception:
        st.session_state["user_candidate_offsets"] = tuple()


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

if "time_travel_slider" not in st.session_state:
    st.session_state.time_travel_slider = 0

def reset_time_travel():
    st.session_state.time_travel_slider = 0

if predictor._WIDGET_TEMPLATE is None:
    st.error(T("err_widget_missing", default="⚠️ Không tìm thấy file `widget_template.html`."))
    st.stop()

_lang_errs = check_locales_errors()
if _lang_errs:
    st.error(T("err_lang_files", default="⚠️ Language files error:\n\n") + "\n\n".join(f"- {e}" for e in _lang_errs))
    st.stop()

try:
    predictor.set_secrets(dict(st.secrets))
except Exception:
    pass

_default_files = list_default_files()
_loaded_default = None
if _default_files:
    try:
        _loaded_default = load_default_csv()
    except Exception as e:
        st.warning(T("read_error", default="⚠️ Read error: `{e}`", e=e))

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
        st.button(T("utc_reset_btn", default="🔄 Reset"), on_click=reset_utc)
        _render_tz_milestone_table(utc_offset)
    with col_tz_btn:
        st.write("")
        st.write("")

    _now_local = datetime.now(timezone.utc) + timedelta(hours=utc_offset)
    _now_str = _now_local.strftime('%Y-%m-%d %H:%M:%S')
    if lang == "vi":
        st.caption(f"🕐 **Giờ hiện tại (theo offset trên):** `{_now_str}` — UTC{utc_offset:+.1f}")
    else:
        st.caption(f"🕐 **Current time (per offset above):** `{_now_str}` — UTC{utc_offset:+.1f}")

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

    st.markdown("---")
    offset_days = st.slider(
        T("slider_label", default="🕰️ Time travel (days)"),
        min_value=-7,
        max_value=30,
        step=1,
        key="time_travel_slider",
    )
    _render_time_machine_guide()
    st.button(T("reset_time_travel", default="🔄 Reset Time Travel"), on_click=reset_time_travel)

    st.markdown("---")
    use_default = st.checkbox(T("use_default", default="📚 Use default baseline"), value=True)
    st.markdown(
        T(
            'csv_logic_cols_html',
            default="<div style=\"display:flex;flex-wrap:wrap;align-items:center;gap:6px;font-size:12.5px;line-height:1.55;color:#a8b0c4;margin:4px 0 8px 0;max-width:100%;overflow-wrap:anywhere;word-break:break-word;\"><span style=\"white-space:nowrap;\">📄 <b style=\"color:#e2e6f0;\">Cột logic CSV:</b></span> <span style=\"display:inline-flex;align-items:center;gap:4px;flex-wrap:wrap;min-width:0;overflow-wrap:anywhere;\"><code style=\"color:#ffd166;background:rgba(255,209,102,.15);padding:1px 6px;border-radius:4px;font-weight:600;white-space:nowrap;\">ID</code><span style=\"color:#c8ccd8;\">(Snowflake ID nếu có — không dùng tính chu kỳ/slot)</span></span> <span style=\"color:#6c7288;margin:0 2px;\">·</span> <span style=\"display:inline-flex;align-items:center;gap:4px;flex-wrap:wrap;min-width:0;overflow-wrap:anywhere;\"><code style=\"color:#7ab7ff;background:rgba(122,183,255,.16);padding:1px 6px;border-radius:4px;font-weight:600;white-space:nowrap;\">Timestamp</code><span style=\"color:#c8ccd8;\">(mốc thời gian quy đổi slot 6h)</span></span> <span style=\"color:#6c7288;margin:0 2px;\">·</span> <span style=\"display:inline-flex;align-items:center;gap:4px;flex-wrap:wrap;min-width:0;overflow-wrap:anywhere;\"><code style=\"color:#90ee90;background:rgba(144,238,144,.15);padding:1px 6px;border-radius:4px;font-weight:600;white-space:nowrap;\">Content</code><span style=\"color:#c8ccd8;\">(nội dung pattern/vật phẩm)</span></span></div>"
        ),
        unsafe_allow_html=True,
    )
    uploaded = st.file_uploader(T("uploader", default="Upload CSV"), type=["csv"], accept_multiple_files=True)

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

    st.markdown("---")

    _settings_status_slot = st.container()
# === PRED_SETTINGS_WITH_TZ_END ===

with st.sidebar:
    st.markdown(T("sidebar_config", default="### ⚙️ Config"))
    if st.button(T("sidebar_reload", default="🔄 Reload config files"), use_container_width=True, key="btn_reload_sidebar"):
        _apply_sync_update()
    st.caption(T("sidebar_hint", default="Sửa config files → bấm Reload"))

    _local_head = _get_local_runtime_commit()
    _chk_time = datetime.now().strftime("%H:%M:%S")
    _current_sha = _get_main_sha()
    _w_store_now = _get_sync_watch_store() or {}
    _w_active = _w_store_now.get("active_sig")
    _w_pending = _w_store_now.get("pending_sig")
    _w_active_short = _w_active[-12:] if isinstance(_w_active, str) and _w_active else "init"
    st.caption(f"🧬 Local HEAD: `{_local_head}` · 🕒 `{_chk_time}`")
    if _current_sha:
        st.caption(f"🟢 GitHub (`{_DATA_BRANCH}`): `{_current_sha[:7]}` · Active: `{_w_active_short}`")
    else:
        st.caption(f"🔴 GitHub: Offline · Active: `{_w_active_short}`")
    if _w_pending and _w_pending != _w_active:
        _p_parts = ", ".join(_w_store_now.get("changed_parts") or [])
        st.warning(f"⚡ Có thay đổi ở: `{_p_parts or '3 files'}`")
    
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
                _curr = bool(st.session_state.get("user_adaptive_enabled", False))
                _tog = st.toggle('🚀 Bật Adaptive Offset (override TRANS)', value=_curr, key='adaptive_offset_toggle')
                if _tog != _curr:
                    st.session_state["user_adaptive_enabled"] = bool(_tog)
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
                            st.session_state["user_candidate_offsets"] = tuple(res['new_offsets'] or [])
                            del st.session_state['offset_verify_result']
                            st.success("Đã áp dụng Offsets mới cho phiên của bạn!"); st.rerun()
                    else:
                        st.error(f"❌ Bộ mới KÉM HƠN ({res['new_acc']-res['old_acc']:.1f}%)")
                        if st.button("⚠️ Vẫn áp dụng (Không khuyến khích)", key="btn_apply_force", use_container_width=True):
                            st.session_state["user_candidate_offsets"] = tuple(res['new_offsets'] or [])
                            del st.session_state['offset_verify_result']
                            st.warning("Đã áp dụng Offsets mới cho phiên của bạn (dù kém hơn)."); st.rerun()
                    if st.button("🗑️ Bỏ qua / Hủy kết quả", key="btn_discard_verify", use_container_width=True):
                        del st.session_state['offset_verify_result']; st.rerun()

_cur_watch_sig, _has_watch_change, _watch_parts = _evaluate_watch_changes()
if _has_watch_change:
    _w_store = _get_sync_watch_store()
    with _SYNC_WATCH_LOCK:
        _det_ts = _w_store.get("detected_at") or time.time()
        _parts_txt = ", ".join(_w_store.get("changed_parts") or _watch_parts)

    _user_postponed = (st.session_state.get("user_postponed_sig") == _cur_watch_sig)
    _elapsed_s = time.time() - _det_ts
    _rem_s = max(0, int(_AUTO_APPLY_TIMEOUT_SEC - _elapsed_s))

    if (not _user_postponed) and _elapsed_s >= _AUTO_APPLY_TIMEOUT_SEC:
        _apply_sync_update()

    with st.container(border=True):
        if _user_postponed:
            st.info(f"⏸️ **Bạn đã hoãn cập nhật (`{_parts_txt}`)** cho phiên này. Bấm **Cập nhật ngay** khi muốn áp dụng.")
        else:
            st.warning(f"🔔 **Phát hiện thay đổi ở `{_parts_txt}`.** Không ai chọn sau **{_rem_s}s** sẽ tự chạy cập nhật.")

        _b1, _b2, _b3 = st.columns([1.4, 1.4, 4.2])
        with _b1:
            if st.button("✅ Cập nhật ngay", key="btn_watch_yes", use_container_width=True):
                _apply_sync_update()
        with _b2:
            if st.button("⏸️ Hoãn (No)", key="btn_watch_no", use_container_width=True):
                st.session_state["user_postponed_sig"] = _cur_watch_sig
                st.rerun()

    if (not _user_postponed) and _rem_s > 0:
        time.sleep(1)
        st.rerun()

st.title(T("title", default="📍 Merchant Location"))

if _default_files:
    if _loaded_default and _loaded_default[0]:
        _d_rows, _d_min, _d_max, _used = _loaded_default
        total_mb = sum(os.path.getsize(f) for f in _default_files) / 1024 / 1024
        shown = ", ".join(f"`{f}` ({n:,})" for f, n in _used[:5]) + (f" … (+{len(_used)-5})" if len(_used) > 5 else "")
        info_text = T("info_header", default="📚 **Default baseline** ({n} file(s)):", n=len(_used)) + "\n\n" + f"- 📁 {shown}\n"
        info_text += T("info_from", default="- 🗓️ **From:** `{v}` (VN, UTC+7)", v=_d_min.strftime('%Y-%m-%d %H:%M')) + "\n"
        info_text += T("info_to", default="- 🗓️ **To:** `{v}` (VN, UTC+7)", v=_d_max.strftime('%Y-%m-%d %H:%M')) + "\n"
        info_text += T("info_total", default="- 📊 **Total:** `{n:,}` posts  ·  💾 `{mb:.1f} MB`", n=len(_d_rows), mb=total_mb) + "\n\n"
        st.info(info_text)
    else:
        st.warning(T("no_valid", default="⚠️ No valid rows"))
else:
    st.caption(T("no_default", default="ℹ️ No baseline CSV"))

_has_something = uploaded or (use_default and bool(_default_files))

if _has_something:
    files_data = tuple((f.name, f.getvalue()) for f in (uploaded or []))
    default_rows = tuple(_loaded_default[0]) if (use_default and _loaded_default and _loaded_default[0]) else tuple()
    used_files = tuple(_loaded_default[3]) if (use_default and _loaded_default and _loaded_default[3]) else tuple()

    _user_adapt_flag = bool(st.session_state.get("user_adaptive_enabled", False))
    _user_cand_tuple = tuple(st.session_state.get("user_candidate_offsets") or ())

    @st.cache_data(show_spinner=False)
    def _cached(files_tuple, default_rows_tuple, used_files_tuple, offset, use_def, lang_code, utc_off, trans_lookback, adaptive_state, cand_offsets_tuple):
        import copy as _cp
        with _PIPELINE_LOCK:
            _prev_adapt = predictor.get_adaptive_offset_state()
            _prev_cands = list(getattr(predictor, "ADAPTIVE_CANDIDATE_OFFSETS", []) or [])
            try:
                predictor.set_adaptive_offset_state(bool(adaptive_state))
                if cand_offsets_tuple:
                    predictor.ADAPTIVE_CANDIDATE_OFFSETS = list(cand_offsets_tuple)
                if hasattr(predictor, "_build_context_offset_cache"):
                    predictor._build_context_offset_cache()
                _res = predictor.run_pipeline(list(files_tuple), list(default_rows_tuple), list(used_files_tuple), offset, use_def, lang_code, utc_off, trans_lookback)
                return (_res[0], _res[1], _res[2], _cp.deepcopy(_res[3]))
            finally:
                predictor.set_adaptive_offset_state(_prev_adapt)
                predictor.ADAPTIVE_CANDIDATE_OFFSETS = _prev_cands
                if hasattr(predictor, "_build_context_offset_cache"):
                    predictor._build_context_offset_cache()

    widget_html, log_text, trans_text, trans_stats = _cached(
        files_data, default_rows, used_files, offset_days, use_default, lang, st.session_state.utc_offset, trans_lookback_input, _user_adapt_flag, _user_cand_tuple
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

    parts = ([T("part_default", default="{n} baseline", n=len(_default_files))] if use_default else []) + ([T("part_upload", default="{n} uploaded", n=len(uploaded))] if uploaded else [])
    _n_miss_04 = int(trans_stats.get('total_missing_04', 0) or 0)
    _n_miss_all = int(trans_stats.get('total_missing_all', 0) or 0)

    with _settings_status_slot:
        if widget_html is not None:
            st.success(T("success", default="✅ Processed: {parts}", parts=" + ".join(parts)))
        if _n_miss_04 > 0 or _n_miss_all > 0:
            st.error(
                T(
                    "gap_stats",
                    default="⚠️ **Thống kê thiếu data:** {n04} slot 04:00 bị thiếu (tổng {nall} slot thiếu trong khoảng dữ liệu).",
                    n=_n_miss_04,
                    n04=_n_miss_04,
                    nall=_n_miss_all,
                )
            )
            if trans_stats.get("missing_04"):
                with st.popover(T("gap_detail_btn_settings", default="🔍 Xem chi tiết các slot 04:00 bị thiếu gần nhất")):
                    missing_str = format_missing_slots(trans_stats["missing_04"], st.session_state.utc_offset)
                    st.code(missing_str, language="text")
        else:
            st.success(T("gap_none", default="✅ Dữ liệu đầy đủ, không phát hiện slot thiếu nào."))

    if widget_html is None:
        st.error(T("failed", default="❌ Pipeline failed")); st.code(log_text, language="text")
    else:
        components.html(widget_html, height=1100, scrolling=True)
        with st.expander(T("expander", default="📋 Log"), expanded=False):
            col_log_a, col_log_b = st.columns([4, 1])
            with col_log_b:
                st.download_button(T("log_download", default="💾 Tải log"), log_text, file_name=f"pipeline_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt", key="dl_log_btn", use_container_width=True)
            st.code(log_text, language="text")
else:
    st.info(T("upload_hint", default="👆 Upload CSV to start"))

