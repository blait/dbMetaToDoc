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
