# SETUP — AWS RDS PostgreSQL + Bedrock + OMOP 적재 (step-by-step)

이 문서는 환경 구성을 **재현 가능하게** 기록한다. 막힌 부분/해결도 그대로 남긴다.
값은 `.env`(gitignore)로 관리하며, 예시는 `.env.example` 참고.

대상 버전: **OMOP CDM 5.3** (GiBleed 데모 데이터가 5.3 → DDL·정답지도 5.3으로 통일).

---

## 0. 사전 점검 (완료 ✅)

로컬 도구 / 클라우드 접근을 먼저 확인했다.

| 항목 | 확인 결과 |
|---|---|
| aws cli | `aws-cli/2.34.47`, region `us-east-1` |
| AWS 자격증명 | account `986930576673`, user `hyeonsup` (`aws sts get-caller-identity`) |
| Bedrock Opus 4.8 | `us.anthropic.claude-opus-4-8` (inference profile) **ACTIVE**, invoke 스모크 테스트 통과 |
| psql / python / boto3 / sqlite3 | psql 14.17, python 3.13, boto3 1.40, sqlite3 3.51 |
| OMOP 5.3 DDL | `inst/ddl/5.3/postgresql/*.sql` 4종(ddl/pk/constraints/indices) 확인 |
| 정답지 5.3 | `OMOP_CDMv5.3_Field_Level.csv` / `Table_Level.csv` (HTTP 200, `userGuidance` 포함) |
| GiBleed 데이터 | `EunomiaDatasets/datasets/GiBleed/GiBleed_5.3.zip` — 전 테이블 CSV(실데이터) |

### Bedrock 호출 시 주의 (실측)
- base model `anthropic.claude-opus-4-8` 는 **on-demand 호출 불가** → **inference profile**
  `us.anthropic.claude-opus-4-8` 사용.
- Opus 4.8 은 **`temperature` 파라미터 미지원** (`ValidationException: temperature is deprecated`)
  → 요청 body에서 temperature 제거. (`common.invoke_claude`가 처리)

스모크 테스트:
```bash
python3 - <<'PY'
import boto3, json
br = boto3.client("bedrock-runtime", region_name="us-east-1")
body = {"anthropic_version":"bedrock-2023-05-31","max_tokens":32,
        "messages":[{"role":"user","content":"Reply with exactly: OPUS48_OK"}]}
r = br.invoke_model(modelId="us.anthropic.claude-opus-4-8", body=json.dumps(body))
print(json.loads(r["body"].read())["content"][0]["text"])
PY
# -> OPUS48_OK
```

---

## 1. 의존성 설치

```bash
cd /Users/hyeonsup/db2doc
cp .env.example .env          # 값 채우기 (RDS는 2단계 이후 채움)
python3 -m pip install -r requirements.txt
```

---

## 2. RDS PostgreSQL 생성  _(infra/create_rds.sh — 작성 예정)_

> TODO: aws cli로 RDS 인스턴스 생성, 보안그룹 인바운드(5432, 내 IP) 설정, 엔드포인트 확보.
> 진행하며 실제 명령/출력 기록.

---

## 3. OMOP 스키마 적재  _(infra/run_ddl.sh — 작성 예정)_

> TODO: 5.3 DDL을 `ddl → primary_keys → indices` 순서로 적재(**constraints 제외** = FK 없는
> "문서 없는" 상태). 정답지 채점용으로 constraints/Field_Level.csv는 `truth/`에 보관.

---

## 4. GiBleed 데이터 적재  _(infra/load_eunomia.py — 작성 예정)_

> TODO: GiBleed_5.3.zip 다운로드 → CSV → `COPY`로 적재.

---

## 5. 정답지 다운로드  _(작성 예정)_

> TODO: 5.3 Field_Level/Table_Level CSV를 `truth/`에 저장.
