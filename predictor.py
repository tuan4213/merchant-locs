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

_kp = _DEFAULTS
CYCLE, JITTERS, K_ACTIVE = _kp['CYCLE'], _kp['JITTERS'], _kp['K_ACTIVE']
PATCH1_K, MARKOV_A2_CFG = _kp['PATCH1_K'], _kp['MARKOV_A2_CFG']
MARKOV_A2_FALLBACK, MARKOV_BRANCH_OFFSETS = _kp['MARKOV_A2_FALLBACK'], _kp['MARKOV_BRANCH_OFFSETS']
AUTO_HEAL_THRESHOLD, AUTO_HEAL_MIN_SAMPLES = _kp['AUTO_HEAL_THRESHOLD'], _kp['AUTO_HEAL_MIN_SAMPLES']
MIN_STABLE_SLOT, MIN_MARKOV_SAMPLES = _kp['MIN_STABLE_SLOT'], _kp['MIN_MARKOV_SAMPLES']
TRANS_ADAPTIVE_LOOKBACK = _kp.get('TRANS_ADAPTIVE_LOOKBACK', 50)
TRANS_CFG = _DEFAULT_TRANS
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
    pat_first2 = get_first_2_pairs(pat)
    for k in range(1, 25):
        prev = slot - 119 * k
        if prev in slot_to_pat and not _is_bridge(prev) and get_first_2_pairs(slot_to_pat[prev]) == pat_first2: return '119', 119 * k
    for off, phase in KEY_OFFSETS.items():
        prev = slot - off
        if prev in slot_to_pat and not _is_bridge(prev) and get_first_2_pairs(slot_to_pat[prev]) == pat_first2: return phase, off
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
    anoms = ANOMALY_SLOTS_BY_HOUR.get(hour, [])
    if not anoms: return False
    if hour in EXTRA_ANOMALY_POSITIONS:
        pos = target_slot % MACRO_CYCLE
        if pos in EXTRA_ANOMALY_POSITIONS[hour]: return True
    diff = target_slot - anoms[-1]
    if diff <= 0: return False
    if diff in (116, 132): return True
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

def predict_last_merch_phase(current_phase, next_gap_distance, branch_name):
    if branch_name == 'A3':
        if next_gap_distance == 16: return 'A3'
        elif next_gap_distance in [100, 84]: return 'A4'
        elif next_gap_distance == 4: return 'C7'
    elif branch_name == 'C1': return 'C7'
    return 'Unknown'
