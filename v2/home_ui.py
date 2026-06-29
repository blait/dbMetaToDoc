"""Home page template — run list + new-DB connection (served at /)."""

HOME = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>db2doc — 자동 데이터 카탈로그</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<style>
:root{--bg:#f5f6f8;--surface:#fff;--ink:#16181d;--muted:#6b7280;--line:#e5e7eb;
 --accent:#4f46e5;--accent-soft:#eef2ff;--ok:#16a34a;--warn:#d97706;--bad:#dc2626;
 --shadow:0 1px 2px rgba(16,24,40,.06),0 1px 3px rgba(16,24,40,.08)}
*{box-sizing:border-box}
body{font:14px/1.6 "Pretendard Variable",Pretendard,-apple-system,BlinkMacSystemFont,
 "Segoe UI","Apple SD Gothic Neo","Malgun Gothic",sans-serif;color:var(--ink);
 margin:0;background:var(--bg)}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:#eef0f3;
 padding:1px 6px;border-radius:6px;font-size:88%}
/* ---- topbar ---- */
.topbar{background:#14171f;color:#e8eaef;display:flex;align-items:center;gap:12px;
 padding:0 26px;height:54px;position:sticky;top:0;z-index:10}
.brand{display:flex;align-items:center;gap:9px;font-weight:700;font-size:15.5px;
 letter-spacing:-.01em}
.brand .logo{width:24px;height:24px;border-radius:7px;display:grid;place-items:center;
 background:linear-gradient(135deg,#6366f1,#a855f7);font-size:13px;color:#fff}
.brand .ver{font-size:10.5px;font-weight:700;background:#2a2f3c;color:#aab2c5;
 border-radius:999px;padding:2px 8px;letter-spacing:.02em}
.topbar .right{margin-left:auto;font-size:12px;color:#8b93a5}
.topbar .right code{background:#222736;color:#aab2c5}
/* ---- layout ---- */
.page{max-width:1240px;margin:0 auto;padding:30px 26px;display:grid;
 grid-template-columns:368px 1fr;gap:24px;align-items:start}
@media (max-width:980px){.page{grid-template-columns:1fr}}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;
 box-shadow:var(--shadow)}
/* ---- connect panel ---- */
.connect{padding:22px;position:sticky;top:78px}
.connect h2{margin:0 0 2px;font-size:16px;letter-spacing:-.01em}
.connect .sub{color:var(--muted);font-size:12.5px;margin:0 0 18px}
.field{margin-bottom:12px}
.field label{display:block;font-size:12px;font-weight:600;color:#374151;margin:0 0 5px}
.field input{width:100%;padding:9px 12px;border:1px solid var(--line);border-radius:9px;
 font-size:13.5px;font-family:inherit;background:#fafbfc;transition:border .15s}
.field input:focus{outline:none;border-color:var(--accent);background:#fff;
 box-shadow:0 0 0 3px rgba(79,70,229,.12)}
.field-row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.checks{margin:6px 0 4px;display:flex;flex-direction:column;gap:8px}
.checks label{display:flex;gap:8px;align-items:flex-start;font-size:12.5px;color:#374151;line-height:1.4}
.checks input{accent-color:var(--accent);margin-top:2px}
.adv{margin-top:14px;border-top:1px solid var(--line);padding-top:10px}
.adv summary{font-size:12px;color:var(--muted);cursor:pointer;font-weight:600;
 list-style:none}
.adv summary:hover{color:var(--ink)}
.adv summary::before{content:'▸ ';font-size:10px}
.adv[open] summary::before{content:'▾ '}
.btns{display:flex;gap:8px;margin-top:14px}
button{border:1px solid var(--line);background:#fff;border-radius:9px;
 padding:9px 16px;font-size:13.5px;font-family:inherit;font-weight:600;cursor:pointer;
 transition:all .15s}
button:hover{background:#f5f6f8}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff;flex:1}
button.primary:hover{background:#4338ca}
button:disabled{opacity:.5;cursor:default}
.msg{font-size:12.5px;margin-top:10px;display:block;min-height:18px}
.msg.ok{color:var(--ok)}.msg.err{color:var(--bad)}
.connect .note{font-size:11.5px;color:var(--muted);margin:14px 0 0;line-height:1.55;
 border-top:1px solid var(--line);padding-top:12px}
/* ---- runs ---- */
.runs-head{display:flex;align-items:baseline;gap:10px;margin:2px 0 14px}
.runs-head h2{margin:0;font-size:17px;letter-spacing:-.01em}
.runs-head .cnt{color:var(--muted);font-size:13px}
.run-card{display:block;padding:18px 20px;margin-bottom:12px;cursor:pointer;
 transition:all .15s;position:relative}
.run-card:hover{border-color:#c7cdd6;box-shadow:0 4px 14px rgba(16,24,40,.1);
 transform:translateY(-1px)}
.run-top{display:flex;align-items:center;gap:10px;margin-bottom:2px}
.run-top b{font-size:14.5px;letter-spacing:-.01em}
.run-target{color:var(--muted);font-size:12px;margin-bottom:12px}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:700;
 border-radius:999px;padding:3px 10px;letter-spacing:.01em}
.chip::before{content:"";width:6px;height:6px;border-radius:50%}
.chip.running{background:#fef3c7;color:#92400e}
.chip.running::before{background:#f59e0b;animation:pulse 1.1s ease-in-out infinite}
.chip.done{background:#dcfce7;color:#166534}.chip.done::before{background:#22c55e}
.chip.failed{background:#fee2e2;color:#991b1b}.chip.failed::before{background:#ef4444}
@keyframes pulse{50%{opacity:.35}}
.metrics{display:flex;gap:0;border:1px solid var(--line);border-radius:10px;
 overflow:hidden;background:#fafbfc}
.metric{flex:1;padding:9px 14px;border-right:1px solid var(--line)}
.metric:last-child{border-right:none}
.metric .k{font-size:10.5px;color:var(--muted);font-weight:600;
 text-transform:uppercase;letter-spacing:.05em}
.metric .v{font-size:16.5px;font-weight:700;letter-spacing:-.02em;
 font-variant-numeric:tabular-nums}
.metric .v .pct{font-size:11px;color:var(--muted);font-weight:600}
.metric.llm .k::after{content:"LLM";margin-left:5px;background:var(--accent-soft);
 color:var(--accent);border-radius:4px;padding:0 4px;font-size:9px}
.run-foot{display:flex;align-items:center;gap:10px;margin-top:11px;
 color:var(--muted);font-size:11.5px}
.run-foot .del{margin-left:auto;border:none;background:none;color:#b6bcc6;
 font-size:14px;padding:4px 6px;font-weight:400}
.run-foot .del:hover{color:var(--bad);background:none}
.empty-state{padding:54px 20px;text-align:center;color:var(--muted)}
.empty-state .big{font-size:34px;margin-bottom:8px}
.foot-note{color:var(--muted);font-size:12px;margin-top:14px;line-height:1.6}
.skel{height:96px;border-radius:14px;background:linear-gradient(90deg,#eee 25%,#f6f6f6 50%,#eee 75%);
 background-size:200% 100%;animation:sh 1.2s infinite}
@keyframes sh{to{background-position:-200% 0}}
</style></head><body>
<nav class="topbar">
 <span class="brand"><span class="logo">◈</span>db2doc<span class="ver">v2</span></span>
 <span class="right">의미 추론 LLM: <code id="genmodel">Bedrock</code></span>
</nav>
<div class="page">

<aside>
<div class="card connect">
 <h2>새 DB 연결</h2>
 <p class="sub">문서 없는 DB에 연결하면 의미를 추론해 카탈로그를 만듭니다</p>
 <form id="connform" onsubmit="return false">
  <div class="field"><label>표시 이름 <span style="color:#9ca3af;font-weight:400">(선택)</span></label>
   <input type="text" name="name" placeholder="예: 고객A 운영DB"></div>
  <div class="field"><label>호스트</label>
   <input type="text" name="host" required placeholder="db.example.com"></div>
  <div class="field-row">
   <div class="field"><label>포트</label><input type="number" name="port" value="5432"></div>
   <div class="field"><label>스키마</label><input type="text" name="schema_name" value="public"></div>
  </div>
  <div class="field"><label>데이터베이스</label><input type="text" name="dbname" required></div>
  <div class="field-row">
   <div class="field"><label>사용자</label><input type="text" name="user" required></div>
   <div class="field"><label>비밀번호</label><input type="password" name="password" required></div>
  </div>
  <div class="btns">
   <button id="testbtn">연결 테스트</button>
   <button id="startbtn" class="primary">분석 시작</button>
  </div>
  <span class="msg" id="connmsg"></span>
  <p class="note">스키마·통계·샘플만 읽는 <b>읽기 전용</b> 분석입니다. 기존 주석(COMMENT)·
  키 제약이 있으면 단서로 활용하고, DB를 변경하지 않습니다. 비밀번호는 실행 프로세스에만
  전달되고 저장되지 않습니다. 현재 PostgreSQL 지원.</p>
  <details class="adv">
   <summary>고급 — 평가 모드 (정답지가 있는 벤치마크 DB 전용)</summary>
   <div class="checks">
    <label><input type="checkbox" name="with_truth"> 정답지 채점 포함 (OMOP 등 공식
     데이터 딕셔너리와 대조)</label>
    <label id="njwrap" style="display:none"><input type="checkbox" name="no_judge">
     LLM judge 생략 (cosine만)</label>
   </div>
   <p class="note" style="margin-top:6px">고객 DB에는 사용하지 마세요 — 정답지가 없으면
   채점이 의미 없습니다. 일반 분석은 위 "분석 시작"으로 카탈로그만 생성됩니다.</p>
  </details>
 </form>
</div>
</aside>

<main>
 <div class="runs-head"><h2>분석 런</h2><span class="cnt" id="runcount"></span></div>
 <div id="runbody"><div class="skel"></div></div>
 <p class="foot-note">새 DB를 연결하면 <b>카탈로그</b>(테이블·컬럼 의미, 키, 신뢰도)를
 생성합니다. 정답지가 있는 벤치마크 DB는 고급 옵션에서 채점을 켜면 의미 일치도(LLM judge)와
 PK/FK F1까지 측정합니다.</p>
</main>

</div>
<script>
const esc = s => (s??'').toString().replace(/[&<>"]/g,
  c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const pct = v => v==null ? '—' : `${(v*100).toFixed(1)}<span class="pct">%</span>`;
const f3 = v => v==null ? '—' : (+v).toFixed(3);

const form = document.getElementById('connform');
function payload(){
  const f = new FormData(form);
  return {
    name: f.get('name')||'', host: f.get('host'),
    port: +(f.get('port')||5432), dbname: f.get('dbname'),
    user: f.get('user'), password: f.get('password'),
    schema_name: f.get('schema_name')||'public',
    with_truth: !!f.get('with_truth'), no_judge: !!f.get('no_judge'),
  };
}
form.with_truth.onchange = () =>
  document.getElementById('njwrap').style.display =
    form.with_truth.checked ? '' : 'none';

const msg = (t, ok) => {
  const el = document.getElementById('connmsg');
  el.textContent = t; el.className = 'msg ' + (ok?'ok':'err');
};
document.getElementById('testbtn').onclick = async () => {
  if(!form.reportValidity()) return;
  msg('연결 확인 중…', true);
  const r = await fetch('/api/test-connection', {method:'POST',
    headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload())});
  const j = await r.json();
  msg(j.ok ? `연결 성공 — 테이블 ${j.tables}개 발견` : `실패: ${j.error}`, j.ok);
};
document.getElementById('startbtn').onclick = async () => {
  if(!form.reportValidity()) return;
  const btn = document.getElementById('startbtn');
  btn.disabled = true; msg('파이프라인 시작 중…', true);
  const r = await fetch('/api/runs', {method:'POST',
    headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload())});
  btn.disabled = false;
  if(r.ok){ msg('시작됨 — 우측 리스트에서 진행 상황을 확인하세요', true);
    form.password.value=''; loadRuns(); }
  else msg('시작 실패: ' + (await r.text()), false);
};

function metricsHTML(m){
  const h = m.headline||{};
  if (m.status==='running')
    return `<div class="metrics"><div class="metric">
      <div class="k">진행</div><div class="v" style="font-size:13px;font-weight:500;color:var(--muted)">
      프로파일링 → 관계 복원 → 의미 추론 → 카탈로그${m.with_truth?' → 채점':''} 진행 중…</div></div></div>`;
  if (m.status==='failed')
    return `<div class="metrics"><div class="metric">
      <div class="k">오류</div><div class="v" style="font-size:13px;color:var(--bad)">
      ${esc(m.error || '파이프라인 실패')}</div></div></div>`;
  if (!m.with_truth)
    return `<div class="metrics">
      <div class="metric"><div class="k">테이블</div><div class="v">${h.tables??'—'}</div></div>
      <div class="metric"><div class="k">컬럼</div><div class="v">${h.columns??'—'}</div></div>
      <div class="metric"><div class="k">도메인 추론</div>
        <div class="v" style="font-size:13px">${esc(h.domain||'—')}</div></div>
      <div class="metric"><div class="k">결과</div>
        <div class="v" style="font-size:12px;font-weight:600;color:var(--accent)">카탈로그 생성됨<br>클릭해 열람</div></div>
    </div>`;
  return `<div class="metrics">
    <div class="metric llm" title="LLM judge: ${esc(h.judge_model||'')}">
      <div class="k">컬럼 일치</div><div class="v">${pct(h.col_judge)}</div></div>
    <div class="metric llm" title="LLM judge: ${esc(h.judge_model||'')}">
      <div class="k">테이블 일치</div><div class="v">${pct(h.tbl_judge)}</div></div>
    <div class="metric"><div class="k">PK F1</div><div class="v">${f3(h.pk_f1)}</div></div>
    <div class="metric"><div class="k">FK F1</div><div class="v">${f3(h.fk_f1)}</div></div>
    <div class="metric"><div class="k">종합</div><div class="v">${f3(h.s_overall)}</div></div>
  </div>`;
}

async function loadRuns(){
  const r = await fetch('/api/runs');
  const {runs} = await r.json();
  const body = document.getElementById('runbody');
  document.getElementById('runcount').textContent = runs.length ? runs.length+'개' : '';
  if(!runs.length){
    body.innerHTML = `<div class="card empty-state">
      <div class="big">◈</div>아직 분석 런이 없습니다.<br>
      좌측에서 DB를 연결해 첫 분석을 시작하세요.</div>`;
    return;
  }
  const gm = runs.find(x=>x.headline?.gen_model)?.headline.gen_model;
  if (gm) document.getElementById('genmodel').textContent = gm;
  body.innerHTML = runs.map(m=>{
    const h = m.headline||{};
    return `<div class="card run-card" data-id="${esc(m.id)}">
     <div class="run-top"><b>${esc(m.name)}</b>
      <span class="chip ${esc(m.status)}">${
        m.status==='running'?'실행 중':m.status==='done'?'완료':'실패'}</span></div>
     <div class="run-target">${esc(m.dbname)}@${esc(m.host)} · schema <code>${esc(m.schema)}</code></div>
     ${metricsHTML(m)}
     <div class="run-foot">
      <span>${esc((m.created_at||'').slice(0,16).replace('T',' '))}</span>
      ${h.tables!=null&&m.with_truth?`<span>· ${h.tables}T / ${h.columns}C</span>`:''}
      ${h.domain&&m.with_truth?`<span>· ${esc(h.domain)}</span>`:''}
      <span>· ${esc(m.id)}</span>
      <button class="del" data-del="${esc(m.id)}" title="런 삭제">✕</button>
     </div>
    </div>`;
  }).join('');
  body.querySelectorAll('.run-card').forEach(el=>el.onclick = e=>{
    if(e.target.dataset.del) return;
    location.href = '/runs/' + el.dataset.id;
  });
  body.querySelectorAll('[data-del]').forEach(b=>b.onclick = async e=>{
    e.stopPropagation();
    if(!confirm('이 런과 산출물을 삭제할까요?')) return;
    await fetch('/api/runs/'+b.dataset.del, {method:'DELETE'});
    loadRuns();
  });
}
loadRuns();
setInterval(loadRuns, 5000);
</script>
</body></html>
"""
