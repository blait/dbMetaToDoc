"""text2sql test page (served at /runs/{rid}/text2sql).

Shows the LangGraph pipeline step by step so the user can see HOW our
ontology / graph-RAG / metadata drives SQL generation:
  retrieve (OpenSearch) → expand (Neptune joins) → generate → execute → repair
"""

T2SQL_PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>db2doc v2 — text2sql</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<style>
:root{--bg:#f5f6f8;--surface:#fff;--ink:#16181d;--muted:#6b7280;--line:#e5e7eb;
 --accent:#4f46e5;--accent-soft:#eef2ff;--ok:#16a34a;--warn:#d97706;--bad:#dc2626;
 --shadow:0 1px 2px rgba(16,24,40,.06)}
*{box-sizing:border-box}
body{font:14px/1.6 "Pretendard Variable",Pretendard,-apple-system,BlinkMacSystemFont,
 "Segoe UI","Apple SD Gothic Neo","Malgun Gothic",sans-serif;color:var(--ink);
 margin:0;height:100vh;display:flex;flex-direction:column;overflow:hidden;background:var(--bg)}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:#eef0f3;
 padding:1px 6px;border-radius:6px;font-size:88%}
header{background:#14171f;color:#e8eaef;display:flex;align-items:center;gap:12px;
 padding:0 22px;height:54px;flex:none}
header .brand{display:flex;align-items:center;gap:9px;font-weight:700;font-size:15px}
header .brand .logo{width:24px;height:24px;border-radius:7px;display:grid;
 place-items:center;background:linear-gradient(135deg,#6366f1,#a855f7);font-size:13px;color:#fff}
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
.askbar{padding:14px 22px;border-bottom:1px solid var(--line);background:var(--surface);
 flex:none;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.askbar input{flex:1;min-width:280px;padding:10px 14px;border:1px solid var(--line);
 border-radius:10px;font-size:14px;font-family:inherit;background:#fafbfc}
.askbar input:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px rgba(79,70,229,.12);background:#fff}
.askbar button{padding:10px 20px;border:1px solid var(--accent);background:var(--accent);
 color:#fff;border-radius:10px;font-size:14px;font-weight:600;font-family:inherit;cursor:pointer}
.askbar button:disabled{opacity:.5;cursor:default}
.examples{padding:8px 22px;border-bottom:1px solid var(--line);background:#fbfcfd;flex:none;
 display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.examples .lbl{font-size:11.5px;color:var(--muted);font-weight:600}
.examples .ex{font-size:12px;color:var(--accent);background:var(--accent-soft);
 border:1px solid #c7d2fe;border-radius:999px;padding:3px 11px;cursor:pointer}
.examples .ex:hover{background:#e0e7ff}
.layout{flex:1;display:flex;min-height:0}
.body{flex:1;overflow-y:auto;padding:20px 22px;min-width:0}
.wrap{max-width:1000px;margin:0 auto}
.placeholder{text-align:center;color:var(--muted);padding:60px 20px}
/* history panel */
.histpanel{width:300px;flex:none;border-left:1px solid var(--line);
 background:var(--surface);display:flex;flex-direction:column;min-height:0}
.histhead{display:flex;align-items:center;justify-content:space-between;
 padding:12px 16px;border-bottom:1px solid var(--line);font-size:13px}
.histhead button{font-size:11px;color:var(--muted);background:none;border:1px solid var(--line);
 border-radius:7px;padding:3px 9px;cursor:pointer;font-family:inherit}
.histhead button:hover{color:var(--bad);border-color:var(--bad)}
.histlist{overflow-y:auto;flex:1;padding:8px 10px 30px}
.histempty{color:var(--muted);font-size:12px;text-align:center;padding:30px 10px}
.histitem{border:1px solid var(--line);border-radius:10px;padding:9px 11px;
 margin-bottom:8px;cursor:pointer;transition:all .12s;background:#fff}
.histitem:hover{border-color:#c7cdd6;box-shadow:var(--shadow)}
.histitem .hq{font-size:12.5px;font-weight:600;line-height:1.4;margin-bottom:5px;
 display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.histitem .hmeta{display:flex;gap:8px;align-items:center;font-size:11px;color:var(--muted)}
.histitem .hstat{font-size:10px;border-radius:999px;padding:1px 7px;font-weight:700}
.histitem .hstat.ok{background:#dcfce7;color:#166534}
.histitem .hstat.bad{background:#fee2e2;color:#991b1b}
.placeholder .big{font-size:34px;margin-bottom:10px}
.step{background:var(--surface);border:1px solid var(--line);border-radius:14px;
 margin-bottom:14px;box-shadow:var(--shadow);overflow:hidden}
.step-head{display:flex;align-items:center;gap:10px;padding:12px 18px;
 border-bottom:1px solid var(--line);background:#fafbfc}
.step-num{width:24px;height:24px;border-radius:50%;display:grid;place-items:center;
 font-size:12px;font-weight:700;background:var(--accent);color:#fff;flex:none}
.step-head h3{margin:0;font-size:14px}
.step-head .sub{font-size:11.5px;color:var(--muted);margin-left:auto}
.step-head .tool{font-size:10.5px;border-radius:999px;padding:2px 9px;font-weight:600;
 background:#e0e7ff;color:var(--accent);border:1px solid #c7d2fe}
.step-head .tool.aws{background:#fff4e5;color:#b45309;border-color:#fcd9a8}
.step-body{padding:14px 18px}
.chips{display:flex;gap:6px;flex-wrap:wrap}
.chip{font-size:12px;border:1px solid var(--line);border-radius:8px;padding:3px 10px;
 background:#fafbfc}
.chip b{color:var(--accent)}
.chip.from-concept{background:#fffbeb;border-color:#fcd34d}
.chip.from-concept b{color:#b45309}
.concept-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;
 background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:8px 12px;
 margin-bottom:10px;font-size:12px}
.concept-row .clbl{font-weight:700;color:#92400e}
.concept-row .cchip{background:#fde68a;color:#92400e;border-radius:999px;
 padding:1px 9px;font-weight:600}
.concept-row .cnote{color:var(--muted);margin-left:4px}
/* retrieve 하위 단계 */
.substage{border:1px solid var(--line);border-radius:10px;margin-bottom:10px;
 overflow:hidden;background:#fff}
.substage.concept{border-color:#fde68a}
.substage.merge{border-color:#c7d2fe}
.ss-head{display:flex;align-items:center;gap:7px;padding:7px 12px;font-size:12.5px;
 font-weight:700;background:#fafbfc;border-bottom:1px solid var(--line)}
.substage.concept .ss-head{background:#fffbeb;color:#92400e}
.substage.merge .ss-head{background:#f5f7ff;color:var(--accent)}
.ss-num{width:20px;height:20px;border-radius:50%;display:grid;place-items:center;
 font-size:11px;background:#e5e7eb;color:#374151;flex:none}
.substage.concept .ss-num{background:#fde68a;color:#92400e}
.substage.merge .ss-num{background:#c7d2fe;color:var(--accent)}
.ss-eng{margin-left:auto;font-size:10.5px;font-weight:600;color:var(--muted);
 background:#eef0f3;border-radius:999px;padding:1px 9px}
.ss-body{padding:9px 12px;font-size:12px}
.metric{display:inline-block;margin-right:10px;color:var(--muted)}
.metric b{color:var(--ink);font-size:14px}
.hits-box{margin-top:7px;border-top:1px dashed var(--line);padding-top:5px}
.cchip{display:inline-block;background:#fde68a;color:#92400e;border-radius:999px;
 padding:1px 9px;font-weight:600;margin-right:5px}
.cnote{color:var(--muted);font-size:11.5px}
.hit{display:flex;gap:10px;align-items:baseline;font-size:12.5px;padding:4px 0;
 border-bottom:1px dashed var(--line)}
.hit:last-child{border-bottom:none}
.hit .score{font-variant-numeric:tabular-nums;color:var(--muted);font-size:11px;width:42px;flex:none}
.hit .kind{font-size:10px;border-radius:5px;padding:0 6px;font-weight:700;flex:none}
.hit .kind.table{background:#dbeafe;color:#1e40af}.hit .kind.column{background:#f3f4f6;color:#374151}
.hit .desc{color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.path{font-family:ui-monospace,Menlo,monospace;font-size:12px;background:#fafbfc;
 border:1px solid var(--line);border-radius:8px;padding:7px 10px;margin:4px 0;word-break:break-all}
.path .on{color:var(--muted)}
.sqlbox{background:#14171f;color:#d8dee9;border-radius:10px;padding:12px 14px;
 font:12.5px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap;
 word-break:break-word;margin:6px 0}
.reason{font-size:12.5px;color:var(--muted);margin:0 0 8px}
.repair-badge{font-size:10.5px;background:#fef3c7;color:#92400e;border:1px solid #fde68a;
 border-radius:999px;padding:2px 9px;font-weight:600;margin-left:8px}
.err{background:#fef2f2;border:1px solid #fecaca;color:#991b1b;border-radius:10px;
 padding:10px 14px;font-size:12.5px;font-family:ui-monospace,Menlo,monospace;word-break:break-word}
.result-meta{font-size:12px;color:var(--muted);margin-bottom:8px}
table{border-collapse:separate;border-spacing:0;width:100%;font-size:12.5px;
 border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{border-bottom:1px solid var(--line);padding:6px 10px;text-align:left;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:240px}
tr:last-child td{border-bottom:none}
th{background:#fafbfc;color:var(--muted);font-size:10.5px;font-weight:700;
 text-transform:uppercase;letter-spacing:.04em}
.tablewrap{overflow-x:auto}
.spin{display:inline-block;width:14px;height:14px;border:2px solid #c7d2fe;
 border-top-color:var(--accent);border-radius:50%;animation:sp .7s linear infinite;
 vertical-align:-2px;margin-right:6px}
@keyframes sp{to{transform:rotate(360deg)}}
.ok-tag{color:var(--ok);font-weight:700}.bad-tag{color:var(--bad);font-weight:700}
.note{font-size:11.5px;color:var(--muted);margin-top:14px;line-height:1.6}
</style></head><body>
<header>
 <span class="brand"><span class="logo">◈</span>db2doc</span>
 <h1>text2sql</h1>
 <span style="margin-left:auto;display:flex;align-items:center;gap:10px">
   <nav class="navtabs">
     <a class="navtab" href="__BACK__">📚 카탈로그</a>
     <a class="navtab" href="/runs/__RID__/graph">🕸 스키마 그래프</a>
     <a class="navtab active" href="/runs/__RID__/text2sql">💬 text2sql</a>
   </nav>
   <a class="navback" href="/">← 런 목록</a>
 </span>
</header>
<div class="askbar">
 <input id="q" placeholder="자연어로 질문하세요. 예: 가장 흔한 진단명 상위 10개"
   value="가장 흔한 진단명 상위 10개와 진단 건수">
 <button id="ask">질의 실행</button>
</div>
<div class="examples" id="exlist">
 <span class="lbl">예시</span>
 <span class="ex">가장 흔한 진단명 상위 10개와 진단 건수</span>
 <span class="ex">가장 많이 처방된 약물 이름 상위 10개</span>
 <span class="ex">성별별 환자 수를 보여줘</span>
 <span class="ex">연도별 신규 환자 수 추이</span>
 <span class="ex">환자당 평균 방문 횟수</span>
</div>
<div class="layout">
 <div class="body"><div class="wrap" id="out">
  <div class="placeholder"><div class="big">◈</div>
   자연어 질문을 입력하면, 우리 솔루션이 만든 <b>OpenSearch 메타데이터 RAG</b>로 관련
   스키마를 찾고 → <b>Neptune 온톨로지 그래프</b>로 조인 경로를 펼치고 →
   <b>LangGraph</b>가 SQL을 생성·실행하는 과정을 단계별로 보여줍니다.</div>
 </div></div>
 <aside class="histpanel">
  <div class="histhead"><b>실행 이력</b>
   <button id="histclear" title="이력 비우기">전체 삭제</button></div>
  <div id="histlist" class="histlist"><div class="histempty">아직 실행 이력이 없습니다.</div></div>
 </aside>
</div>
<script>
const RID = "__RID__";
const esc = s => (s??'').toString().replace(/[&<>"]/g,
  c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const out = document.getElementById('out');

function bindExamples(){
  document.querySelectorAll('.examples .ex').forEach(e=>e.onclick=()=>{
    document.getElementById('q').value = e.dataset.q || e.textContent; ask();
  });
}
bindExamples();

// replace hardcoded examples with EXECUTION-VERIFIED questions for this run
(async ()=>{
  try{
    const r = await fetch(`/api/runs/${RID}/text2sql/verified`);
    if (!r.ok) return;
    const v = (await r.json()).verified || [];
    if (!v.length) return;   // keep hardcoded fallback
    const box = document.getElementById('exlist');
    box.innerHTML = '<span class="lbl">예시 <b style="color:#059669">✓ 검증됨</b></span>'
      + v.map(x=>`<span class="ex" data-q="${esc(x.question)}"`
        + ` title="이 DB에서 실행 검증된 질문 (rows=${x.rowcount??'—'})">`
        + `✓ ${esc(x.question)}</span>`).join('');
    const first = v[0];
    if (first) document.getElementById('q').value = first.question;
    bindExamples();
  }catch(e){/* fallback stays */}
})();

const STEP_META = {
  retrieve: {n:1, title:'후보 스키마 검색', tool:'OpenSearch 벡터 + Neptune 개념', cls:'aws',
    sub:'① 벡터 의미검색 → ② 온톨로지 개념매칭 → ③ 후보 통합'},
  expand:   {n:2, title:'그래프로 후보 상세 확장', tool:'Neptune · openCypher', cls:'aws',
    sub:'후보 테이블의 컬럼·키·FK·조인 경로 조회'},
  generate: {n:3, title:'SQL 생성', tool:'LangGraph · Claude', cls:'',
    sub:'확장된 스키마 컨텍스트만으로 PostgreSQL 작성'},
  execute:  {n:4, title:'실행 (읽기 전용)', tool:'RDS PostgreSQL', cls:'aws',
    sub:'SELECT만, LIMIT 강제, 15s 타임아웃'},
};

function renderStep(st){
  const m = STEP_META[st.step]; const d = st.data;
  let inner = '';
  if (st.step === 'retrieve'){
    const ss = d.substages || {};
    const vec = ss.vector || {}, con = ss.concept || {}, mg = ss.merge || {};
    const conceptTables = new Set(con.added_tables || []);

    // ① 벡터 의미 검색
    const vecBlock = `<div class="substage">
      <div class="ss-head"><span class="ss-num">①</span> 벡터 의미 검색
        <span class="ss-eng">${esc(vec.engine||'OpenSearch')}</span></div>
      <div class="ss-body">
        <span class="metric">히트 <b>${vec.n_hits??0}</b></span>
        <span class="metric">테이블 매치 <b>${vec.n_table_hits??0}</b></span>
        <span class="metric">컬럼 매치 <b>${vec.n_column_hits??0}</b></span>
        <span class="metric">→ 테이블 <b>${(vec.tables_from_vector||[]).length}</b>종</span>
        <div class="hits-box">
        ${(d.hits||[]).slice(0,8).map(h=>`<div class="hit">
          <span class="score">${h.score?.toFixed(3)??''}</span>
          <span class="kind ${h.kind}">${h.kind}</span>
          <code>${esc(h.table)}${h.column?'.'+esc(h.column):''}</code>
          <span class="desc">${esc(h.description||'')}</span></div>`).join('')}
        </div></div></div>`;

    // ② 개념(온톨로지) 매칭
    const conBlock = `<div class="substage concept">
      <div class="ss-head"><span class="ss-num">②</span> 온톨로지 개념 매칭
        <span class="ss-eng">${esc(con.engine||'Neptune 개념')}</span></div>
      <div class="ss-body">
        ${(con.matched||[]).length
          ? `<span class="metric">매칭 개념</span>
             ${con.matched.map(x=>`<span class="cchip">◆ ${esc(x)}</span>`).join('')}
             ${(con.added_tables||[]).length
               ? `<div class="cnote">IS_A 계층을 펼쳐 벡터검색이 놓친 테이블 보강:
                  ${con.added_tables.map(t=>`<code>${esc(t)}</code>`).join(' ')}</div>`
               : `<div class="cnote">매칭 개념의 테이블은 벡터 결과에 이미 포함 (보강 0)</div>`}`
          : `<span class="cnote">질문 용어에 매칭된 개념 없음 — 벡터 결과만 사용</span>`}
      </div></div>`;

    // ③ 후보 통합
    const mergeBlock = `<div class="substage merge">
      <div class="ss-head"><span class="ss-num">③</span> 최종 후보 테이블 통합
        <span class="ss-eng">벡터 ∪ 개념 · 중복 제거</span></div>
      <div class="ss-body">
        <span class="metric">최종 후보 <b>${mg.n_final??(d.tables||[]).length}</b>종</span>
        <div class="chips" style="margin-top:6px">
        ${(d.tables||[]).map(t=>{
          const fromConcept = conceptTables.has(t);
          return `<span class="chip${fromConcept?' from-concept':''}">${esc(t)}${
            fromConcept?' <b>◆</b>':''}</span>`;
        }).join('')}</div>
        <div class="cnote" style="margin-top:6px">◆ = 개념 레이어가 보강한 테이블</div>
      </div></div>`;

    inner = vecBlock + conBlock + mergeBlock;
  } else if (st.step === 'expand'){
    const cpt = d.columns_per_table || {};
    inner = `<div class="chips" style="margin-bottom:8px">
      <span class="chip">출처 <b>${esc(d.source)}</b></span>
      <span class="chip">조회 컬럼 <b>${d.n_columns}</b>개</span>
      <span class="chip">FK <b>${d.fk_count}</b>개</span>
      <span class="chip">조인 경로 <b>${d.join_paths.length}</b>개</span></div>
      <div class="ss-body" style="margin-bottom:8px">
        <div class="cnote">후보 테이블별로 컬럼·설명·키를 그래프에서 조회:</div>
        <div class="chips" style="margin-top:5px">
        ${Object.entries(cpt).map(([t,n])=>`<span class="chip">${esc(t)}
          <b>${n}</b>컬럼</span>`).join('')}</div></div>
      <div class="cnote" style="margin:8px 0 4px">후보 간 최단 조인 경로 (상위 6개):</div>` +
      d.join_paths.slice(0,6).map(p=>`<div class="path">
        ${esc(p.tables.join(' → '))}<br><span class="on">ON ${esc(p.vias.join('; '))}</span>
      </div>`).join('');
  } else if (st.step === 'generate'){
    inner = (d.repair?`<span class="repair-badge">⟳ self-correct 재생성</span>`:'') +
      (d.reasoning?`<p class="reason">${esc(d.reasoning)}</p>`:'') +
      `<div class="sqlbox">${esc(d.sql)}</div>`;
  } else if (st.step === 'execute'){
    if (d.ok){
      const cols = d.columns, rows = d.rows;
      inner = `<div class="result-meta"><span class="ok-tag">✓ 성공</span> ·
        ${d.rowcount}행 · <code>${esc(d.executed_sql)}</code></div>`;
      if (rows.length){
        inner += `<div class="tablewrap"><table><thead><tr>` +
          cols.map(c=>`<th>${esc(c)}</th>`).join('') + `</tr></thead><tbody>` +
          rows.slice(0,20).map(r=>`<tr>`+r.map(v=>`<td>${esc(v)}</td>`).join('')+`</tr>`).join('') +
          `</tbody></table></div>`;
      } else inner += `<p class="note">조건에 맞는 행이 없습니다 (SQL은 정상 실행됨 —
        해당 테이블이 데모 데이터에서 비어있을 수 있음).</p>`;
    } else {
      inner = `<div class="result-meta"><span class="bad-tag">✗ 오류</span> →
        다음 단계에서 재생성</div><div class="err">${esc(d.error)}</div>`;
    }
  }
  return `<div class="step"><div class="step-head">
    <span class="step-num">${m.n}</span><h3>${m.title}</h3>
    <span class="tool ${m.cls}">${m.tool}</span>
    <span class="sub">${m.sub}</span></div>
    <div class="step-body">${inner}</div></div>`;
}

function renderResult(steps, attempts, ok, replayQ){
  let html = '';
  if (replayQ) html += `<div class="note" style="margin:0 0 12px">
    <b>이력 재생:</b> "${esc(replayQ)}"</div>`;
  html += steps.map(renderStep).join('');
  html += `<div class="note">LangGraph 노드 ${steps.length}개 ·
    시도 ${attempts}회 · 최종 ${ok?'<span class="ok-tag">성공</span>':'<span class="bad-tag">실패</span>'}.
    이 전 과정이 우리 솔루션의 온톨로지·Graph RAG·복원된 메타데이터만으로 동작합니다.</div>`;
  out.innerHTML = html;
}

async function ask(){
  const q = document.getElementById('q').value.trim();
  if(!q) return;
  const btn = document.getElementById('ask'); btn.disabled = true;
  out.innerHTML = `<div class="placeholder"><span class="spin"></span>
    파이프라인 실행 중… (검색 → 그래프 → 생성 → 실행)</div>`;
  try {
    const r = await fetch(`/api/runs/${RID}/text2sql`, {method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify({question:q})});
    if(!r.ok){ out.innerHTML = `<div class="err">${esc(await r.text())}</div>`; return; }
    const data = await r.json();
    renderResult(data.steps, data.attempts, data.result?.ok);
    loadHistory();
  } catch(e){ out.innerHTML = `<div class="err">${esc(e)}</div>`; }
  finally { btn.disabled = false; }
}
document.getElementById('ask').onclick = ask;
document.getElementById('q').addEventListener('keydown', e=>{ if(e.key==='Enter') ask(); });

// ----- 실행 이력 -----
let HISTORY = [];
function fmtTime(iso){
  try { const d = new Date(iso);
    return d.toLocaleString('ko-KR',{month:'2-digit',day:'2-digit',
      hour:'2-digit',minute:'2-digit'}); } catch(e){ return ''; }
}
async function loadHistory(){
  try {
    const r = await fetch(`/api/runs/${RID}/text2sql/history`);
    HISTORY = (await r.json()).history || [];
  } catch(e){ HISTORY = []; }
  const list = document.getElementById('histlist');
  if(!HISTORY.length){
    list.innerHTML = '<div class="histempty">아직 실행 이력이 없습니다.</div>';
    return;
  }
  list.innerHTML = HISTORY.map((h,i)=>`<div class="histitem" data-i="${i}">
    <div class="hq">${esc(h.question)}</div>
    <div class="hmeta">
      <span class="hstat ${h.ok?'ok':'bad'}">${h.ok?'성공':'실패'}</span>
      <span>${h.rowcount!=null?h.rowcount+'행':''}</span>
      ${h.attempts>1?`<span>· 재시도 ${h.attempts-1}</span>`:''}
      <span style="margin-left:auto">${fmtTime(h.ts)}</span>
    </div></div>`).join('');
  list.querySelectorAll('.histitem').forEach(el=>el.onclick=()=>{
    const h = HISTORY[+el.dataset.i];
    document.getElementById('q').value = h.question;
    renderResult(h.steps||[], h.attempts, h.ok, h.question);
    document.querySelector('.body').scrollTop = 0;
  });
}
document.getElementById('histclear').onclick = async ()=>{
  if(!confirm('실행 이력을 모두 삭제할까요?')) return;
  await fetch(`/api/runs/${RID}/text2sql/history`, {method:'DELETE'});
  loadHistory();
};
loadHistory();
</script></body></html>
"""


def render_t2sql_page(run_id):
    return (T2SQL_PAGE
            .replace("__RID__", run_id)
            .replace("__BACK__", f"/runs/{run_id}"))
