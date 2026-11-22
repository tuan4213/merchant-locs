from pathlib import Path

src_path = Path("/content/merchant-locs/app.py")
if not src_path.exists():
    # Fallback nếu chưa clone sẵn vào /content/merchant-locs
    import subprocess
    subprocess.run(["git", "clone", "https://github.com/tuan4213/merchant-locs.git", "/content/merchant-locs"], check=True)

src = src_path.read_text(encoding="utf-8")

old_block_start = "def _compute_local_watch_sig():"
old_block_end = "def _load_at_sha(sha):"

assert old_block_start in src and old_block_end in src, "Không tìm thấy khối watch cũ trong app.py"

new_watch_block = '''def _compute_local_watch_sig():
    parts_hash = {}
    watch_files = ["predictor.py", "widget_template.html"] + list_default_files()
    for rel in sorted(set(watch_files)):
        p = _resolve_local_file(rel)
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


def _evaluate_watch_changes(_repo_sig_ignored=None):
    store = _get_sync_watch_store()
    local_map = _compute_local_watch_sig()
    sig_str = _build_three_parts_sig(local_map)

    with _SYNC_WATCH_LOCK:
        if store["active_sig"] is None:
            store["active_sig"] = sig_str
            store["last_files"] = local_map
            store["pending_sig"] = None
            store["detected_at"] = None
            store["user_choice"] = None
            store["changed_parts"] = []
            return sig_str, False, []

        if sig_str == store["active_sig"]:
            store["pending_sig"] = None
            store["detected_at"] = None
            store["user_choice"] = None
            store["changed_parts"] = []
            return sig_str, False, []

        prev_files = store.get("last_files") or {}
        changed = []
        prev_csv = {k: v for k, v in prev_files.items() if k.endswith(".csv")}
        curr_csv = {k: v for k, v in local_map.items() if k.endswith(".csv")}
        if prev_csv != curr_csv:
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
            store["user_choice"] = None
            store["changed_parts"] = changed

        return sig_str, True, list(store["changed_parts"])


def _apply_sync_update(_new_sig_ignored=None):
    store = _get_sync_watch_store()
    st.cache_data.clear()
    local_map = _compute_local_watch_sig()
    sig_str = _build_three_parts_sig(local_map)
    with _SYNC_WATCH_LOCK:
        store["active_sig"] = sig_str
        store["last_files"] = local_map
        store["pending_sig"] = None
        store["detected_at"] = None
        store["user_choice"] = None
        store["changed_parts"] = []
    st.rerun()


'''

i0 = src.index(old_block_start)
i1 = src.index(old_block_end)
src = src[:i0] + new_watch_block + src[i1:]

old_sidebar_sig = '''        _w_active = (_get_sync_watch_store() or {}).get("active_sig")
        _w_active_short = _w_active.split(":")[-1] if isinstance(_w_active, str) and ":" in _w_active else (_w_active or "none")
        st.caption(f"📌 Active sig: `{_w_active_short}`")
        if _w_active and _current_sha and _w_active != _current_sha:
            st.warning("⚡ Phát hiện SHA remote khác Active sig!")'''

new_sidebar_sig = '''        _w_store_now = _get_sync_watch_store() or {}
        _w_active = _w_store_now.get("active_sig")
        _w_pending = _w_store_now.get("pending_sig")
        _w_active_short = _w_active[-12:] if isinstance(_w_active, str) and _w_active else "init"
        st.caption(f"📌 Active sig: `{_w_active_short}`")
        if _w_pending and _w_pending != _w_active:
            _p_parts = ", ".join(_w_store_now.get("changed_parts") or [])
            st.warning(f"⚡ Có thay đổi ở: `{_p_parts or '3 files'}`")'''

if old_sidebar_sig in src:
    src = src.replace(old_sidebar_sig, new_sidebar_sig, 1)

compile(src, "/content/patch_watch_3files.py", "exec")
Path("/content/patch_watch_3files.py").write_text(src, encoding="utf-8")
print("✅ Đã tạo và kiểm tra cú pháp /content/patch_watch_3files.py")
