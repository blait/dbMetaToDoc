#!/usr/bin/env python3
"""Build a self-contained, clickable UI prototype from the PoC outputs.

Reads out/{descriptions,profile,relations,score}.json and bakes them into a
single static HTML file (ui/db2doc_ui.html) that opens with file:// — no server,
no deps.  Demonstrates the product UX: Sources dashboard, Review Queue (with
evidence + confidence triage), Catalog/table detail, and the score report.
"""
import os
import sys
import json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")


def load(name):
    with open(os.path.join(OUT, name), encoding="utf-8") as f:
        return json.load(f)


def build_dataset():
    desc = load("descriptions.json")
    profile = load("profile.json")
    relations = load("relations.json")
    score = load("score.json")

    pks = relations.get("primary_keys", {})
    fks = relations.get("foreign_keys", [])
    fk_by_child = {}
    for fk in fks:
        fk_by_child.setdefault(fk["child_table"], []).append(fk)

    # index profile column stats for evidence
    prof_idx = {}
    for t, tinfo in profile["tables"].items():
        for c in tinfo["columns"]:
            prof_idx[(t, c["name"])] = c

    tables = []
    for tname, tdesc in desc["tables"].items():
        tinfo = profile["tables"].get(tname, {})
        cols = []
        for c in tdesc["columns"]:
            pc = prof_idx.get((tname, c["name"]), {})
            st = pc.get("stats", {})
            cols.append({
                "name": c["name"],
                "description": c["description"],
                "confidence": c.get("confidence"),
                "type": pc.get("data_type"),
                "nullable": pc.get("nullable"),
                "evidence": {
                    "distinct_ratio": st.get("distinct_ratio"),
                    "null_ratio": st.get("null_ratio"),
                    "examples": st.get("examples", []),
                    "top_values": st.get("top_values", [])[:6],
                    "min": st.get("min"), "max": st.get("max"),
                },
            })
        tables.append({
            "name": tname,
            "rowcount": tinfo.get("rowcount", 0),
            "table_description": tdesc["table_description"],
            "pk": pks.get(tname, {}).get("column"),
            "fks": [{"col": f["child_column"], "ref_table": f["parent_table"],
                     "ref_col": f["parent_column"], "inclusion": f["inclusion"]}
                    for f in fk_by_child.get(tname, [])],
            "columns": cols,
        })

    tables.sort(key=lambda t: (-t["rowcount"], t["name"]))
    return {
        "source": {
            "name": desc.get("db", {}).get("domain", "database"),
            "db_description": desc.get("db", {}).get("db_description", ""),
            "model": desc.get("model", ""),
            "schema": profile.get("schema", ""),
            "usage": desc.get("usage", {}),
        },
        "tables": tables,
        "score": score,
    }


HTML = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>db2doc — Schema Documentation Studio</title>
<style>
  :root{
    --bg:#0f1419; --panel:#171d26; --panel2:#1d2530; --line:#2a3441;
    --txt:#e6edf3; --mut:#8b98a8; --acc:#4c9aff; --acc2:#3fb950;
    --warn:#d29922; --bad:#f85149; --chip:#243042;
  }
  *{box-sizing:border-box}
  body{margin:0;font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       background:var(--bg);color:var(--txt)}
  a{color:var(--acc);text-decoration:none}
  .top{display:flex;align-items:center;gap:18px;padding:0 18px;height:52px;
       background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
  .brand{font-weight:700;letter-spacing:.3px}
  .brand b{color:var(--acc)}
  .nav{display:flex;gap:4px}
  .nav button{background:none;border:0;color:var(--mut);padding:8px 12px;border-radius:7px;
              cursor:pointer;font-size:13px}
  .nav button.on{background:var(--panel2);color:var(--txt)}
  .nav .badge{background:var(--acc);color:#fff;border-radius:10px;padding:1px 7px;font-size:11px;margin-left:6px}
  .wrap{max-width:1180px;margin:0 auto;padding:22px 18px 60px}
  h1{font-size:20px;margin:0 0 4px} .sub{color:var(--mut);margin:0 0 18px;font-size:13px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:14px}
  .row{display:flex;gap:14px;flex-wrap:wrap}
  .kpi{flex:1;min-width:150px;background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:14px}
  .kpi .n{font-size:26px;font-weight:700} .kpi .l{color:var(--mut);font-size:12px}
  .kpi .n.good{color:var(--acc2)} .kpi .n.warn{color:var(--warn)}
  table{width:100%;border-collapse:collapse}
  th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
  th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.4px}
  tr.clk{cursor:pointer} tr.clk:hover{background:var(--panel2)}
  .bar{height:7px;background:var(--chip);border-radius:4px;overflow:hidden;min-width:90px}
  .bar>i{display:block;height:100%;background:var(--acc)}
  .pill{display:inline-block;padding:1px 8px;border-radius:20px;font-size:11px;background:var(--chip);color:var(--mut)}
  .pill.pk{background:#1f3a2e;color:#7ee2a8} .pill.fk{background:#22324a;color:#8bb9ff}
  .mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
  .conf{display:inline-flex;align-items:center;gap:6px}
  .dot{width:8px;height:8px;border-radius:50%}
  .hi{color:var(--acc2)} .md{color:var(--warn)} .lo{color:var(--bad)}
  .btn{border:1px solid var(--line);background:var(--panel2);color:var(--txt);border-radius:7px;
       padding:5px 11px;cursor:pointer;font-size:12px}
  .btn:hover{border-color:var(--acc)} .btn.ok{background:#16331f;border-color:#2ea043;color:#7ee2a8}
  .btn.ok:hover{background:#1c4327}
  .rev{border:1px solid var(--line);border-radius:10px;margin-bottom:10px;overflow:hidden}
  .rev .h{display:flex;align-items:center;gap:10px;padding:11px 13px;background:var(--panel2);cursor:pointer}
  .rev .h .name{font-weight:600} .rev .body{padding:13px;display:none;border-top:1px solid var(--line)}
  .rev.open .body{display:block}
  .ev{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:11px;margin:10px 0;font-size:12.5px}
  .ev b{color:var(--mut);font-weight:600}
  .ev .kv{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}
  .tag{background:var(--chip);border-radius:6px;padding:2px 8px;font-size:11px}
  .acts{display:flex;gap:8px;margin-top:10px}
  .acts .done{color:var(--acc2);font-weight:600}
  .filt{display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap}
  .filt input,.filt select{background:var(--panel2);border:1px solid var(--line);color:var(--txt);
       border-radius:7px;padding:7px 10px;font-size:13px}
  .desc{color:var(--txt)} .small{color:var(--mut);font-size:12px}
  .backlink{cursor:pointer;color:var(--acc);font-size:13px;margin-bottom:10px;display:inline-block}
  .erd{white-space:pre;font-family:ui-monospace,monospace;font-size:12px;color:var(--mut);
       background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:12px;overflow:auto}
  .note{background:#1a2230;border-left:3px solid var(--acc);padding:10px 12px;border-radius:6px;
        color:var(--mut);font-size:12.5px;margin:10px 0}
</style></head>
<body>
<div class="top">
  <div class="brand"><b>db2</b>doc <span style="color:var(--mut);font-weight:400">· Schema Documentation Studio</span></div>
  <div class="nav" id="nav"></div>
</div>
<div class="wrap" id="view"></div>

<script>
const DATA = __DATA__;
const T = DATA.tables;
const fmtPct = x => x==null?'—':(x*100).toFixed(0)+'%';
const num = n => (n||0).toLocaleString();
function confClass(c){ return c>=0.9?'hi':c>=0.75?'md':'lo'; }
function confDot(c){ const col=c>=0.9?'var(--acc2)':c>=0.75?'var(--warn)':'var(--bad)';
  return `<span class="dot" style="background:${col}"></span>`; }

// review decisions kept in-memory (prototype)
const decided = {};  // key: table/col -> 'approve'|'edit'|'reject'
function decKey(t,c){return t+'/'+c}

let route = {page:'sources', table:null};
function go(page, table){ route={page, table:table||null}; render(); window.scrollTo(0,0); }

function nav(){
  const pendingCount = T.reduce((a,t)=>a+t.columns.filter(c=>c.confidence<0.9 && !decided[decKey(t.name,c.name)]).length,0);
  const items=[['sources','Sources'],['review','Review Queue'],['catalog','Catalog'],['score','Quality']];
  document.getElementById('nav').innerHTML = items.map(([k,l])=>{
    const b = k==='review'&&pendingCount?`<span class="badge">${pendingCount}</span>`:'';
    return `<button class="${route.page===k?'on':''}" onclick="go('${k}')">${l}${b}</button>`;
  }).join('');
}

function pageSources(){
  const s=DATA.source;
  const totalCols=T.reduce((a,t)=>a+t.columns.length,0);
  const docd=T.reduce((a,t)=>a+t.columns.filter(c=>c.description).length,0);
  const lowConf=T.reduce((a,t)=>a+t.columns.filter(c=>c.confidence<0.9 && !decided[decKey(t.name,c.name)]).length,0);
  const withData=T.filter(t=>t.rowcount>0).length;
  return `
  <h1>Data Sources</h1>
  <p class="sub">연결된 소스의 문서화 현황. AI가 초안을 만들고 DBA가 검수합니다.</p>
  <div class="row">
    <div class="kpi"><div class="n">${T.length}</div><div class="l">테이블</div></div>
    <div class="kpi"><div class="n good">${fmtPct(docd/totalCols)}</div><div class="l">문서화율 (${docd}/${totalCols} 컬럼)</div></div>
    <div class="kpi"><div class="n warn">${lowConf}</div><div class="l">검수 대기 (신뢰도&lt;0.9)</div></div>
    <div class="kpi"><div class="n">${withData}</div><div class="l">데이터 있는 테이블</div></div>
  </div>
  <div class="card">
    <table><thead><tr><th>Source / schema</th><th>도메인 (AI 추론)</th><th>모델</th><th>토큰</th></tr></thead>
    <tbody><tr class="clk" onclick="go('catalog')">
      <td><span class="pill" style="background:#1f3a2e;color:#7ee2a8">⬤ live</span> <span class="mono">${s.schema}</span></td>
      <td>${s.name}</td><td class="small mono">${s.model.split('.').pop()}</td>
      <td class="small">in ${num(s.usage.input_tokens)} / out ${num(s.usage.output_tokens)}</td>
    </tr></tbody></table>
    <div class="note">🔎 <b>AI가 추론한 DB 설명:</b> ${s.db_description}</div>
  </div>`;
}

function evidenceHTML(c){
  const e=c.evidence||{};
  const tv=(e.top_values||[]).map(v=>`<span class="tag mono">${v.value} <span class="small">(${v.count})</span></span>`).join(' ');
  const ex=(e.examples||[]).map(v=>`<span class="tag mono">${v}</span>`).join(' ');
  return `<div class="ev">
    <b>근거 (왜 이 설명인가)</b>
    <div class="kv">
      <span>type: <span class="mono">${c.type||'?'}</span></span>
      <span>distinct_ratio: <span class="mono">${e.distinct_ratio==null?'—':e.distinct_ratio}</span></span>
      <span>null: <span class="mono">${fmtPct(e.null_ratio)}</span></span>
      ${e.min!=null?`<span>range: <span class="mono">${e.min}…${e.max}</span></span>`:''}
    </div>
    ${tv?`<div style="margin-top:7px"><b>top-k 샘플값:</b><br>${tv}</div>`:(ex?`<div style="margin-top:7px"><b>샘플값:</b><br>${ex}</div>`:'')}
  </div>`;
}

function reviewItem(t,c){
  const k=decKey(t.name,c.name); const d=decided[k];
  const acts = d ? `<span class="done">✓ ${d}</span> <button class="btn" onclick="undo('${t.name}','${c.name}')">undo</button>`
    : `<button class="btn ok" onclick="decide('${t.name}','${c.name}','approved')">✓ Approve</button>
       <button class="btn" onclick="decide('${t.name}','${c.name}','edited')">✎ Edit</button>
       <button class="btn" onclick="decide('${t.name}','${c.name}','rejected')">✗ Reject</button>`;
  return `<div class="rev" id="rev_${k.replace(/[^a-z0-9]/gi,'_')}">
    <div class="h" onclick="this.parentNode.classList.toggle('open')">
      <span class="conf ${confClass(c.confidence)}">${confDot(c.confidence)} ${c.confidence.toFixed(2)}</span>
      <span class="name mono">${t.name}.${c.name}</span>
      <span class="small" style="margin-left:auto">${t.rowcount? num(t.rowcount)+' rows':'empty'}</span>
    </div>
    <div class="body">
      <div class="desc">${c.description}</div>
      ${evidenceHTML(c)}
      <div class="acts">${acts}</div>
    </div>
  </div>`;
}

function pageReview(){
  // triage: low-confidence first, only undecided
  const items=[];
  T.forEach(t=>t.columns.forEach(c=>{ if(!decided[decKey(t.name,c.name)] || true) items.push([t,c]); }));
  const pending = items.filter(([t,c])=>c.confidence<0.9 && !decided[decKey(t.name,c.name)]);
  const auto = items.filter(([t,c])=>c.confidence>=0.9);
  pending.sort((a,b)=>a[1].confidence-b[1].confidence);
  return `
  <h1>Review Queue</h1>
  <p class="sub">신뢰도 낮은 항목만 사람이 검수합니다. 0.9↑은 자동 승인 후보. 각 항목은 <b>판단 근거</b>를 함께 제시합니다.</p>
  <div class="row" style="margin-bottom:14px">
    <div class="kpi"><div class="n warn">${pending.length}</div><div class="l">검수 필요 (&lt;0.9)</div></div>
    <div class="kpi"><div class="n good">${auto.length}</div><div class="l">자동 승인 후보 (≥0.9)</div></div>
    <div class="kpi"><div class="n">${Object.keys(decided).length}</div><div class="l">검수 완료</div></div>
  </div>
  <div class="card">
    <div class="filt">
      <b style="color:var(--warn)">⚠ 검수 필요 (낮은 신뢰도 먼저)</b>
      <button class="btn ok" style="margin-left:auto" onclick="bulkApprove()">≥0.9 일괄 승인 (${auto.length})</button>
    </div>
    ${pending.length? pending.map(([t,c])=>reviewItem(t,c)).join('') : '<p class="small">검수 대기 항목 없음 🎉</p>'}
  </div>`;
}

function bulkApprove(){ T.forEach(t=>t.columns.forEach(c=>{ if(c.confidence>=0.9) decided[decKey(t.name,c.name)]='approved'; })); render(); }
function decide(tn,cn,how){ decided[decKey(tn,cn)]=how; render(); }
function undo(tn,cn){ delete decided[decKey(tn,cn)]; render(); }

function pageCatalog(){
  if(route.table) return tableDetail(route.table);
  const q = (document.getElementById('q')?.value||'').toLowerCase();
  const rows = T.filter(t=>!q|| t.name.includes(q)||t.table_description.toLowerCase().includes(q))
   .map(t=>{
    const avg = t.columns.reduce((a,c)=>a+(c.confidence||0),0)/(t.columns.length||1);
    return `<tr class="clk" onclick="go('catalog','${t.name}')">
      <td><span class="mono">${t.name}</span> ${t.pk?`<span class="pill pk">PK ${t.pk}</span>`:''}</td>
      <td class="small">${t.table_description}</td>
      <td>${num(t.rowcount)}</td>
      <td><div class="bar"><i style="width:${(avg*100).toFixed(0)}%"></i></div></td>
    </tr>`;}).join('');
  return `
  <h1>Catalog</h1>
  <p class="sub">복원된 데이터 딕셔너리. 클릭하면 테이블 상세.</p>
  <div class="filt"><input id="q" placeholder="테이블/설명 검색…" oninput="render()" value="${q}"></div>
  <div class="card"><table>
    <thead><tr><th>Table</th><th>설명 (AI)</th><th>Rows</th><th>평균 신뢰도</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}

function tableDetail(name){
  const t=T.find(x=>x.name===name); if(!t) return 'not found';
  const fkrows = t.fks.map(f=>`<span class="pill fk">FK ${f.col} → ${f.ref_table}.${f.ref_col} <span class="small">(incl ${f.inclusion})</span></span>`).join(' ');
  const cols=t.columns.map(c=>`<tr>
     <td><span class="mono">${c.name}</span><div class="small">${c.type||''}${c.nullable?' · null':''}</div></td>
     <td class="desc">${c.description}</td>
     <td><span class="conf ${confClass(c.confidence)}">${confDot(c.confidence)} ${c.confidence?.toFixed(2)??'—'}</span></td>
   </tr>`).join('');
  return `
  <span class="backlink" onclick="go('catalog')">← Catalog</span>
  <h1 class="mono">${t.name}</h1>
  <p class="sub">${t.table_description}</p>
  <div class="card">
    <div style="margin-bottom:8px">
      ${t.pk?`<span class="pill pk">PK ${t.pk}</span> `:''}${fkrows}
      <span class="small" style="float:right">${num(t.rowcount)} rows · ${t.columns.length} columns</span>
    </div>
    <table><thead><tr><th>Column</th><th>설명 (AI 복원)</th><th>신뢰도</th></tr></thead>
      <tbody>${cols}</tbody></table>
  </div>
  <div class="note">💡 이 설명들은 <b>COMMENT ON</b> SQL로 export 되어 DBA 검토 후 실제 DB에 주석으로 반영할 수 있습니다.</div>`;
}

function pageScore(){
  const s=DATA.score; const dm=s.description_match; const rel=s.relations;
  return `
  <h1>Quality Report</h1>
  <p class="sub">생성한 설명을 정답지(OMOP 공식 데이터 딕셔너리)와 대조한 결과.</p>
  <div class="row">
    <div class="kpi"><div class="n good">${fmtPct(dm.column.judge_accuracy)}</div><div class="l">컬럼 설명 의미 일치 (LLM-judge, n=${dm.column.n})</div></div>
    <div class="kpi"><div class="n good">${fmtPct(dm.table.judge_accuracy)}</div><div class="l">테이블 설명 의미 일치 (n=${dm.table.n})</div></div>
    <div class="kpi"><div class="n">${fmtPct(s.coverage.column)}</div><div class="l">컬럼 커버리지</div></div>
    <div class="kpi"><div class="n">${fmtPct(s.coverage.table)}</div><div class="l">테이블 커버리지</div></div>
  </div>
  <div class="card">
    <h3 style="margin:0 0 8px">관계 복원 (보조 지표)</h3>
    <table><thead><tr><th></th><th>precision</th><th>recall</th><th>F1</th></tr></thead><tbody>
    <tr><td>Primary Key</td><td>${rel.primary_key_f1.precision}</td><td>${rel.primary_key_f1.recall}</td><td>${rel.primary_key_f1.f1}</td></tr>
    <tr><td>Foreign Key</td><td>${rel.foreign_key_f1.precision}</td><td>${rel.foreign_key_f1.recall}</td><td>${rel.foreign_key_f1.f1}</td></tr>
    </tbody></table>
    <div class="note">precision은 매우 높음(복원한 관계는 거의 다 정답). recall이 낮은 건 데모 데이터에 빈 테이블이 많아 값 기반 FK 측정이 불가능했기 때문 — 알고리즘 한계가 아니라 데이터 희소성.</div>
  </div>`;
}

function render(){
  nav();
  const v=document.getElementById('view');
  v.innerHTML = route.page==='sources'?pageSources()
    : route.page==='review'?pageReview()
    : route.page==='catalog'?pageCatalog()
    : pageScore();
}
render();
</script>
</body></html>
"""


def main():
    data = build_dataset()
    html = HTML.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    out = os.path.join(HERE, "db2doc_ui.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f">> wrote {out}")
    print(f"   open with:  open {out}")


if __name__ == "__main__":
    main()
