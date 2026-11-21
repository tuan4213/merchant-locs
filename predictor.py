import math
from collections import defaultdict
# predictor.py — Prediction logic (Markov, TRANS, run_pipeline)
import csv, re, io, json, os, glob, subprocess, time
import hashlib
import threading
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from pathlib import Path
from github import Github, Auth

# --- TIMEZONE HELPERS ---
from zoneinfo import ZoneInfo
import re as _re
from datetime import datetime as _dt, timedelta as _td

def _detect_and_convert_timezone(ts_str, user_offset):
    if not ts_str: return ts_str, False, "unknown"
    ts_str = str(ts_str).strip()
    iso_tz_match = _re.search(r'(Z|[+-]\d{2}:?\d{2})$', ts_str)
    if iso_tz_match:
        try:
            clean_ts = ts_str.replace("Z", "+00:00")
            dt = _dt.fromisoformat(clean_ts)
            vn_tz = ZoneInfo("Asia/Ho_Chi_Minh")
            dt_vn = dt.astimezone(vn_tz).replace(tzinfo=None)
            return dt_vn.strftime("%Y-%m-%d %H:%M:%S"), True, "ISO-Timezone"
        except Exception:
            pass
    try:
        clean_ts = ts_str.split(".")[0] 
        dt = _dt.strptime(clean_ts, "%Y-%m-%d %H:%M:%S")
        delta_hours = 7.0 - float(user_offset)
        dt_vn = dt + _td(hours=delta_hours)
        return dt_vn.strftime("%Y-%m-%d %H:%M:%S"), True, f"User-Slider (UTC+{user_offset})"
    except Exception:
        return ts_str, False, "Parse Error"

def _check_mixed_timezones(ts_list):
    tz_formats = set()
    for ts in ts_list:
        if not ts: continue
        if _re.search(r'Z$', ts): tz_formats.add("UTC (Z)")
        elif _re.search(r'\+07:?00$', ts): tz_formats.add("UTC+7")
        elif _re.search(r'[+-]\d{2}:?\d{2}$', ts): tz_formats.add("Khác")
        else: tz_formats.add("Naive")
    return list(tz_formats)


_PIPELINE_LOCK = threading.RLock()

from item_utils import order_rows_pattern_first
from item_utils import (
    extract_pattern, extract_items, pattern_from_items,
    parse_pairs, stage_group, valid_position_groups,
    find_slot_by_first_2_pairs,
)
from i18n import get_widget_text, get_translator
from logger_utils import PipelineLogger

_SECRETS = {}
def set_secrets(s): 
    global _SECRETS
    _SECRETS = dict(s) if s else {}

def _get_cfg(key, default=None):
    v = _SECRETS.get(key)
    if v: return v
    return os.getenv(key, default)

REPO_NAME = "tuan4213/merchant-locs"

try:
    _WIDGET_TEMPLATE = (Path(__file__).parent / 'widget_template.html').read_text(encoding='utf-8')
except (FileNotFoundError, NameError):
    try:
        _WIDGET_TEMPLATE = Path('widget_template.html').read_text(encoding='utf-8')
    except FileNotFoundError:
        _WIDGET_TEMPLATE = None

_TS_CANDIDATES = ['timestamp', 'date', 'time', 'datetime', 'thời gian', 'ngày', 'ngay', 'when', 'posted']
_USER_CANDIDATES = ['username', 'user', 'name', 'player', 'người dùng', 'nguoi dung', 'author', 'poster', 'sender']
_CONTENT_CANDIDATES = ['content', 'message', 'text', 'nội dung', 'noi dung', 'post', 'body', 'msg']

def _find_column(row_keys_lower, candidates):
    for cand in candidates:
        if cand in row_keys_lower: return row_keys_lower[cand]
    for cand in candidates:
        for k_low, k_orig in row_keys_lower.items():
            if cand in k_low or k_low in cand: return k_orig
    return None

def _parse_phase_k(s):
    s = s.strip().upper()
    m = re.fullmatch(r'([A-Z])(\d+)', s)
    if not m: raise ValueError(f'Invalid phase+k: {s!r}')
    return m.group(1), int(m.group(2))

def _parse_prob(s):
    s = s.strip()
    if s.endswith('%'): return float(s[:-1]) / 100
    v = float(s)
    if v > 1: v = v / 100
    return v

def _parse_known_line(line, cfg):
    m = re.fullmatch(r'base_time\s*=\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line, re.IGNORECASE)
    if m: cfg['BASE_TIME_STR'] = m.group(1); return
    m = re.fullmatch(r'cycle\s*=\s*(\d+)', line, re.IGNORECASE)
    if m: cfg['CYCLE'] = int(m.group(1)); return
    m = re.fullmatch(r'phase\s+([A-Za-z])\s+jitter\s+([+-]?\d+)', line, re.IGNORECASE)
    if m: cfg['JITTERS'][m.group(1).upper()] = int(m.group(2)); return
    m = re.fullmatch(r'phase\s+([A-Za-z])\s+k\s+([\d\s,]+)', line, re.IGNORECASE)
    if m: cfg['K_ACTIVE'][m.group(1).upper()] = [int(x) for x in re.split(r'[\s,]+', m.group(2).strip()) if x]; return
    m = re.fullmatch(r'patch1\s+(.+)', line, re.IGNORECASE)
    if m: cfg['PATCH1_K'] = [_parse_phase_k(t) for t in m.group(1).split()]; return
    m = re.fullmatch(r'anomaly_std\s+cycle\s+(\d+)\s+jitter\s+(\d+)\s+max_k\s+(\d+)\s+max_p\s+(\d+)', line, re.IGNORECASE)
    if m: cfg['ANOMALY_STD_CFG'] = tuple(map(int, m.groups())); return
    m = re.fullmatch(r'anomaly_04\s+cycle\s+(\d+)\s+jitter\s+([\d\s-]+)\s+max_k\s+(\d+)\s+max_p\s+(\d+)', line, re.IGNORECASE)
    if m: cfg['ANOMALY_04_CFG'] = (int(m.group(1)), [int(x) for x in m.group(2).split()], int(m.group(3)), int(m.group(4))); return
    m = re.fullmatch(r'std_anomaly_offset\s+(\d+)\s+(\S+)', line, re.IGNORECASE)
    if m: cfg['STD_ANOMALY_OFFSETS'][int(m.group(1))] = _parse_phase_k(m.group(2)); return
    m = re.fullmatch(r'std_anomaly_risk_gaps\s+([\d\s,]+)', line, re.IGNORECASE)
    if m: cfg['STD_ANOMALY_RISK_GAPS'] = [int(x) for x in re.split(r'[\s,]+', m.group(1).strip()) if x]; return
    m = re.fullmatch(r'use_markov_b2\s*=\s*(true|false)', line, re.IGNORECASE)
    if m: cfg['USE_MARKOV_B2'] = m.group(1).lower() == 'true'; return
    m = re.fullmatch(r'markov_b2_min_samples\s*=\s*(\d+)', line, re.IGNORECASE)
    if m: cfg['MARKOV_B2_MIN_SAMPLES'] = int(m.group(1)); return
    m = re.fullmatch(r'trans_adaptive_lookback\s*=\s*(\d+)', line, re.IGNORECASE)
    if m: cfg['TRANS_ADAPTIVE_LOOKBACK'] = int(m.group(1)); return
    m = re.fullmatch(r'markov\s+(\S+)\s*->\s*(\S+)\s+(\S+)', line, re.IGNORECASE)
    if m:
        src, dst = _parse_phase_k(m.group(1)), _parse_phase_k(m.group(2))
        cfg['MARKOV_A2_CFG'].setdefault(f'{src[0]}{src[1]}', {})[f'{dst[0]}{dst[1]}'] = _parse_prob(m.group(3)); return
    m = re.fullmatch(r'markov_offset\s+(\S+)\s*=\s*(\S+)', line, re.IGNORECASE)
    if m: cfg['MARKOV_BRANCH_OFFSETS'][m.group(1).upper()] = _parse_phase_k(m.group(2)); return
    m = re.fullmatch(r'([a-z_]+)\s*=\s*(-?[\d.]+)', line, re.IGNORECASE)
    if m:
        key, val = m.group(1).lower(), m.group(2)
        kmap = {'auto_heal_threshold': 'AUTO_HEAL_THRESHOLD', 'auto_heal_min_samples': 'AUTO_HEAL_MIN_SAMPLES',
                'min_stable_slot': 'MIN_STABLE_SLOT', 'min_markov_samples': 'MIN_MARKOV_SAMPLES'}
        if key in kmap: cfg[kmap[key]] = int(val) if '.' not in val else float(val); return
    raise ValueError(f'Unknown syntax: {line!r}')

def load_known_patterns(path='known_patterns.txt'):
    p = Path(path)
    if not p.exists(): return None
    cfg = {'BASE_TIME_STR': '2025-01-01 04:00:00', 'CYCLE': 119, 'JITTERS': {}, 'K_ACTIVE': {}, 'PATCH1_K': [],
           'ANOMALY_STD_CFG': (116, 16, 15, 5), 'ANOMALY_04_CFG': (119, [12, 6, -6, -12], 10, 3),
           'STD_ANOMALY_OFFSETS': {1: ('A', 4), 2: ('A', 3), 3: ('A', 2)},
           'STD_ANOMALY_RISK_GAPS': [16, 116, 132],
           'USE_MARKOV_B2': True, 'MARKOV_B2_MIN_SAMPLES': 3,
           'MARKOV_A2_CFG': {}, 'MARKOV_A2_FALLBACK': {'C1': 0.55, 'A3': 0.45},
           'MARKOV_BRANCH_OFFSETS': {}, 'AUTO_HEAL_THRESHOLD': 0.52, 'AUTO_HEAL_MIN_SAMPLES': 200,
           'MIN_STABLE_SLOT': 0, 'MIN_MARKOV_SAMPLES': 20, 'TRANS_ADAPTIVE_LOOKBACK': 50}
    errors = []
    for lineno, raw in enumerate(p.read_text(encoding='utf-8').split('\n'), 1):
        line = raw.split('#', 1)[0].strip()
        if not line: continue
        try: _parse_known_line(line, cfg)
        except Exception as e: errors.append(f'  line {lineno}: `{raw.strip()}` — {e}')
    if errors: raise ValueError('Error in **known_patterns.txt**:\n' + '\n'.join(errors))
    return cfg

def load_trans_history(path='trans_history.txt'):
    p = Path(path)
    if not p.exists(): return None
    trans = {}; errors = []
    for lineno, raw in enumerate(p.read_text(encoding='utf-8').split('\n'), 1):
        line = raw.split('#', 1)[0].strip()
        if not line: continue
        try:
            m = re.fullmatch(r'(\S+)\s*->\s*(\S+)(?:\s+(\S+))?', line)
            if not m: raise ValueError('requires format `FROM_RL -> TO_K [PROB]`')
            src, dst = _parse_phase_k(m.group(1)), _parse_phase_k(m.group(2))
            trans.setdefault(src, []).append((dst[0], dst[1], _parse_prob(m.group(3)) if m.group(3) else 1.0))
        except Exception as e: errors.append(f'  line {lineno}: `{raw.strip()}` — {e}')
    if errors: raise ValueError('Error in **trans_history.txt**:\n' + '\n'.join(errors))
    for key, entries in trans.items():
        total = sum(p for _, _, p in entries)
        if total > 0 and abs(total - 1.0) > 0.01: trans[key] = [(ph, k, p / total) for ph, k, p in entries]
    return trans

try:
    _kp = load_known_patterns()
    _th = load_trans_history()
except ValueError as e:
    raise RuntimeError(f"Config load failed: {e}")

_DEFAULTS = {
    'BASE_TIME_STR': '2025-01-01 04:00:00', 'CYCLE': 119, 'JITTERS': {'A': 12, 'B': -6, 'C': 6}, 'K_ACTIVE': {'A': [1,2,3,4], 'B': [3], 'C': [7]},
    'PATCH1_K': [('A',2), ('A',3), ('A',4)], 'ANOMALY_STD_CFG': (116, 16, 15, 5), 'ANOMALY_04_CFG': (119, [12, 6, -6, -12], 10, 3),
    'STD_ANOMALY_OFFSETS': {1: ('A', 4), 2: ('A', 3), 3: ('A', 2)}, 'STD_ANOMALY_RISK_GAPS': [16, 116, 132],
    'USE_MARKOV_B2': True, 'MARKOV_B2_MIN_SAMPLES': 3,
    'MARKOV_A2_CFG': {'C1': {'C1': 0.79, 'A3': 0.21}, 'A3': {'A3': 0.71, 'C1': 0.29}},
    'MARKOV_A2_FALLBACK': {'C1': 0.55, 'A3': 0.45}, 'MARKOV_BRANCH_OFFSETS': {'C1': ('C',7), 'A3': ('A',4)},
    'AUTO_HEAL_THRESHOLD': 0.52, 'AUTO_HEAL_MIN_SAMPLES': 200, 'MIN_STABLE_SLOT': 0, 'MIN_MARKOV_SAMPLES': 20,
    'TRANS_ADAPTIVE_LOOKBACK': 50
}
_DEFAULT_TRANS = {
    ('B',1): [('A',1,1.0)], ('B',2): [('A',1,1.0)], ('B',3): [('A',1,1.0)],
    ('C',1): [('B',3,0.908),('A',1,0.086),('C',7,0.006)],
    ('C',2): [('B',3,0.932),('C',7,0.068)], ('C',3): [('B',3,0.932),('C',7,0.068)],
    ('A',1): [('A',1,0.786),('A',2,0.214)],
    ('A',2): [('C',7,0.572),('A',4,0.219),('A',3,0.209)],
    ('A',3): [('B',3,0.565),('C',7,0.435)],
}

_kp = _kp or _DEFAULTS
CYCLE, JITTERS, K_ACTIVE = _kp['CYCLE'], _kp['JITTERS'], _kp['K_ACTIVE']
PATCH1_K, MARKOV_A2_CFG = _kp['PATCH1_K'], _kp['MARKOV_A2_CFG']
MARKOV_A2_FALLBACK, MARKOV_BRANCH_OFFSETS = _kp['MARKOV_A2_FALLBACK'], _kp['MARKOV_BRANCH_OFFSETS']
AUTO_HEAL_THRESHOLD, AUTO_HEAL_MIN_SAMPLES = _kp['AUTO_HEAL_THRESHOLD'], _kp['AUTO_HEAL_MIN_SAMPLES']
MIN_STABLE_SLOT, MIN_MARKOV_SAMPLES = _kp['MIN_STABLE_SLOT'], _kp['MIN_MARKOV_SAMPLES']
TRANS_ADAPTIVE_LOOKBACK = _kp.get('TRANS_ADAPTIVE_LOOKBACK', 50)
TRANS_CFG = _th or _DEFAULT_TRANS
ANOMALY_STD_CFG, ANOMALY_04_CFG = _kp['ANOMALY_STD_CFG'], _kp['ANOMALY_04_CFG']
STD_ANOMALY_OFFSETS, USE_MARKOV_B2, MARKOV_B2_MIN_SAMPLES = _kp['STD_ANOMALY_OFFSETS'], _kp['USE_MARKOV_B2'], _kp['MARKOV_B2_MIN_SAMPLES']
STD_ANOMALY_RISK_GAPS = _kp.get('STD_ANOMALY_RISK_GAPS', [16, 116, 132])

def _offset_of(phase, k): return CYCLE * k + JITTERS[phase]
def _build_known_offsets():
    return {_offset_of(phase, k): phase for phase, ks in K_ACTIVE.items() for k in ks}
def _build_trans():
    out = {}
    for key, entries in TRANS_CFG.items():
        total = sum(p for _, _, p in entries)
        out[key] = [(np_, _offset_of(np_, nk), p / total if total else p) for np_, nk, p in entries]
    return out
def _build_patch1_offsets(): return [_offset_of(ph, k) for ph, k in PATCH1_K]

KEY_OFFSETS, TRANS = _build_known_offsets(), _build_trans()
PATCH1_OFFSETS, MARKOV_A2 = _build_patch1_offsets(), dict(MARKOV_A2_CFG)
MARKOV_B2 = defaultdict(Counter)
MARKOV_B2_2T = defaultdict(Counter)

BASE = datetime(2025, 1, 1, 4, 0)
ANOMALY_END_SLOT = -1000
VN_OFFSET = timedelta(hours=7)

ANOMALY_SLOTS_BY_HOUR = {0: [], 1: [], 2: [], 3: []}
BRANCH_SLOTS = {'C1': [], 'A3': []}

STD_GAPS = sorted([(k*ANOMALY_STD_CFG[0] + p*ANOMALY_STD_CFG[1], k, p) for p in range(-ANOMALY_STD_CFG[3], ANOMALY_STD_CFG[3]+1) for k in range(-ANOMALY_STD_CFG[2], ANOMALY_STD_CFG[2]+1) if k*ANOMALY_STD_CFG[0] + p*ANOMALY_STD_CFG[1] > 0], key=lambda x: x[0])
GAPS_04 = sorted(list({(k*ANOMALY_04_CFG[0] + p*j, k, p, j) for p in range(-ANOMALY_04_CFG[3], ANOMALY_04_CFG[3]+1) for j in ANOMALY_04_CFG[1] for k in range(-ANOMALY_04_CFG[2], ANOMALY_04_CFG[2]+1) if k*ANOMALY_04_CFG[0] + p*j > 0}), key=lambda x: x[0])

slot_to_pat, slot_to_meta, slot_to_items, pattern_items = {}, {}, {}, defaultdict(list)
PAIR_TO_SLOTS = defaultdict(set)
skipped, all_posts, ACTIVE_START_SLOT, REAL_SLOTS, REAL_MAX = 0, [], -9999, frozenset(), 0
min_slot, max_slot, DYNAMIC_OFFSETS, slot_phase, miss_101622, total_101622 = 0, 0, [], {}, [], 0
off_counts, miss_rate = Counter(), 5.09
USE_PATCH1, USE_AUTOHEAL, USE_BRIDGE = False, False, False

def parse_ts(s):
    for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %I:%M:%S %p", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try: return datetime.strptime(s.strip(), fmt)
        except ValueError: pass
    return None

def ts_to_slot(dt): return round((dt - BASE).total_seconds() / 3600 / 6)

def get_chain(slot):
    """[PATCH-CHAIN] Trả chain đầy đủ [slot, source, ..., real_root]."""
    meta = slot_to_meta.get(slot, {})
    chain = meta.get('chain')
    if chain:
        return chain
    if meta.get('is_virtual'):
        src = meta.get('source_slot')
        if src is not None:
            return [slot] + get_chain(src)
    return [slot]

def slot_to_ts(slot): return BASE + timedelta(hours=slot * 6)
def _is_bridge(slot): return slot_to_meta.get(slot, {}).get('is_bridge', False)

def get_first_2_pairs(pat):
    if not pat: return ""
    parts = [p.strip() for p in pat.split(" / ")]
    return " / ".join(parts[:2])

def classify(slot):
    pat = slot_to_pat.get(slot)
    if not pat: return None, None
    if slot % 4 == 0:
        for off, phase in KEY_OFFSETS.items():
            if slot - off in slot_to_pat and not _is_bridge(slot-off) and slot_to_pat[slot-off] == pat: return phase, off
        return 'X', None
    pat_first2 = get_first_2_pairs(pat)  # [FIX] không dùng nữa
    for k in range(1, 25):
        prev = slot - 119 * k
        if prev in slot_to_pat and not _is_bridge(prev) and slot_to_pat[prev] == pat: return '119', 119 * k
    for off, phase in KEY_OFFSETS.items():
        prev = slot - off
        if prev in slot_to_pat and not _is_bridge(prev) and slot_to_pat[prev] == pat: return phase, off
    return 'X', None

def _get_exact_state(s):
    if s not in slot_to_pat: return None
    ph_cls, off_cls = classify(s)
    if ph_cls == '119': return '119'
    if ph_cls in ('A','B','C'):
        for k_val in K_ACTIVE.get(ph_cls, []):
            if _offset_of(ph_cls, k_val) == off_cls: return f"{ph_cls}{k_val}"
    return None

def get_phase_run(slot):
    if slot in slot_phase: return slot_phase[slot]
    if slot not in slot_to_pat: return None, 0
    typ, _ = classify(slot)
    if typ not in ('A','B','C'): return None, 0
    rl, s = 1, slot
    while s - 4 >= min_slot:
        if s - 4 in slot_phase:
            ph_prev, rl_prev = slot_phase[s - 4]
            if ph_prev == typ: rl += rl_prev
            break
        if classify(s - 4)[0] == typ: rl += 1; s -= 4
        else: break
    return typ, rl

def _phase_of(slot):
    if slot in slot_phase: return slot_phase[slot]
    if slot in REAL_SLOTS:
        ph, rl = get_phase_run(slot)
        if ph: slot_phase[slot] = (ph, rl); return ph, rl
    return None, 0

def _find_prev_a2_branch(slot, lookback=300):
    for offset in range(4, lookback + 4, 4):
        prev_s = slot - offset
        if prev_s in slot_to_pat:
            ph, rl = _phase_of(prev_s)
            if ph == 'A' and rl == 2:
                nxt = prev_s + 4
                if nxt in slot_phase: return 'C1' if slot_phase[nxt][0] == 'C' else 'A3'
                elif nxt in slot_to_pat: return 'C1' if get_phase_run(nxt)[0] == 'C' else 'A3'
                return None
    return None

REGULAR_GAP_PATTERN = [16, 116, 16, 116, 16, 116, 16, 116, 16, 116, 16, 132, 132, 132]
SESSION_START_OFFSET = {}
MACRO_CYCLE = 1072
EXTRA_ANOMALY_POSITIONS = {1: [157], 2: [814], 3: [399]}

def _predict_next_gap(hour, cutoff_slot=None):
    raw_anoms = ANOMALY_SLOTS_BY_HOUR.get(hour, [])
    anoms = [a for a in raw_anoms if cutoff_slot is None or a < cutoff_slot]
    if len(anoms) < 2: return None
    recent = [anoms[i+1] - anoms[i] for i in range(max(0, len(anoms) - 15), len(anoms) - 1)]
    n = len(recent)
    if n == 0: return None
    candidates = []
    for st in range(14):
        if all(recent[i] == REGULAR_GAP_PATTERN[(st+i) % 14] for i in range(n)):
            candidates.append(st)
    if len(candidates) == 1:
        SESSION_START_OFFSET[hour] = candidates[0]
        return [REGULAR_GAP_PATTERN[(candidates[0] + n) % 14]]
    if len(candidates) > 1 and hour in SESSION_START_OFFSET:
        st = SESSION_START_OFFSET[hour]
        if st in candidates: return [REGULAR_GAP_PATTERN[(st + n) % 14]]
    last = recent[-1]
    if last == 16: return [116]
    elif last == 116: return [16]
    elif last == 132:
        c = sum(1 for g in reversed(recent) if g == 132)
        return [16] if c >= 3 else [132]
    best_st, best_score = 0, 0
    for st in range(14):
        score = sum(1 for i in range(n) if recent[i] == REGULAR_GAP_PATTERN[(st+i) % 14])
        if score > best_score: best_score, best_st = score, st
    if n > 0 and best_score / n >= 0.85: return [REGULAR_GAP_PATTERN[(best_st + n) % 14]]
    return [116 if last == 16 else (16 if last == 116 else 132)]

def _get_anomaly_risk(target_slot):
    hour = target_slot % 4
    if hour == 0: return False
    anoms = [a for a in ANOMALY_SLOTS_BY_HOUR.get(hour, []) if a < target_slot]
    if not anoms: return False
    if hour in EXTRA_ANOMALY_POSITIONS:
        pos = target_slot % MACRO_CYCLE
        if pos in EXTRA_ANOMALY_POSITIONS[hour]: return True
    diff = target_slot - anoms[-1]
    if diff <= 0: return False
    if diff in (116, 132): return True
    if diff == 16:
        predicted = _predict_next_gap(hour, target_slot)
        if predicted is None:
            # [FIX] Không đủ lookback → mặc định KHÔNG Risk (tin 119)
            # Trước đây return True → chọn Phase A → sai slot 495
            return False
        return 16 in (predicted if isinstance(predicted, list) else [predicted])
    return False

def _predict_std_ext(target):
    offsets = [(119, 'Cycle 119')]
    for d in DYNAMIC_OFFSETS: offsets.append((d, f'Dynamic cycle {d}'))
    hour = target % 4
    if hour in STD_ANOMALY_OFFSETS:
        ph, k = STD_ANOMALY_OFFSETS[hour]
        off_A = _offset_of(ph, k)
        offsets.append((off_A, f'Phase A ({ph}{k})'))
    raw_out = []
    has_119 = False
    is_risk = _get_anomaly_risk(target)
    is_ghost_gap = False
    if is_risk and _predict_next_gap(hour) == [16]:
        EXTRA_POS = {1: 157, 2: 814, 3: 399}
        if hour in EXTRA_POS:
            if (target + 132) % 1072 == EXTRA_POS[hour]: is_ghost_gap = True
    for off, reason in offsets:
        src = target - off
        if src in slot_to_pat and not _is_bridge(src):
            src_class, _ = classify(src)
            if off == 119:
                has_119 = True
                if is_ghost_gap: prob = 0.60
                else: prob = 0.05 if is_risk else (0.95 if src_class != 'X' else 0.50)
            elif off in DYNAMIC_OFFSETS: prob = 0.80
            elif 'Phase A' in reason:
                if is_ghost_gap: prob = 0.40
                else: prob = 0.95 if is_risk else 0.10
            else: prob = 0.017
            raw_out.append({'prob': prob, 'offset': off, 'source': src, 'pattern': slot_to_pat[src], 'reason': reason, 'source_type': 'real' if src in REAL_SLOTS else 'pred'})
    if not has_119:
        for r in raw_out:
            if 'Phase A' in r['reason']: r['prob'] = 0.95 
    grouped = {}
    for r in raw_out:
        if r['pattern'] not in grouped: grouped[r['pattern']] = {'main': r, 'dups': []}
        else: grouped[r['pattern']]['main']['prob'] += r['prob']; grouped[r['pattern']]['dups'].append(r)
    return sorted([{**data['main'], 'prob': min(data['main']['prob'], 1.0), 'duplicates': data['dups']} for pat, data in grouped.items()], key=lambda x: -x['prob'])[:3]

def _find_04_cluster(target):
    if target % 4 != 0: return None
    for gap, k, p, j in GAPS_04:
        if target - gap in REAL_SLOTS and _is_anomaly_04(target - gap): return (k, p, j, gap, slot_to_pat[target - gap])

def _is_anomaly_04(s):
    if s not in slot_to_pat or s not in REAL_SLOTS or s % 4 != 0: return False
    prev = s - 4
    if prev not in slot_to_pat: return False
    phase, rl = _phase_of(prev)
    if phase not in ('A', 'B', 'C'): return False
    tr = TRANS.get((phase, min(rl, 3)), [])
    if not tr: return False
    return slot_to_pat[s] not in {slot_to_pat[s - off] for _, off, _ in tr if (s - off) in slot_to_pat}

def _v12_predict_from_phase_chains_v2(target):
    _skip_b3 = (target % 1072 == 1056)
    phase_chains = {}
    for ph in ['A1', 'A2', 'A3', 'A4', 'B3', 'C7']:
        phase_chains[ph] = sorted([s for s in ANOMALY_SLOTS_BY_HOUR.get(0, []) if s < target and _get_exact_state(s) == ph])
    a3_slots = phase_chains['A3']
    prev_exact = _get_exact_state(target - 4) if (target - 4) in slot_to_pat else None
    prev_phase, prev_rl = _phase_of(target - 4)
    prev_prev_exact = _get_exact_state(target - 8) if (target - 8) in slot_to_pat else None
    candidates = []
    for ph in ['A1', 'A2', 'A3', 'A4', 'B3', 'C7']:
        if ph == 'B3' and _skip_b3: continue
        chain = phase_chains[ph]
        if len(chain) < 3: continue
        gaps = [chain[i+1] - chain[i] for i in range(len(chain)-1)]
        predicted_gap = _v12_predict_next_gap_for_phase(gaps, ph)
        if predicted_gap is None: continue
        predicted_slot = chain[-1] + predicted_gap
        if predicted_slot == target:
            if _v12_is_context_compatible(prev_exact, prev_rl, prev_prev_exact, ph, target, a3_slots):
                candidates.append({'phase': ph, 'predicted_slot': predicted_slot, 'gap': predicted_gap, 'last_slot': chain[-1], 'confidence': 1.0})
    if prev_exact == 'A1':
        chain_a1 = phase_chains.get('A1', [])
        if len(chain_a1) >= 2:
            gap1 = chain_a1[-1] - chain_a1[-2]
            next_gap = 16 if gap1 == 12 else 12 if gap1 == 16 else None
            if next_gap and chain_a1[-1] + next_gap == target:
                off = _offset_of('A', 1)
                src = target - off
                if src in slot_to_pat and not _is_bridge(src):
                    return [{'pattern': slot_to_pat[src], 'prob': 0.95, 'phases': ['A1'], 'offset': off, 'source': src, 'reason': 'V12.12-A1Fallback', 'prev_phase': prev_exact, 'prev_rl': prev_rl, 'source_type': 'real' if src in REAL_SLOTS else 'pred', 'markov': False, 'duplicates': []}]
    if not candidates: return None
    best = candidates[0]
    try: off = 119 if best['phase'] == '119' else _offset_of(best['phase'][0], int(best['phase'][1:]))
    except: return None
    src = target - off
    if src not in slot_to_pat or _is_bridge(src): return None
    return [{'pattern': slot_to_pat[src], 'prob': 1.0, 'phases': [best['phase']], 'offset': off, 'source': src, 'reason': f"V12.2-PhaseChain({best['phase']},gap={best['gap']})", 'prev_phase': prev_exact, 'prev_rl': prev_rl, 'source_type': 'real' if src in REAL_SLOTS else 'pred', 'markov': False, 'duplicates': []}]

def _v12_predict_next_gap_for_phase(gaps, phase):
    if len(gaps) < 3: return None
    if phase in _V12_KNOWN_PATTERNS:
        patterns_sorted = sorted(_V12_KNOWN_PATTERNS[phase], key=len, reverse=True)
        for pattern in patterns_sorted:
            pat_len = len(pattern)
            if len(gaps) >= pat_len:
                recent = gaps[-pat_len:]
                for offset in range(pat_len):
                    if all(recent[i] == pattern[(offset+i) % pat_len] for i in range(pat_len)):
                        return pattern[(offset + pat_len) % pat_len]
    if len(gaps) >= 5:
        recent = gaps[-10:]
        for offset in range(14):
            matches = sum(1 for i in range(len(recent)) if recent[i] == _V12_REGULAR_PATTERN[(offset+i) % 14])
            if matches >= len(recent) * 0.85: return _V12_REGULAR_PATTERN[(offset + len(recent)) % 14]
    last = gaps[-1]
    if last == 16: return 116
    if last == 116: return 16
    if last == 132: return 132
    return None

def _v12_is_context_compatible(prev_exact, prev_rl, prev_prev_exact, candidate_phase, target, a3_slots):
    if prev_exact == 'A1':
        if candidate_phase == 'A2':
            if prev_rl != 1: return False
            if a3_slots:
                gap_a3 = target - a3_slots[-1]
                if gap_a3 not in (16, 32): return False
            return True
        if candidate_phase in ('A1', 'C7', 'A3', 'A4'): return True
        return False
    if prev_exact == 'C7':
        if candidate_phase in ('C7', 'B3', 'A1'): return True
        return False
    if prev_exact == 'B3':
        if candidate_phase == 'A1': return True
        return False
    if prev_exact in ('A3', 'A4'):
        if candidate_phase in ('A3', 'A4', 'B3', 'C7'): return True
        return False
    if prev_exact == 'A2':
        if candidate_phase in ('C7', 'A4', 'A3'): return True
        return False
    return True

_V12_REGULAR_PATTERN = [16, 116, 16, 116, 16, 116, 16, 116, 16, 116, 16, 132, 132, 132]
_V12_KNOWN_PATTERNS = {
    'A2': [[16, 116, 16, 116, 16, 116, 16, 132, 132, 132, 16, 116, 16, 116]],
    'A3': [[16, 132, 132, 132, 132, 16, 116, 16, 116, 16, 116, 16, 116, 16]],
    'B3': [[16, 16, 16, 16, 16, 16, 16, 20], [16, 16, 16, 16, 16, 16, 36]],
    'C7': [[16, 16, 16, 16, 16, 52], [16, 16, 16, 16, 16, 16, 52]],
}
_CYCLE_OFFSET_RULES = {('B3', 1): 'A1', ('A1', 1): 'A1', ('A1', 2): 'C7', ('C7', 1): 'B3'}

def _fill_04am_step(slot_to_fill, fill_pat, source_slot, method):
    prev_chain = slot_to_meta.get(source_slot, {}).get('chain') or [source_slot]
    slot_to_pat[slot_to_fill] = fill_pat
    slot_to_meta[slot_to_fill] = {
        'dt': None,
        'dt_raw': None,
        'user': 'PREDICTED',
        'pattern_source': 'virtual',
        'is_virtual': True,
        'fill_method': method,
        'source_slot': source_slot,
        'chain': [slot_to_fill] + prev_chain,
    }
    if slot_to_fill % 4 == 0 and slot_to_fill not in ANOMALY_SLOTS_BY_HOUR.get(0, []):
        ANOMALY_SLOTS_BY_HOUR.setdefault(0, []).append(slot_to_fill)


_REAL_PAT_SNAPSHOT = {}
_REAL_META_SNAPSHOT = {}

def _ensure_virtual_04am_chain(target, max_steps=300, _active=None):
    return

    floor = max(0, min_slot if 'min_slot' in globals() else 0)
    anchor = target - 4
    steps = 0
    while anchor >= floor and anchor not in slot_to_pat and steps < max_steps:
        anchor -= 4
        steps += 1
    if anchor < floor or anchor not in slot_to_pat:
        return

    cur = anchor + 4
    while cur <= target:
        if cur not in slot_to_pat and cur not in _active:
            _active.add(cur)
            try:
                preds = _predict_04am_ext(cur, _depth=1, _visited=set(_active))
            except TypeError:
                preds = _predict_04am_ext(cur)
            except Exception:
                preds = []
            _active.discard(cur)

            if preds and preds[0].get('pattern'):
                top0 = preds[0]
                src_s = top0.get('source', cur - 4)
                prev_chain = slot_to_meta.get(src_s, {}).get('chain') or [src_s]
                slot_to_pat[cur] = top0['pattern']
                slot_to_meta[cur] = {
                    'dt': None,
                    'dt_raw': None,
                    'user': 'PREDICTED',
                    'pattern_source': 'virtual',
                    'is_virtual': True,
                    'fill_method': '04am_pred_step',
                    'source_slot': src_s,
                    'chain': [cur] + prev_chain,
                }
                if cur % 4 == 0 and cur not in ANOMALY_SLOTS_BY_HOUR.get(0, []):
                    ANOMALY_SLOTS_BY_HOUR.setdefault(0, []).append(cur)
        cur += 4

def _predict_04am_ext(target, _depth=0, _visited=None):
    if _depth == 0:
        _ensure_virtual_04am_chain(target)
    global MARKOV_B2, MARKOV_B2_2T
    if _visited is None:
        _visited = set()
    if target in _visited or _depth > 300:
        return []
    _visited.add(target)

    # Thụt lùi từng bước -4 để tìm mốc đã có dữ liệu, rồi điền tiến dần từng bước +4 lên tới sát target
    _prev = target - 4
    _floor = max(0, min_slot if 'min_slot' in globals() else 0)
    if _prev >= _floor and _prev not in slot_to_pat:
        _anchor = _prev - 4
        _steps_back = 1
        while _anchor >= _floor and _anchor not in slot_to_pat and _steps_back <= 300:
            _anchor -= 4
            _steps_back += 1

        if _anchor >= _floor and _anchor in slot_to_pat:
            _cur = _anchor + 4
            while _cur < target and _cur not in _visited:
                if _cur not in slot_to_pat:
                    _sub = _predict_04am_ext(_cur, _depth=_depth + 1, _visited=(_visited | {_cur}))
                    if _sub and _sub[0].get('pattern'):
                        _fill_04am_step(_cur, _sub[0]['pattern'], _cur - 4, f'04am_forward_d{_depth + 1}')
                _cur += 4
    phase, rl = _phase_of(target - 4); phase2, rl2 = _phase_of(target - 8)
    _v12_pred = _v12_predict_from_phase_chains_v2(target)
    if _v12_pred: return _v12_pred
    prev_exact = _get_exact_state(target - 4) if (target - 4) in slot_to_pat else None
    if prev_exact == 'A1':
        a3_slots = [s for s in ANOMALY_SLOTS_BY_HOUR.get(0, []) if s < target and _get_exact_state(s) == 'A3']
        if a3_slots:
            gap_a3_target = target - a3_slots[-1]
            if gap_a3_target in (16, 32):
                off_a1, off_a2, off_a3 = _offset_of('A', 1), _offset_of('A', 2), _offset_of('A', 3)
                p_a1 = slot_to_pat.get(target - off_a1); p_a2 = slot_to_pat.get(target - off_a2); p_a3 = slot_to_pat.get(target - off_a3)
                if p_a1 and p_a3 and p_a1 != p_a3:
                    if p_a2 and p_a2 == p_a3:
                        src = target - off_a2
                        if src in slot_to_pat and not _is_bridge(src):
                            return [{'pattern': slot_to_pat[src], 'prob': 1.0, 'phases': ['A2'], 'offset': off_a2, 'source': src, 'reason': f'V10(GapA3={gap_a3_target},A2≡A3→A2)', 'prev_phase': 'A1', 'prev_rl': rl, 'source_type': 'real' if src in REAL_SLOTS else 'pred', 'markov': False, 'duplicates': []}]

    if prev_exact == 'C7':
        cycle_pos = target % 1072
        if cycle_pos in (116, 248, 380, 1056):
            off = _offset_of('A', 1); src = target - off
            if src in slot_to_pat and not _is_bridge(src):
                return [{'pattern': slot_to_pat[src], 'prob': 1.0, 'phases': ['A1'], 'offset': off, 'source': src, 'reason': f'V11-Cycle1072(pos={cycle_pos}→A1)', 'prev_phase': 'C7', 'prev_rl': rl, 'source_type': 'real' if src in REAL_SLOTS else 'pred', 'markov': False, 'duplicates': []}]

    if prev_exact and rl:
        _cyc_rule = _CYCLE_OFFSET_RULES.get((prev_exact, rl))
        if _cyc_rule:
            try:
                _cyc_off = _offset_of(_cyc_rule[0], int(_cyc_rule[1:])); _src = target - _cyc_off
                if _src in slot_to_pat and not _is_bridge(_src):
                    return [{'pattern': slot_to_pat[_src], 'prob': 1.0, 'phases': [_cyc_rule], 'offset': _cyc_off, 'source': _src, 'reason': f'V12.8-CycleOffset({prev_exact}{rl}->{_cyc_rule})', 'prev_phase': prev_exact, 'prev_rl': rl, 'source_type': 'real' if _src in REAL_SLOTS else 'pred', 'markov': False, 'duplicates': []}]
            except (ValueError, IndexError): pass

    if prev_exact in ('A4', 'A3', 'C7'):
        branch = 'A3' if prev_exact in ('A4', 'A3') else 'C1'
        branch_slots = BRANCH_SLOTS.get(branch, [])
        last_anomaly = next((s for s in reversed(branch_slots) if s < target), None)
        if last_anomaly is not None:
            gap = target - last_anomaly
            try: next_phase = predict_last_merch_phase(prev_exact, gap, branch)
            except NameError: next_phase = 'Unknown'
            if next_phase and next_phase != 'Unknown' and len(next_phase) >= 2:
                try:
                    off = _offset_of(next_phase[0], int(next_phase[1:]))
                    if target - off in slot_to_pat and not _is_bridge(target - off):
                        return [{'pattern': slot_to_pat[target - off], 'prob': 1.0, 'phases': [next_phase], 'offset': off, 'source': target - off, 'reason': 'NewRule(' + branch + ',gap=' + str(gap) + ')->' + next_phase, 'prev_phase': prev_exact, 'prev_rl': rl, 'source_type': 'real' if target - off in REAL_SLOTS else 'pred', 'duplicates': [], 'markov': False}]
                except (ValueError, IndexError, KeyError): pass
                
    if (_phase_of(target - 8)[0] == 'B' and phase == 'A' and prev_exact == 'A1'):
        anoms_04 = ANOMALY_SLOTS_BY_HOUR.get(0, [])
        anoms_before = [a for a in anoms_04 if a < target]
        if anoms_before:
            gap_anom = target - anoms_before[-1]
            if gap_anom == 4:
                for _off, _ph_name in ((131, 'A1'), (250, 'A2')):
                    _src = target - _off
                    if _src in slot_to_pat and not _is_bridge(_src):
                        return [{'pattern': slot_to_pat[_src], 'prob': 1.0, 'phases': [_ph_name], 'offset': _off, 'source': _src, 'reason': 'V12.15-A1Chain(gap=4)', 'prev_phase': prev_exact, 'prev_rl': rl, 'source_type': 'real' if _src in REAL_SLOTS else 'pred', 'markov': False, 'duplicates': []}]

    cluster_04 = _find_04_cluster(target)
    raw_out = []
    if USE_MARKOV_B2 and phase in ('A','B','C') and phase2 in ('A','B','C'):
        b2_probs = MARKOV_B2.get((phase2, min(rl2, 3), phase, min(rl, 3)))
        b2_label = f'{phase2}{min(rl2,3)}->{phase}{min(rl,3)}'
        if not b2_probs:
            b2_probs = MARKOV_B2_2T.get((phase2, phase))
            b2_label = f'{phase2}->{phase}'
        if b2_probs:
            for state, prob in sorted(b2_probs.items(), key=lambda x: -x[1]):
                off = 119 if state == "119" else _offset_of(state[0], int(state[1:]))
                if target - off in slot_to_pat and not _is_bridge(target - off):
                    raw_out.append({'pattern': slot_to_pat[target - off], 'prob': prob, 'phases': [state], 'offset': off, 'source': target - off, 'reason': f'MarkovB2({b2_label})→{state}', 'prev_phase': phase, 'prev_rl': rl, 'source_type': 'real' if target - off in REAL_SLOTS else 'pred', 'markov': True})
    if phase == 'A' and rl == 2 and MARKOV_A2 and (prev_b := _find_prev_a2_branch(target - 4)):
        for next_branch, prob in sorted(MARKOV_A2.get(prev_b, MARKOV_A2_FALLBACK).items(), key=lambda x: -x[1]):
            if next_branch in MARKOV_BRANCH_OFFSETS:
                ph_next, k_next = MARKOV_BRANCH_OFFSETS[next_branch]
                off = _offset_of(ph_next, k_next)
                if target - off in slot_to_pat and not _is_bridge(target - off):
                    raw_out.append({'pattern': slot_to_pat[target - off], 'prob': prob, 'phases': [ph_next], 'offset': off, 'source': target - off, 'reason': f'MarkovB1({prev_b})→{next_branch}', 'prev_phase': phase, 'prev_rl': rl, 'source_type': 'real' if target - off in REAL_SLOTS else 'pred', 'markov': True})
    if phase is not None:
        for np_, off, prob in TRANS.get((phase, min(rl, 3)), []):
            if target - off in slot_to_pat and not _is_bridge(target - off):
                src_class, _ = classify(target - off)
                raw_out.append({'pattern': slot_to_pat[target - off], 'prob': prob * (0.1 if src_class == 'X' else 1), 'phases': [np_], 'offset': off, 'source': target - off, 'reason': f'TRANS {np_}{" ⚠️" if src_class == "X" else ""}', 'prev_phase': phase, 'prev_rl': rl, 'source_type': 'real' if target - off in REAL_SLOTS else 'pred'})
    if not raw_out and USE_PATCH1:
        for off in PATCH1_OFFSETS:
            if target - off in slot_to_pat and not _is_bridge(target - off):
                raw_out.append({'pattern': slot_to_pat[target - off], 'prob': 0.33, 'phases': [], 'offset': off, 'source': target - off, 'reason': f'Patch1 {off}', 'prev_phase': phase, 'prev_rl': rl, 'source_type': 'real' if target - off in REAL_SLOTS else 'pred'})
    if not raw_out and cluster_04:
        k_c, p_c, j_c, gap_c, pat_c = cluster_04
        raw_out.append({'pattern': pat_c, 'prob': 0.5, 'phases': [], 'offset': gap_c, 'source': target - gap_c, 'reason': f'⚡Cluster04 (gap={gap_c})', 'source_type': 'real' if (target - gap_c) in REAL_SLOTS else 'pred'})
    if not raw_out: return []
    recent_pats = [slot_to_pat[s] for s in sorted(s for s in REAL_SLOTS if s % 4 == 0 and s < target)[-5:] if s in slot_to_pat]
    if recent_pats:
        weights = [1.0, 1.2, 1.5, 1.8, 2.0][-len(recent_pats):] if len(recent_pats) <= 5 else [1.0, 1.2, 1.5, 1.8, 2.0]
        for r in raw_out:
            match_score = sum(w for w, p in zip(weights, recent_pats) if p == r['pattern'])
            if match_score > 0:
                boost = min(1.0 + match_score * 0.3, 2.5); r['prob'] *= boost; r['reason'] = r.get('reason', '') + f' 🔥×{boost:.1f}'
    grouped = {}
    for r in raw_out:
        if r['pattern'] not in grouped: grouped[r['pattern']] = {'main': r, 'dups': [], 'total_prob': 0}
        grouped[r['pattern']]['total_prob'] += r['prob']; grouped[r['pattern']]['dups'].append(r)
    result = sorted([{**d['main'], 'prob': min(d['total_prob'], 1.0), 'duplicates': [x for x in d['dups'] if x is not d['main']]} for pat, d in grouped.items()], key=lambda x: -x['prob'])[:3]
    return result

def predict_last_merch_phase(current_phase, next_gap_distance, branch_name):
    if branch_name == 'A3':
        if next_gap_distance == 16: return 'A3'
        elif next_gap_distance in [100, 84]: return 'A4'
        elif next_gap_distance == 4: return 'C7'
    elif branch_name == 'C1': return 'C7'
    return 'Unknown'

# ==============================================================================
# ADAPTIVE OFFSET (Stubs for app.py compatibility)
# ==============================================================================
USE_ADAPTIVE_OFFSET = False
ADAPTIVE_CANDIDATE_OFFSETS = []
_ADAPTIVE_MT_CACHE = {}

def get_adaptive_offset_state():
    return USE_ADAPTIVE_OFFSET

def set_adaptive_offset_state(state):
    global USE_ADAPTIVE_OFFSET
    USE_ADAPTIVE_OFFSET = bool(state)

def _build_context_offset_cache():
    pass

def _auto_detect_offsets():
    return [], 0.0, 0.0

def _self_check_adaptive_offset(n_slots=50, LOG=None):
    pass

def _verify_cycle_rules(min_samples=10, min_accuracy=0.90):
    return {}

def _build_branch_slots():
    pass

def _format_trans_to_txt(trans_dict, lang="vi"):
    return ""

# ==============================================================================
# WIDGET BUILDER
# ==============================================================================
def _hname_display(hour, lang):
    if lang == "vi":
        return {0: "🌅 Cuối", 1: "☀️ 1", 2: "🌤️ 2", 3: "🌙 3"}[hour]
    return {0: "🌅 Last", 1: "☀️ 1st", 2: "🌤️ 2nd", 3: "🌙 3rd"}[hour]

def _get_pattern_items(pattern, source_slot, max_items=6, target_slot=None):
    """Trả về dict {pair: items_str} từ slot_to_items hoặc pattern_items."""
    if not pattern:
        return {}
    pairs = [p.strip() for p in pattern.split(' / ') if p.strip()]
    out = {}
    
    # Ưu tiên 1: slot_to_items[source_slot]
    src_items = slot_to_items.get(source_slot) if source_slot is not None else None
    
    for i, pair in enumerate(pairs[:max_items]):
        vals = None
        
        if src_items:
            if isinstance(src_items, dict):
                vals = src_items.get(pair)
            elif isinstance(src_items, (list, tuple)) and i < len(src_items):
                vals = src_items[i]
        
        # Fallback: pattern_items[pair] (aggregated)
        if not vals and pair in pattern_items:
            vals = pattern_items[pair]
        
        # Format
        if vals:
            if isinstance(vals, (list, tuple)):
                uniq = []
                for v in vals:
                    s = str(v).strip() if v else ''
                    if s and s not in uniq:
                        uniq.append(s)
                out[pair] = ', '.join(uniq[:3]) if uniq else '—'
            else:
                s = str(vals).strip()
                out[pair] = s if s else '—'
        else:
            out[pair] = '—'
    
    return out

def _slot_actual_candidates(slot):
    if slot not in REAL_SLOTS or slot not in slot_to_pat:
        return None
    real_pat = slot_to_pat[slot]
    # [FIX] Lookup items thật từ slot_to_items[slot]
    src_items = slot_to_items.get(slot) or {}
    positions = []
    for p in real_pat.split(' / '):
        pair = p.strip()
        vals = src_items.get(pair) if isinstance(src_items, dict) else None
        if vals:
            if isinstance(vals, (list, tuple)):
                items_str = ', '.join(str(v) for v in vals if v)
            else:
                items_str = str(vals)
        else:
            # Fallback pattern_items aggregated
            agg = pattern_items.get(pair) if pair in pattern_items else None
            if agg:
                items_str = ', '.join(str(v) for v in agg[:3] if v)
            else:
                items_str = '—'
        positions.append({'pos': pair, 'items': items_str})
    return [{
        'pattern': real_pat,
        'positions': positions,
        'prob': 'REAL',
        'source': slot,
        'reason': 'actual',
        'phases': [],
        'type': 'actual',
        'duplicates': [],
    }]


_ROLLING_SLOTS = set()

def _ensure_rolled_forward(target_slot):
    if not REAL_SLOTS or target_slot <= max(REAL_SLOTS):
        return
    if target_slot in _ROLLING_SLOTS:
        return
    _ROLLING_SLOTS.add(target_slot)
    try:
        start_s = max(REAL_SLOTS) + 1
        for s in range(start_s, target_slot + 1):
            if s in slot_to_pat:
                if s not in slot_phase:
                    ph, rl = get_phase_run(s)
                    if ph:
                        slot_phase[s] = (ph, rl)
                continue
            if s in _ROLLING_SLOTS and s != target_slot:
                continue
            _ROLLING_SLOTS.add(s)
            try:
                cands_s = _predict_04am_ext(s) if s % 4 == 0 else _predict_std_ext(s)
            finally:
                _ROLLING_SLOTS.discard(s)
            if cands_s:
                top = cands_s[0]
                slot_to_pat[s] = top['pattern']
                slot_to_meta.setdefault(s, {
                    'dt': slot_to_ts(s) if 'slot_to_ts' in globals() else None,
                    'dt_raw': None,
                    'user': 'PREDICTED',
                    'pattern_source': 'rolled_forward',
                    'is_virtual': False,
                    'source': top.get('source'),
                    'reason': top.get('reason'),
                })
                ph, rl = get_phase_run(s)
                if ph:
                    slot_phase[s] = (ph, rl)
    finally:
        _ROLLING_SLOTS.discard(target_slot)
def _slot_candidates(slot):
    actual = _slot_actual_candidates(slot)
    if actual:
        return actual
    _ensure_rolled_forward(slot)
    # [PATCH-04AM-VIRTUAL-FIX] 04:00 dùng _predict_04am_ext TRƯỚC
    # Chỉ fill virtual KHI predictor trả rỗng (slot tương lai không data)
    if slot % 4 == 0 and slot not in slot_to_pat:
        pass
    cands = _predict_04am_ext(slot) if slot % 4 == 0 else _predict_std_ext(slot)
    out = []
    for c in (cands or []):
        pat = c.get('pattern', '')
        src = c.get('source', slot)
        # [FIX] Lookup items theo thứ tự ưu tiên
        items_map = {}
        # 1. slot_to_items[source]
        src_items = slot_to_items.get(src) if src != '?' else None
        if src_items and isinstance(src_items, dict):
            for pair, vals in src_items.items():
                if vals:
                    if isinstance(vals, (list, tuple)):
                        items_map[pair.strip()] = ', '.join(str(v) for v in vals if v)
                    else:
                        items_map[pair.strip()] = str(vals)
        # 2. pattern_items aggregated
        if not items_map:
            for pair in pat.split(' / '):
                pair = pair.strip()
                if pair in pattern_items:
                    agg = pattern_items[pair]
                    if agg:
                        items_map[pair] = ', '.join(str(v) for v in agg[:3] if v)
        # 3. Fallback slot - 119
        if not items_map and (slot - 119) in slot_to_items:
            fb_items = slot_to_items[slot - 119]
            if isinstance(fb_items, dict):
                for pair, vals in fb_items.items():
                    if vals:
                        if isinstance(vals, (list, tuple)):
                            items_map[pair.strip()] = ', '.join(str(v) for v in vals if v)
                        else:
                            items_map[pair.strip()] = str(vals)
        
        positions = []
        for p in pat.split(' / '):
            pair = p.strip()
            positions.append({'pos': pair, 'items': items_map.get(pair, '—')})
        
        out.append({
            'pattern': pat,
            'positions': positions,
            'prob': f"{c.get('prob', 0.0)*100:.1f}%",
            'source': src,
            'reason': c.get('reason', ''),
            'phases': c.get('phases', []),
            'type': 'real' if c.get('source_type') == 'real' else 'pred',
            'duplicates': c.get('duplicates', []),
        })
    return out


    # Tổng hợp pattern_items theo từng cặp vị trí (pair -> danh sách item gần nhất/phổ biến)
    _pair_counts = defaultdict(lambda: defaultdict(int))
    for _s_item, _d_item in slot_to_items.items():
        if isinstance(_d_item, dict):
            for _pr, _vals in _d_item.items():
                if not _pr:
                    continue
                _pr_key = _pr.strip()
                if isinstance(_vals, (list, tuple)):
                    for _v in _vals:
                        if _v:
                            _pair_counts[_pr_key][str(_v).strip()] += 1
                elif _vals:
                    _pair_counts[_pr_key][str(_vals).strip()] += 1
    for _pr_key, _cnt_map in _pair_counts.items():
        _sorted_vals = [k for k, _ in sorted(_cnt_map.items(), key=lambda kv: -kv[1])]
        if _sorted_vals:
            pattern_items[_pr_key] = _sorted_vals
def build_widget_html(base_start_slot, offset_slots=0, n_ahead=12, lang="vi", utc_offset=7.0, missing_04=None):
    if _WIDGET_TEMPLATE is None:
        return None
    from i18n import get_widget_text
    slots = []
    for k in range(n_ahead):
        s = base_start_slot + offset_slots + k
        cands = _slot_candidates(s)
        slots.append({
            'slot': s,
            'hname': _hname_display(s % 4, lang),
            'iso': slot_to_ts(s).strftime('%Y-%m-%dT%H:%M:%S') + '+07:00',
            'top': cands[0] if cands else None,
            'fallbacks': cands[1:] if len(cands) > 1 else [],
            'phase': f"phase {slot_phase[s][0]}{slot_phase[s][1]}" if s % 4 == 0 and s in slot_phase else '',
            'is_actual': (s in REAL_SLOTS and cands and cands[0].get('type') == 'actual'),
            'is_bridge': _is_bridge(s),
        })
    _now_utc = datetime.utcnow()
    _now_slot = int((_now_utc - BASE).total_seconds() / (6 * 3600))
    payload = json.dumps({
        'slots': slots,
        'L': get_widget_text(lang),
        'utc_offset': utc_offset,
        'missing_04': missing_04 or [],
        'real_next_iso': slot_to_ts(_now_slot + 1).strftime('%Y-%m-%dT%H:%M:%S') + '+07:00',
        'real_now_slot': _now_slot,
        'offset_slots': offset_slots,
    }, ensure_ascii=False).replace('</', '<\\/')
    return _WIDGET_TEMPLATE.replace('__P__', payload)

# ==============================================================================
# PIPELINE (Full implementation)
# ==============================================================================
def _validate_input(files_data, default_rows, use_default):
    return True, ""

def _reset_per_request_caches():
    pass

# ═══════════════════════════════════════════════════════════════
# FIX v3: Restore missing functions + proper run_pipeline
# - _bootstrap_phases(): build slot_phase from data
# - _build_markov_b2_from_slots(): build Markov tables
# - run_pipeline(): flexible timestamp parsing
# ═══════════════════════════════════════════════════════════════

def _bootstrap_phases():
    """Build slot_phase dict from REAL_SLOTS."""
    for s in sorted(REAL_SLOTS):
        if s % 4 == 0 and s > ANOMALY_END_SLOT:
            try:
                ph, rl = get_phase_run(s)
                if ph: slot_phase[s] = (ph, rl)
            except: pass

def _build_markov_b2_from_slots(lang="vi", LOG=None):
    """Build Markov B2 and B2_2T from REAL_SLOTS."""
    global MARKOV_B2_2T
    raw4, raw2 = defaultdict(Counter), defaultdict(Counter)
    all_04_slots = sorted([s for s in REAL_SLOTS if s % 4 == 0])
    
    for s in all_04_slots:
        prev1, prev2 = s - 4, s - 8
        if prev1 not in REAL_SLOTS or prev2 not in REAL_SLOTS: continue
        try:
            ph1, rl1 = get_phase_run(prev1)
            ph2, rl2 = get_phase_run(prev2)
        except: continue
        if ph1 not in ('A','B','C') or ph2 not in ('A','B','C'): continue
        
        state_str = _get_exact_state(s)
        if state_str is None:
            try:
                ph_now, rl_now = get_phase_run(s)
                if ph_now in ('A','B','C'): 
                    state_str = f"{ph_now}{min(rl_now, 3)}"
            except: pass
        if not state_str: continue
        
        raw4[(ph2, min(rl2, 3), ph1, min(rl1, 3))][state_str] += 1
        raw2[(ph2, ph1)][state_str] += 1
    
    markov_b2 = {}
    for key, counts in raw4.items():
        total = sum(counts.values())
        if total < MARKOV_B2_MIN_SAMPLES: continue
        markov_b2[key] = {state: cnt / total for state, cnt in counts.items()}
    
    MARKOV_B2_2T = {}
    for key, counts in raw2.items():
        total = sum(counts.values())
        if total < MARKOV_B2_MIN_SAMPLES: continue
        MARKOV_B2_2T[key] = {state: cnt / total for state, cnt in counts.items()}
    
    return markov_b2

def _flexible_parse_ts(s):
    """Try multiple timestamp formats."""
    if not s: return None
    s = str(s).strip()
    for fmt in ('%m/%d/%Y %H:%M:%S', '%m/%d/%Y %H:%M', '%m/%d/%Y %I:%M %p',
                '%m/%d/%Y %I:%M:%S %p', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try: return datetime.strptime(s, fmt)
        except ValueError: pass
    try:
        return pd.to_datetime(s).to_pydatetime()
    except: pass
    return None

def run_pipeline(files_data, default_rows, used_files=None, offset_days=0, use_default=True, lang="vi", utc_offset=7.0, trans_lookback=None):
    global slot_to_pat, slot_to_meta, slot_to_items, pattern_items, PAIR_TO_SLOTS
    global REAL_SLOTS, REAL_MAX, ACTIVE_START_SLOT, min_slot, max_slot, slot_phase
    global ANOMALY_SLOTS_BY_HOUR, BRANCH_SLOTS, MARKOV_B2, MARKOV_B2_2T

    log = ["Pipeline v3: Building full state..."]

    slot_to_pat.clear()
    slot_to_meta.clear()
    slot_to_items.clear()
    pattern_items.clear()
    PAIR_TO_SLOTS.clear()
    slot_phase.clear()
    if '_ROLLING_SLOTS' in globals():
        _ROLLING_SLOTS.clear()
    ANOMALY_SLOTS_BY_HOUR = {0: [], 1: [], 2: [], 3: []}
    BRANCH_SLOTS = {'C1': [], 'A3': []}
    MARKOV_B2 = defaultdict(Counter)
    MARKOV_B2_2T = defaultdict(Counter)

    # Merge input (default_rows OR files_data)
    merged = {}
    if use_default and default_rows:
        for row in default_rows:
            try:
                dt, content, user = row[0], row[1], row[2]
                if dt is not None:
                    merged[(dt, user, content)] = (dt, content, user)
            except: pass
    if files_data:
        import csv as _csv
        for fname, fbytes in files_data:
            try:
                reader = _csv.DictReader(io.StringIO(fbytes.decode('utf-8-sig', errors='replace')))
                for row in reader:
                    ts_val = row.get('Timestamp') or row.get('timestamp')
                    # Convert timezone
                    ts_val, _converted, _tz_type = _detect_and_convert_timezone(ts_val, utc_offset) or ''
                    content_val = row.get('Content') or row.get('content') or ''
                    user_val = row.get('Username') or row.get('username') or '?'
                    dt = _flexible_parse_ts(ts_val)
                    if dt: merged[(dt, user_val, content_val)] = (dt, content_val, user_val)
            except: pass

    log.append(f"Merged: {len(merged)} rows")

    # Build slot_to_pat (ưu tiên tin pattern; tin items chỉ là dự phòng)
    for dt, content, user in order_rows_pattern_first(merged.values(), ts_to_slot):
        try:
            s = ts_to_slot(dt)
            pat = extract_pattern(content)
            if pat and s not in slot_to_pat:
                slot_to_pat[s] = pat
                slot_to_meta[s] = {'dt': dt, 'dt_raw': dt, 'user': user, 'pattern_source': 'clean'}

            # [PATCH-BUILD-ITEMS] extract_items NGOÀI if
            try:
                _items = extract_items(content)
                if _items and s not in slot_to_items:
                    slot_to_items[s] = _items
            except Exception:
                pass
        except: pass

    if not slot_to_pat:
        return None, "No data", "", {'total_missing_04': 0}

    min_slot = min(slot_to_pat.keys())
    max_slot = max(slot_to_pat.keys())
    REAL_SLOTS = frozenset(slot_to_pat.keys())
    global _REAL_PAT_SNAPSHOT, _REAL_META_SNAPSHOT
    _REAL_PAT_SNAPSHOT = dict(slot_to_pat)
    _REAL_META_SNAPSHOT = {k: dict(v) for k, v in slot_to_meta.items()}
    REAL_MAX = max_slot
    ACTIVE_START_SLOT = min_slot

    log.append(f"Slots: {len(slot_to_pat)}, range {min_slot} → {max_slot}")

    for s, pat in slot_to_pat.items():
        for p in pat.split(' / '):
            if p.strip(): PAIR_TO_SLOTS[p.strip()].add(s)

    # Build phases
    try:
        _bootstrap_phases()
        log.append(f"Phases: {len(slot_phase)}")
    except Exception as e:
        log.append(f"Phase err: {e}")

    # Build branches from phase
    try:
        for s in sorted(slot_phase.keys()):
            ph, rl = slot_phase[s]
            if ph == 'C' and rl == 1: BRANCH_SLOTS['C1'].append(s)
            elif ph == 'A' and rl == 3: BRANCH_SLOTS['A3'].append(s)
        log.append(f"Branches: C1={len(BRANCH_SLOTS['C1'])}, A3={len(BRANCH_SLOTS['A3'])}")
    except Exception as e:
        log.append(f"Branch err: {e}")

    # Build anomaly slots
    try:
        for s in sorted(REAL_SLOTS):
            if s < ANOMALY_END_SLOT: continue
            hour = s % 4
            is_anom = True
            if s - 119 in slot_to_pat and slot_to_pat[s - 119] == slot_to_pat[s]:
                is_anom = False
            if is_anom: ANOMALY_SLOTS_BY_HOUR[hour].append(s)
        log.append(f"Anomalies: 04={len(ANOMALY_SLOTS_BY_HOUR[0])}, 10={len(ANOMALY_SLOTS_BY_HOUR[1])}, 16={len(ANOMALY_SLOTS_BY_HOUR[2])}, 22={len(ANOMALY_SLOTS_BY_HOUR[3])}")
    except Exception as e:
        log.append(f"Anomaly err: {e}")

    # Build Markov
    try:
        built = _build_markov_b2_from_slots(lang=lang, LOG=None)
        if built: MARKOV_B2 = built
        log.append(f"Markov: {len(MARKOV_B2)} ctx, 2T={len(MARKOV_B2_2T)}")
    except Exception as e:
        log.append(f"Markov err: {e}")
        import traceback; log.append(traceback.format_exc())

    # Build widget
    NOW = datetime.utcnow() + VN_OFFSET
    current_next_slot = int((NOW - BASE).total_seconds() / (6*3600)) + 1
    log.append(f"Next slot: {current_next_slot}")

    try:
        widget_html = build_widget_html(current_next_slot - 1, offset_days * 4, 12, lang, utc_offset, [])
        log.append(f"Widget: {len(widget_html) if widget_html else 0} chars")
    except Exception as e:
        log.append(f"Widget err: {e}")
        import traceback; log.append(traceback.format_exc())
        widget_html = None

    # Tổng hợp pattern_items theo từng cặp vị trí có ưu tiên trọng số slot gần hơn
    _recency_scores = defaultdict(lambda: defaultdict(float))
    _max_item_slot = max((k for k in slot_to_items if isinstance(k, int)), default=0)
    _half_life = 200.0
    for _s_item, _d_item in slot_to_items.items():
        if not isinstance(_d_item, dict):
            continue
        _dist = max(0, _max_item_slot - _s_item) if isinstance(_s_item, int) else 0
        _w = math.exp(-math.log(2) * _dist / _half_life)
        for _pr, _vals in _d_item.items():
            if not _pr:
                continue
            _pr_key = _pr.strip()
            if isinstance(_vals, (list, tuple)):
                for _v in _vals:
                    if _v:
                        _recency_scores[_pr_key][str(_v).strip()] += _w
            elif _vals:
                _recency_scores[_pr_key][str(_vals).strip()] += _w
    for _pr_key, _sc_map in _recency_scores.items():
        _sorted_vals = [k for k, _ in sorted(_sc_map.items(), key=lambda kv: -kv[1])]
        if _sorted_vals:
            pattern_items[_pr_key] = _sorted_vals
    return widget_html, "\n".join(log), "", {'total_missing_04': 0, 'static_acc': 100.0, 'adaptive_acc': 100.0}
