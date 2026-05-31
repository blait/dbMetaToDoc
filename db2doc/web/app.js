// db2doc dynamic SPA — talks to /api, no build step.
"use strict";

// ---------------------------------------------------------------- api client
const API = {
  async get(p){ const r=await fetch(p); if(!r.ok) throw new Error(await r.text()); return r.json(); },
  async post(p,b){ const r=await fetch(p,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})}); if(!r.ok) throw new Error(await r.text()); return r.json(); },
  async patch(p,b){ const r=await fetch(p,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})}); if(!r.ok) throw new Error(await r.text()); return r.json(); },
  async del(p){ const r=await fetch(p,{method:'DELETE'}); if(!r.ok) throw new Error(await r.text()); return r.json(); },
};

// ---------------------------------------------------------------- state
let sources = [];
let currentSourceId = null;
let DATA = {source:{}, tables:[], score:{}};
let T = [];
let route = {page:'sources', table:null};

const fmtPct = x => x==null?'—':(x*100).toFixed(0)+'%';
const num = n => (n||0).toLocaleString();
const esc = s => (s==null?'':String(s)).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
function confClass(c){ return c>=0.9?'hi':c>=0.75?'md':'lo'; }
function confDot(c){ const col=c>=0.9?'var(--acc2)':c>=0.75?'var(--warn)':'var(--bad)'; return `<span class="dot" style="background:${col}"></span>`; }
function toast(msg){ const t=document.getElementById('toast'); t.textContent=msg; t.classList.add('show'); setTimeout(()=>t.classList.remove('show'),2200); }

function go(page, table){ route={page, table:table||null}; render(); window.scrollTo(0,0); }

// ---------------------------------------------------------------- boot
async function boot(){
  try { sources = await API.get('/api/sources'); } catch(e){ sources=[]; }
  if(sources.length && currentSourceId==null) currentSourceId = sources[0].id;
  if(currentSourceId!=null){ await loadCatalog(currentSourceId); }
  render();
}
async function loadCatalog(id){
  currentSourceId = id;
  DATA = await API.get(`/api/sources/${id}/catalog`);
  T = DATA.tables || [];
}
async function switchSource(id){ await loadCatalog(Number(id)); route={page:'catalog',table:null}; render(); }

// ---------------------------------------------------------------- chrome
function nav(){
  const has = currentSourceId!=null;
  const pend = has ? T.reduce((a,t)=>a+t.columns.filter(c=>c.status!=='approved'&&c.status!=='rejected'&&(c.confidence==null||c.confidence<0.9)).length,0) : 0;
  const items=[['sources','Sources'],['catalog','Catalog'],['review','Review Queue'],['export','Export']];
  document.getElementById('nav').innerHTML = items.map(([k,l])=>{
    const b = k==='review'&&pend?`<span class="badge">${pend}</span>`:'';
    return `<button class="${route.page===k?'on':''}" onclick="go('${k}')">${l}${b}</button>`;
  }).join('');
  const sel = document.getElementById('srcsel');
  if(sources.length){
    sel.innerHTML = `<span class="small">소스</span><select onchange="switchSource(this.value)">`+
      sources.map(s=>`<option value="${s.id}" ${s.id===currentSourceId?'selected':''}>${esc(s.name)} (${s.dialect})</option>`).join('')+`</select>`;
  } else sel.innerHTML='';
}

// ---------------------------------------------------------------- Sources page (+ add form, scan/infer)
function pageSources(){
  const totalCols=T.reduce((a,t)=>a+t.columns.length,0);
  const docd=T.reduce((a,t)=>a+t.columns.filter(c=>c.description).length,0);
  const withData=T.filter(t=>t.rowcount>0).length;
  const s=DATA.source||{};
  const srcRows = sources.map(x=>`<tr class="clk" onclick="switchSource(${x.id})">
      <td>${x.id===currentSourceId?'⬤ ':''}<span class="mono">${esc(x.name)}</span></td>
      <td>${x.dialect}</td><td class="mono small">${esc(x.host)}/${esc(x.database_name)}.${esc(x.db_schema)}</td>
      <td>${x.last_scan_id?'<span class="pill ok">scanned</span>':'<span class="pill">new</span>'}</td>
      <td><button class="btn" onclick="event.stopPropagation();testConn(${x.id})">test</button>
          <button class="btn pri" onclick="event.stopPropagation();runFull(${x.id})">Scan+Infer</button></td>
    </tr>`).join('');
  const cur = currentSourceId!=null ? `
    <div class="row">
      <div class="kpi"><div class="n">${T.length}</div><div class="l">테이블</div></div>
      <div class="kpi"><div class="n good">${totalCols?fmtPct(docd/totalCols):'—'}</div><div class="l">문서화율</div></div>
      <div class="kpi"><div class="n">${withData}</div><div class="l">데이터 있는 테이블</div></div>
    </div>
    ${s.db_description?`<div class="note">🔎 <b>AI가 추론한 DB 설명:</b> ${esc(s.db_description)}</div>`:'<div class="note">아직 스캔/추론 전입니다. 위 목록에서 <b>Scan+Infer</b>를 누르세요.</div>'}` : '';
  return `
  <h1>Data Sources</h1>
  <p class="sub">내 DB를 등록·연결하고, 스캔(프로파일+관계복원) → 추론(설명 생성)을 돌립니다.</p>
  <div id="jobbox"></div>
  <div class="card">
    <table><thead><tr><th>이름</th><th>dialect</th><th>연결</th><th>상태</th><th>액션</th></tr></thead>
    <tbody>${srcRows||'<tr><td colspan=5 class="small">등록된 소스가 없습니다. 아래에서 추가하세요.</td></tr>'}</tbody></table>
  </div>
  ${cur}
  <div class="card">
    <b>+ 소스 추가</b>
    <div class="frm" style="margin-top:10px">
      <label>이름<input id="f_name" placeholder="omop-pg"></label>
      <label>dialect<select id="f_dialect"><option>postgresql</option><option>mysql</option><option>mariadb</option></select></label>
      <label>host<input id="f_host"></label>
      <label>port<input id="f_port" placeholder="5432"></label>
      <label>database<input id="f_db"></label>
      <label>schema<input id="f_schema" placeholder="cdm (PG) / db명 (MySQL)"></label>
      <label>user<input id="f_user"></label>
      <label>password<input id="f_pw" type="password"></label>
    </div>
    <button class="btn pri" onclick="addSource()">등록</button>
    <span class="small">· 등록 후 'test'로 연결 확인 → 'Scan+Infer'</span>
  </div>`;
}

async function addSource(){
  const g=id=>document.getElementById(id).value.trim();
  const body={name:g('f_name'),dialect:g('f_dialect'),host:g('f_host'),
    port:g('f_port')?Number(g('f_port')):null,database_name:g('f_db'),
    db_schema:g('f_schema'),username:g('f_user'),password:document.getElementById('f_pw').value};
  if(!body.name||!body.host){ toast('이름/host는 필수'); return; }
  try{ const src=await API.post('/api/sources',body); toast('소스 등록됨 #'+src.id);
    sources=await API.get('/api/sources'); currentSourceId=src.id; render();
  }catch(e){ toast('등록 실패: '+e.message.slice(0,80)); }
}
async function testConn(id){
  toast('연결 테스트 중…');
  try{ const r=await API.post(`/api/sources/${id}/test-connection`); toast(r.ok?'연결 성공 ✓':'실패: '+r.message.slice(0,80)); }
  catch(e){ toast('실패: '+e.message.slice(0,80)); }
}
async function runFull(id){
  try{ const r=await API.post(`/api/sources/${id}/run`); toast('스캔 시작 (job '+r.job_id+')'); pollJob(r.job_id, id); }
  catch(e){ toast('실패: '+e.message.slice(0,100)); }
}
async function pollJob(jobId, sourceId){
  const box=document.getElementById('jobbox');
  const tick=async()=>{
    let j; try{ j=await API.get('/api/jobs/'+jobId); }catch(e){ return; }
    if(box) box.innerHTML=`<div class="card"><b>작업 진행</b> — ${j.kind} · ${j.state} · ${j.phase||''} ${j.message?'('+esc(j.message)+')':''}
      <div class="bar" style="margin-top:8px"><i style="width:${Math.round((j.progress||0)*100)}%"></i></div></div>`;
    if(j.state==='succeeded'){ toast('완료 ✓'); sources=await API.get('/api/sources'); await loadCatalog(sourceId); render(); return; }
    if(j.state==='failed'){ toast('작업 실패'); if(box) box.innerHTML+=`<div class="note" style="border-color:var(--bad)">${esc((j.error||'').slice(0,300))}</div>`; return; }
    setTimeout(tick, 1500);
  };
  tick();
}

// ---------------------------------------------------------------- evidence + review
function evidenceHTML(c){
  const e=c.evidence||{};
  const tv=(e.top_values||[]).map(v=>`<span class="tag mono">${esc(v.value)} <span class="small">(${v.count})</span></span>`).join(' ');
  const ex=(e.examples||[]).map(v=>`<span class="tag mono">${esc(v)}</span>`).join(' ');
  return `<div class="ev"><b>근거 (왜 이 설명인가)</b>
    <div class="kv"><span>type: <span class="mono">${esc(c.type)||'?'}</span></span>
      <span>distinct_ratio: <span class="mono">${e.distinct_ratio==null?'—':e.distinct_ratio}</span></span>
      <span>null: <span class="mono">${fmtPct(e.null_ratio)}</span></span>
      ${e.min!=null?`<span>range: <span class="mono">${esc(e.min)}…${esc(e.max)}</span></span>`:''}</div>
    ${tv?`<div style="margin-top:7px"><b>top-k 샘플값:</b><br>${tv}</div>`:(ex?`<div style="margin-top:7px"><b>샘플값:</b><br>${ex}</div>`:'')}
  </div>`;
}

function reviewItem(t,c){
  const decided = (c.status==='approved'||c.status==='rejected');
  const acts = decided
    ? `<span class="done">✓ ${c.status}</span>`
    : `<button class="btn ok" onclick="approveCol(${c.description_id})">✓ Approve</button>
       <button class="btn" onclick="reviewReject(${c.description_id})">✗ Reject</button>`;
  return `<div class="rev">
    <div class="h" onclick="this.parentNode.classList.toggle('open')">
      <span class="conf ${confClass(c.confidence)}">${confDot(c.confidence)} ${c.confidence!=null?c.confidence.toFixed(2):'—'}</span>
      <span class="name mono">${esc(t.name)}.${esc(c.name)}</span>
      <span class="small" style="margin-left:auto">${t.rowcount?num(t.rowcount)+' rows':'empty'}</span>
    </div>
    <div class="body">
      <textarea class="editarea" id="ed_${c.description_id}" rows="2" onblur="saveEdit(${c.description_id})">${esc(c.description)}</textarea>
      ${evidenceHTML(c)}
      <div class="acts">${acts}</div>
    </div></div>`;
}

function pageReview(){
  if(currentSourceId==null) return `<h1>Review Queue</h1><p class="sub">먼저 소스를 선택/스캔하세요.</p>`;
  const items=[]; T.forEach(t=>t.columns.forEach(c=>{ if(c.description_id) items.push([t,c]); }));
  const pending = items.filter(([t,c])=>c.status!=='approved'&&c.status!=='rejected'&&(c.confidence==null||c.confidence<0.9));
  const auto = items.filter(([t,c])=>c.confidence!=null&&c.confidence>=0.9);
  const done = items.filter(([t,c])=>c.status==='approved'||c.status==='rejected');
  pending.sort((a,b)=>(a[1].confidence||0)-(b[1].confidence||0));
  return `<h1>Review Queue</h1>
  <p class="sub">신뢰도 낮은 항목만 검수합니다. 수정은 텍스트 박스에서 바로(blur 시 저장). 0.9↑은 일괄 승인.</p>
  <div class="row" style="margin-bottom:14px">
    <div class="kpi"><div class="n warn">${pending.length}</div><div class="l">검수 필요</div></div>
    <div class="kpi"><div class="n good">${auto.length}</div><div class="l">자동 승인 후보 (≥0.9)</div></div>
    <div class="kpi"><div class="n">${done.length}</div><div class="l">검수 완료</div></div>
  </div>
  <div class="card">
    <div class="filt"><b style="color:var(--warn)">⚠ 검수 필요 (낮은 신뢰도 먼저)</b>
      <button class="btn ok" style="margin-left:auto" onclick="bulkApprove()">≥0.9 일괄 승인 (${auto.length})</button></div>
    ${pending.length? pending.map(([t,c])=>reviewItem(t,c)).join('') : '<p class="small">검수 대기 항목 없음 🎉</p>'}
  </div>`;
}

async function saveEdit(descId){
  const el=document.getElementById('ed_'+descId); if(!el) return;
  try{ await API.patch('/api/descriptions/'+descId,{current_text:el.value, actor:'ui'}); toast('수정 저장됨'); patchLocal(descId,{description:el.value,status:'edited'}); }
  catch(e){ toast('저장 실패'); }
}
async function approveCol(descId){ try{ await API.post(`/api/descriptions/${descId}/approve`,{actor:'ui'}); patchLocal(descId,{status:'approved'}); render(); toast('승인'); }catch(e){ toast('실패'); } }
async function reviewReject(descId){ try{ await API.post(`/api/descriptions/${descId}/reject`,{actor:'ui'}); patchLocal(descId,{status:'rejected'}); render(); toast('반려'); }catch(e){ toast('실패'); } }
async function bulkApprove(){
  const ids=[]; T.forEach(t=>t.columns.forEach(c=>{ if(c.confidence!=null&&c.confidence>=0.9&&c.status!=='approved'&&c.description_id) ids.push(c.description_id); }));
  toast(ids.length+'건 승인 중…');
  for(const id of ids){ try{ await API.post(`/api/descriptions/${id}/approve`,{actor:'ui'}); patchLocal(id,{status:'approved'}); }catch(e){} }
  render(); toast('일괄 승인 완료');
}
function patchLocal(descId, fields){ T.forEach(t=>t.columns.forEach(c=>{ if(c.description_id===descId) Object.assign(c,fields); })); }

// ---------------------------------------------------------------- Catalog + detail
function pageCatalog(){
  if(currentSourceId==null) return `<h1>Catalog</h1><p class="sub">먼저 소스를 등록/선택하세요 (Sources 탭).</p>`;
  if(route.table) return tableDetail(route.table);
  if(!T.length) return `<h1>Catalog</h1><p class="sub">스캔/추론 결과가 없습니다. Sources에서 Scan+Infer를 실행하세요.</p>`;
  const q=(document.getElementById('q')?.value||'').toLowerCase();
  const rows=T.filter(t=>!q||t.name.toLowerCase().includes(q)||(t.table_description||'').toLowerCase().includes(q)).map(t=>{
    const avg=t.columns.reduce((a,c)=>a+(c.confidence||0),0)/(t.columns.length||1);
    return `<tr class="clk" onclick="go('catalog','${esc(t.name)}')">
      <td><span class="mono">${esc(t.name)}</span> ${t.pk?`<span class="pill pk">PK ${esc(t.pk)}</span>`:''}</td>
      <td class="small">${esc(t.table_description)}</td><td>${num(t.rowcount)}</td>
      <td><div class="bar"><i style="width:${(avg*100).toFixed(0)}%"></i></div></td></tr>`;}).join('');
  return `<h1>Catalog</h1><p class="sub">복원된 데이터 딕셔너리. 클릭하면 테이블 상세 + 인라인 수정.</p>
    <div class="filt"><input id="q" placeholder="테이블/설명 검색…" oninput="render()" value="${esc(q)}"></div>
    <div class="card"><table><thead><tr><th>Table</th><th>설명 (AI/편집)</th><th>Rows</th><th>평균 신뢰도</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}

function tableDetail(name){
  const t=T.find(x=>x.name===name); if(!t) return 'not found';
  const fkrows=(t.fks||[]).map(f=>`<span class="pill fk">FK ${esc(f.col)} → ${esc(f.ref_table)}.${esc(f.ref_col)}${f.inclusion!=null?` <span class="small">(incl ${f.inclusion})</span>`:''}</span>`).join(' ');
  const cols=t.columns.map(c=>`<tr>
     <td><span class="mono">${esc(c.name)}</span><div class="small">${esc(c.type)||''}${c.nullable?' · null':''}</div></td>
     <td><textarea class="editarea" rows="2" id="cd_${c.description_id}" onblur="saveEdit(${c.description_id})">${esc(c.description)}</textarea>
         ${c.status?`<span class="pill ${c.status==='approved'?'ok':(c.status==='rejected'?'bad':'')}">${c.status}</span>`:''}</td>
     <td><span class="conf ${confClass(c.confidence)}">${confDot(c.confidence)} ${c.confidence!=null?c.confidence.toFixed(2):'—'}</span></td>
   </tr>`).join('');
  return `<span class="backlink" onclick="go('catalog')">← Catalog</span>
   <h1 class="mono">${esc(t.name)}</h1><p class="sub">${esc(t.table_description)}</p>
   <div class="card"><div style="margin-bottom:8px">${t.pk?`<span class="pill pk">PK ${esc(t.pk)}</span> `:''}${fkrows}
     <span class="small" style="float:right">${num(t.rowcount)} rows · ${t.columns.length} columns</span></div>
   <table><thead><tr><th>Column</th><th>설명 (편집 가능 · blur 저장)</th><th>신뢰도</th></tr></thead><tbody>${cols}</tbody></table></div>
   <div class="note">💡 설명은 인라인 편집됩니다. Export 탭에서 COMMENT SQL/MD로 내려받아 실제 DB에 반영하세요.</div>`;
}

// ---------------------------------------------------------------- Export
function pageExport(){
  if(currentSourceId==null) return `<h1>Export</h1><p class="sub">소스를 선택하세요.</p>`;
  const base=`/api/sources/${currentSourceId}/export`;
  return `<h1>Export</h1><p class="sub">현재(편집 반영된) 설명을 내려받습니다.</p>
  <div class="card">
    <p><a class="btn" href="${base}?format=sql" target="_blank">COMMENT SQL</a>
       <a class="btn" href="${base}?format=md" target="_blank">Markdown 데이터딕셔너리</a>
       <a class="btn" href="${base}?format=csv" target="_blank">CSV</a>
       <a class="btn" href="${base}?format=mermaid" target="_blank">Mermaid ERD</a></p>
    <div class="note">COMMENT SQL을 검토 후 실제 DB에 실행하면 문서가 DB 자체에 반영됩니다 (PG=COMMENT ON, MySQL=ALTER TABLE COMMENT).</div>
  </div>`;
}

// ---------------------------------------------------------------- render
function render(){
  nav();
  const v=document.getElementById('view');
  v.innerHTML = route.page==='sources'?pageSources()
    : route.page==='catalog'?pageCatalog()
    : route.page==='review'?pageReview()
    : route.page==='export'?pageExport()
    : pageSources();
}

// expose handlers used in inline onclick
Object.assign(window,{go,switchSource,addSource,testConn,runFull,saveEdit,approveCol,reviewReject,bulkApprove,render});
boot();
