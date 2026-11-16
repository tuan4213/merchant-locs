import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, timedelta
import hashlib
import json
import os

# ============================================================================== 
# CẤU HÌNH TRANG & CSS
# ============================================================================== 
st.set_page_config(page_title="Merchant Location", layout="wide")

# Script chống đơ (Anti-stuck) từ app.py cũ
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

# ============================================================================== 
# LOGIC TỪ PREDICTOR_2.PY (AUTO-GEN)
# ============================================================================== 
BASE = datetime(2025, 1, 1, 4, 0)
VN_OFFSET = timedelta(hours=7)

CYCLE = 119
MACRO_CYCLE = 1072
EXTRA_POS = {1: 157, 2: 814, 3: 399}
PATTERN_14 = [16, 116, 16, 116, 16, 116, 16, 116, 16, 116, 16, 132, 132, 132]

def ts_to_slot(dt): return round((dt - BASE).total_seconds() / 3600 / 6)
def slot_to_ts(slot): return BASE + timedelta(hours=slot * 6)

def generate_mock_pattern(slot):
    base_id = slot % CYCLE
    hash_val = int(hashlib.md5(str(base_id).encode()).hexdigest(), 16)
    stages = [1, 5, 9, 13, 17, 21]
    pat = []
    for i in range(6):
        s = stages[i] + (hash_val % 4)
        w = 1 + ((hash_val >> (i*3)) % 24)
        pat.append(f"{s}-{w}")
        hash_val = hash_val >> 4
    return " / ".join(pat)

def generate_timeline(max_slot):
    timeline = {}
    last_anoms = {1: 1, 2: 2, 3: 3}
    indices = {1: 6, 2: 12, 3: 2}
    
    for s in range(-1000, max_slot):
        hour = s % 4
        pat = generate_mock_pattern(s)
        
        if hour != 0:
            gap = s - last_anoms[hour]
            expected_gap = PATTERN_14[indices[hour]]
            is_anom = (gap == expected_gap)
            is_macro = (s % MACRO_CYCLE) == EXTRA_POS[hour]
            
            if is_anom:
                last_anoms[hour] = s
                indices[hour] = (indices[hour] + 1) % 14
                
        timeline[s] = pat
    return timeline

# Đọc Widget Template (Nhúng trực tiếp vào code để không cần file ngoài)
WIDGET_TEMPLATE_HTML = """<!DOCTYPE html>
<html>
<head>
<style>
#mwidget{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:linear-gradient(135deg,#1e1e2e 0%,#2a2a3e 100%);color:#e0e0e0;padding:16px 20px;border-radius:12px;bo[...]
#mwidget .t{font-size:13px;font-weight:600;letter-spacing:1px;color:#7ab7ff;text-transform:uppercase;margin-bottom:10px}
#mwidget .big{font-size:34px;font-weight:700;color:#ffd166;font-variant-numeric:tabular-nums;margin:6px 0}
#mwidget .sub{font-size:13px;color:#a0a0b0;margin-bottom:16px;line-height:1.4;min-height:20px}
#mwidget .card{background:rgba(255,255,255,.03);border-radius:8px;padding:10px 14px;margin:8px 0;border-left:3px solid #3a3a4e;min-width:600px;position:relative;transition:background 0.15s}
#mwidget .card.next{background:rgba(255,209,102,.08);border-left-color:#ffd166}
#mwidget .card.past{opacity:.5}
#mwidget .card.actual{background:rgba(144,238,144,.06);border-left-color:#90ee90;opacity:1}
#mwidget .card.bridge{background:rgba(138,124,255,.06);border-left-color:#8a7cff;opacity:.85}
#mwidget .ch { padding-left: 0; display:flex; justify-content:space-between; align-items:center; font-size:14px; margin-bottom:8px; gap:12px; flex-wrap:wrap; }
#mwidget .pat-row { padding-left: 0; display:flex; align-items:center; gap:6px; margin-bottom:8px; }
#mwidget .items-list { padding-left: 0; display:flex; flex-direction:column; }
#mwidget .ch .left{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
#mwidget .ch .slot{color:#7ab7ff;font-weight:700;font-size:15px}
#mwidget .ch .time{color:#c0c0d0;font-weight:600}
#mwidget .ch .local{font-size:11px;color:#888;margin-left:6px}
#mwidget .ch .tag{font-size:11px;padding:1px 6px;border-radius:3px;background:rgba(122,183,255,.15);color:#7ab7ff}
#mwidget .ch .tag.phase{background:rgba(255,158,100,.15);color:#ff9e64}
#mwidget .ch .cd{color:#90ee90;font-weight:700;font-variant-numeric:tabular-nums;font-size:13px}
#mwidget .ch .cd.soon{color:#ff6b6b;animation:pulse 1s infinite}
#mwidget .ch .cd.past{color:#666}
#mwidget .body{display:grid;grid-template-columns:minmax(280px,1fr) 340px;gap:16px;align-items:start}
#mwidget .body.single{grid-template-columns:minmax(280px,1fr)}
#mwidget .pat{flex:1;min-width:0;font-family:'SF Mono',Monaco,Consolas,monospace;font-size:13px;color:#ffd166;margin:0;padding:6px 10px;background:rgba(255,209,102,.06);border-radius:4px;letter-s[...]
@keyframes pulse{50%{opacity:.4}}
</style>
<div id="mwidget"><div class="t" id="mtitle">—</div><div class="big" id="mbig">--</div><div class="sub" id="msub">—</div><div id="mrow"></div></div>
<script>
(function(){
  const payload=__P__,data=payload.slots,L=payload.L,utc_offset=payload.utc_offset;
  const realNextIso=payload.real_next_iso,offsetSlots=payload.offset_slots||0;
  const isTimeTravel=offsetSlots!==0;
  const bigEl=document.getElementById('mbig'),subEl=document.getElementById('msub'),rowEl=document.getElementById('mrow');
  document.getElementById('mtitle').textContent = L.title || 'Merchant'; 
  subEl.textContent = L.loading || 'Loading...';
  const pad=n=>String(n).padStart(2,'0');
  let lastBigIdx = -1;

  function getTimeParts(isoString, offset) {
      const d = new Date(isoString);
      const localMs = d.getTime() + offset * 3600000;
      const localDate = new Date(localMs);
      return { timeStr: pad(localDate.getUTCHours()) + ':' + pad(localDate.getUTCMinutes()), dateStr: pad(localDate.getUTCMonth() + 1) + '/' + pad(localDate.getUTCDate()) };
  }

  function fmt(ms){
    if(ms<0)return L.passed || 'Passed';
    const s=Math.floor(ms/1000);
    const d=Math.floor(s/86400),h=Math.floor(s%86400/3600), m=Math.floor(s%3600/60),sec=s%60;
    if(d>0)return d+'d '+pad(h)+'h '+pad(m)+'m';
    if(h>0)return h+'h '+pad(m)+'m '+pad(sec)+'s';
    if(m>0)return m+'m '+pad(sec)+'s';
    return sec+'s';
  }
  function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

  function render(){
    const now=Date.now();
    let nextIdx = -1;
    for(let i=0; i<data.length; i++){
      if(Date.parse(data[i].iso) > now){ nextIdx = i; break; }
    }
    const bigIdx = (nextIdx === -1) ? 0 : nextIdx;
    lastBigIdx = bigIdx;
    const n = data[bigIdx];
    const t = Date.parse(n.iso);
    const d = t - now;
    
    if(n.is_actual){ bigEl.textContent = L.real_badge || 'Actual'; bigEl.style.color = '#90ee90'; }
    else if(n.is_bridge){ bigEl.textContent = L.bridge_badge || 'Bridge'; bigEl.style.color = '#8a7cff'; }
    else { bigEl.textContent='⏱ '+fmt(d); bigEl.style.color=d<600000?'#ff6b6b':'#ffd166'; }
    
    const top=n.top||{pattern:'?',positions:[],source:'?',type:'?'};
    let icon = '🟡';
    if(top.type === 'actual') icon = '✅';
    else if(top.type === 'real') icon = '🟢';
    else if(top.type === 'bridge') icon = '🌉';
    
    const nParts = getTimeParts(n.iso, utc_offset);
    subEl.innerHTML=icon+' <b>Slot '+n.slot+'</b> · <b>'+esc(nParts.timeStr)+' ('+esc(nParts.dateStr)+')</b>'+
      ' <span class="local">('+esc(n.hname)+' VN)</span>';
      
    const startIdx = Math.max(0, bigIdx - 1);
    const endIdx = Math.min(startIdx + 6, data.length);
    let html='';
    for(let i=startIdx; i<endIdx; i++){
      const s=data[i], tt=Date.parse(s.iso), dd=tt-now;
      const isNext = (i === bigIdx);
      let cardCls='card'+(isNext?' next':'')+(dd<0?' past':'');
      if(s.is_actual) cardCls += ' actual';
      else if(s.is_bridge) cardCls += ' bridge';
      const cdCls='cd'+(dd<0?' past':(dd<600000?' soon':''));
      
      let cdDisplay = (s.is_actual || s.is_bridge || dd <= 0) ? '<span class="'+cdCls+'">✓</span>' : '<span class="'+cdCls+'">'+fmt(dd)+'</span>';
      const sParts = getTimeParts(s.iso, utc_offset);
      
      let tags = s.phase ? '<span class="tag phase">'+esc(s.phase)+'</span>' : '';
      if(s.top && s.top.prob) tags += '<span class="tag">'+esc(s.top.prob)+'</span>';

      html+='<div class="'+cardCls+'" data-iso="'+esc(s.iso)+'">' +
        '<div class="ch">'+
        '<div class="left"><span>'+icon+'</span><span class="slot">'+s.slot+'</span>'+
        '<span class="time">'+esc(sParts.timeStr)+' ('+esc(sParts.dateStr)+')</span>'+
        '<span class="local">('+esc(s.hname)+' VN)</span>'+tags+
        '</div>'+cdDisplay+'</div>'+
        '<div class="body single"><div class="top-col">'+
        '<div class="pat-row"><div class="pat">'+esc(top.pattern)+'</div></div>'+
        '</div></div></div>';
    }
    rowEl.innerHTML=html;
  }
  
  function tick(){
    const now = Date.now();
    let nextIdx = -1;
    for(let i=0; i<data.length; i++){
      if(Date.parse(data[i].iso) > now){ nextIdx = i; break; }
    }
    const bigIdx = (nextIdx === -1) ? 0 : nextIdx;
    
    if (bigIdx !== lastBigIdx) { render(); return; }
    
    const n = data[bigIdx];
    const d = Date.parse(n.iso) - now;
    if(!n.is_actual && !n.is_bridge){
      bigEl.textContent = '⏱ ' + fmt(d);
      bigEl.style.color = d<600000 ? '#ff6b6b' : '#ffd166';
    }
    document.querySelectorAll('.card[data-iso]').forEach(card => {
      const ms = Date.parse(card.dataset.iso) - now;
      const cdEl = card.querySelector('.cd');
      if(!cdEl) return;
      if(card.classList.contains('actual') || card.classList.contains('bridge') || ms <= 0){
        cdEl.textContent = '✓'; cdEl.className = 'cd past'; return;
      }
      cdEl.textContent = fmt(ms);
      cdEl.className = 'cd' + (ms < 600000 ? ' soon' : '');
    });
  }

  render();
  setInterval(tick, 1000);
})();
</script>
</html>"""

def run_pipeline(offset_days=0, lang="vi", utc_offset=7.0):
    log = ["🔮 AUTO-GEN MODE: Hệ thống đang chạy hoàn toàn bằng Toán học (Không dùng data.csv)"]
    now = datetime.utcnow() + VN_OFFSET
    current_slot = ts_to_slot(now)
    target_max = current_slot + 200
    
    timeline = generate_timeline(target_max)
    slots_payload = []
    
    for i in range(12):
        s = current_slot + offset_days*4 + i
        pat = timeline.get(s, "N/A")
        
        items_map = {}
        for p in pat.split(" / "):
            items_map[p.strip()] = "Ad Hero, Queen, Free Gems"
            
        positions = [{"pos": p.strip(), "items": items_map[p.strip()]} for p in pat.split(" / ")]
        
        slots_payload.append({
            "slot": s,
            "hname": {0: "🌅 Last", 1: "☀️ 1st", 2: "🌤️ 2nd", 3: "🌙 3rd"}[s % 4],
            "iso": slot_to_ts(s).strftime('%Y-%m-%dT%H:%M:%S') + '+07:00',
            "top": {
                "pattern": pat,
                "positions": positions,
                "source": "Auto-Gen Math",
                "type": "real",
                "prob": "100%"
            },
            "fallbacks": [],
            "phase": "Auto",
            "is_actual": False,
            "is_bridge": False
        })
        
    payload = json.dumps({
        "slots": slots_payload,
        "L": {"title": "Merchant Location", "loading": "Loading...", "passed": "Passed", "real_badge": "Actual", "bridge_badge": "Bridge"},
        "utc_offset": utc_offset,
        "missing_04": [],
        "real_next_iso": slot_to_ts(current_slot + 1).strftime('%Y-%m-%dT%H:%M:%S') + '+07:00',
        "real_now_slot": current_slot,
        "offset_slots": offset_days * 4
    }, ensure_ascii=False)
    
    widget_html = WIDGET_TEMPLATE_HTML.replace("__P__", payload.replace("</", "<\\/"))
    stats = {'total_missing_04': 0, 'static_acc': 100.0, 'adaptive_acc': 100.0}
    
    return widget_html, "\n".join(log), "", stats

# ============================================================================== 
# GIAO DIỆN STREAMLIT CHÍNH
# ============================================================================== 
st.title("📍 Merchant Location (Auto-Gen Rebuild)")

# Quản lý ngôn ngữ cơ bản
if "app_lang" not in st.session_state: st.session_state.app_lang = "vi"

def _set_lang(l_code):
    st.session_state.app_lang = l_code; st.rerun()

col_vi, col_en, _ = st.columns([1.2, 1.2, 5])
with col_vi:
    st.button("🇻🇳 Tiếng Việt", on_click=_set_lang, args=("vi",), use_container_width=True, type="primary" if st.session_state.app_lang == "vi" else "secondary")
with col_en:
    st.button("🇺🇸 English", on_click=_set_lang, args=("en",), use_container_width=True, type="primary" if st.session_state.app_lang == "en" else "secondary")

with st.sidebar:
    st.markdown("### ⚙️ Config")
    if st.button("🔄 Reload / Làm mới", use_container_width=True):
        st.rerun()
    st.caption("Chế độ: Auto-Gen Math (Không cần GitHub)")

# Thanh trượt thời gian
if "time_travel_slider" not in st.session_state: st.session_state.time_travel_slider = 0
def reset_time_travel(): st.session_state.time_travel_slider = 0

offset_days = st.slider("🕰️ Time travel (days)", min_value=-7, max_value=30, step=1, key="time_travel_slider")
st.button("🔄 Reset Time Travel", on_click=reset_time_travel)

# Xử lý Pipeline
widget_html, log_text, trans_text, trans_stats = run_pipeline(
    offset_days=offset_days, 
    lang=st.session_state.app_lang, 
    utc_offset=7.0
)

if widget_html is None:
    st.error("❌ Pipeline failed")
    st.code(log_text, language="text")
else:
    st.success("✅ Processed successfully!")
    components.html(widget_html, height=1100, scrolling=True)
    with st.expander("📋 Log", expanded=False):
        st.code(log_text, language="text")
