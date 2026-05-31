# 정확도 향상 방안 (DBAutoDoc 논문 대조) — 전 영역

논문 *DBAutoDoc* (arXiv:2603.23050, Nagarajan & Altman, 2026) **및 그 오픈소스 구현**
(`github.com/MemberJunction/MJ`, `packages/DBAutoDoc/`, **MIT**)을 우리 구현과 대조해 도출.
FK뿐 아니라 **PK · 테이블/컬럼/DB description · confidence 신뢰성 · 평가 · 운영**까지 포함하며,
저장소에서 차용 가능한 전체 메커니즘은 **G절** 참조.

우리 PoC 실측(`out/score.json`, `score_details.json` 기준):
- FK: precision 0.951 / **recall 0.248** / F1 0.394 (정답 157개 중 39개)
- PK: precision 0.875 / **recall 0.538** (정답 26개 중 14개; **미검출 12개 전부 빈 테이블**)
- column description judge 94% (불일치 19개 중 6개가 빈 테이블)
- **공통 근본원인: GiBleed 데모의 빈 테이블 19개** → 통계 기반 추론(PK/FK)이 작동 불가.
- **추가로 발견된 문제: 빈 테이블 컬럼도 confidence 0.917로 높음** → 검증 불가인데 과신(아래 C절).

## A. 관계 복원 — FK (가장 큰 격차)

현재 구현: `recover/keys.py`, `db2doc/pipeline/relations.py`. FK 점수
`40·v + 20·s + 15·r + 15·k + 10·ν` (논문 가중치와 동일). 게이트 4개만 부분 구현(G1 이름신호,
G2 값포함<0.5 컷, G3 점수<60 컷, G4 자식당 best 1개). **단일 패스, 관계 복원에 LLM 미사용.**

### A1. 통계↔LLM **양방향** FK 검증 (논문 핵심, +23 F1의 출처)
논문: "deterministic gates가 precision을, **LLM이 referential relationship에 대한 의미추론으로
recall을** 담당." 통계만=30% F1, LLM만=71.7%, **둘 합치면 94.2%**.
우리: 관계 복원이 **순수 통계**라 통계가 못 잡는 FK(이름이 안 닮았거나 빈 테이블)를 통째로 놓침
→ recall 0.248의 직접 원인.
**개선**: FK 후보 단계에서 LLM에게 "이 컬럼이 어느 테이블을 참조하는가?"를 물어 후보를 **추가 생성**하고,
통계(값포함)로 **검증**하는 bidirectional 루프 추가. (`relations.py`에 LLM 후보 생성 훅)

### A2. 빈 테이블 / 값으로 못 보는 FK → 이름·타입 기반 후보 보강
우리: GiBleed 19개 테이블 0행 → inclusion 측정 불가 → FK 누락(fn 118 중 다수).
**개선**: 데이터 없거나 inclusion 0이어도 **이름 규칙**(`<parent>_id` → `<parent>`)으로
**저-confidence FK 후보** 제시("데이터 미검증" 플래그). recall↑, precision은 confidence로 방어 →
Review Queue로.

### A3. 결정론적 게이트 G1–G8 완전 구현
논문 게이트: 대상 PK-eligibility 검증, **rowguid 제외**, **row-count 비율 신뢰도 조정**,
**fan-out top-3 제한**, 75% 값포함 임계 — "FP의 ~75% 제거하면서 정답 FK 손실 0."
우리는 4개만. **개선**: 나머지(특히 fan-out 제한, row-count 비율) 추가 → precision 유지하며 임계 완화.

## B. 관계 복원 — PK (FK에 가려졌던 영역)
실측: PK recall 0.538, **미검출 12개가 전부 빈 테이블**(`<table>_id`의 distinct_ratio=None).
즉 PK도 FK와 같은 "빈 테이블이면 통계로 못 본다"가 원인.

### B1. 빈 테이블 PK도 이름·타입으로 보강
`<table>_id`가 정수·position 앞쪽이면 데이터가 없어도 **PK 후보**로 제시(저-confidence).
빈 테이블 12개 PK가 여기서 회복됨. (A2의 PK 버전)

### B2. 복합 PK(composite key) 지원
현재 `detect_pks`는 테이블당 **단일 컬럼 1개**만 고른다. OMOP엔 없지만(복합PK 0개) 일반 DB·연결
테이블(junction)·이력 테이블엔 흔함. **개선**: 단일로 unique가 안 되면 2~3개 컬럼 조합의
distinct=rowcount를 검사해 복합 PK 후보 생성.

### B3. 선언된 PK 활용
Inspector의 `get_pk_constraint`로 **DB에 선언된 PK가 있으면 그대로 채택**(복원보다 정답).
현재는 strip 실험 탓에 안 쓰지만, 실고객 DB는 PK가 살아있는 경우가 많음 → 무료 정확도.

## C. 설명(description) 품질 + confidence 신뢰성
### C1. 반복 정제(iterative refinement) — 논문의 backprop식 역전파
논문: 위상정렬 leaf부터 → **자식 인사이트를 부모로 역전파** → 재분석, 최대 3회,
수렴(변화없음 w=2 / 모든 confidence≥τ=0.6 / 의미비교 중 2개). 우리는 FK순서+이웃컨텍스트까지만(1패스).
**개선**: child→parent 역전파 + 2~3회 수렴 추가 → 부모 테이블 설명이 자식 맥락으로 교정.

### C2. confidence 보정 (calibration) — **새로 발견한 문제**
실측: **빈 테이블 컬럼도 평균 confidence 0.917**(데이터 테이블 0.931과 거의 동일).
데이터로 검증 못 했는데 모델이 과신 → Review Queue triage(저신뢰만 사람에게)가 무력화됨.
**개선**: confidence를 **증거 가용성으로 패널티**. rowcount=0 / inclusion 미측정 / top_values 부재면
confidence를 강등(예: ×0.5). "데이터 미검증" 항목이 자동으로 검수 큐에 오르게.

### C3. 코드값 의미 보강 — 도메인 사전/매핑 테이블 활용
코드값(예: `*_concept_id`)의 구체 의미는 데이터에 매핑이 없으면 확정 불가(README의 한계).
**개선**: ① 같은 DB 안의 **lookup/매핑 테이블**(예: OMOP `concept`)을 조인해 코드→레이블 실제값을
프롬프트에 주입 → 데이터 근거로 의미 확정. ② 고객 제공 용어집(glossary)을 시드 컨텍스트로.

### C4. 다단계 프롬프트 파이프라인 — 논문의 "13개 템플릿"
논문: "The prompt layer comprises **thirteen Nunjucks templates** (see Appendix D)." 단,
Table 9에는 **12개**만 나열됨(본문 13 ↔ 표 12 불일치 — 논문 자체의 오타/누락 가능성).
의미: 설명 생성을 **거대 단일 프롬프트가 아니라 역할별로 분리**한 다단계 파이프라인.

Table 9의 12개 (verbatim) — 4역할로 묶임:
- **생성**: `table-analysis`(테이블/컬럼 설명 + FK 제안)
- **전파**: `backpropagation`(자식 인사이트로 부모 설명 교정)
- **관계 정제**: `fk-pruning`, `pk-pruning`
- **자기검증(loss)**: `dep-level-sanity`, `schema-sanity`, `cross-schema-sanity`
- **수렴 판정**: `semantic-comparison`(실질변화 vs 표현변화 구분)
- **text2sql**: `query-planning`, `query-generation`, `query-fix`, `query-refinement` (→ F절)

우리 현재: **2개**(table 설명, db 설명)뿐. description 품질에 직결되는 것은
backpropagation(C1) + sanity 3종(아래). **개선**: 최소 `backpropagation` + `dep-level-sanity`
2개를 추가해 "생성→자기검증→재생성" 루프를 만든다.

### C5. sanity-check를 "loss signal"로 — 자기검증 루프 (hallucination 방어)
논문: 6개 구조 규칙을 dep-level/schema/cross-schema 3단계로 적용, 위반을 **"loss signal"**로 보고
해당 테이블을 **재분석 큐**에 넣음. (단 논문은 6규칙을 명시 열거하지 않음 — "PK/FK 정규화 원칙 강제"
수준만 기술.) 우리에겐 **자기검증이 전혀 없음**.
**개선**: 우리 데이터로 검증 가능한 규칙부터 구현 — 예: ①FK가 가리키는 부모 설명과 자식 컬럼 설명이
모순되지 않는가, ②PK라면서 설명이 "식별자"가 아닌가, ③같은 이름 컬럼이 테이블마다 상충 설명인가.
위반 시 confidence 강등 + 재생성. (논문이 6규칙을 안 밝혔으므로 **여기는 우리가 설계해야 하는 영역**.)

## D. 평가(eval) 보강
### D1. confidence≥0.5 커버리지로 채점 기준 통일
논문 `S_overall = 0.35·F1_FK + 0.30·F1_PK + 0.20·C_table + 0.15·C_col`,
커버리지 = "confidence≥0.5인 비어있지 않은 설명 비율". 우리 식은 같으나 커버리지 정의가 다름 →
**통일**해 논문과 직접 비교.
### D2. 데이터 충분/희소 분리 리포트
빈 테이블이 모든 지표를 끌어내림. **데이터 있는 테이블만의 F1**을 별도 산출해 "알고리즘 자체 성능"과
"데이터 희소 영향"을 분리 보고.

## E. 운영(production) 보강 — PoC→고객
- **E1. 다중 컬럼 통계 단축**: 통계 3쿼리/컬럼 → 1쿼리로 합쳐 RDS 왕복 감소(현재 스캔 ~9분).
- **E2. 증분 재스캔(drift)**: 스키마 변경분만 재프로파일·재추론(전체 재실행 회피).
- **E3. PII 마스킹**: top_values/examples를 LLM에 보내기 전 민감 컬럼은 형태/통계만(고객 보안 요건).
- **E4. 승인 학습 루프**: 사람이 교정한 설명을 유사 컬럼 재추론의 few-shot으로 → 갈수록 정확.

## F. text2sql — 논문에도 있는 후속 단계 (Table 9의 query 템플릿 4종)
논문 Table 9에 `query-planning` / `query-generation` / `query-fix` / `query-refinement`가 있음 →
**논문 범위가 문서화를 넘어 자연어→SQL까지** 포함. 우리가 원래 후속으로 미뤄둔 기능과 정확히 일치.
의미하는 4단계: 질문→**계획**(어느 테이블·조인경로)→**SQL 생성**→실행 오류 시 **수정**→**개선**(반복).
**개선/연계**: 우리가 복원한 메타스토어(테이블/컬럼 설명 + PK/FK 조인경로)가 그대로 text2sql의
컨텍스트가 됨. 즉 description 품질↑ = text2sql 정확도↑. (원 계획의 Property Graph/Neptune + text2sql
단계로 자연 확장.)

## G. 차용 가능한 전체 메커니즘 (출처: MemberJunction/MJ, **MIT 라이선스**)

DBAutoDoc은 실재하는 오픈소스다 — `github.com/MemberJunction/MJ`, `packages/DBAutoDoc/`.
**라이선스 MIT** → 코드·프롬프트를 합법적으로 차용 가능(출처 표기 권장). SQL Server/PostgreSQL/MySQL
지원으로 우리 다중 DBMS 방향과 일치. 저장소에는 **프롬프트 18개 전문 + 설계문서 + 가드레일 문서 +
run-analysis**가 공개돼 있다. 앞 A~F가 이 중 일부였고, 아래는 **저장소 ARCHITECTURE.md/GUARDRAILS.md/
README.md에서 확인한 전체 메커니즘**이다(★ = 앞 절에 없던 것).

출처 파일:
- `packages/DBAutoDoc/docs/ARCHITECTURE.md` (메커니즘 68종)
- `packages/DBAutoDoc/docs/GUARDRAILS*.md` (자원 가드레일 16종)
- `packages/DBAutoDoc/prompts/*.md` (실제 프롬프트 18개: table-analysis, backpropagation,
  fk-evaluation, fk-pruning-{holistic,table}, pk-pruning-{holistic,table}, convergence-check,
  semantic-comparison, {dependency-level,schema,cross-schema}-sanity-check, query-{planning,fix,
  refinement}, single-query-generation 등)
- `packages/DBAutoDoc/plans/completed/{deterministic-fk-gates,enum-detection,entity-naming-normalization}.md`

### G-a. PK/FK (앞 A·B 보강)
- ★**PK 위치 휴리스틱 H9–H12** (컬럼 순서·이름패턴으로 PK 우선순위)
- ★**복합키 탐지** (단일로 unique 안 되면 다컬럼 조합 검사) — 우리 B2와 동일, 저장소에 구현 존재
- ★**fan-out confidence 패널티** (한 키가 너무 많은 테이블을 참조하면 신뢰도↓)
- ★**2-pass LLM pruning** (1패스 통계 후보 → 2패스 LLM 검증) + **0.8 초과 후보만 LLM에 올림**
  → 정확도↑와 LLM 비용↓ 동시 달성. (우리 A1의 구체적 형태)
- ★**FK를 table 관점 + holistic 관점 2가지로** 평가 (`fk-pruning-table` vs `-holistic`)

### G-b. 설명 정제·수렴 (앞 C 보강)
- ★**backpropagation 엔진 + 20% 변화 임계 트리거 + 깊이 제한** (역전파를 언제/얼마나 깊이 할지 정량화)
- ★**수렴 탐지 세트**: stability window, material-change 정량화, iteration capping, 최소 iteration 보장
- ★**semantic-comparison**: 새 설명이 실질변화인지 표현변화인지 LLM으로 판정(수렴 신호)

### G-c. 품질·검증 (앞 C5 보강)
- ★**제약 만족 검증**: 설명이 탐지된 PK/FK 제약과 모순 없는지
- ★**완전성 검증**: 모든 테이블·컬럼·관계가 문서화됐는지

### G-d. confidence (앞 C2 보강)
- PK 임계 0.7 / FK 0.6 (우리와 동일), ★**LLM 검증 escalation 임계 0.8**,
  ★**통계+의미 confidence 합성**(compound) — 우리 "과신" 문제를 합성식으로 완화.

### G-e. ★자원 가드레일 (우리에게 전무 — 제품화 필수)
run/phase/iteration별 **토큰·비용·시간 하드리밋** + 80% 경고 임계 + 프롬프트별 token truncation +
초과 시 즉시 중단 + 감사기록(`guardrailsEnforced`). 스캔/추론 전에 **예상 비용**을 보여주고 폭주를 막음.

### G-f. ★상태·재개 (우리에게 전무)
**phase별 상태 체크포인트 저장 → 중단 후 재개**, iteration 히스토리 보존. 수백 DB 대량 처리 시 필수.

### G-g. ★Ground Truth System (우리 ai_text/current_text와 같은 개념, 더 정교)
사람이 확정한 설명을 **덮어쓰기 금지 앵커**로 두고 이후 추론의 불변 컨텍스트로 사용
→ 우리 메타스토어의 `current_text`(승인본)를 재추론 프롬프트에 앵커로 주입(C·E4와 연결).

### G-h. ★enum 탐지 + 명명 정규화 (설계문서로 공개)
- **enum-detection**: low-cardinality 컬럼을 enum 후보로 보고 top_values로 의미 해석(코드값 의미, C3 보강)
- **entity-naming-normalization**: 컬럼 설명을 "비즈니스 중심 간결형"으로 재작성 + 자동 concept 태깅

> 주의: 위 메커니즘 목록은 저장소 docs(ARCHITECTURE/GUARDRAILS/README)를 WebFetch로 읽어 정리.
> 실제 코드 동작은 차용 구현 시 해당 소스를 직접 보고 확인한다. MIT라 차용은 자유이나 **출처 표기**.

## 우선순위 (효과/비용)
0. **(신규) 자원 가드레일 + phase 재개** (G-e/G-f) — 정확도 아닌 **제품화 필수**. 비용 폭주·중단복구 대비.
1. **빈 테이블 PK/FK 이름 기반 보강** (A2+B1) — 가장 싸고 recall에 즉효. 미검출의 직접 원인 해결.
2. **선언된 PK/FK 활용** (B3) — 실고객 DB에서 거의 무료 정확도.
3. **confidence 보정 + 통계·의미 합성** (C2/G-d) — 싸고, 검수 triage 신뢰성 회복(제품 핵심).
4. **2-pass LLM pruning(0.8 escalation)** (A1/G-a) — 정확도↑ + LLM 비용↓ 동시. 양방향 FK의 구체형.
5. **fan-out 패널티 + 복합키 + 위치휴리스틱** (G-a/B2) — PK/FK 정확도.
6. **sanity-check 자기검증 + 제약/완전성 검증** (C5/G-c) — hallucination·누락 방어.
7. **반복정제 backprop(20% 임계·깊이제한) + 수렴세트** (C1/G-b) — 설명 품질. 비용 큼.
8. **Ground Truth 앵커 + enum/명명정규화 + 코드값 매핑** (G-g/G-h/C3) — 설명 품질·고객 적합성.
9. **평가 통일/분리** (D), **운영(증분·마스킹·학습루프)** (E) — 병행.
10. **text2sql** (F/K) — 별도 단계(원 로드맵 후속). description 품질이 선행 조건.

## 검증 방법
- 데이터 **꽉 찬** 대상 DB로 재측정해 빈 테이블 영향(A2/B1) 분리 확인.
- ablation: baseline → +이름보강 → +선언PK → +게이트 → +양방향LLM 순으로 PK/FK F1 추적.
- 논문 ablation(통계 30% / LLM 71.7% / 풀 94.2%)을 우리 데이터로 재현 대조.
- confidence 보정(C2) 후 "빈 테이블 컬럼 평균 confidence"가 실제로 내려가는지 확인.

## 주의 (정직성)
- **DBAutoDoc은 실재 오픈소스로 확인됨**: `github.com/MemberJunction/MJ`의 `packages/DBAutoDoc/`,
  **MIT 라이선스**, 프롬프트 18개·설계문서·가드레일 공개. (앞서 "arXiv ID 최신이라 환각 우려"라 했던
  것은 저장소 실재 확인으로 **해소**.) 단 논문 본문 ↔ 코드의 세부 차이는 차용 시 소스로 대조.
- **템플릿 개수**: 논문 본문 "thirteen templates" ↔ 논문 Table 9 12개 ↔ 실제 저장소 prompts/ **18개**.
  C4 목록은 논문 Table 9 기준, G절은 저장소 실제 파일 기준.
- 메커니즘 목록(G)은 저장소 docs를 **WebFetch로** 읽어 정리 — 실제 코드 동작은 차용 구현 시 직접 확인.
- 차용은 MIT라 자유이나 **출처 표기**(MemberJunction/MJ, MIT)를 README/코드에 남긴다.
- 우리 구현 가치는 차용과 무관하게 **자체 정답지(OMOP) 채점으로 입증**됨. 각 개선은 채택 시
  우리 데이터로 재측정해 효과를 확인한다.
