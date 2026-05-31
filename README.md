# db2doc — 스키마 메타데이터 기반 자동 "의미 문서(description)" 복원

문서(스키마 정의서·주석·ERD)가 **전혀 없는** 데이터베이스에서, **스키마(테이블/컬럼명·타입)와
샘플 튜플만으로** 각 DB / 테이블 / 컬럼이 무엇인지 **자연어 설명(description)을 자동 복원**하고,
그 정확도를 **정답지와 대조해 정량 채점**하는 PoC.

> 최종 목표(후속 단계)는 복원한 메타구조를 온톨로지(Property Graph) + Amazon Neptune으로 올려
> text2sql / 스키마 검수 / SQL 튜닝을 돕는 DBA agent를 만드는 것. 이 저장소는 그 **1단계 = 의미 문서
> 복원이 실제로 가능한가를 정답지로 증명**하는 데 집중한다.

## 왜 OMOP CDM인가

OMOP CDM은 공식 **데이터 딕셔너리(`Field_Level.csv`)** 가 컬럼 설명(`userGuidance`)과
PK/FK 관계를 모두 기계 판독 가능한 형태로 제공한다 → **우리가 생성한 설명을 채점할 정답지**로 이상적.
합성 데이터(Eunomia/GiBleed)라 개인정보 이슈도 없다. 버전은 **5.3**으로 통일
(GiBleed 데모 데이터가 5.3 → DDL·정답지도 5.3으로 맞춰 ETL 불필요).

## 파이프라인

```
RDS 적재(OMOP+GiBleed) → 문서제거(strip_docs) → 프로파일링(profile)
   → (보조)관계복원(recover) → ★description 생성(document, Opus 4.8)
   → 렌더(render) → 채점(eval: 정답지 대조)
```

| 단계 | 디렉터리 | 산출 |
|---|---|---|
| 0. 환경 | `infra/` | RDS 생성·적재 (→ `SETUP.md`) |
| 1. 문서 제거 | `prepare/` | FK·comment 제거된 "문서 없는 DB" |
| 2. 프로파일 | `profile/` | `out/profile.json` |
| 3. 관계 복원(보조) | `recover/` | `out/relations.json` |
| 4. ★description 생성 | `document/` | `out/descriptions.json` |
| 5. 렌더 | `render/` | Markdown / SQL COMMENT / CSV / Mermaid |
| 6. 채점 | `eval/` | description 의미 일치도 + PK/FK F1 |

## DB / 테이블 / 컬럼의 의미를 추론하는 방식

문서가 없으므로 **물리 스키마 + 실제 데이터에서 단서를 모아 LLM에 넘기고, LLM이 의미를 추론**한다.
규칙·통계가 객관적 단서를 만들고, LLM이 그 단서로 자연어 설명을 쓴다. 단계는 작은 단위→큰 단위
(컬럼 → 테이블 → DB)로 올라간다.

### 1) 컬럼에서 모으는 단서 (프로파일러 + 관계복원이 생성)
LLM에게 주는 컬럼당 입력은 다음으로 구성된다 (코드: `db2doc/pipeline/describe.py:compact_columns`,
통계 출처: `db2doc/targets/stats.py`):
- **이름·타입·nullable** — `gender_concept_id` / `integer` / `not null`
- **카디널리티** — `distinct_ratio`(고유값 비율). 1.0이면 식별자 후보, 0.002처럼 낮으면 코드값(enum) 신호
- **null 비율** — `null_ratio`
- **값 범위** — `min` / `max`
- **실제 분포 샘플** — `top_values`(가장 흔한 값 top-k와 빈도), `examples`
- **복원된 관계** — 이 컬럼이 어느 테이블을 가리키는 FK인지 (`recovered_relations`)

관계(FK)는 선언이 없어도 **값 포함관계(inclusion dependency)** 로 복원한다: 자식 컬럼의 샘플 값이
부모 후보 컬럼(주로 PK)에 모두 포함되면 FK로 본다(`db2doc/pipeline/relations.py`). 이름 유사도·
카디널리티와 가중합해 점수화하고 게이트로 거른다. PK는 카디널리티·이름패턴·타입·위치로 점수화한다.

### 2) LLM에 넘기는 방식 (테이블 1개 = 호출 1회)
`db2doc/pipeline/describe.py`가 두 메시지를 AWS Bedrock으로 보낸다:
- **system**: "문서 없는 DB를, 물리 스키마·통계·샘플값만 보고 의미를 추론하라. **데이터가 뒷받침하지
  않는 사실은 지어내지 말 것.**"
- **user**: 테이블 1개를 JSON으로 — `table_name`, `row_count`, `recovered_relations`(PK/FK),
  그리고 위 컬럼 단서 배열. (예: `{"name":"gender_concept_id","type":"integer",
  "distinct_ratio":0.002,"top_values":[...],"examples":["8532","8507"]}`)

출력은 **JSON 스키마를 강제**(tool use)해 항상 `{table_description, columns:[{name, description,
confidence}]}` 형태로 받는다. 각 설명에는 **LLM이 매긴 confidence(0~1)** 가 붙는다.

### 3) 테이블 → DB로 합성
- 테이블은 **FK 의존 순서**(부모 먼저)로 처리하고, 이미 만든 이웃 테이블 설명을 다음 테이블
  프롬프트에 컨텍스트로 넣는다 (`fk_order`, `neighbour_table_descriptions`).
- 모든 테이블 설명이 모이면 그것들을 묶어 **DB 전체 설명**을 한 번 더 생성한다(`synthesize_db`).

### 추론의 한계 = confidence와 검수
이 방식이 확실히 알 수 있는 것은 **데이터에 드러나는 구조적 사실**이다: 카디널리티로 "식별자냐
코드값이냐", inclusion으로 "무엇을 가리키는 FK냐", 분포로 "이진/소수 범주냐". 반면 **코드값의 구체적
의미(예: 어떤 코드가 무엇을 뜻하는지)** 는 데이터에 그 매핑이 함께 들어있지 않으면 확정할 수 없다.
그런 항목은 confidence가 낮게 나오고, 제품에서는 **Review Queue로 올라가 사람(DBA)이 확정**한다
(메타스토어 제품: `db2doc/`). 즉 자동 추론은 **초안**이고, 최종 의미는 근거(통계·관계)를 보고
사람이 검수해 확정하는 구조다.

## 환경

- DB: **AWS RDS PostgreSQL 16** (로컬 docker 없음). 셋업 절차는 [`SETUP.md`](SETUP.md).
- LLM: **AWS Bedrock — Claude Opus 4.8** (`us.anthropic.claude-opus-4-8`). 자격증명은 AWS로 통일.

## 빠른 시작

```bash
cp .env.example .env        # 값 채우기
pip install -r requirements.txt
# 이후 SETUP.md 절차에 따라 RDS 생성 → 적재 → 파이프라인 실행
```

근거 연구: DBAutoDoc (arXiv 2603.23050, Nagarajan & Altman, 2026) — 통계 + LLM 반복정제로
미문서 스키마의 PK/FK·설명을 복원. 본 PoC는 그 방식을 차용해 **description 복원**에 초점을 둔다.
