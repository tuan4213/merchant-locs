# predictor.py — Prediction logic (Markov, TRANS, run_pipeline)
import csv, re, io, json, os, glob, subprocess, time
import hashlib
import threading
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from pathlib import Path
from github import Github, Auth

_PIPELINE_LOCK = threading.RLock()

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

REPO_NAME = "tuanlt4213/Fortress-Saga-IDLE-Merchant-Location"

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
        if cand in row_keys_lower:
            return row_keys_lower[cand]
    for cand in candidates:
        for k_low, k_orig in row_keys_lower.items():
            if cand in k_low or k_low in cand:
                return k_orig
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

_base_str = _kp.get('BASE_TIME_STR', '2025-01-01 04:00:00')
try:
    BASE = datetime.strptime(_base_str, '%Y-%m-%d %H:%M:%S')
except ValueError:
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
LAST_TRANS_STATS = {
    'static_acc': 0.0, 'adaptive_acc': 0.0, 'was_overridden': False, 
    'train_size': 0, 'test_size': 0, 'lookback_requested': 0, 'lookback_used': 0,
    'missing_04': [], 'total_missing_04': 0
}

def _format_trans_to_txt(trans_dict, lang="vi"):
    lines = [f"# TRANS AUTO-UPDATED BY AI" if lang == "en" else f"# TRANS TỰ ĐỘNG CẬP NHẬT BỞI AI", f"# Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}" if lang == "en" else f"# Thời gian: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ""]
    for (phase, rl), entries in sorted(trans_dict.items()):
        for state, off, prob in entries: lines.append(f"{phase}{rl} -> {state} {prob*100:.1f}%")
    return "\n".join(lines)

def parse_ts(s):
    for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %I:%M:%S %p", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try: return datetime.strptime(s.strip(), fmt)
        except ValueError: pass
    return None

def ts_to_slot(dt): return round((dt - BASE).total_seconds() / 3600 / 6)
def slot_to_ts(slot): return BASE + timedelta(hours=slot * 6)
def _is_bridge(slot): return slot_to_meta.get(slot, {}).get('is_bridge', False)

def _hname_display(hour, lang):
    if lang == "vi": return {0: "🌅 Cuối — Trước Reset", 1: "☀️ 1 — Sau Reset", 2: "🌤️ 2 — Chiều", 3: "🌙 3 — Tối"}[hour]
    else: return {0: "🌅 Last — Before Reset", 1: "☀️ 1st — After Reset", 2: "🌤️ 2nd — Afternoon", 3: "🌙 3rd — Night"}[hour]

def _detect_mod6_offset(parsed):
    cm = Counter(((dt.hour % 6)*60 + dt.minute) for dt, _ in parsed if dt is not None)
    if not cm: return 0
    peak = cm.most_common(1)[0][0]
    near = {m: c for m, c in cm.items() if abs(m - peak) <= 60}
    pf = sum(m*c for m, c in near.items()) / sum(near.values())
    return round((((pf - 240 + 180) % 360) - 180) / 60 * 2) / 2

def _trans_anomaly_rate(parsed, offset):
    slots = {}
    for dt, pat in parsed:
        if dt is not None and pat:
            s = ts_to_slot(dt + timedelta(hours=offset))
            if s >= ACTIVE_START_SLOT: slots[s] = pat
    if len(slots) < 200: return None
    def cls(s):
        p = slots.get(s)
        if not p: return None
        for k in range(1, 25):
            if slots.get(s - 119*k) == p: return '119'
        for o, ph in KEY_OFFSETS.items():
            if slots.get(s - o) == p: return ph
        return 'X'
    anom = tot = 0
    for s in sorted(slots):
        if s % 4 != 0 or s <= ANOMALY_END_SLOT or (s-4) not in slots: continue
        pt = cls(s - 4)
        if pt not in ('A','B','C'): continue
        rl = 1; c = s - 4
        while (c-4) in slots and cls(c-4) == pt: rl += 1; c -= 4
        tr = TRANS.get((pt, min(rl, 3)), [])
        if not tr: continue
        tot += 1
        if slots.get(s) not in {slots[s-o] for _, o, _ in tr if (s-o) in slots}: anom += 1
    return anom / tot if tot else None

def detect_csv_timezone(parsed):
    if sum(1 for dt, _ in parsed if dt is not None) < 300: return 0.0
    m6 = _detect_mod6_offset(parsed)
    temp_slots = {}
    for dt, pat in parsed:
        if dt is not None and pat:
            temp_slots[ts_to_slot(dt + timedelta(hours=m6))] = pat
    results = []
    for shift in range(4):
        c119 = tot = 0
        for s, pat in temp_slots.items():
            if s % 4 == shift:
                tot += 1
                if temp_slots.get(s - 119) == pat: c119 += 1
        results.append((shift, c119/tot if tot else 1.0, tot))
    results.sort(key=lambda x: x[1])
    best_offset = m6 + results[0][0] * 6
    trans_rate = _trans_anomaly_rate(parsed, best_offset)
    return (best_offset if trans_rate is None else (best_offset if trans_rate <= 0.45 else 0.0))

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
        
    pat_first2 = get_first_2_pairs(pat)
    for k in range(1, 25):
        prev = slot - 119 * k
        if prev in slot_to_pat and not _is_bridge(prev) and get_first_2_pairs(slot_to_pat[prev]) == pat_first2:
            return '119', 119 * k
    for off, phase in KEY_OFFSETS.items():
        prev = slot - off
        if prev in slot_to_pat and not _is_bridge(prev) and get_first_2_pairs(slot_to_pat[prev]) == pat_first2:
            return phase, off
    return 'X', None

def _get_exact_state(s):
    if s not in slot_to_pat: return None
    ph_cls, off_cls = classify(s)
    if ph_cls == '119': return '119'
    if ph_cls in ('A','B','C'):
        for k_val in K_ACTIVE.get(ph_cls, []):
            if _offset_of(ph_cls, k_val) == off_cls: return f"{ph_cls}{k_val}"
    return None

def _is_anomaly_slot(s):
    if s not in slot_to_pat or s not in REAL_SLOTS: return False
    for k in range(1, 25):
        if slot_to_pat.get(s - 119*k) == slot_to_pat[s]: return False
    return True

def _is_anomaly_04(s):
    if s not in slot_to_pat or s not in REAL_SLOTS or s % 4 != 0: return False
    prev = s - 4
    if prev not in slot_to_pat: return False
    phase, rl = _phase_of(prev)
    if phase not in ('A', 'B', 'C'): return False
    tr = TRANS.get((phase, min(rl, 3)), [])
    if not tr: return False
    return slot_to_pat[s] not in {slot_to_pat[s - off] for _, off, _ in tr if (s - off) in slot_to_pat}

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

def find_regime_shift():
    global ACTIVE_START_SLOT
    streak, break_slot = 0, None
    for s in sorted(s for s in REAL_SLOTS if s % 4 == 0)[-1000:]:
        if s - 4 not in slot_to_pat: continue
        phase, rl = get_phase_run(s - 4)
        if phase not in ('A','B','C'): continue
        tr = TRANS.get((phase, min(rl, 3)), [])
        if slot_to_pat[s] not in {slot_to_pat[s-o] for _, o, _ in tr if (s-o) in slot_to_pat}:
            streak += 1
            if streak >= 20: break_slot = s; break
        else: streak = 0
    if break_slot: ACTIVE_START_SLOT = break_slot - 1000

def init_dynamic_cycles():
    global DYNAMIC_OFFSETS
    DYNAMIC_OFFSETS = []

def _bootstrap_phases():
    for s in sorted(REAL_SLOTS):
        if s % 4 == 0 and s > ANOMALY_END_SLOT:
            ph, rl = get_phase_run(s)
            if ph: slot_phase[s] = (ph, rl)

def _phase_of(slot):
    if slot in slot_phase: return slot_phase[slot]
    if slot in REAL_SLOTS:
        ph, rl = get_phase_run(slot)
        if ph: slot_phase[slot] = (ph, rl); return ph, rl
    return None, 0

def build_markov_from_data():
    global MARKOV_A2
    if MARKOV_A2_CFG: return dict(MARKOV_A2_CFG)
    slots_04 = sorted(s for s in REAL_SLOTS if s % 4 == 0 and s > ANOMALY_END_SLOT and s >= MIN_STABLE_SLOT)
    slots_set = set(slots_04)
    branches = []
    for s in slots_04:
        if s + 4 not in slots_set: continue
        ph1, rl1 = get_phase_run(s)
        if ph1 != 'A' or rl1 != 2: continue
        ph2, rl2 = get_phase_run(s + 4)
        if ph2 == 'C' and rl2 == 1: branches.append((s, 'C1'))
        elif ph2 == 'A' and rl2 == 3: branches.append((s, 'A3'))
    trans = defaultdict(Counter)
    for i in range(len(branches) - 1): trans[branches[i][1]][branches[i+1][1]] += 1
    return {from_b: {b: c/sum(counts.values()) for b, c in counts.items()}
            for from_b, counts in trans.items() if sum(counts.values()) >= MIN_MARKOV_SAMPLES}

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

def _build_markov_b2_from_slots(lang="vi", LOG=None):
    global MARKOV_B2_2T
    LOG = LOG or PipelineLogger()
    LOG.section("BUILD MARKOV B2 (2 Phases + run-length)")
    raw4, raw2 = defaultdict(Counter), defaultdict(Counter)
    all_04_slots = sorted([s for s in REAL_SLOTS if s % 4 == 0])
    
    exact_hits = fallback_hits = skipped = 0
    for s in all_04_slots:
        prev1, prev2 = s - 4, s - 8
        if prev1 not in REAL_SLOTS or prev2 not in REAL_SLOTS: skipped += 1; continue
        ph1, rl1 = get_phase_run(prev1); ph2, rl2 = get_phase_run(prev2)
        if ph1 not in ('A','B','C') or ph2 not in ('A','B','C'): skipped += 1; continue
        state_str = _get_exact_state(s)
        if state_str: exact_hits += 1
        else:
            ph_now, rl_now = get_phase_run(s)
            if ph_now in ('A','B','C'): state_str = f"{ph_now}{min(rl_now, 3)}"; fallback_hits += 1
        if not state_str: skipped += 1; continue
        raw4[(ph2, min(rl2, 3), ph1, min(rl1, 3))][state_str] += 1
        raw2[(ph2, ph1)][state_str] += 1
    
    markov_b2, dropped_4t = {}, 0
    for key, counts in raw4.items():
        total = sum(counts.values())
        if total < MARKOV_B2_MIN_SAMPLES: dropped_4t += 1; continue
        markov_b2[key] = {state: cnt / total for state, cnt in counts.items()}

    MARKOV_B2_2T, dropped_2t = {}, 0
    for key, counts in raw2.items():
        total = sum(counts.values())
        if total < MARKOV_B2_MIN_SAMPLES: dropped_2t += 1; continue
        MARKOV_B2_2T[key] = {state: cnt / total for state, cnt in counts.items()}

    return markov_b2

REGULAR_GAP_PATTERN = [16, 116, 16, 116, 16, 116, 16, 116, 16, 116, 16, 132, 132, 132]
SESSION_START_OFFSET = {}
MACRO_CYCLE = 1072
EXTRA_ANOMALY_POSITIONS = {1: [157], 2: [814], 3: [399]}

def _predict_next_gap(hour):
    anoms = ANOMALY_SLOTS_BY_HOUR.get(hour, [])
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
        if st in candidates:
            return [REGULAR_GAP_PATTERN[(st + n) % 14]]
    last = recent[-1]
    if last == 16: return [116]
    elif last == 116: return [16]
    elif last == 132:
        c = sum(1 for g in reversed(recent) if g == 132)
        return [16] if c >= 3 else [132]
    best_st, best_score = 0, 0
    for st in range(14):
        score = sum(1 for i in range(n) if recent[i] == REGULAR_GAP_PATTERN[(st+i) % 14])
        if score > best_score:
            best_score, best_st = score, st
    if n > 0 and best_score / n >= 0.85:
        return [REGULAR_GAP_PATTERN[(best_st + n) % 14]]
    return [116 if last == 16 else (16 if last == 116 else 132)]

def _get_anomaly_risk(target_slot):
    hour = target_slot % 4
    if hour == 0: return False
    anoms = ANOMALY_SLOTS_BY_HOUR.get(hour, [])
    if not anoms: return False
    if hour in EXTRA_ANOMALY_POSITIONS:
        pos = target_slot % MACRO_CYCLE
        if pos in EXTRA_ANOMALY_POSITIONS[hour]:
            return True
    diff = target_slot - anoms[-1]
    if diff <= 0: return False
    if diff in (116, 132):
        return True
    if diff == 16:
        predicted = _predict_next_gap(hour)
        if predicted is None: return True
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
            if (target + 132) % 1072 == EXTRA_POS[hour]:
                is_ghost_gap = True

    for off, reason in offsets:
        src = target - off
        if src in slot_to_pat and not _is_bridge(src):
            src_class, _ = classify(src)
            
            if off == 119:
                has_119 = True
                if is_ghost_gap:
                    prob = 0.60
                else:
                    prob = 0.05 if is_risk else (0.95 if src_class != 'X' else 0.50)
            elif off in DYNAMIC_OFFSETS:
                prob = 0.80
            elif 'Phase A' in reason:
                if is_ghost_gap:
                    prob = 0.40
                else:
                    prob = 0.95 if is_risk else 0.10
            else:
                prob = 0.017
            
            raw_out.append({
                'prob': prob, 'offset': off, 'source': src, 'pattern': slot_to_pat[src], 
                'reason': reason, 'source_type': 'real' if src in REAL_SLOTS else 'pred'
            })

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
_CYCLE_OFFSET_RULES_ORIGINAL = dict(_CYCLE_OFFSET_RULES)
_CYCLE_RULE_STATS = {}

def _predict_04am_ext(target):
    global MARKOV_B2, MARKOV_B2_2T
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

def extend_predictions(target_slot):
    for t in range(REAL_MAX + 1, target_slot + 1):
        cands = (_predict_04am_ext(t) if t % 4 == 0 else _predict_std_ext(t)) or _predict_std_ext(t)
        if not cands: continue
        best = cands[0]
        slot_to_pat[t] = best['pattern']; slot_to_meta[t] = {'dt': slot_to_ts(t), 'dt_raw': None, 'user': f"←src{best['source']}", 'source': best['source'], 'source_type': best.get('source_type', 'real'), 'probability': best.get('prob', 0.99)}
        if t % 4 == 0:
            if not (phases := best.get('phases', [])):
                ph, rl = _phase_of(t - 4); slot_phase[t] = (ph, (rl or 1) + 1) if ph else ('?', 1)
            else:
                ph = phases[0]; slot_phase[t] = (ph, slot_phase[t-4][1] + 1) if t-4 in slot_phase and slot_phase[t-4][0] == ph else (ph, 1)

def _complete_crowns(items_map_lists, pattern, target_slot=None, min_siblings=1, threshold=1.0):
    if not items_map_lists or not pattern: return items_map_lists
    if not any('Crown' in items for items in items_map_lists.values()): return items_map_lists
    siblings = [s for s, p in slot_to_pat.items() if p == pattern and s in slot_to_items and s != target_slot]
    if not siblings: return items_map_lists
    result = {k: list(v) for k, v in items_map_lists.items()}
    for pos, items in items_map_lists.items():
        if 'Crown' not in items: continue
        sib_crowns = Counter()
        for s in siblings:
            for it in slot_to_items.get(s, {}).get(pos, []):
                if 'Crown' in it and it != 'Crown': sib_crowns[it] += 1
        total = sum(sib_crowns.values())
        if total < min_siblings: continue
        top_crown, top_cnt = sib_crowns.most_common(1)[0]
        if top_cnt / total >= threshold:
            result[pos] = [top_crown if x == 'Crown' else x for x in items]
    return result

def _complete_essences(items_map_lists, pattern):
    if not items_map_lists or not pattern or not any('Ess' in v for v in items_map_lists.values()): return items_map_lists
    same_pat_slots = [s for s, pat in slot_to_pat.items() if pat == pattern and s in slot_to_items]
    if not same_pat_slots: return items_map_lists
    result = {k: list(v) for k, v in items_map_lists.items()}
    for pos, items_list in items_map_lists.items():
        if 'Ess' not in items_list: continue
        for s in same_pat_slots:
            specific = [x for x in slot_to_items.get(s, {}).get(pos, []) if x.startswith('Ess of ')]
            if specific:
                new_list = []
                for x in items_list:
                    if x == 'Ess': new_list.extend(specific)
                    else: new_list.append(x)
                seen = set()
                result[pos] = [x for x in new_list if not (x in seen or seen.add(x))]
                break
    return result

def _get_pattern_items(pattern, source_slot, max_items=6, target_slot=None):
    if not pattern or pattern == '?': return {}
    if not isinstance(source_slot, int): source_slot = None
    raw_lists = slot_to_items.get(source_slot) if source_slot and slot_to_pat.get(source_slot) == pattern and source_slot in slot_to_items else next((m for s, m in reversed(pattern_items.get(pattern, [])) if m), None)
    if raw_lists is None:
        match_slot = find_slot_by_first_2_pairs(pattern, PAIR_TO_SLOTS, slot_to_items, slot_to_pat, target_slot=target_slot or source_slot)
        raw_lists = slot_to_items.get(match_slot, {}) if match_slot is not None else None
    if raw_lists is None: return {p.strip(): '—' for p in pattern.split(' / ')}
    completed = _complete_essences(raw_lists, pattern)
    completed = _complete_crowns(completed, pattern, target_slot=target_slot or source_slot)
    return {p.strip(): ', '.join(completed.get(p.strip(), [])[:max_items]) if completed.get(p.strip()) else '—' for p in pattern.split(' / ')}

def _slot_actual_candidates(slot):
    if slot not in REAL_SLOTS or not (real_pat := slot_to_pat.get(slot)): return None
    items_map = slot_to_items.get(slot, {})
    if not items_map and (match_slot := find_slot_by_first_2_pairs(real_pat, PAIR_TO_SLOTS, slot_to_items, slot_to_pat, target_slot=slot)) is not None and match_slot != slot:
        items_map = slot_to_items.get(match_slot, {})
    completed = _complete_essences(items_map, real_pat)
    completed = _complete_crowns(completed, real_pat, target_slot=slot)
    return [{'pattern': real_pat, 'positions': [{'pos': p.strip(), 'items': ', '.join(completed.get(p.strip(), [])[:6]) if completed.get(p.strip()) else '—'} for p in real_pat.split(' / ')], 'prob': 'REAL', 'source': slot, 'reason': 'actual', 'phases': [], 'type': 'actual', 'duplicates': []}]

def _slot_candidates(slot):
    if actual := _slot_actual_candidates(slot): return actual
    if _is_bridge(slot):
        pat = slot_to_pat.get(slot)
        return [{'pattern': pat, 'positions': [{'pos': p.strip(), 'items': '—'} for p in pat.split(' / ')], 'prob': 'BRIDGE', 'source': slot_to_meta[slot].get('source', '?'), 'reason': 'bridge', 'phases': [], 'type': 'bridge', 'duplicates': []}]
    cands = (_predict_04am_ext(slot) if slot % 4 == 0 else _predict_std_ext(slot)) or _predict_std_ext(slot)
    out = []
    for c in cands:
        pat_items = _get_pattern_items(c['pattern'], c['source'], target_slot=slot)
        out.append({
            'pattern': c['pattern'], 
            'positions': [{'pos': p.strip(), 'items': pat_items.get(p.strip(), '—')} for p in c['pattern'].split(' / ')], 
            'prob': f"{c.get('prob', 0.0)*100:.1f}%", 'source': c['source'], 'reason': c.get('reason', ''), 'phases': c.get('phases', []), 'type': 'real' if c.get('source_type') == 'real' else 'pred', 'duplicates': c.get('duplicates', []),
            'is_risk': c.get('is_risk', False),
            'is_main': c.get('is_main', False),
        })
    return out

def build_widget_html(base_start_slot, offset_slots=0, n_ahead=12, lang="vi", utc_offset=7.0, missing_04=None):
    T = get_translator(lang)
    if _WIDGET_TEMPLATE is None: return None
    slots = []
    for k in range(n_ahead):
        s = base_start_slot + offset_slots + k
        cands = _slot_candidates(s)
        slots.append({'slot': s, 'hname': _hname_display(s % 4, lang), 'iso': slot_to_ts(s).strftime('%Y-%m-%dT%H:%M:%S') + '+07:00', 'top': cands[0] if cands else None, 'fallbacks': cands[1:] if len(cands) > 1 else [], 'phase': f"phase {slot_phase[s][0]}{slot_phase[s][1]}" if s % 4 == 0 and s in slot_phase else '', 'is_actual': (s in REAL_SLOTS and cands and cands[0].get('type') == 'actual'), 'is_bridge': (s in slot_to_meta and _is_bridge(s))})
    from datetime import datetime as _dt
    _now_utc = _dt.utcnow()
    _now_slot = int((_now_utc - BASE).total_seconds() / (6 * 3600))
    _real_next_iso = slot_to_ts(_now_slot + 1).strftime('%Y-%m-%dT%H:%M:%S') + '+07:00'

    payload = json.dumps({
        "slots": slots, "L": get_widget_text(lang), "utc_offset": utc_offset, "missing_04": missing_04 or [], "real_next_iso": _real_next_iso, "real_now_slot": _now_slot, "offset_slots": offset_slots
    }, ensure_ascii=False).replace('</', '<\\/')
    return _WIDGET_TEMPLATE.replace('__P__', payload)

def _run_pipeline_impl(files_data, default_rows, used_files=None, offset_days=0, use_default=True, lang="vi", utc_offset=7.0, trans_lookback=None):
    global slot_to_pat, slot_to_meta, slot_to_items, pattern_items, PAIR_TO_SLOTS, skipped, all_posts, ACTIVE_START_SLOT, REAL_SLOTS, REAL_MAX
    global min_slot, max_slot, DYNAMIC_OFFSETS, slot_phase, miss_101622, total_101622, off_counts, miss_rate
    global USE_PATCH1, USE_AUTOHEAL, USE_BRIDGE, KEY_OFFSETS, TRANS, PATCH1_OFFSETS, MARKOV_A2, MARKOV_B2, MARKOV_B2_2T, LAST_TRANS_STATS
    global ANOMALY_SLOTS_BY_HOUR

    USE_PATCH1, USE_AUTOHEAL, USE_BRIDGE = False, False, False
    KEY_OFFSETS, TRANS, PATCH1_OFFSETS, MARKOV_A2, MARKOV_B2, MARKOV_B2_2T = _build_known_offsets(), _build_trans(), _build_patch1_offsets(), dict(MARKOV_A2_CFG), defaultdict(Counter), defaultdict(Counter)
    slot_to_pat, slot_to_meta, slot_to_items, pattern_items, PAIR_TO_SLOTS, skipped, all_posts = {}, {}, {}, defaultdict(list), defaultdict(set), 0, []
    ACTIVE_START_SLOT, DYNAMIC_OFFSETS, slot_phase, miss_101622, total_101622, off_counts = -9999, [], {}, [], 0, Counter()
    ANOMALY_SLOTS_BY_HOUR = {0: [], 1: [], 2: [], 3: []}
    LAST_TRANS_STATS = {'static_acc': 0.0, 'adaptive_acc': 0.0, 'was_overridden': False, 'train_size': 0, 'test_size': 0, 'lookback_requested': 0, 'lookback_used': 0, 'missing_04': [], 'total_missing_04': 0}
    try: SESSION_START_OFFSET.clear()
    except Exception: pass

    T = get_translator(lang)
    LOG = PipelineLogger()
    widget_html = None
    with redirect_stdout(LOG.buffer):
        try:
            t_start = time.time()
            LOG.hdr(T("log_title", default="MERCHANT LOCATION — PIPELINE LOG"))
            LOG.info(T("log_lang_info", default="Language: {lang} | Time shift: {offset:+d}d | UTC offset: {utc:+.1f}", lang=lang, offset=offset_days, utc=utc_offset))
            LOG.info(T("log_toggles", default="Toggles: Patch1={p1} | AutoHeal={ah} | Bridge={br} | MarkovB2={m2}", p1=USE_PATCH1, ah=USE_AUTOHEAL, br=USE_BRIDGE, m2=USE_MARKOV_B2))

            LOG.hdr(T("log_phase_0", default="⚙️ PHASE 0: CONFIG"))
            LOG.summary(T("log_settings", default="Settings"), {"CYCLE": CYCLE, "JITTERS": JITTERS, "K_ACTIVE": K_ACTIVE, "TRANS chains": len(TRANS), "Patch1 offsets": PATCH1_OFFSETS, "Anomaly gaps": f"STD:{len(STD_GAPS)} + 04:{len(GAPS_04)}", "TRANS lookback": f"{trans_lookback or TRANS_ADAPTIVE_LOOKBACK} slots", "Anomaly end slot": ANOMALY_END_SLOT, "Risk Gaps": STD_ANOMALY_RISK_GAPS})
            
            gh_token, gh_repo, gh_branch = _get_cfg("GITHUB_TOKEN"), _get_cfg("GITHUB_REPO"), _get_cfg("GITHUB_BRANCH")
            LOG.summary(T("log_secrets", default="🔐 Secrets"), {"GITHUB_TOKEN": '✅' if gh_token else '❌ MISSING', "GITHUB_REPO": '✅' if gh_repo else '❌ MISSING', "GITHUB_BRANCH": gh_branch or '(default)'})
            if not gh_token or not gh_repo: LOG.info(T("log_no_push", default="⚠️ Auto-push TRANS sẽ KHÔNG hoạt động (app vẫn chạy)"))

            LOG.hdr(T("log_phase_1", default="📥 PHASE 1: LOAD DATA"))
            t_phase = time.time(); merged = {}
            if use_default and default_rows:
                for dt, content, user in default_rows: merged[(dt, user, content)] = (dt, content, user)
                LOG.info(T("log_base_rows", default="Base rows: {n:,}", n=len(default_rows)))
                if used_files: LOG.table(T("log_files", default="Files"), used_files[:10], headers=[T("log_file_col", default="File"), T("log_posts_col", default="Posts")], widths=[40, 10])
            for fname, data in files_data:
                n_file = 0
                reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig', errors='replace')))
                fieldnames_lower = {}
                ts_col = user_col = content_col = None
                for row in reader:
                    if not fieldnames_lower and row.keys():
                        fieldnames_lower = {k.lower().strip(): k for k in row.keys() if k}
                        ts_col = _find_column(fieldnames_lower, _TS_CANDIDATES)
                        user_col = _find_column(fieldnames_lower, _USER_CANDIDATES)
                        content_col = _find_column(fieldnames_lower, _CONTENT_CANDIDATES)
                        LOG.info(f"[V12.9] Detected columns: ts='{ts_col}', user='{user_col}', content='{content_col}'")
                        if not ts_col or not content_col:
                            LOG.info(f"⚠️ Cannot detect required columns in {fname} — skip file")
                            break
                    if not fieldnames_lower: continue
                    ts_val = row.get(ts_col, '') if ts_col else ''
                    content_val = row.get(content_col, '') if content_col else ''
                    user_val = row.get(user_col, '?') if user_col else '?'
                    if (dt := parse_ts(ts_val)): merged[(dt, user_val, content_val)] = (dt, content_val, user_val); n_file += 1
                LOG.info(T("log_uploaded", default="Uploaded: {fname} → {n:,} rows", fname=fname, n=n_file))
            LOG.info(T("log_merged", default="🔀 Merged unique: {n:,} rows | ⏱️ {t:.2f}s", n=len(merged), t=time.time() - t_phase))
            if not merged: return None, LOG.getvalue(), "", LAST_TRANS_STATS

            LOG.hdr(T("log_phase_2", default="🔍 PHASE 2: PARSE PATTERNS & ITEMS"))
            t_phase = time.time(); raw_rows = []
            for idx, (dt, content, user) in enumerate(merged.values()):
                try: raw_rows.append((dt, extract_pattern(content), content, user))
                except: pass
                if (idx + 1) % 2000 == 0: LOG.info(T("log_parsed", default="⏳ Parsed {cur:,}/{total:,}...", cur=idx + 1, total=len(merged)))
            
            with_pat = sum(1 for _, p, _, _ in raw_rows if p)
            _parsed = [(dt, pat) for dt, pat, _, _ in raw_rows]
            ACTIVE_START_SLOT = min(ts_to_slot(dt) for dt, _ in _parsed if dt is not None)
            CSV_OFFSET = detect_csv_timezone(_parsed)
            LOG.info(T("log_rows_pattern", default="Rows with pattern: {wp:,}/{tr:,} | CSV offset: {off:+.2f}h", wp=with_pat, tr=len(raw_rows), off=CSV_OFFSET))

            items_count = 0; skip_reasons = Counter()
            for dt, pat, content, user in raw_rows:
                try:
                    adj = dt + timedelta(hours=CSV_OFFSET); s = ts_to_slot(adj); items_map = extract_items(content)
                    if items_map: items_count += 1
                    all_posts.append({'slot': s, 'dt': adj, 'dt_raw': dt, 'pat': pat, 'user': user, 'raw': content})
                    if not content or not content.strip(): skip_reasons['empty_content'] += 1; continue

                    is_item = _is_item_post(content)
                    if is_item:
                        pat_source = 'items'
                        if not pat and items_map: pat = pattern_from_items(items_map)
                    else:
                        pat_source = 'clean'

                    if not pat: skip_reasons['no_pattern'] += 1; skipped += 1; continue

                    existing_source = slot_to_meta.get(s, {}).get('pattern_source') if s in slot_to_pat else None

                    if existing_source is None:
                        slot_to_pat[s] = pat
                        slot_to_meta[s] = {
                            'dt': adj, 'dt_raw': dt, 'user': user,
                            'pattern_source': pat_source,
                            'all_clean_posts': (
                                [{'ts': dt, 'pattern': pat, 'user': user}]
                                if pat_source == 'clean' else []
                            ),
                        }
                        if items_map: slot_to_items[s] = items_map
                        pattern_items[pat].append((s, items_map or {}))

                    elif existing_source == 'clean':
                        if pat_source == 'clean' and pat != slot_to_pat[s]:
                            all_clean = slot_to_meta[s].get('all_clean_posts', [])
                            all_clean.append({'ts': dt, 'pattern': pat, 'user': user})
                            slot_to_meta[s]['all_clean_posts'] = all_clean
                            votes = Counter(p['pattern'] for p in all_clean)
                            winner, win_count = votes.most_common(1)[0]
                            if win_count > len(all_clean) / 2:
                                slot_to_pat[s] = winner
                                skip_reasons['conflict_majority_win'] += 1
                            else:
                                slot_to_meta[s]['has_conflict'] = True
                                skip_reasons['conflict_tie_keep_first'] += 1
                        if items_map and len(items_map) > len(slot_to_items.get(s, {})):
                            slot_to_items[s] = items_map
                            skip_reasons['merge_items_only'] += 1

                    elif existing_source == 'items':
                        if pat_source == 'clean':
                            slot_to_pat[s] = pat
                            slot_to_meta[s] = {
                                'dt': adj, 'dt_raw': dt, 'user': user,
                                'pattern_source': 'clean',
                                'all_clean_posts': [{'ts': dt, 'pattern': pat, 'user': user}],
                            }
                            if items_map and len(items_map) > len(slot_to_items.get(s, {})):
                                slot_to_items[s] = items_map
                            pattern_items[pat].append((s, items_map or {}))
                            skip_reasons['item_replaced_by_clean'] += 1
                        else:
                            if len(items_map or {}) < len(slot_to_items.get(s, {})):
                                skip_reasons['fewer_items'] += 1
                                continue
                            slot_to_pat[s] = pat
                            slot_to_meta[s] = {
                                'dt': adj, 'dt_raw': dt, 'user': user,
                                'pattern_source': 'items',
                                'all_clean_posts': [],
                            }
                            if items_map: slot_to_items[s] = items_map
                            pattern_items[pat].append((s, items_map or {}))
                except Exception as e: skip_reasons[f'err_{type(e).__name__}'] += 1

            LOG.summary(T("log_parse_stats", default="Parse Stats"), {T("log_slots_with_pat", default="Slots with pattern"): f"{len(slot_to_pat):,}", T("log_slots_with_items", default="Slots with items"): items_count, T("log_skipped", default="Skipped"): skipped, T("log_time", default="Time"): f"{time.time() - t_phase:.2f}s"})
            if skip_reasons: LOG.table(T("log_skip_breakdown", default="Skip Breakdown"), list(skip_reasons.items()), headers=[T("log_reason", default="Reason"), T("log_count", default="Count")], widths=[25, 10])

            tie_slots = sorted([s for s, m in slot_to_meta.items() if m.get('has_conflict')])
            majority_count = skip_reasons.get('conflict_majority_win', 0)
            tie_count = skip_reasons.get('conflict_tie_keep_first', 0)
            if majority_count or tie_count or tie_slots:
                LOG.info(T("log_conflict", default="\n⚠️ CONFLICT RESOLUTION:"))
                LOG.info(T("log_majority_win", default="  Majority win         : {n} slots", n=majority_count))
                LOG.info(T("log_tie_kept", default="  Tie (kept first)     : {n} slots", n=tie_count))
                if tie_slots:
                    LOG.info(T("log_tie_slots", default="  Tie slots (verify)   : {slots}", slots=str(tie_slots[:20]) + (' ...' if len(tie_slots) > 20 else '')))

            if not slot_to_pat: return None, LOG.getvalue(), "", LAST_TRANS_STATS

            min_slot, max_slot = min(slot_to_pat), max(slot_to_pat); REAL_SLOTS = frozenset(slot_to_pat.keys()); REAL_MAX = max_slot
            PAIR_TO_SLOTS.clear()
            for _s, _imap in slot_to_items.items():
                for _p in slot_to_pat.get(_s, '').split(' / '):
                    if _p.strip(): PAIR_TO_SLOTS[_p.strip()].add(_s)

            LOG.hdr(T("log_phase_3", default="🎯 PHASE 3: REGIME & ANOMALY DETECTION"))
            t_phase = time.time(); find_regime_shift()
            LOG.info(T("log_active_start", default="Active start after regime shift: {s}", s=ACTIVE_START_SLOT))

            for s in sorted(slot_to_pat):
                if s < ACTIVE_START_SLOT or s % 4 == 0 or s <= ANOMALY_END_SLOT: continue
                if s - 119 >= ACTIVE_START_SLOT and s - 119 in slot_to_pat and slot_to_pat[s] != slot_to_pat[s-119]:
                    actual = slot_to_pat[s]; found_off = None
                    for k in range(1, 30):
                        for j in range(-50, 51):
                            if s - (119*k + j) in slot_to_pat and slot_to_pat[s - (119*k + j)] == actual: found_off = 119*k + j; break
                        if found_off: break
                    miss_101622.append({'slot': s, 'offset': found_off})
                    if found_off: off_counts[found_off] += 1
            
            LOG.info(T("log_anomalies_checked", default="Anomalies checked: {n:,} slots", n=len(miss_101622)))
            if off_counts: LOG.table(T("log_top_offsets", default="Top offsets found"), off_counts.most_common(10), headers=[T("log_offset", default="Offset"), T("log_count", default="Count")], widths=[15, 10])
            
            for s in sorted(REAL_SLOTS):
                if s < ANOMALY_END_SLOT: continue
                hour = s % 4
                is_anom = True
                if s - 119 in slot_to_pat and slot_to_pat[s - 119] == slot_to_pat[s]: is_anom = False
                if is_anom: ANOMALY_SLOTS_BY_HOUR[hour].append(s)
            LOG.info(T("log_anomaly_cache", default="Anomaly cache built: 10:00={h1}, 16:00={h2}, 22:00={h3}", h1=len(ANOMALY_SLOTS_BY_HOUR[1]), h2=len(ANOMALY_SLOTS_BY_HOUR[2]), h3=len(ANOMALY_SLOTS_BY_HOUR[3])))
            
            _build_branch_slots()
            LOG.info(T("log_branch_slots", default="Branch slots: C1={c1}, A3={a3}", c1=len(BRANCH_SLOTS['C1']), a3=len(BRANCH_SLOTS['A3'])))

            _ao_cache = _build_context_offset_cache()
            LOG.info(T("log_adaptive_cache", default="Adaptive offset cache: {n} contexts (SHADOW MODE, USE_ADAPTIVE_OFFSET={flag})", n=len(_ao_cache), flag=USE_ADAPTIVE_OFFSET))

            try: _self_check_adaptive_offset(n_slots=50, LOG=LOG)
            except Exception as _sc_e: LOG.info(f"⚠️ Self-check failed: {_sc_e}")

            for h in [1, 2, 3]:
                pred_slots = [ANOMALY_SLOTS_BY_HOUR[h][-1] + p for p in (_predict_next_gap(h) or [])]
                pred_gap = _predict_next_gap(h)
                if pred_slots and pred_gap:
                    hour_label = {1: "10:00", 2: "16:00", 3: "22:00"}[h]
                    gap_str = pred_gap if isinstance(pred_gap, int) else ", ".join(map(str, pred_gap))
                    slot_str = ", ".join(f"slot {s} ({slot_to_ts(s).strftime('%Y-%m-%d')})" for s in pred_slots)
                    LOG.info(T("log_predict_std", default="📊 Predict anchor {hour_label}: gap [{gap}] → next anomaly at {slots}", hour_label=hour_label, gap=gap_str, slots=slot_str))
            
            for bt in ['C1', 'A3']:
                pg = _predict_next_branch_gap(bt)
                if pg and BRANCH_SLOTS[bt]:
                    last_slot = BRANCH_SLOTS[bt][-1]
                    pred_str = pg if isinstance(pg, int) else ", ".join(map(str, pg))
                    pred_next = last_slot + (pg if isinstance(pg, int) else pg[0])
                    LOG.info(T("log_predict_branch", default="📊 Predict 04:00 branch {bt}: gap [{gap}] → possible branch at slot {next} ({dt})", bt=bt, gap=pred_str, next=pred_next, dt=slot_to_ts(pred_next).strftime('%Y-%m-%d')))

            LOG.info(T("log_time", default="Time: {t:.2f}s", t=time.time() - t_phase))

            LOG.hdr(T("log_phase_4", default="🧬 PHASE 4: ADAPTATION"))
            t_phase = time.time(); init_dynamic_cycles(); _bootstrap_phases(); build_markov_from_data()
            LOG.info(T("log_dynamic_cycles", default="Dynamic cycles: {dc} | Phase cache: {n:,} slots", dc=DYNAMIC_OFFSETS, n=len(slot_phase)))
            
            try: MARKOV_B2 = _build_markov_b2_from_slots(lang=lang, LOG=LOG) if USE_MARKOV_B2 else defaultdict(Counter)
            except Exception as e: LOG.info(f"⚠️ MarkovB2 build failed: {e}"); MARKOV_B2 = defaultdict(Counter)
            LOG.info(T("log_time", default="Time: {t:.2f}s", t=time.time() - t_phase))

            try:
                _rs = _verify_cycle_rules(min_samples=10, min_accuracy=0.90)
                if _rs:
                    rows = []
                    for (pe, prl), stat in _rs.items():
                        status = "INSUFFICIENT" if stat['total'] < 10 else ("KEPT" if stat['acc'] >= 0.90 else "DISABLED")
                        rows.append((f"({pe},{prl})->{stat['state']}", stat['total'], f"{stat['acc']*100:.0f}%", status))
                    LOG.table("V12.8 Cycle Rules Verification", rows, headers=["Rule", "N", "Acc", "Status"], widths=[20, 6, 8, 12])
            except Exception as _e:
                LOG.info(f"[V12.8.1] verify failed: {_e}")

            LOG.hdr(T("log_phase_5", default="🔮 PHASE 5: PREDICTION"))
            t_phase = time.time(); NOW = datetime.utcnow() + VN_OFFSET
            current_next_slot = int((NOW - BASE).total_seconds() / (6*3600)) + 1
            
            start_check = max(ACTIVE_START_SLOT, current_next_slot - 1000)
            missing_slots = [s for s in range(start_check, current_next_slot) if s not in REAL_SLOTS]
            missing_04_data = [{'slot': s, 'iso': slot_to_ts(s).strftime('%Y-%m-%dT%H:%M:%S') + '+07:00'} for s in missing_slots]
            
            LAST_TRANS_STATS['missing_04'] = missing_04_data[-20:]
            LAST_TRANS_STATS['total_missing_04'] = len(missing_slots)
            if missing_slots: LOG.info(f"⚠️ Phát hiện {len(missing_slots)} slot bị thiếu trong 1000 slot gần nhất.")

            extend_predictions(current_next_slot + 200)

            bridge_count = sum(1 for s in slot_to_pat if _is_bridge(s)); pred_count = len(slot_to_pat) - len(REAL_SLOTS) - bridge_count
            LOG.summary(T("log_memory_stats", default="Memory Stats"), {T("log_real_slots", default="Real slots"): f"{len(REAL_SLOTS):,}", T("log_bridge_slots", default="Bridge slots"): f"{bridge_count:,}", T("log_predicted", default="Predicted"): f"{pred_count:,}", T("log_total_in_memory", default="Total in memory"): f"{len(slot_to_pat):,}"})

            LOG.write(T("log_predict_12", default="\n📋 PREDICTIONS FOR NEXT 12 SLOTS:"))
            for k in range(12):
                s = current_next_slot - 1 + offset_days * 4 + k; h = s % 4
                phase_info = f" [prev: {_phase_of(s-4)[0]}{_phase_of(s-4)[1]} ← {_phase_of(s-8)[0]}{_phase_of(s-8)[1]}]" if h == 0 else ""
                header = f"Slot {s} @ {slot_to_ts(s).strftime('%Y-%m-%d %H:%M')} | hour {h}{phase_info}"
                
                if s in REAL_SLOTS: LOG.info(T("log_actual", default="┌─ {header}\n│  ✅ ACTUAL: {pat}", header=header, pat=slot_to_pat.get(s, "?"))); continue
                if _is_bridge(s): LOG.info(T("log_bridge", default="┌─ {header}\n│  🌉 BRIDGE: {pat}", header=header, pat=slot_to_pat.get(s, "?"))); continue
                
                cands = (_predict_04am_ext(s) if h == 0 else _predict_std_ext(s))
                if not cands: LOG.info(T("log_no_pred", default="┌─ {header}\n│  ⚠️ No prediction", header=header)); continue
                
                rows = []
                for i, c in enumerate(cands[:3], 1):
                    prob_pct = c.get('prob', 0) * 100; reason = c.get('reason', ''); src = c.get('source', '?'); stype = c.get('source_type', '?')
                    phase_str = f" [{','.join(c.get('phases', []))}]" if c.get('phases') else ""
                    rows.append((f"#{i}", f"[{prob_pct:5.1f}%]", phase_str, c['pattern'], f"← {reason} | src={src} ({stype})"))
                LOG.table(T("log_pred_table", default="┌─ {header}", header=header), rows, headers=["", T("log_prob", default="Prob"), T("log_state", default="State"), T("log_pattern", default="Pattern"), T("log_reason_src", default="Reason / Source")], widths=[4, 8, 8, 40, 40])

            past_04 = sorted([s for s in REAL_SLOTS if s % 4 == 0])[-5:]
            if past_04:
                LOG.write(T("log_recent_04", default="\n📚 RECENT 5 SLOTS @ 04:00 (already passed):"))
                for s in past_04:
                    ph, rl = _phase_of(s - 4)
                    LOG.info(f"Slot {s} | prev={ph}{rl} | actual={slot_to_pat.get(s, '?')[:50]}...")
                    if (ph, min(rl, 3)) in TRANS: LOG.info(f"   TRANS({ph}{rl}) predicted: {TRANS[(ph, min(rl, 3))][0][0]} ({TRANS[(ph, min(rl, 3))][0][2]*100:.1f}%)")

            widget_html = build_widget_html(current_next_slot - 1, offset_days * 4, 12, lang, utc_offset, missing_04_data)
            LOG.info(T("log_widget_built", default="\nWidget HTML: {status}", status=('✅ built (' + str(len(widget_html)) + ' chars)' if widget_html else '❌ FAILED')))
            NOW_LOCAL = datetime.utcnow() + timedelta(hours=utc_offset)
            LOG.info(T("log_now", default="\n🕐 NOW (Local UTC{off:+.1f}): {time} | Next: slot {slot} = {dt} | ⏱️ {elapsed:.2f}s", off=utc_offset, time=NOW_LOCAL.strftime('%Y-%m-%d %H:%M:%S'), slot=current_next_slot, dt=(slot_to_ts(current_next_slot) + timedelta(hours=utc_offset - 7)).strftime('%Y-%m-%d %H:%M'), elapsed=time.time() - t_phase))

            LOG.hdr(T("log_complete", default="✅ PIPELINE COMPLETE"))
            LOG.summary(T("log_total", default="Total"), {T("log_time", default="Time"): f"{time.time() - t_start:.2f}s", T("log_log_size", default="Log size"): f"{len(LOG.getvalue()):,} chars"})
        except Exception:
            import traceback
            LOG.write(T("log_critical", default="\n❌ CRITICAL ERROR:\n{err}", err=traceback.format_exc()))

    return widget_html, LOG.getvalue(), _format_trans_to_txt(TRANS, lang=lang), LAST_TRANS_STATS

def _validate_input(files_data, default_rows, use_default):
    if not files_data and not use_default and not default_rows:
        return False, "Không có dữ liệu: cần upload CSV hoặc dùng default rows"
    seen = set()
    unique_bytes = 0
    for name, data in (files_data or []):
        h = hashlib.sha256(data).digest()
        if h not in seen:
            seen.add(h)
            unique_bytes += len(data)
    if unique_bytes > 50_000_000:
        return False, f"CSV quá lớn ({unique_bytes / 1e6:.1f}MB unique), giới hạn 50MB"
    return True, ""

def _reset_per_request_caches():
    global SESSION_START_OFFSET, ADAPTIVE_CANDIDATE_OFFSETS, _ADAPTIVE_MT_CACHE
    for name in ('SESSION_START_OFFSET', 'ADAPTIVE_CANDIDATE_OFFSETS', '_ADAPTIVE_MT_CACHE'):
        try:
            obj = globals().get(name)
            if hasattr(obj, 'clear'): obj.clear()
        except Exception: pass

def run_pipeline(files_data, default_rows, used_files=None, offset_days=0, use_default=True, lang="vi", utc_offset=7.0, trans_lookback=None):
    ok, reason = _validate_input(files_data, default_rows, use_default)
    if not ok:
        _LOG = PipelineLogger()
        _LOG.info(f"⚠️ Input rejected: {reason}")
        return None, _LOG.getvalue(), "", {"error": reason}
    with _PIPELINE_LOCK:
        _reset_per_request_caches()
        return _run_pipeline_impl(files_data, default_rows, used_files, offset_days, use_default, lang, utc_offset, trans_lookback)

def predict_last_merch_phase(current_phase, next_gap_distance, branch_name):
    if branch_name == 'A3':
        if next_gap_distance == 16: return 'A3'
        elif next_gap_distance in [100, 84]: return 'A4'
        elif next_gap_distance == 4: return 'C7'
    elif branch_name == 'C1': return 'C7'
    return 'Unknown'
