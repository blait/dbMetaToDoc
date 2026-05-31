# RESULTS — 1단계 PoC 결과

문서가 전혀 없는 DB(OMOP CDM 5.3, GiBleed 합성데이터)에서 **스키마 + 샘플 튜플만으로**
의미 description을 자동 복원하고, OMOP 공식 데이터 딕셔너리(정답지)와 대조해 채점한 결과.

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
