"""Schema-graph visualization page (Neptune-backed).

Served by webapp.py at /runs/{rid}/graph. Fetches nodes/edges + join paths
from the backend API (openCypher on Neptune Analytics) and renders with
vis-network. Local catalog fallback keeps the page working without Neptune.

UX notes:
  - physics runs only during initial stabilization, then is switched OFF so
    the layout stays put; dragged nodes stay where the user drops them.
  - the right panel is drag-resizable (320-720px, persisted in localStorage).
  - edges are first-class: hover shows the join condition, click opens a
    relation panel (joined columns, provenance, confidence, inclusion).
"""

GRAPH_PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>db2doc v2 — Schema Graph</title>
<script src="https://cdn.jsdelivr.net/npm/vis-network@10.1.0/standalone/umd/vis-network.min.js"></script>
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
header a{color:#a5b4fc;text-decoration:none;font-size:12.5px;font-weight:600}
header a:hover{color:#c7d2fe}
.navtabs{display:flex;gap:4px;background:#222736;border:1px solid #2c3242;
 border-radius:9px;padding:3px}
.navtab{display:inline-flex;align-items:center;gap:5px;font-size:12.5px;
 font-weight:600;color:#aab2c5;text-decoration:none;padding:5px 12px;
 border-radius:7px;transition:all .12s;white-space:nowrap}
.navtab:hover{color:#fff;background:#2c3242}
.navtab.active{background:linear-gradient(135deg,#6366f1,#7c5cf0);color:#fff;
 box-shadow:0 1px 3px rgba(99,102,241,.4)}
.navtab.active:hover{color:#fff}
.navback{display:inline-flex;align-items:center;gap:5px;font-size:12.5px;
 font-weight:600;color:#8b93a5;text-decoration:none;padding:5px 12px;
 border:1px solid #2c3242;border-radius:9px;transition:all .12s}
.navback:hover{color:#e8eaef;border-color:#3b4150;background:#222736}
.src-pill{font-size:10.5px;border-radius:999px;padding:2px 10px;font-weight:600;
 background:#222736;color:#8b93a5;border:1px solid #2c3242}
.src-pill.neptune{background:#1e2742;border-color:#3b4a7a;color:#a5b4fc}
.toolbar{padding:9px 22px;border-bottom:1px solid var(--line);flex:none;
 display:flex;gap:9px;align-items:center;flex-wrap:wrap;background:var(--surface)}
.toolbar .tlabel{font-size:12.5px;font-weight:700;color:var(--muted)}
.toolbar select{padding:7px 11px;border:1px solid var(--line);border-radius:9px;
 font-size:13px;font-family:inherit;background:#fafbfc;max-width:190px}
.toolbar select:focus{outline:none;border-color:var(--accent)}
.toolbar .arrow{color:var(--muted)}
.toolbar button{padding:7px 14px;border:1px solid var(--line);border-radius:9px;
 font-size:13px;font-family:inherit;font-weight:600;background:#fff;cursor:pointer;
 transition:all .15s}
.toolbar button:hover{background:#f5f6f8}
.toolbar button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
.toolbar button.primary:hover{background:#4338ca}
.toolbar label.toggle{display:flex;align-items:center;gap:6px;font-size:12.5px;
 color:var(--muted);cursor:pointer;user-select:none}
.toolbar label.toggle input{accent-color:var(--accent)}
.toolbar .hint{font-size:11.5px;color:var(--muted)}
.legend{display:flex;gap:13px;font-size:11.5px;color:var(--muted);margin-left:auto;
 align-items:center}
.legend i{display:inline-block;width:9px;height:9px;border-radius:50%;
 margin-right:5px;vertical-align:-1px}
.legend .ln{display:inline-block;width:18px;height:0;border-top:2px solid #9aa4b2;
 margin-right:5px;vertical-align:3px}
.legend .ln.dash{border-top-style:dashed}
.main{flex:1;display:flex;min-height:0;position:relative}
#net{flex:1;min-width:0;background:
 radial-gradient(circle,#e2e5ea 1px,transparent 1px) 0 0/22px 22px}
/* resizable side panel */
.resizer{width:5px;flex:none;cursor:col-resize;background:transparent;
 border-left:1px solid var(--line);transition:background .15s;position:relative;z-index:5}
.resizer:hover,.resizer.active{background:var(--accent);border-left-color:var(--accent)}
.side{width:400px;min-width:320px;max-width:720px;flex:none;overflow-y:auto;
 padding:18px 20px;background:var(--surface)}
.side h2{font-size:17px;margin:0 0 8px;letter-spacing:-.01em;word-break:break-all}
.side h3{font-size:11px;margin:18px 0 8px;color:var(--muted);
 text-transform:uppercase;letter-spacing:.07em;font-weight:700}
.side .desc{border:1px solid #c7d2fe;background:#f5f7ff;border-radius:11px;
 padding:10px 14px;font-size:13px;margin:8px 0}
.kv{display:grid;grid-template-columns:92px 1fr;gap:4px 12px;font-size:12.5px;
 margin:10px 0}
.kv dt{color:var(--muted);font-weight:600}.kv dd{margin:0;word-break:break-all}
table{border-collapse:separate;border-spacing:0;width:100%;font-size:12.5px;
 margin:4px 0;background:var(--surface);border:1px solid var(--line);
 border-radius:10px;overflow:hidden}
th,td{border-bottom:1px solid var(--line);padding:6px 10px;text-align:left;
 vertical-align:top}
tr:last-child td{border-bottom:none}
th{background:#fafbfc;color:var(--muted);font-size:10.5px;font-weight:700;
 text-transform:uppercase;letter-spacing:.05em}
.pill{display:inline-block;border:1px solid var(--line);border-radius:999px;
 padding:0 8px;font-size:10.5px;color:var(--muted);font-weight:600;background:#fff}
.pill.declared{background:#dcfce7;border-color:#bbf7d0;color:#166534}
.pill.stat{background:#dbeafe;border-color:#bfdbfe;color:#1e40af}
.pill.llm{background:var(--accent-soft);border-color:#c7d2fe;color:var(--accent)}
.pill.name{background:#fef3c7;border-color:#fde68a;color:#92400e}
.conf-hi{color:var(--ok);font-weight:700}.conf-lo{color:var(--warn);font-weight:700}
.pathbox{border:1px solid var(--line);border-radius:11px;padding:10px 14px;
 margin:7px 0;font-size:13px;cursor:pointer;transition:all .12s;background:#fff}
.pathbox:hover{border-color:#c7cdd6;box-shadow:var(--shadow)}
.pathbox.sel{border-color:var(--accent);background:var(--accent-soft);
 box-shadow:0 0 0 3px rgba(79,70,229,.1)}
.pathbox .hop{display:inline-block;background:#eef0f3;border-radius:5px;
 padding:0 6px;font-size:10.5px;font-weight:700;color:var(--muted);margin-left:6px}
.pathbox .joins{margin-top:5px;font-size:11px;color:var(--muted);
 font-family:ui-monospace,Menlo,monospace;line-height:1.7}
.sqlbox{background:#14171f;color:#d8dee9;border-radius:11px;padding:12px 14px;
 font:12px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre;
 overflow-x:auto;margin:8px 0}
.relcard{border:1px solid var(--line);border-radius:11px;padding:12px 14px;
 margin:8px 0;background:#fff}
.relcard .join{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;
 background:#f6f7f9;border-radius:8px;padding:8px 10px;margin:8px 0;
 word-break:break-all}
.relcard .cols{display:grid;grid-template-columns:1fr auto 1fr;gap:8px;
 align-items:center;margin:10px 0;font-size:12px}
.relcard .colbox{border:1px solid var(--line);border-radius:9px;padding:7px 10px;
 background:#fafbfc;min-width:0}
.relcard .colbox b{display:block;font-size:12px;word-break:break-all}
.relcard .colbox span{color:var(--muted);font-size:11px}
.relcard .dirarrow{color:var(--accent);font-weight:700}
.small{font-size:12px;color:var(--muted)}
.muted-block{color:var(--muted);font-size:12.5px;line-height:1.7}
</style></head><body>
<header>
 <span class="brand"><span class="logo">◈</span>db2doc</span>
 <h1>스키마 그래프</h1>
 <span class="src-pill" id="srcpill">로딩…</span>
 <span style="margin-left:auto;display:flex;align-items:center;gap:10px">
   <nav class="navtabs">
     <a class="navtab" href="__BACK__">📚 카탈로그</a>
     <a class="navtab active" href="__BACK__/graph">🕸 스키마 그래프</a>
     <a class="navtab" href="__BACK__/text2sql">💬 text2sql</a>
   </nav>
   <a class="navback" href="/">← 런 목록</a>
 </span>
</header>
<div class="toolbar">
 <span class="tlabel">조인 경로</span>
 <select id="fromT"></select> <span class="arrow">→</span> <select id="toT"></select>
 <button class="primary" id="findbtn">경로 탐색</button>
 <button id="resetbtn">초기화</button>
 <button id="fitbtn" title="전체 보기">⤢ 맞춤</button>
 <label class="toggle"><input type="checkbox" id="edgelbl"> 엣지 라벨</label>
 <label class="toggle"><input type="checkbox" id="conceptlayer"> 개념 레이어</label>
 <input type="search" id="csearch" placeholder="개념 검색 (예: 환자, 처방)"
   style="display:none;padding:7px 11px;border:1px solid var(--line);
   border-radius:9px;font-size:13px;font-family:inherit;background:#fafbfc;width:180px">
 <span class="hint" id="qhint"></span>
 <span class="legend">
  <span><i style="background:#6366f1"></i>테이블 (크기=행수)</span>
  <span><i style="background:#c8ccd4"></i>빈 테이블</span>
  <span id="lg-concept" style="display:none"><i style="background:#f59e0b"></i>개념</span>
  <span><span class="ln"></span>선언/통계 FK</span>
  <span><span class="ln dash"></span>이름/LLM 추정</span>
 </span>
</div>
<div class="main">
 <div id="net"></div>
 <div class="resizer" id="resizer"></div>
 <div class="side" id="side">
  <p class="muted-block">· <b>테이블 노드</b>를 클릭하면 생성된 설명·컬럼·FK 상세<br>
  · <b>엣지(선)</b>를 클릭하면 관계 정보(조인 컬럼·복원 출처·신뢰도)<br>
  · 위에서 두 테이블을 고르면 Neptune openCypher 최단 조인 경로와
  JOIN SQL 스켈레톤이 표시됩니다.<br>
  · 노드는 드래그한 자리에 고정되고, 패널 폭은 경계선을 끌어 조절합니다.</p>
 </div>
</div>
<script>
const RID = "__RID__";
let NET, NODES, EDGES, GRAPH;
let edgeLabelsOn = false;
let CONCEPTS = null;          // fetched on first toggle
let conceptsOn = false;
const cid = name => 'concept::' + name;   // concept node id namespace

const esc = s => (s??'').toString().replace(/[&<>"]/g,
  c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const conf = c => c==null ? '—' :
  `<span class="${c>=0.7?'conf-hi':'conf-lo'}">${(+c).toFixed(2)}</span>`;
const srcPill = s => {
  const cls = s==='declared'?'declared':(s==='stat'||s==='llm+stat')?'stat'
            :(s==='llm')?'llm':'name';
  const label = {declared:'선언됨',stat:'통계 검증',
                 'llm+stat':'LLM 제안+값 검증',llm:'LLM 제안',name:'이름 추정'}[s]||s;
  return `<span class="pill ${cls}">${label}</span>`;
};

async function api(path){
  const r = await fetch(path);
  if(!r.ok) throw new Error(await r.text());
  return r.json();
}

function nodeSize(rc){ return rc>0 ? Math.min(14+6*Math.log10(rc+1), 52) : 12; }
const edgeLabel = via => via.split('=')[0].trim().split('.').pop();

async function load(){
  GRAPH = await api(`/api/runs/${RID}/graph`);
  const pill = document.getElementById('srcpill');
  if (GRAPH.source === 'neptune'){
    pill.textContent = `AWS Neptune Analytics · ${GRAPH.graph_id} · openCypher`;
    pill.className = 'src-pill neptune';
  } else {
    pill.textContent = '로컬 카탈로그 (Neptune 미설정)';
  }
  NODES = new vis.DataSet(GRAPH.tables.map(t=>({
    id: t.name, label: t.name,
    value: nodeSize(t.rowcount),
    shape: 'dot',
    color: t.rowcount>0
      ? {background:'#c7d2fe',border:'#6366f1',
         highlight:{background:'#a5b4fc',border:'#4f46e5'},
         hover:{background:'#b9c4fd',border:'#4f46e5'}}
      : {background:'#e6e8ec',border:'#c8ccd4',
         highlight:{background:'#dcdfe5',border:'#9aa4b2'},
         hover:{background:'#dfe2e8',border:'#9aa4b2'}},
    font:{size:13, color:'#1f2328'},
    title: `${t.name} — ${(t.rowcount||0).toLocaleString()} rows`,
  })));
  EDGES = new vis.DataSet(GRAPH.joins.map((j,i)=>({
    id: 'e'+i, from: j.from, to: j.to,
    arrows: {to:{enabled:true,scaleFactor:.5}},
    dashes: !(j.source==='declared'||j.source==='stat'||j.source==='llm+stat'),
    color: {color:'#c3c9d4', highlight:'#4f46e5', hover:'#818cf8'},
    width: 1.4, hoverWidth: 1.2, selectionWidth: 1.6,
    font: {size:10, color:'#6b7280', strokeWidth:4, strokeColor:'#f5f6f8',
           align:'middle'},
    title: `${j.via}\n출처: ${j.source} · 신뢰도: ${j.confidence??'—'}`,
  })));
  NET = new vis.Network(document.getElementById('net'),
    {nodes:NODES, edges:EDGES},
    {physics:{solver:'forceAtlas2Based',
      forceAtlas2Based:{gravitationalConstant:-90,springLength:140,
        avoidOverlap:.7},
      stabilization:{iterations:300, fit:true}},
     nodes:{scaling:{min:12,max:52}},
     edges:{smooth:{type:'continuous'}},
     interaction:{hover:true, tooltipDelay:100}});

  // ★ stop the perpetual motion: once stabilized, physics OFF for good.
  NET.once('stabilizationIterationsDone', ()=>{
    NET.setOptions({physics:false});
    NET.fit({animation:{duration:400}});
  });

  NET.on('click', p=>{
    if(p.nodes.length){
      const id = p.nodes[0];
      if(id.startsWith('concept::')) showConcept(id.slice(9));
      else showTable(id);
    }
    else if(p.edges.length && isJoinEdge(p.edges[0]))
      showRelation(p.edges[0]);
  });

  const names = GRAPH.tables.map(t=>t.name).sort();
  for (const id of ['fromT','toT']){
    document.getElementById(id).innerHTML =
      names.map(n=>`<option>${esc(n)}</option>`).join('');
  }
  document.getElementById('fromT').value =
    names.includes('drug_exposure') ? 'drug_exposure' : names[0];
  document.getElementById('toT').value =
    names.includes('provider') ? 'provider' : names[names.length-1];
}

// ---------------- side panel: table ----------------
async function showTable(name){
  const side = document.getElementById('side');
  const t = GRAPH.tables.find(x=>x.name===name);
  let detail = null;
  try { detail = await api(`/api/runs/${RID}/graph/table/${name}`); }
  catch(e){}
  side.innerHTML = `<h2><code>${esc(name)}</code></h2>
   <div class="desc">${esc((detail?.description ?? t.description) || '설명 없음')}</div>
   <dl class="kv">
    <dt>행 수</dt><dd>${(t.rowcount||0).toLocaleString()}</dd>
    <dt>컬럼</dt><dd>${t.n_columns??'—'}</dd>
    ${t.pk?`<dt>PK</dt><dd><code>${esc(t.pk)}</code></dd>`:''}
   </dl>
   ${detail?.fks?.length ? `<h3>이 테이블의 FK (${detail.fks.length})</h3>${detail.fks.map(f=>
     `<div class="small" style="margin:4px 0"><code>${esc(f.via)}</code> ${srcPill(f.source)}</div>`).join('')}`:''}
   ${detail?.columns ? `<h3>컬럼</h3>
    <table><thead><tr><th>이름</th><th>타입</th><th>설명</th></tr></thead><tbody>
    ${detail.columns.map(c=>`<tr><td>${c.is_pk?'🔑 ':''}${esc(c.name)}</td>
      <td>${esc(c.type)}</td><td>${esc(c.description)}</td></tr>`).join('')}
    </tbody></table>`:''}`;
}

// ---------------- side panel: relation (edge) ----------------
function showRelation(edgeId){
  const j = GRAPH.joins[parseInt(edgeId.slice(1))];
  if(!j) return;
  const side = document.getElementById('side');
  const [lhs, rhs] = j.via.split('=').map(s=>s.trim());
  const [ct, cc] = lhs.split('.'), [pt, pc] = rhs.split('.');
  side.innerHTML = `<h2>관계 (FK)</h2>
   <div class="relcard">
    <div class="cols">
     <div class="colbox"><b>${esc(ct)}</b><span>.${esc(cc)} (자식)</span></div>
     <span class="dirarrow">→</span>
     <div class="colbox"><b>${esc(pt)}</b><span>.${esc(pc)} (부모)</span></div>
    </div>
    <div class="join">JOIN ON ${esc(j.via)}</div>
    <dl class="kv">
     <dt>복원 출처</dt><dd>${srcPill(j.source)}</dd>
     <dt>신뢰도</dt><dd>${conf(j.confidence)}</dd>
    </dl>
    <p class="small">출처 의미 — <b>선언됨</b>: DB 카탈로그에 있던 제약 ·
    <b>통계 검증</b>: 값 포함관계로 확인 · <b>LLM 제안+값 검증</b>: LLM이 제안하고
    데이터로 검증 · <b>이름 추정</b>: 컬럼명 규칙(데이터 미검증, 저신뢰)</p>
   </div>
   <h3>이 관계로 조인하기</h3>
   <div class="sqlbox">SELECT *
FROM ${esc(ct)}
JOIN ${esc(pt)} ON ${esc(j.via)};</div>
   <p class="small">두 테이블을 양쪽 노드 클릭으로 살펴보거나, 상단에서
   다른 테이블까지의 전체 경로를 탐색해 보세요.</p>`;
}

// ---------------- join-path search ----------------
function pathSQL(path){
  const tables = path.filter(p=>p.table).map(p=>p.table);
  const joins = path.filter(p=>p.via).map(p=>p.via);
  let sql = 'SELECT *\nFROM ' + tables[0];
  for (let i=0;i<joins.length;i++)
    sql += `\nJOIN ${tables[i+1]} ON ${joins[i]}`;
  return sql + ';';
}

const isJoinEdge = id => /^e\d+$/.test(String(id));

function highlight(path){
  const names = new Set(path.filter(p=>p.table).map(p=>p.table));
  const vias = new Set(path.filter(p=>p.via).map(p=>p.via));
  NODES.forEach(n=>{
    const isConcept = String(n.id).startsWith('concept::');
    NODES.update({id:n.id,
      opacity: names.has(n.id)?1:(isConcept?.3:.15),
      font:{size:isConcept?12:13,
            color: names.has(n.id)?'#1f2328':(isConcept?'#d8c39a':'#c0c5cd')}});
  });
  EDGES.forEach(e=>{
    if(!isJoinEdge(e.id)) return;   // leave concept edges alone
    const hit = GRAPH.joins[parseInt(e.id.slice(1))];
    const on = hit && vias.has(hit.via);
    EDGES.update({id:e.id, width: on?3.5:0.6,
      label: (on||edgeLabelsOn) && hit ? edgeLabel(hit.via) : undefined,
      color:{color: on?'#4f46e5':'#e8eaef'}});
  });
}

function resetView(){
  NODES.forEach(n=>{
    const isConcept = String(n.id).startsWith('concept::');
    NODES.update({id:n.id, opacity:1,
      font:{size:isConcept?12:13, color:isConcept?'#92400e':'#1f2328'}});
  });
  EDGES.forEach(e=>{
    if(!isJoinEdge(e.id)) return;
    const hit = GRAPH.joins[parseInt(e.id.slice(1))];
    EDGES.update({id:e.id, width:1.4,
      label: edgeLabelsOn && hit ? edgeLabel(hit.via) : undefined,
      color:{color:'#c3c9d4'}});
  });
  document.getElementById('qhint').textContent = '';
}

document.getElementById('findbtn').onclick = async ()=>{
  const a = document.getElementById('fromT').value;
  const b = document.getElementById('toT').value;
  const side = document.getElementById('side');
  side.innerHTML = '<p class="small">경로 탐색 중…</p>';
  const t0 = performance.now();
  const res = await api(`/api/runs/${RID}/graph/paths?frm=${a}&to=${b}`);
  const ms = (performance.now()-t0).toFixed(0);
  document.getElementById('qhint').textContent =
    `${res.source==='neptune'?'Neptune openCypher':'로컬 BFS'} · ${ms}ms`;
  if(!res.paths.length){
    side.innerHTML = `<h2>${esc(a)} → ${esc(b)}</h2>
     <p class="small">FK 그래프상 연결 경로가 없습니다.</p>`;
    return;
  }
  side.innerHTML = `<h2>${esc(a)} → ${esc(b)}</h2>
   <h3>조인 경로 ${res.paths.length}개 (짧은 순)</h3>` +
   res.paths.map((p,i)=>`<div class="pathbox" data-i="${i}">
     <b>#${i+1}</b> ${p.filter(x=>x.table).map(x=>esc(x.table)).join(' → ')}
     <span class="hop">${(p.length-1)/2} hop</span>
     <div class="joins">${p.filter(x=>x.via).map(x=>esc(x.via)).join('<br>')}</div>
    </div>`).join('') +
   `<h3>JOIN SQL (선택 경로)</h3><div class="sqlbox" id="sqlbox">${esc(pathSQL(res.paths[0]))}</div>
    <p class="small">text2sql 플래너가 이 경로/SQL 스켈레톤을 컨텍스트로 받습니다.</p>`;
  highlight(res.paths[0]);
  side.querySelectorAll('.pathbox').forEach(el=>el.onclick=()=>{
    side.querySelectorAll('.pathbox').forEach(x=>x.classList.remove('sel'));
    el.classList.add('sel');
    const p = res.paths[+el.dataset.i];
    document.getElementById('sqlbox').textContent = pathSQL(p);
    highlight(p);
  });
  side.querySelector('.pathbox')?.classList.add('sel');
};
document.getElementById('resetbtn').onclick = resetView;
document.getElementById('fitbtn').onclick =
  ()=>NET&&NET.fit({animation:{duration:400}});
document.getElementById('edgelbl').onchange = e=>{
  edgeLabelsOn = e.target.checked;
  EDGES.forEach(ed=>{
    if(String(ed.id).startsWith('c')) return;
    const hit = GRAPH.joins[parseInt(ed.id.slice(1))];
    EDGES.update({id:ed.id,
      label: edgeLabelsOn && hit ? edgeLabel(hit.via) : undefined});
  });
};

// ---------------- concept (ontology) layer ----------------
async function ensureConcepts(){
  if (CONCEPTS) return CONCEPTS;
  CONCEPTS = await api(`/api/runs/${RID}/graph/concepts`);
  return CONCEPTS;
}

function addConceptLayer(){
  const C = CONCEPTS;
  // concept nodes: amber diamonds, label = 한국어(영문)
  NODES.add(C.concepts.map(c=>({
    id: cid(c.name),
    label: c.name_ko ? `${c.name_ko}` : c.name,
    shape: 'diamond', size: 14,
    color: {background:'#fde68a', border:'#f59e0b',
            highlight:{background:'#fcd34d', border:'#d97706'},
            hover:{background:'#fde68a', border:'#d97706'}},
    font: {size:12, color:'#92400e'},
    title: `${c.name} — ${c.description||''}`,
  })));
  const eds = [];
  C.is_a.forEach((r,i)=>eds.push({
    id: 'cisa'+i, from: cid(r.child), to: cid(r.parent),
    arrows: {to:{enabled:true,scaleFactor:.5}},
    color: {color:'#f59e0b', highlight:'#d97706'},
    width: 1.6, label: 'IS_A',
    font: {size:9, color:'#b45309', strokeWidth:4, strokeColor:'#f5f6f8'},
  }));
  C.mappings.forEach((m,i)=>eds.push({
    id: 'cmap'+i, from: cid(m.concept), to: m.table,
    dashes: [2,4], color: {color:'#fbbf24', highlight:'#d97706'},
    width: 1, arrows: {to:{enabled:true,scaleFactor:.4}},
    title: `${m.concept} → ${m.table} (MAPPED_TO, conf ${m.confidence??'—'})`,
  }));
  EDGES.add(eds);
  // brief physics re-run to place the new nodes, then freeze again
  NET.setOptions({physics:{enabled:true,
    forceAtlas2Based:{gravitationalConstant:-90,springLength:140,avoidOverlap:.7},
    solver:'forceAtlas2Based', stabilization:{enabled:false}}});
  setTimeout(()=>{ NET.setOptions({physics:false}); }, 2500);
}

function removeConceptLayer(){
  NODES.remove(NODES.getIds().filter(id=>String(id).startsWith('concept::')));
  EDGES.remove(EDGES.getIds().filter(id=>String(id).startsWith('c')));
}

document.getElementById('conceptlayer').onchange = async e=>{
  conceptsOn = e.target.checked;
  const search = document.getElementById('csearch');
  const lg = document.getElementById('lg-concept');
  if (conceptsOn){
    await ensureConcepts();
    if (!CONCEPTS.concepts.length){
      document.getElementById('qhint').textContent =
        '개념 레이어 없음 — concepts.py를 먼저 실행하세요';
      e.target.checked = false; conceptsOn = false; return;
    }
    addConceptLayer();
    search.style.display = ''; lg.style.display = '';
    document.getElementById('qhint').textContent =
      `개념 ${CONCEPTS.concepts.length}개 (${CONCEPTS.source})`;
  } else {
    removeConceptLayer();
    search.style.display = 'none'; lg.style.display = 'none';
    document.getElementById('qhint').textContent = '';
  }
};

// concept search: matches name / 한국어 / synonyms, focuses + opens panel
document.getElementById('csearch').addEventListener('keydown', async e=>{
  if (e.key !== 'Enter') return;
  const q = e.target.value.trim().toLowerCase();
  if (!q) return;
  await ensureConcepts();
  const hit = CONCEPTS.concepts.find(c=>
    c.name.toLowerCase().includes(q) ||
    (c.name_ko||'').toLowerCase().includes(q) ||
    (c.synonyms||'').toLowerCase().includes(q));
  if (!hit){
    document.getElementById('qhint').textContent = `'${q}' 매칭 개념 없음`;
    return;
  }
  if (!conceptsOn){
    document.getElementById('conceptlayer').checked = true;
    document.getElementById('conceptlayer').dispatchEvent(new Event('change'));
    await new Promise(r=>setTimeout(r, 300));
  }
  NET.focus(cid(hit.name), {scale:1.0, animation:{duration:500}});
  NET.selectNodes([cid(hit.name)]);
  showConcept(hit.name);
});

function showConcept(name){
  const c = CONCEPTS.concepts.find(x=>x.name===name);
  if (!c) return;
  const maps = CONCEPTS.mappings.filter(m=>m.concept===name);
  const parents = CONCEPTS.is_a.filter(r=>r.child===name).map(r=>r.parent);
  const children = CONCEPTS.is_a.filter(r=>r.parent===name).map(r=>r.child);
  const side = document.getElementById('side');
  side.innerHTML = `<h2>◆ ${esc(c.name_ko||c.name)}
    <span class="small" style="font-weight:400">${esc(c.name)}</span></h2>
   <div class="desc" style="border-color:#fcd34d;background:#fffbeb">
     ${esc(c.description||'')}</div>
   <dl class="kv">
    <dt>동의어</dt><dd>${esc(c.synonyms||'—')}</dd>
    ${parents.length?`<dt>상위 개념</dt><dd>${parents.map(p=>
      `<span class="pill">${esc(p)}</span>`).join(' ')}</dd>`:''}
    ${children.length?`<dt>하위 개념</dt><dd>${children.map(p=>
      `<span class="pill">${esc(p)}</span>`).join(' ')}</dd>`:''}
    <dt>신뢰도</dt><dd>${conf(c.confidence)}</dd>
   </dl>
   <h3>매핑된 테이블 (${maps.length})</h3>
   ${maps.map(m=>`<div class="small" style="margin:4px 0">
     <code class="clickable" data-tbl="${esc(m.table)}"
       style="cursor:pointer;color:var(--accent)">${esc(m.table)}</code></div>`).join('')
     || '<p class="small">매핑된 테이블 없음 (추상 개념)</p>'}
   ${c.key_columns?.length?`<h3>핵심 컬럼</h3>
    ${c.key_columns.map(k=>`<div class="small" style="margin:3px 0">
      <code>${esc(k)}</code></div>`).join('')}`:''}
   <p class="small" style="margin-top:14px">자연어 질문의 용어("${esc((c.synonyms||'').split(',')[0]||c.name_ko)}")가
   이 개념에 매칭되고, 매핑된 테이블에서 조인 경로를 펼치는 것이 text2sql 스키마 링킹입니다.</p>`;
  side.querySelectorAll('[data-tbl]').forEach(el=>el.onclick=()=>{
    NET.focus(el.dataset.tbl, {scale:1.1, animation:{duration:400}});
    NET.selectNodes([el.dataset.tbl]);
    showTable(el.dataset.tbl);
  });
}

// ---------------- resizable side panel ----------------
(function(){
  const side = document.getElementById('side');
  const rez = document.getElementById('resizer');
  const saved = localStorage.getItem('db2doc-graph-panel-w');
  if (saved) side.style.width = saved + 'px';
  let dragging = false;
  rez.addEventListener('mousedown', e=>{
    dragging = true; rez.classList.add('active');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
  });
  window.addEventListener('mousemove', e=>{
    if(!dragging) return;
    const w = Math.min(720, Math.max(320, window.innerWidth - e.clientX));
    side.style.width = w + 'px';
  });
  window.addEventListener('mouseup', ()=>{
    if(!dragging) return;
    dragging = false; rez.classList.remove('active');
    document.body.style.cursor = ''; document.body.style.userSelect = '';
    localStorage.setItem('db2doc-graph-panel-w', parseInt(side.style.width));
    NET && NET.redraw();
  });
})();

load();
</script></body></html>
"""


def render_graph_page(run_id):
    return (GRAPH_PAGE
            .replace("__RID__", run_id)
            .replace("__BACK__", f"/runs/{run_id}"))
