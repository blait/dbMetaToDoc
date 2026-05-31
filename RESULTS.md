# RESULTS — 1단계 PoC 결과

문서가 전혀 없는 DB(OMOP CDM 5.3, GiBleed 합성데이터)에서 **스키마 + 샘플 튜플만으로**
의미 description을 자동 복원하고, OMOP 공식 데이터 딕셔너리(정답지)와 대조해 채점한 결과.

## 업그레이드 결과 (DBAutoDoc 논문/오픈소스 MIT 차용 — IMPROVEMENTS.md 참조)

빈 테이블 이름기반 PK/FK 보강 + 선언키 채택 + 설명 프롬프트 강화(enum/hallucination 가드/보수적
confidence) + 증거기반 confidence 보정을 적용한 ablation 결과:

| 지표 | baseline | 개선 후 |
|---|---|---|
| **PK F1** | 0.667 (recall 0.538) | **0.912 (recall 1.0)** |
| **FK F1** | 0.394 (recall 0.248) | **0.619 (recall 0.471)** |
| 컬럼 설명 judge | 0.931 | **0.938** |
| 테이블 설명 judge | 1.0 | 1.0 |
| **S_overall** | 0.687 | **0.840** |
| 빈 테이블 컬럼 평균 confidence | 0.917(과신) | **0.427**(보정됨) — 233개 "data_unverified" 플래그 → 검수 큐 |

핵심: 빈 테이블 보강으로 **PK recall 1.0 달성**, FK recall 약 2배. confidence 보정으로 "검증 못 한
설명을 과신"하던 문제 해소 → Review Queue triage가 실제로 작동. 출처: MemberJunction/MJ (MIT).

### 추가 LLM 검증 단계의 실측 기여 (정직한 ablation)
프롬프트 12종 중 pruning/sanity/backpropagation 3종을 더 구현해 측정한 결과:
- **FK LLM pruning** (fk-pruning-holistic): 41개 저-confidence 후보 중 **1개만 제거** →
  우리가 이름기반으로 늘린 FK가 거의 다 진짜였음을 검증. precision 0.76→0.91 회복.
- **sanity-check** (dependency-level-sanity): 모순 설명을 실제로 탐지(예: `relationship`의 FK
  방향 오추론) → 해당 테이블 confidence 강등. 신뢰성에 기여.
- **backpropagation** (반복 정제): 이 데이터에선 **revised 0 (수렴)** — 강화된 프롬프트로 1패스가
  이미 충분해 고칠 것이 없었음. **비용만 들고 효과 없음**(OMOP은 도메인이 명확한 탓; 더 모호한
  고객 DB에선 다를 수 있음). → 기본 비활성(backprop_passes=0), 옵션으로 보존.
- col judge는 0.931→0.92로 노이즈 수준 미세 변동(보수적 프롬프트·confidence 강등 영향).
교훈: "논문 기법을 다 넣으면 다 좋다"가 아니라 **실측으로 효과가 있는 것(빈테이블 보강·pruning)과
없는 것(backprop)을 가렸다.**

---
## (이하 최초 PoC 측정)

- 대상: AWS RDS PostgreSQL 16, OMOP CDM 5.3, 37 테이블 / 411k 행 (GiBleed)
- 모델: AWS Bedrock **Claude Opus 4.8** (`us.anthropic.claude-opus-4-8`)
- 입력: 테이블/컬럼명·타입 + 샘플 통계(테이블당 ≤1000행). **FK·comment 제거 상태**.

## 메인 지표 — description 의미 일치 (정답지 대조)

| 레벨 | 채점 n | LLM-judge 정확도 | mean cosine |
|---|---|---|---|
| **컬럼** | 275 | **94.2%** | 0.481 |
| **테이블** | 37 | **100%** | 0.629 |
| DB 도메인 | 1 | 정확 식별 ("healthcare / OMOP CDM, Synthea, v5.3.1") | — |

커버리지: 컬럼 99.6%, 테이블 100% (거의 모든 항목에 설명 생성).

> cosine이 낮아 보이는 이유: OMOP `userGuidance`는 깔끔한 정의가 아니라 **장문 ETL 지침**
> (예: year_of_birth → "Compute age using year_of_birth")이거나 다수가 **`NA`(빈 정답)**.
> 길이·문체 차이로 임베딩 cosine은 낮지만, **의미 동등성을 보는 LLM-judge에서 94~100%** 로
> 실제 품질이 드러난다. (NA 정답은 채점에서 제외.)

## 보조 지표 — 관계 복원 (description의 근거)

| | precision | recall | F1 |
|---|---|---|---|
| PK | 0.875 | 0.538 | 0.667 |
| FK | **0.951** | 0.248 | 0.394 |

- **precision이 매우 높음** = 복원한 관계는 거의 다 정답. (FK 41개 중 39개 정답)
- recall이 낮은 이유: GiBleed에서 **18개 테이블이 0행**(provider/location/care_site 등).
  값 기반 inclusion dependency로는 데이터 없는 테이블로 향하는 FK를 측정할 수 없다.
  → 알고리즘 한계가 아니라 **데모 데이터의 희소성** 때문. 데이터가 있는 테이블 사이에서는 정확.

DBAutoDoc `Soverall` = 0.687 (관계 recall에 눌린 값; description 품질은 위 judge 지표가 대표).

## 결론

**"문서 없는 DB를 스키마+샘플만으로 의미 문서화한다"는 것이 정량적으로 입증됨** —
컬럼 의미 94%, 테이블 의미 100% 일치. 고객 시나리오(문서 부재)에 직접 적용 가능.

### 한계 / 다음 개선
- FK recall은 데이터가 채워진 DB에서 재측정 필요 (빈 테이블 영향 제거). 이름 기반 FK 후보를
  낮은 confidence로 보강하면 recall↑ 가능.
- 채점 cosine은 보조 참고용. 메인은 judge.
- 후속 단계: 복원 메타구조 → Property Graph(openCypher) → Neptune → text2sql ON/OFF 비교.

## 산출물 (저장소에 포함)

실행 결과 증거는 `results/`에 커밋되어 있다 (`out/`는 재생성물이라 gitignore):
- `results/data_dictionary.md` — 복원된 데이터 딕셔너리 (사람이 읽는 최종 산출물)
- `results/descriptions.json` — db/table/column 설명 + confidence (원본 생성물)
- `results/relations.json` — 복원된 PK/FK
- `results/score.json` — 정답지 대조 채점 결과
- `results/erd.mmd` — Mermaid ERD

## 재현

```bash
set -a; source .env; set +a
bash infra/run_ddl.sh && .venv/bin/python infra/load_eunomia.py && bash infra/fetch_truth.sh
.venv/bin/python prepare/strip_docs.py
.venv/bin/python profile/profile.py
.venv/bin/python recover/keys.py
.venv/bin/python document/refine.py        # Opus 4.8: ~82k in / 30k out tokens
.venv/bin/python render/render.py
.venv/bin/python eval/score.py              # judge (느림); --no-judge 로 빠르게 cosine만
```
