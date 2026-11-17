# item_utils.py — Pattern & Item utilities
import re

STAGE_GROUPS = [(1,4), (5,8), (9,12), (13,16), (17,20), (21,24)]

def get_first_2_pairs(pat):
    if not pat: return ""
    parts = [p.strip() for p in pat.split(" / ")]
    return " / ".join(parts[:2])

def extract_pattern(content):
    if not content: return None
    pairs = re.findall(r'\b(\d{1,2})-(\d{1,2})\b', content)
    if len(pairs) < 3: return None
    return " / ".join(f"{a}-{b}" for a, b in pairs[:6])

def extract_items(content):
    if not content: return {}
    result = {}
    for m in re.finditer(r'\[?(\d{1,2})-(\d{1,2})\]?\s*[:–-]\s*([^\n\[]+)', content):
        pos = f"{m.group(1)}-{m.group(2)}"
        items_str = m.group(3).strip()
        items = [it.strip() for it in re.split(r'[,;]', items_str) if it.strip() and it.strip() != '-']
        if items: result[pos] = items
    return result

def pattern_from_items(items):
    if not items: return None
    sorted_pos = sorted(items.keys(), key=lambda p: tuple(map(int, p.split('-'))))
    return " / ".join(sorted_pos[:6])

def parse_pairs(p):
    if not p: return []
    pairs = []
    for m in re.finditer(r'(\d{1,2})-(\d{1,2})', p):
        pairs.append((int(m.group(1)), int(m.group(2))))
    return pairs

def stage_group(stage_num):
    for idx, (lo, hi) in enumerate(STAGE_GROUPS):
        if lo <= stage_num <= hi: return idx
    return -1

def valid_position_groups():
    return STAGE_GROUPS

def find_slot_by_first_2_pairs(pattern, pair_to_slots, slot_to_items, slot_to_pat, target_slot=None):
    if not pattern: return None
    first2 = get_first_2_pairs(pattern)
    if not first2: return None
    candidates = None
    for pair_str in first2.split(" / "):
        slots = pair_to_slots.get(pair_str.strip())
        if not slots: return None
        if candidates is None: candidates = set(slots)
        else: candidates &= slots
        if not candidates: return None
    if not candidates: return None
    if target_slot is not None:
        return min(candidates, key=lambda s: abs(s - target_slot))
    return max(candidates)
