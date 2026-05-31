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

## 2. RDS PostgreSQL 생성 (완료 ✅)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
PGPASSWORD="$(생성한_비번)" AWS_REGION=us-east-1 bash infra/create_rds.sh
```
- 기본 VPC(`vpc-0730eb31c8af2c67d`)에 보안그룹 `db2doc-pg-sg` 생성, **내 IP/32 만 5432 허용**.
- 인스턴스: `db2doc-omop`, **db.t4g.micro + 20GB gp3 + PostgreSQL 16.14**, publicly-accessible,
  backup 0일, single-AZ (PoC용 최소 구성).
- 엔드포인트: `db2doc-omop.coztdyijwdme.us-east-1.rds.amazonaws.com:5432` (DB명 `omop`).
- 접속 확인: `psql ... -c "SELECT version();"` → PostgreSQL 16.14 OK.
- 비번은 `.env`에 저장(gitignore). **다 쓰면 삭제**:
  `aws rds delete-db-instance --db-instance-identifier db2doc-omop --skip-final-snapshot --region us-east-1`

---

## 3. OMOP 스키마 적재

```bash
set -a; source .env; set +a
bash infra/run_ddl.sh        # ddl -> primary_keys -> indices (constraints 제외)
```
- DDL의 `@cdmDatabaseSchema` placeholder를 `cdm` 스키마로 치환해 적재.
- **FK(constraints)는 적재하지 않음** = "문서 없는" 입력. 원본 FK 파일은 `truth/`에 보관(채점용).

---

## 4. GiBleed 데이터 적재

```bash
.venv/bin/python infra/load_eunomia.py
```
- GiBleed_5.3.zip 다운로드 → 테이블별 CSV → `COPY`로 적재 (헤더 소문자 매핑, ISO `Z` 제거).

---

## 5. 정답지 다운로드

```bash
bash infra/fetch_truth.sh    # 5.3 Field_Level / Table_Level CSV -> truth/
```
