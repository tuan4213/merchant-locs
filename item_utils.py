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


# ============================================================
# LEGACY — ported from old Drive version
# ============================================================

DASH = r'[-–—−]'

PAIR_POS = re.compile(rf'(\d{{1,2}})\s*{DASH}\s*(\d{{1,2}})')

ITEM_CANON = [
    ("queen's crown", "Queen's Crown"), ("queens crown", "Queen's Crown"),
    ("barrage", "Barrage Crystal"), ("barage", "Barrage Crystal"),
    ("def cryst", "Defense Crystal"), ("def crystal", "Defense Crystal"),
    ("defense cryst", "Defense Crystal"), ("defense crystal", "Defense Crystal"),
    ("machine ruin", "Machine Ruins"), ("special engine", "Special Engine"),
    ("blue gift", "Blue Gift"), ("gold gift", "Gold Gift"),
    ("free cake", "Free Cake"), ("fr cake", "Free Cake"),
    ("free gem", "Free Gems"), ("fr gem", "Free Gems"),
    ("free steel", "Free Steel"), ("fr metal", "Free Steel"),
    ("free mine", "Free Mine"), ("fr mine", "Free Mine"),
    ("free trove", "Free Trove"), ("fr trove", "Free Trove"),
    ("free hero ticket", "Free Hero"), ("hero ticket", "Free Hero"),
    ("free hero", "Free Hero"), ("fr hero", "Free Hero"),
    ("ad hero", "Ad Hero"), ("ad cannon", "Ad Cannon"), ("ad cat", "Ad Cat"),
    ("ad tower", "Ad Tower"), ("ad arena", "Ad Arena"),
    ("ad equip", "Ad Equipment"), ("ad ep", "Ad Equipment"), ("ad equiment", "Ad Equipment"),
    ("elite equipment", "Elite Equipment"),
    ("boost cryst", "Boost Crystal"), ("boost", "Boost Crystal"),
    ("libo", "Libo"), ("gand", "Gandalfu"),
    ("wagzak", "Wagzak"), ("wagz", "Wagzak"), ("wag", "Wagzak"), ("waq", "Wagzak"),
    ("king", "King"), ("queen", "Queen"), ("grave", "Graveyard"),
    ("treasure key", "Treasure Key"), ("treasure", "Treasure"),
    ("cannon", "Ad Cannon"), ("tower", "Ad Tower"), ("arena", "Ad Arena"),
    ("crown", "Queen's Crown"), ("engine", "Special Engine"),
]

def normalize_hero_name(h):
    h = h.lower().strip()
    M = {'libo': 'Libo', 'gand': 'Gandalfu', 'gandalfu': 'Gandalfu', 'gandalf': 'Gandalfu',
         'wag': 'Wagzak', 'wagz': 'Wagzak', 'wagzak': 'Wagzak', 'waqzak': 'Wagzak',
         'king': 'King', 'queen': 'Queen', 'cannon': 'Ad Cannon', 'cat': 'Ad Cat',
         'tower': 'Ad Tower', 'arena': 'Ad Arena', 'hero': 'Free Hero', 'trove': 'Free Trove',
         'mine': 'Free Mine', 'steel': 'Free Steel', 'gem': 'Free Gems', 'gems': 'Free Gems', 'cake': 'Free Cake'}
    return M.get(h, h.title() if h else None)

def smart_split(s, delims=',;•/'):
    parts, depth, current = [], 0, ''
    for ch in s:
        if ch in '([{': depth += 1; current += ch
        elif ch in ')]}': depth = max(0, depth - 1); current += ch
        elif ch in delims and depth == 0:
            if current.strip(): parts.append(current.strip())
            current = ''
        else: current += ch
    if current.strip(): parts.append(current.strip())
    return parts

def normalize_item(text):
    if not text: return None
    s = text.lower().strip()
    s = re.sub(r'<[^>]+>', ' ', s)
    if re.search(r'\bess(?:ence)?\b', s):
        m_paren = re.search(r'\bess(?:ence)?\s*\(([^)]+)\)', s)
        hero_str = m_paren.group(1) if m_paren else (re.search(r'\bess(?:ence)?\s+(?:of\s+)?(.+)', s).group(1) if re.search(r'\bess(?:ence)?\s+(?:of\s+)?(.+)', s) else '')
        heroes = []
        for h in re.split(r'[,;/]', hero_str):
            h = re.sub(r'[^a-z\s]', '', h).strip()
            if not h: continue
            n = normalize_hero_name(h)
            if n and n not in heroes: heroes.append(n)
        return 'Ess of ' + ', '.join(heroes) if heroes else 'Ess'
    s = re.sub(r'\([^)]*\)', ' ', s)
    s = re.sub(r'x?\s*\d[\d,\.]*\s*(?:gems?|k|m|t)?\b', ' ', s)
    s = re.sub(r"[^a-z\s'\-]", ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    if not s: return None
    if s in ('nothing', 'none', 'empty', 'n/a', 'no', 'null'): return None
    for kw, canon in ITEM_CANON:
        if kw in s: return canon
    return text.strip()

def normalize_pattern_order(pairs):
    """Sort 6 pairs by (stage, wave) để position i luôn map về group i+1.

    Game rule (RULES.md 1.5):
      - position 1 → stage 1-4 (group 1)
      - position 2 → stage 5-8 (group 2)
      - ...
      - position 6 → stage 21-24 (group 6)

    User có thể post đảo thứ tự (toàn bộ hoặc 1 phần). Sort theo stage sẽ
    tự sửa. Đây là patch a — thay logic cũ chỉ reverse khi fully reversed
    (không xử lý được partial swap như `.../21-4/19-18` vs `.../19-18/21-4`).
    """
    if len(pairs) != 6: return pairs
    # ✅ PATCH A: full sort theo (stage, wave)
    return sorted(pairs, key=lambda p: (p[0], p[1]))

