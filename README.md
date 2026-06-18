# db2doc — 문서 없는 DB를 자동으로 "설명"해 주는 도구

> **한 줄 요약**: 스키마 정의서·주석·ERD가 **하나도 없는** 데이터베이스를 받아서,
> **테이블/컬럼 이름과 실제 데이터만 보고** "이 테이블/컬럼이 무엇인지"를 사람이 읽을 수 있는
> 문장으로 **자동 복원**하고, 사람이 검수·수정해 **살아있는 데이터 카탈로그(메타스토어)**로 만든다.

DBA가 처음 보는 DB를 받았을 때 하는 일 — *데이터 좀 떠보고, 키·조인 관계 파악하고, "아 이 테이블은
환자 진단 기록이구나" 결론 내리는 것* — 을 자동화한다. 100% 자동이 아니라 **AI가 초안을 만들고
DBA가 검수**하는 구조다.
<img width="750" height="761" alt="KakaoTalk_Photo_2026-06-18-11-56-34 002" src="https://github.com/user-attachments/assets/e212c53c-3778-4036-a2c5-95add4f075cb" />
<img width="759" height="766" alt="KakaoTalk_Photo_2026-06-18-11-56-34 003" src="https://github.com/user-attachments/assets/6839ea70-aa82-4cb2-9532-a122d54a3ef9" />
<img width="761" height="774" alt="KakaoTalk_Photo_2026-06-18-11-56-33 001" src="https://github.com/user-attachments/assets/8405c51a-0a26-4d55-8193-2d1285415657" />

---

## 어떻게 돌아가나 (전체 흐름)

```mermaid
flowchart TD
    A["내 DB 연결<br/>(PostgreSQL / MySQL …)"] --> B["1. 프로파일링<br/>테이블·컬럼·타입 + 데이터 통계·샘플값"]
    B --> C["2. 관계 복원<br/>PK / FK 자동 발견 (데이터+이름)"]
    C --> D["3. 의미 추론 ★<br/>Claude Opus 4.8가 컬럼→테이블→DB 설명 생성"]
    D --> E["4. 자가 검증<br/>모순 탐지 · 신뢰도 보정"]
    E --> F["5. 사람 검수<br/>신뢰도 낮은 것만 DBA가 확인·수정"]
    F --> G["산출물<br/>데이터 딕셔너리 · COMMENT SQL · ERD"]
    F -. 교정 내용 축적 .-> D
```

핵심 원칙: **데이터로 확인되는 것만 자신 있게 말하고, 확인 못 한 건 솔직히 "낮은 신뢰도"로 표시**해
사람이 검수하게 한다. 그래서 틀린 설명을 그럴듯하게 우기는 일(hallucination)을 막는다.

---

## 무엇을 복원하나 — 실제 예시

문서가 0인 상태에서, `person.gender_concept_id` 컬럼 하나를 보자.

**입력 (시스템이 데이터에서 모은 단서):**
| 단서 | 값 | 의미 |
|---|---|---|
| 컬럼명 | `gender_concept_id` | "성별 + 개념 ID" |
| 고유값 비율 | 0.002 | 거의 안 변함 → **코드값(enum)** 신호 |
| 가장 흔한 값 | `8532`(511건), `8507`(489건) | 딱 2종, 반반 → 이진 범주 |
| 복원된 관계 | → `concept.concept_id` | 표준 개념 테이블을 가리키는 FK |

**출력 (AI가 생성한 설명):**
> *"성별을 나타내는 표준 개념 ID이며 concept 테이블을 참조하는 외래키. 데이터상 값은 두 종류로,
> 성별 코드로 보인다."* (신뢰도 0.9+)

→ 이름·통계·관계 세 단서를 합쳐 **"성별 코드이고 concept를 가리킨다"**까지 데이터 근거로 추론한다.
(단, "8507이 정확히 무엇인지"처럼 데이터에 매핑이 없는 부분은 단정하지 않고 검수로 넘긴다.)

---

## 단계별 상세

| 단계 | 하는 일 | 결과물 |
|---|---|---|
| **1. 프로파일링** | `information_schema`에서 테이블/컬럼/타입 + 컬럼별 통계(고유값·null·min/max·top-k 분포) + 테이블당 ≤1000행 샘플 | 구조화된 프로파일 |
| **2. 관계 복원** | PK·FK를 **데이터로** 발견: 자식 컬럼 값이 부모 키에 다 들어있으면 FK(값 포함관계). 데이터 없는 빈 테이블은 **이름 규칙**으로 보강. 선언된 키가 있으면 그대로 채택 | PK/FK + 신뢰도·근거 |
| **3. 의미 추론 ★** | Claude Opus 4.8에 단서를 주고 **컬럼→테이블→DB** 순으로 설명 생성. enum 해석·hallucination 방지·보수적 신뢰도를 지시 | db/table/column 설명 + 신뢰도 |
| **4. 자가 검증** | 설명들 간 모순 탐지(예: FK 방향 오추론), 데이터로 검증 못 한 항목은 신뢰도 강등 | 검증·보정된 설명 |
| **5. 사람 검수** | 신뢰도 **낮은 것만** 추려 DBA가 확인/수정/승인. 모든 변경은 이력(감사) 기록 | 확정된 설명 |
| **산출물** | 데이터 딕셔너리(Markdown) · `COMMENT ON` SQL(DB에 주석 반영) · CSV · Mermaid ERD | 문서 |

> 이 5단계는 **여러 DBMS**(PostgreSQL·MySQL 등)에서 동일하게 동작한다(SQLAlchemy 추상화).

---

## 검증 — "정말 맞나?"를 숫자로 증명

채점이 가능한 공개 표준 **OMOP CDM**(공식 데이터 딕셔너리가 정답지 역할)으로 측정했다.
문서·FK·주석을 모두 지운 뒤 우리 도구로 복원하고, **공식 정답지와 대조**했다.

| 지표 | 개선 전 | 개선 후 |
|---|---|---|
| 컬럼 설명 의미 일치 (LLM 심사) | 0.93 | **0.92~0.94** |
| 테이블 설명 의미 일치 | 1.00 | **1.00** |
| PK(기본키) 복원 F1 | 0.67 | **0.91** (재현율 1.0) |
| FK(외래키) 복원 F1 | 0.39 | **0.62** |
| 종합 점수(S_overall) | 0.69 | **0.84** |

→ **문서가 0인 DB에서 테이블 의미 100% / 컬럼 의미 ~94% 일치**로 복원. (대상: OMOP CDM 5.3,
합성데이터 GiBleed, 37테이블) 상세·정직한 ablation은 [`RESULTS.md`](RESULTS.md), 개선 로드맵은
[`IMPROVEMENTS.md`](IMPROVEMENTS.md) 참고.

---

## 근거 연구 / 차용 (출처 명시)

이 도구의 핵심 기법은 아래를 **참고·차용**했다.

- **논문**: *DBAutoDoc: Automated Discovery and Documentation of Undocumented Database
  Schemas via Statistical Analysis and Iterative LLM Refinement* (Nagarajan & Altman, 2026,
  arXiv:2603.23050) — 통계 분석 + LLM 반복정제로 미문서 스키마의 PK/FK·설명을 복원한다는 접근.
- **오픈소스 구현**: [`github.com/MemberJunction/MJ`](https://github.com/MemberJunction/MJ)
  의 `packages/DBAutoDoc/` (**MIT 라이선스**). 실제 프롬프트 템플릿(18개)·설계 문서·가드레일이 공개.

우리가 실제로 차용한 메커니즘(전부 출처 표기):
- **PK/FK 점수화 + 값 포함관계(inclusion dependency) + 게이트** — 관계 복원
- **프롬프트 지시**(`table-analysis.md`): enum/저카디널리티 해석, 테이블명 지어내기 금지,
  "모호하면 신뢰도 0.7 미만" 보수적 채점
- **LLM 검증 패스**(`fk-pruning-holistic.md`, `dependency-level-sanity-check.md`): FK 후보 정제,
  설명 간 모순 탐지
- **반복 정제**(`backpropagation.md`): 자식 테이블 맥락으로 부모 설명 재검토 (옵션)

> 검증 메모: 우리 코드의 가치는 인용과 무관하게 **자체 정답지(OMOP) 채점으로 입증**했고,
> 각 차용 기법은 우리 데이터로 재측정해 효과 있는 것만 채택했다(예: backpropagation은 이 데이터에선
> 효과가 없어 기본 비활성). 자세한 내용은 [`IMPROVEMENTS.md`](IMPROVEMENTS.md).

---

## 두 가지 사용 형태

1. **파이프라인(PoC)** — `profile/ recover/ document/ render/ eval/` 스크립트로 한 DB를 한 번에 처리.
   채점·실험용. 빠른 시작:
   ```bash
   cp .env.example .env        # DB 접속·AWS 설정 채우기
   pip install -r requirements.txt
   # 이후 SETUP.md 절차: RDS 생성 → 적재 → 파이프라인 실행
   ```
2. **메타스토어 제품** — `db2doc/` 패키지. 여러 DB를 등록·스캔·추론·검수하고 **MySQL에 영구 저장**,
   웹 UI 제공. 실행법은 [`db2doc/README.md`](db2doc/README.md).

## 환경
- 대상 DB: **PostgreSQL / MySQL 등** (SQLAlchemy 추상화). PoC 검증은 AWS RDS PostgreSQL 16.
- LLM: **AWS Bedrock — Claude Opus 4.8** (`us.anthropic.claude-opus-4-8`). 자격증명은 AWS로 통일.
- 메타스토어: MySQL. 셋업은 [`SETUP.md`](SETUP.md).

## 최종 목표 (로드맵)
이 저장소는 **1단계: 의미 문서 복원이 가능한가를 증명**하는 데 집중한다. 이후:
복원한 메타구조 → **온톨로지(Property Graph) + Amazon Neptune** → **text2sql / 스키마 검수 /
SQL 튜닝**을 돕는 DBA 에이전트로 확장한다. (text2sql은 차용한 논문/저장소에도 query 템플릿으로 존재.)
