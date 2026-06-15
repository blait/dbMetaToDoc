"""Shared detail-page template (tree catalog + similarity comparison).

Used by viewer.py (static, data inlined) and webapp.py (data fetched from
the API). The template defines `init(CATALOG, SCORE, DETAILS)`; the
__BOOTSTRAP__ placeholder supplies the data and calls it. SCORE/DETAILS
may be null (run scored without ground truth) — the page degrades to a
catalog-only view.
"""

DETAIL_PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>db2doc v2 — Catalog & Similarity</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<style>
:root{--bg:#f5f6f8;--surface:#fff;--ink:#16181d;--muted:#6b7280;--line:#e5e7eb;
 --accent:#4f46e5;--accent-soft:#eef2ff;--ok:#16a34a;--warn:#d97706;--bad:#dc2626;
 --shadow:0 1px 2px rgba(16,24,40,.06)}
*{box-sizing:border-box}
body{font:14px/1.6 "Pretendard Variable",Pretendard,-apple-system,BlinkMacSystemFont,
 "Segoe UI","Apple SD Gothic Neo","Malgun Gothic",sans-serif;color:var(--ink);
 margin:0;height:100vh;display:flex;flex-direction:column;overflow:hidden;
 background:var(--bg)}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:#eef0f3;
 padding:1px 6px;border-radius:6px;font-size:88%}
header{background:#14171f;color:#e8eaef;display:flex;align-items:center;gap:12px;
 padding:0 22px;height:54px;flex:none}
header .brand{display:flex;align-items:center;gap:9px;font-weight:700;font-size:15px}
header .brand .logo{width:24px;height:24px;border-radius:7px;display:grid;
 place-items:center;background:linear-gradient(135deg,#6366f1,#a855f7);
 font-size:13px;color:#fff}
header h1{font-size:14px;margin:0;font-weight:600;color:#c8cdd9}
header .small{color:#8b93a5;font-size:12px;overflow:hidden;white-space:nowrap;
 text-overflow:ellipsis;max-width:46vw}
header a{color:#a5b4fc;text-decoration:none;font-size:12.5px;font-weight:600}
header a:hover{color:#c7d2fe}
.scorecards{display:flex;gap:10px;padding:12px 22px;flex-wrap:wrap;flex:none;
 border-bottom:1px solid var(--line);background:var(--surface)}
.card{border:1px solid var(--line);border-radius:12px;padding:9px 16px;
 min-width:148px;background:var(--surface);box-shadow:var(--shadow)}
.card b{display:block;font-size:21px;letter-spacing:-.02em;
 font-variant-numeric:tabular-nums}
.card .lbl{color:var(--muted);font-size:11.5px;font-weight:600}
.card .src{display:inline-block;margin-top:5px;font-size:10px;border-radius:999px;
 padding:1px 8px;border:1px solid var(--line);color:var(--muted);cursor:help;
 font-weight:600;letter-spacing:.01em}
.card .src.llm{background:var(--accent-soft);border-color:#c7d2fe;color:var(--accent)}
.card .src.det{background:#dcfce7;border-color:#bbf7d0;color:#166534}
.split{flex:1;display:flex;min-height:0}
aside{width:332px;flex:none;border-right:1px solid var(--line);display:flex;
 flex-direction:column;min-height:0;background:var(--surface)}
aside .search{padding:12px;border-bottom:1px solid var(--line)}
aside input[type=search]{width:100%;padding:8px 12px;border:1px solid var(--line);
 border-radius:9px;font-size:13px;font-family:inherit;background:#fafbfc}
aside input[type=search]:focus{outline:none;border-color:var(--accent);
 box-shadow:0 0 0 3px rgba(79,70,229,.12);background:#fff}
.tree{overflow-y:auto;flex:1;padding:8px 6px 30px}
.tree .db-node,.tree .tbl-node,.tree .col-node{cursor:pointer;border-radius:8px;
 display:flex;align-items:center;gap:6px;padding:5px 9px;white-space:nowrap;
 overflow:hidden;text-overflow:ellipsis;transition:background .1s}
.tree .db-node{font-weight:700}
.tree .tbl-node{margin-left:10px;font-weight:500}
.tree .col-node{margin-left:34px;font-size:12.5px;color:#4b5563}
.tree .db-node:hover,.tree .tbl-node:hover,.tree .col-node:hover{background:#f1f2f5}
.tree .sel{background:var(--accent-soft)!important;color:var(--accent)}
.tree .sel .cnt{color:var(--accent)}
.tree .twisty{width:12px;flex:none;color:var(--muted);font-size:10px;text-align:center}
.tree .cnt{color:#9ca3af;font-size:11px;margin-left:auto;padding-left:6px}
.tree .badge{font-size:9.5px;border-radius:5px;padding:1px 5px;flex:none;font-weight:700}
.tree .badge.pk{background:#fef3c7;color:#92400e}
.tree .badge.fk{background:var(--accent-soft);color:var(--accent)}
.tree .j1{color:var(--ok);flex:none}.tree .j0{color:var(--bad);flex:none}
.tree .empty{color:#b6bcc6}
.detail{flex:1;overflow-y:auto;padding:22px 30px;min-width:0}
.detail h2{margin:0 0 6px;font-size:19px;letter-spacing:-.01em}
.detail h3{font-size:11.5px;margin:24px 0 10px;color:var(--muted);
 text-transform:uppercase;letter-spacing:.07em;font-weight:700}
.kv{display:grid;grid-template-columns:130px 1fr;gap:5px 14px;font-size:13px;
 margin:12px 0;background:var(--surface);border:1px solid var(--line);
 border-radius:12px;padding:14px 18px;box-shadow:var(--shadow)}
.kv dt{color:var(--muted);font-weight:600}.kv dd{margin:0}
.descbox{border:1px solid var(--line);border-radius:12px;padding:12px 16px;
 margin:8px 0;background:var(--surface);box-shadow:var(--shadow)}
.descbox.gen{background:#f5f7ff;border-color:#c7d2fe}
.descbox.ref{background:#f2fdf5;border-color:#bbf7d0}
.descbox .tag{font-size:10.5px;color:var(--muted);display:block;margin-bottom:5px;
 font-weight:700;text-transform:uppercase;letter-spacing:.05em}
.judge-line{margin:10px 0;font-size:13px}
.judge1{color:var(--ok);font-weight:700}.judge0{color:var(--bad);font-weight:700}
.conf-hi{color:var(--ok);font-weight:600}.conf-lo{color:var(--warn);font-weight:600}
table{border-collapse:separate;border-spacing:0;width:100%;font-size:13px;
 margin:6px 0;background:var(--surface);border:1px solid var(--line);
 border-radius:12px;overflow:hidden;box-shadow:var(--shadow)}
th,td{border-bottom:1px solid var(--line);padding:8px 12px;text-align:left;
 vertical-align:top}
tr:last-child td{border-bottom:none}
th{background:#fafbfc;color:var(--muted);font-size:11px;font-weight:700;
 text-transform:uppercase;letter-spacing:.05em}
.pill{display:inline-block;border:1px solid var(--line);border-radius:999px;
 padding:1px 9px;font-size:11px;color:var(--muted);font-weight:600;background:#fff}
.clickable{cursor:pointer;color:var(--accent);font-weight:500}
.clickable:hover{text-decoration:underline}
.footnote{border-top:1px solid var(--line);margin-top:28px;padding-top:14px;
 color:var(--muted);font-size:12px}
.small{font-size:12px}
</style></head><body>
<header>
 <span class="brand"><span class="logo">◈</span>db2doc</span>
 <h1 id="hdrtitle">카탈로그 &amp; 유사도</h1>
 <span class="small" id="hdrline"></span>
 <span style="margin-left:auto">__BACKLINK__</span>
</header>
<div class="scorecards" id="cards"></div>
<div class="split">
 <aside>
  <div class="search"><input type="search" id="q" placeholder="테이블/컬럼 검색..."></div>
  <div class="tree" id="tree"></div>
 </aside>
 <div class="detail" id="detail"></div>
</div>
<script>
function init(CATALOG, SCORE, DETAILS){
const esc = s => (s??'').toString().replace(/[&<>"]/g,
  c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const conf = c => c==null ? '' :
  `<span class="${c>=0.7?'conf-hi':'conf-lo'}">${c.toFixed(2)}</span>`;

const scoreBy = {};
if (DETAILS) DETAILS.items.forEach(d=>{
  scoreBy[d.level==='table' ? d.table : d.table+'.'+d.column] = d;
});

const GEN_MODEL = CATALOG.model || '?';
const SM = (SCORE && SCORE.scoring_methods) || {};
const judgeModel = SM.judge_accuracy?.model || GEN_MODEL;
const embedModel = SM.mean_cosine?.model || 'embedding';
document.getElementById('hdrline').textContent =
 `${CATALOG.database.domain||''} — ${CATALOG.database.db_description||''}`;

function srcBadge(kind){
  if(kind==='judge') return `<span class="src llm" title="${esc(SM.judge_accuracy?.method||'')}">LLM judge · ${esc(judgeModel)}</span>`;
  if(kind==='cos')   return `<span class="src" title="${esc(SM.mean_cosine?.method||'')}">임베딩(비-LLM) · ${esc(embedModel)}</span>`;
  if(kind==='det')   return `<span class="src det" title="${esc(SM.pk_fk_f1?.method||'')}">결정적 집합비교 (비-LLM)</span>`;
  if(kind==='form')  return `<span class="src det" title="${esc(SM.Soverall?.method||'')}">산식 (비-LLM)</span>`;
  return '';
}
if (SCORE){
  const dm = SCORE.description_match, rel = SCORE.relations;
  document.getElementById('cards').innerHTML = [
   {l:'컬럼 의미 일치', v:dm.column.judge_accuracy!=null?(dm.column.judge_accuracy*100).toFixed(1)+'%':'—',
    s:`n=${dm.column.n}`, b:srcBadge('judge')},
   {l:'테이블 의미 일치', v:dm.table.judge_accuracy!=null?(dm.table.judge_accuracy*100).toFixed(1)+'%':'—',
    s:`n=${dm.table.n}`, b:srcBadge('judge')},
   {l:'컬럼 cosine 평균', v:dm.column.mean_cosine?.toFixed(3)??'—',
    s:'보조 지표', b:srcBadge('cos')},
   {l:'PK F1', v:rel.primary_key_f1.f1,
    s:`P ${rel.primary_key_f1.precision} / R ${rel.primary_key_f1.recall}`, b:srcBadge('det')},
   {l:'FK F1', v:rel.foreign_key_f1.f1,
    s:`P ${rel.foreign_key_f1.precision} / R ${rel.foreign_key_f1.recall}`, b:srcBadge('det')},
   {l:'S_overall', v:SCORE.Soverall, s:'DBAutoDoc 종합', b:srcBadge('form')},
  ].map(c=>`<div class="card"><span class="lbl">${c.l}</span><b>${c.v}</b>
    <span class="lbl">${c.s}</span><br>${c.b}</div>`).join('');
} else {
  document.getElementById('cards').innerHTML =
   `<div class="card"><span class="lbl">채점</span><b>—</b>
     <span class="lbl">정답지 없는 런: 카탈로그만 생성됨</span></div>
    <div class="card"><span class="lbl">테이블</span><b>${CATALOG.tables.length}</b>
     <span class="lbl">컬럼 ${CATALOG.tables.reduce((a,t)=>a+t.columns.length,0)}</span></div>
    <div class="card"><span class="lbl">생성 모델</span>
     <b style="font-size:13px;line-height:2">${esc(GEN_MODEL)}</b>
     <span class="src llm">LLM</span></div>`;
}

const open = new Set();
let selected = null;

function judgeMark(key){
  const d = scoreBy[key];
  if(!d || d.judge==null) return '';
  return d.judge===1 ? '<span class="j1">✓</span>' : '<span class="j0">✗</span>';
}

function renderTree(filter){
  const root = document.getElementById('tree');
  let html = `<div class="db-node ${selected==='db'?'sel':''}" data-id="db">
    <span class="twisty">▦</span>${esc(CATALOG.schema)}
    <span class="cnt">${CATALOG.tables.length} tables</span></div>`;
  CATALOG.tables.forEach(t=>{
    const cols = t.columns.filter(c=>!filter
      || t.name.toLowerCase().includes(filter)
      || c.name.toLowerCase().includes(filter));
    const tblMatch = !filter || t.name.toLowerCase().includes(filter)
      || cols.length;
    if(!tblMatch) return;
    const isOpen = filter ? true : open.has(t.name);
    html += `<div class="tbl-node ${selected===t.name?'sel':''}" data-id="${esc(t.name)}">
      <span class="twisty">${isOpen?'▾':'▸'}</span>
      <span>${esc(t.name)}</span>
      ${t.rowcount===0?'<span class="badge empty">empty</span>':''}
      ${judgeMark(t.name)}
      <span class="cnt">${t.columns.length}c · ${t.rowcount}r</span></div>`;
    if(isOpen){
      (filter?cols:t.columns).forEach(c=>{
        const key = t.name+'.'+c.name;
        html += `<div class="col-node ${selected===key?'sel':''}" data-id="${esc(key)}">
          <span>${esc(c.name)}</span>
          ${c.is_pk?'<span class="badge pk">PK</span>':''}
          ${c.fk?'<span class="badge fk">FK</span>':''}
          ${judgeMark(key)}</div>`;
      });
    }
  });
  root.innerHTML = html;
  root.querySelectorAll('[data-id]').forEach(el=>{
    el.onclick = ()=>{
      const id = el.dataset.id;
      if(id!=='db' && !id.includes('.')){
        if(selected===id) open.has(id)?open.delete(id):open.add(id);
        else open.add(id);
      }
      selected = id;
      renderTree(currentFilter());
      renderDetail(id);
    };
  });
}
const currentFilter = ()=>document.getElementById('q').value.trim().toLowerCase();
document.getElementById('q').oninput = ()=>renderTree(currentFilter());

function compareBlock(key, genText){
  const d = scoreBy[key];
  if(!d) {
    if (genText) return `
      <div class="descbox gen"><span class="tag">생성된 설명 (${esc(GEN_MODEL)})</span>
        ${esc(genText)}</div>
      <p class="small" style="color:var(--muted)">${SCORE
        ? '정답지에 채점 가능한 참조 텍스트가 없어 채점 제외 (정답 NA/빈값).'
        : '이 런은 정답지 채점 없이 생성되었습니다.'}</p>`;
    return '';
  }
  return `
   <div class="descbox gen"><span class="tag">생성된 설명 (${esc(GEN_MODEL)})</span>
     ${esc(d.generated)}</div>
   <div class="descbox ref"><span class="tag">공식 정답지 (한글화)</span>${esc(d.reference)}</div>
   <div class="judge-line">
     judge: ${d.judge===1?'<span class="judge1">✓ 의미 일치</span>'
            :d.judge===0?'<span class="judge0">✗ 불일치</span>':'—'}
     <span class="pill" title="${esc(SM.judge_accuracy?.method||'')}">LLM judge · ${esc(judgeModel)}</span>
     &nbsp; cosine: ${d.cosine?.toFixed(3)??'—'}
     <span class="pill" title="${esc(SM.mean_cosine?.method||'')}">임베딩 · ${esc(embedModel)}</span>
   </div>
   ${d.judge===0&&d.judge_reason?`<p class="small" style="color:var(--bad)">
     judge 사유: ${esc(d.judge_reason)}</p>`:''}`;
}

function renderDetail(id){
  const el = document.getElementById('detail');
  if(!id || id==='db'){
    el.innerHTML = `<h2>${esc(CATALOG.schema)} <span class="pill">database</span></h2>
     <div class="descbox gen"><span class="tag">생성된 DB 설명 (${esc(GEN_MODEL)})</span>
       ${esc(CATALOG.database.db_description||'')}</div>
     <dl class="kv">
       <dt>도메인 추론</dt><dd>${esc(CATALOG.database.domain||'')}</dd>
       <dt>테이블</dt><dd>${CATALOG.tables.length}</dd>
       <dt>컬럼</dt><dd>${CATALOG.tables.reduce((a,t)=>a+t.columns.length,0)}</dd>
     </dl>
     ${Object.keys(SM).length ? `<h3>채점 방법 (점수 출처)</h3>
     <table><thead><tr><th>지표</th><th>방법</th><th>LLM?</th><th>모델</th></tr></thead><tbody>
     ${Object.entries(SM).map(([k,v])=>`<tr><td><code>${esc(k)}</code></td>
       <td>${esc(v.method)}</td><td>${v.is_llm?'예':'아니오'}</td>
       <td>${esc(v.model||'—')}</td></tr>`).join('')}
     </tbody></table>` : `<p class="small" style="color:var(--muted)">
       이 런은 정답지 채점 없이 카탈로그만 생성되었습니다.</p>`}
     <p class="footnote">설명 생성 모델: <code>${esc(GEN_MODEL)}</code> ·
      좌측 트리에서 테이블/컬럼을 선택하면 상세를 봅니다.
      ${SCORE?'✓/✗는 LLM judge 판정.':''}</p>`;
    return;
  }
  if(!id.includes('.')){
    const t = CATALOG.tables.find(x=>x.name===id);
    if(!t) return;
    el.innerHTML = `<h2><code>${esc(t.name)}</code> <span class="pill">table</span>
      ${t.sanity_revised?'<span class="pill">sanity-revised</span>':''}</h2>
     <dl class="kv">
      <dt>행 수</dt><dd>${t.rowcount}</dd>
      <dt>PK (복원)</dt><dd>${t.primary_key
        ? t.primary_key.columns.map(c=>`<code>${esc(c)}</code>`).join(', ')
          + ` <span class="pill">${esc(t.primary_key.source)}</span> ${conf(t.primary_key.confidence)}`
        : '—'}</dd>
      <dt>FK (복원)</dt><dd>${t.foreign_keys.length
        ? t.foreign_keys.map(f=>`<div><code>${esc(f.column)}</code> →
           <code>${esc(f.ref)}</code> <span class="pill">${esc(f.source)}</span>
           ${conf(f.confidence)}</div>`).join('')
        : '—'}</dd>
     </dl>
     <h3>테이블 설명 ${scoreBy[t.name]?'— 생성 vs 정답':''}</h3>
     ${compareBlock(t.name, t.description)}
     ${t.reasoning?`<p class="small" style="color:var(--muted)">추론 근거: ${esc(t.reasoning)}</p>`:''}
     <h3>컬럼 (${t.columns.length})</h3>
     <table><thead><tr><th>컬럼</th><th>타입</th><th>키</th><th>설명 (생성)</th>
       <th>conf</th>${SCORE?'<th>judge</th>':''}</tr></thead><tbody>
     ${t.columns.map(c=>{
        const key = t.name+'.'+c.name;
        return `<tr><td><span class="clickable" data-goto="${esc(key)}">
          ${esc(c.name)}</span></td>
         <td>${esc(c.type)}</td>
         <td>${c.is_pk?'PK':''}${c.fk?` FK→${esc(c.fk)}`:''}</td>
         <td>${esc(c.description)}</td>
         <td>${conf(c.confidence)}${c.data_unverified?' ⚠':''}</td>
         ${SCORE?`<td>${judgeMark(key)||'—'}</td>`:''}</tr>`;}).join('')}
     </tbody></table>`;
  } else {
    const [tn, cn] = [id.slice(0,id.indexOf('.')), id.slice(id.indexOf('.')+1)];
    const t = CATALOG.tables.find(x=>x.name===tn);
    const c = t?.columns.find(x=>x.name===cn);
    if(!c) return;
    const ev = c.evidence||{};
    el.innerHTML = `<h2><span class="clickable" data-goto="${esc(tn)}">
      ${esc(tn)}</span>.<code>${esc(cn)}</code> <span class="pill">column</span></h2>
     <dl class="kv">
      <dt>타입</dt><dd>${esc(c.type)} ${c.nullable?'(nullable)':''}</dd>
      <dt>키</dt><dd>${c.is_pk?'PK ':''}${c.fk?`FK → <code>${esc(c.fk)}</code>
        <span class="pill">${esc(c.fk_source)}</span>`:(c.is_pk?'':'—')}</dd>
      <dt>신뢰도</dt><dd>${conf(c.confidence)}
        ${c.data_unverified?'<span class="pill">⚠ data-unverified</span>':''}</dd>
      <dt>증거</dt><dd>
        ${ev.has_data?'데이터 있음':'<b>데이터 없음(빈 테이블)</b>'} ·
        분포 ${ev.has_distribution?'측정됨':'없음'} ·
        코드 라벨 ${ev.resolved_codes?'<b>FK 조인으로 해석됨</b>':'미해석'}</dd>
      <dt>통계</dt><dd>distinct_ratio ${c.stats.distinct_ratio??'—'} ·
        null_ratio ${c.stats.null_ratio??'—'}</dd>
      <dt>샘플 값</dt><dd>${(c.stats.examples||[]).map(v=>`<code>${esc(v)}</code>`).join(' ')||'—'}</dd>
     </dl>
     <h3>컬럼 설명 ${scoreBy[id]?'— 생성 vs 정답':''}</h3>
     ${compareBlock(id, c.description)}`;
  }
  el.querySelectorAll('[data-goto]').forEach(a=>a.onclick=()=>{
    const gid = a.dataset.goto;
    if(gid.includes('.')) open.add(gid.split('.')[0]); else open.add(gid);
    selected = gid; renderTree(currentFilter()); renderDetail(gid);
    document.getElementById('detail').scrollTop = 0;
  });
}

renderTree('');
renderDetail('db');
}
</script>
<script>__BOOTSTRAP__</script>
</body></html>
"""


def render_inline(catalog_json, score_json, details_json, backlink=""):
    """Static build: inline the data and call init() immediately."""
    boot = (f"init({catalog_json}, {score_json or 'null'}, "
            f"{details_json or 'null'});")
    return (DETAIL_PAGE
            .replace("__BACKLINK__", backlink)
            .replace("__BOOTSTRAP__", boot))


def render_fetching(run_id):
    """Web-app build: fetch the artifacts from the API, then init()."""
    boot = f"""
(async () => {{
  const get = async n => {{
    const r = await fetch('/api/runs/{run_id}/artifact/' + n);
    return r.ok ? r.json() : null;
  }};
  const catalog = await get('catalog.json');
  if (!catalog) {{
    document.getElementById('detail').innerHTML =
      '<p>catalog.json이 아직 없습니다. 파이프라인이 진행 중이거나 실패했습니다.</p>';
    return;
  }}
  init(catalog, await get('score.json'), await get('score_details.json'));
}})();"""
    back = (f'<a href="/runs/{run_id}/graph">스키마 그래프 (Neptune) &rarr;</a>'
            f'&nbsp;&nbsp;<a href="/">&larr; 런 목록</a>')
    return (DETAIL_PAGE
            .replace("__BACKLINK__", back)
            .replace("__BOOTSTRAP__", boot))
