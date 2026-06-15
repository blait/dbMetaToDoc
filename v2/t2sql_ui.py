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
.body{flex:1;overflow-y:auto;padding:20px 22px}
.wrap{max-width:1000px;margin:0 auto}
.placeholder{text-align:center;color:var(--muted);padding:60px 20px}
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
 <h1>text2sql — 온톨로지·Graph RAG 기반 질의</h1>
 <span style="margin-left:auto"></span>
 <a href="__BACK__">&larr; 카탈로그</a>&nbsp;&nbsp;&nbsp;
 <a href="/runs/__RID__/graph">스키마 그래프</a>&nbsp;&nbsp;&nbsp;<a href="/">런 목록</a>
</header>
<div class="askbar">
 <input id="q" placeholder="자연어로 질문하세요. 예: 환자별 처방 약물 수를 세어줘"
   value="환자별 처방 약물 수를 많은 순으로 보여줘">
 <button id="ask">질의 실행</button>
</div>
<div class="examples">
 <span class="lbl">예시</span>
 <span class="ex">환자별 처방 약물 수를 많은 순으로 보여줘</span>
 <span class="ex">여성 환자들이 방문한 진료기관 이름별 방문 횟수</span>
 <span class="ex">가장 흔한 진단(condition) 상위 10개</span>
 <span class="ex">방문 유형별 평균 재원일수</span>
</div>
<div class="body"><div class="wrap" id="out">
 <div class="placeholder"><div class="big">◈</div>
  자연어 질문을 입력하면, 우리 솔루션이 만든 <b>OpenSearch 메타데이터 RAG</b>로 관련
  스키마를 찾고 → <b>Neptune 온톨로지 그래프</b>로 조인 경로를 펼치고 →
  <b>LangGraph</b>가 SQL을 생성·실행하는 과정을 단계별로 보여줍니다.</div>
</div></div>
<script>
const RID = "__RID__";
const esc = s => (s??'').toString().replace(/[&<>"]/g,
  c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const out = document.getElementById('out');

document.querySelectorAll('.examples .ex').forEach(e=>e.onclick=()=>{
  document.getElementById('q').value = e.textContent; ask();
});

const STEP_META = {
  retrieve: {n:1, title:'메타데이터 RAG 검색', tool:'OpenSearch · 벡터', cls:'aws',
    sub:'질문과 의미가 가까운 테이블/컬럼 top-k'},
  expand:   {n:2, title:'온톨로지 그래프 확장', tool:'Neptune · openCypher', cls:'aws',
    sub:'복원된 FK·조인 경로 펼치기'},
  generate: {n:3, title:'SQL 생성', tool:'LangGraph · Claude', cls:'',
    sub:'스키마 컨텍스트만으로 PostgreSQL 작성'},
  execute:  {n:4, title:'실행 (읽기 전용)', tool:'RDS PostgreSQL', cls:'aws',
    sub:'SELECT만, LIMIT 강제, 15s 타임아웃'},
};

function renderStep(st){
  const m = STEP_META[st.step]; const d = st.data;
  let inner = '';
  if (st.step === 'retrieve'){
    inner = `<div class="chips" style="margin-bottom:10px">` +
      d.tables.map(t=>`<span class="chip"><b>${esc(t)}</b></span>`).join('') + `</div>` +
      d.hits.slice(0,8).map(h=>`<div class="hit">
        <span class="score">${h.score?.toFixed(3)??''}</span>
        <span class="kind ${h.kind}">${h.kind}</span>
        <code>${esc(h.table)}${h.column?'.'+esc(h.column):''}</code>
        <span class="desc">${esc(h.description||'')}</span></div>`).join('');
  } else if (st.step === 'expand'){
    inner = `<div class="chips" style="margin-bottom:8px">
      <span class="chip">출처 <b>${esc(d.source)}</b></span>
      <span class="chip">FK <b>${d.fk_count}</b>개</span>
      <span class="chip">조인 경로 <b>${d.join_paths.length}</b>개</span></div>` +
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
    let html = data.steps.map(renderStep).join('');
    const ok = data.result?.ok;
    html += `<div class="note">LangGraph 노드 ${data.steps.length}개 ·
      시도 ${data.attempts}회 · 최종 ${ok?'<span class="ok-tag">성공</span>':'<span class="bad-tag">실패</span>'}.
      이 전 과정이 우리 솔루션의 온톨로지·Graph RAG·복원된 메타데이터만으로 동작합니다.</div>`;
    out.innerHTML = html;
  } catch(e){ out.innerHTML = `<div class="err">${esc(e)}</div>`; }
  finally { btn.disabled = false; }
}
document.getElementById('ask').onclick = ask;
document.getElementById('q').addEventListener('keydown', e=>{ if(e.key==='Enter') ask(); });
</script></body></html>
"""


def render_t2sql_page(run_id):
    return (T2SQL_PAGE
            .replace("__RID__", run_id)
            .replace("__BACK__", f"/runs/{run_id}"))
