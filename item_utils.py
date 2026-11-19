# item_utils.py — Item & Pattern recognition (no Streamlit dependency)
import re

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
    if len(pairs) != 6: return pairs
    return sorted(pairs, key=lambda p: (p[0], p[1]))

def extract_pattern(content):
    if not content: return None
    content_clean = re.sub(r'<a?:[a-zA-Z0-9_]+:\d+>', '', content)
    for line in content_clean.split('\n'):
        line = line.strip()
        if not line: continue
        ms = list(PAIR_POS.finditer(line))
        if len(ms) < 6: continue
        for i in range(len(ms) - 5):
            six = ms[i:i+6]
            seps = [line[six[j].end():six[j+1].start()] for j in range(5)]
            if not all(len(s) <= 20 for s in seps): continue
            pairs = [(int(m.group(1)), int(m.group(2))) for m in six]
            if all(1 <= a <= 24 and 1 <= b <= 20 for a, b in pairs):
                return ' / '.join(f"{a}-{b}" for a, b in normalize_pattern_order(pairs))
    pairs_seq = []
    for line in content_clean.split('\n'):
        line = line.strip()
        if not line: continue
        line_clean = re.sub(r"^[\s\*\-•>`\[\]|'\"`~_#]+", '', line)
        m = re.match(rf'^(\d{{1,2}})\s*{DASH}\s*(\d{{1,2}})\b', line_clean)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if 1 <= a <= 24 and 1 <= b <= 20: pairs_seq.append((a, b))
    if len(pairs_seq) >= 6:
        for i in range(len(pairs_seq) - 5):
            six = pairs_seq[i:i+6]
            if len(set(six)) == 6:
                return ' / '.join(f"{a}-{b}" for a, b in normalize_pattern_order(six))
    return None

def extract_items(content):
    """Parse items từ Discord content."""
    if not content:
        return None
    import re as _re
    items = {}
    
    content = _re.sub(r'<a?:[a-zA-Z0-9_]+:\d+>', '', content)
    content = _re.sub(r'https?://\S+', '', content)
    content = content.replace('```', '')
    
    # Match pair: N-M theo sau là : hoặc space + ít nhất 1 chữ cái
    # Yêu cầu items có chữ cái thực, không chỉ số/dấu
    pattern = _re.compile(
        r'\[?(\d{1,2}[-–—]\d{1,2})\]?\s*[:|]\s*([^\n\r]+?)(?=\n|$|\d{1,2}[-–—]\d{1,2})'
        r'|'
        r'\[?(\d{1,2}[-–—]\d{1,2})\]?\s+([A-Za-z][^\n\r]*?)(?=\n|$|\d{1,2}[-–—]\d{1,2})',
    )
    
    for match in pattern.finditer(content):
        # Group 1-2 (có `:` separator) hoặc 3-4 (có space + chữ cái)
        pair = match.group(1) or match.group(3)
        raw = match.group(2) or match.group(4) or ""
        if not pair:
            continue
        pair = pair.replace('–', '-').replace('—', '-').strip()
        raw = raw.strip().strip(':,|[]-  ')
        if not raw:
            continue
        
        # Skip nếu raw chỉ là ký tự đặc biệt
        if _re.fullmatch(r'[\s/\\|:;,.\-–—\[\](){}<>=+*&^%$#@!?~`\'"]*', raw):
            continue
        
        item_list = [s.strip() for s in _re.split(r'[,;]', raw) if s.strip()]
        # Yêu cầu có ít nhất 1 chữ cái
        item_list = [s for s in item_list if _re.search(r'[A-Za-z]', s)]
        
        if item_list:
            items[pair] = item_list
    
    return items if items else None

def pattern_from_items(items_map):
    if not items_map or len(items_map) < 6: return None
    try:
        keys = sorted(items_map.keys(), key=lambda k: (int(k.split('-')[0]), int(k.split('-')[1])))
    except Exception: return None
    return ' / '.join(keys[:6])

def parse_pairs(pattern):
    pairs = []
    for p in pattern.split(' / '):
        p = p.strip()
        m = re.fullmatch(r'(\d{1,2})-(\d{1,2})', p)
        if m: pairs.append((int(m.group(1)), int(m.group(2))))
        else: pairs.append(None)
    return pairs

def stage_group(stage):
    if not (1 <= stage <= 24): return None
    return (stage - 1) // 4 + 1

def valid_position_groups(pairs):
    if len(pairs) != 6 or any(p is None for p in pairs): return False
    for i, (stage, _) in enumerate(pairs):
        if stage_group(stage) != i + 1: return False
    return True

def find_slot_by_first_2_pairs(pattern, pair_to_slots, slot_to_items, slot_to_pat, target_slot=None):
    target_pairs = parse_pairs(pattern)
    if len(target_pairs) < 2 or target_pairs[0] is None or target_pairs[1] is None: return None
    p0 = f"{target_pairs[0][0]}-{target_pairs[0][1]}"
    p1 = f"{target_pairs[1][0]}-{target_pairs[1][1]}"
    candidates = pair_to_slots.get(p0, set()) & pair_to_slots.get(p1, set())
    if not candidates: return None
    target_set = set(target_pairs)
    valid = []
    for s in candidates:
        if s not in slot_to_items: continue
        s_pairs = parse_pairs(slot_to_pat.get(s, ''))
        if len(s_pairs) != 6 or any(p is None for p in s_pairs): continue
        if set(s_pairs) == target_set: valid.append(s)
    if not valid: return None
    if target_slot is not None:
        valid.sort(key=lambda s: abs(s - target_slot))
        return valid[0]
    return max(valid)


# ===== [PATCH] Pattern lấy từ tin PATTERN; tin ITEMS chỉ là dự phòng (copy items nguyên văn ở chỗ khác) =====
def post_kind(content):
    """'I' = tin items (>=3 dòng 'X-Y <chữ>'), 'P' = tin pattern. Không dùng extract_items nên không bị lỗi dòng trống."""
    import re as _re
    line_re = _re.compile(r"^[\s\*\-•>`\[\]|'\"~_#]*(\d{1,2})\s*[-–—]\s*(\d{1,2})(.*)$")
    n = 0
    for ln in (content or "").split("\n"):
        m = line_re.match(ln.strip())
        if not m or not (1 <= int(m.group(1)) <= 24 and 1 <= int(m.group(2)) <= 20): continue
        rest = _re.sub(r"^[\s:=→\-\|>*•`\[\]~_/]+|[\s\|\*`\[\]>_~\-/]+$", "", m.group(3))
        if len(rest) >= 2 and not PAIR_POS.search(rest): n += 1
    return 'I' if n >= 3 else 'P'

def order_rows_pattern_first(rows, ts_to_slot):
    """rows: (dt, content, user). Trả cùng các dòng đó, sắp theo slot rồi mức ưu tiên:
    0 = tin pattern của người đăng cả pattern+items, 1 = tin pattern khác, 2 = tin items (dự phòng), 3 = không có pattern.
    Trong cùng mức: tin sớm nhất trước. Pipeline lấy tin đầu tiên của mỗi slot."""
    from collections import defaultdict
    recs, kinds = [], defaultdict(lambda: defaultdict(set))
    for r in rows:
        dt, content, user = r[0], r[1], r[2]
        try: s = ts_to_slot(dt)
        except Exception: s = -10**9
        pat = extract_pattern(content)
        kind = post_kind(content) if pat else None
        if pat: kinds[s][user].add(kind)
        recs.append((r, s, kind, user, dt, content))
    def key(t):
        r, s, kind, user, dt, content = t
        if kind is None: tier = 3
        elif kind == 'P': tier = 0 if kinds[s][user] == {'I', 'P'} else 1
        else: tier = 2
        return (s, tier, dt, str(content))
    return [t[0] for t in sorted(recs, key=key)]
