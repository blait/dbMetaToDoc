# db2doc v2 — 설치 & 사용 가이드

문서 없는 데이터베이스에 연결해서 카탈로그(테이블·컬럼 의미, 키, 신뢰도)를 자동 생성하는
도구입니다. 이 문서대로 따라 하면 **repo 클론 → 설치 → 내 DB 연결 → 결과 확인**까지 끝납니다.

> 읽기 전용입니다. 대상 DB의 스키마·통계·샘플만 읽고 **DB를 변경하지 않습니다.**

---

## 0. 사전 준비물

| 항목 | 필요 사항 |
|---|---|
| **Python** | 3.10 이상 (개발/검증은 3.13) |
| **분석 대상 DB** | PostgreSQL. 호스트·포트·DB명·스키마·계정(읽기 권한)·비밀번호 |
| **AWS 계정** | Bedrock(LLM) 접근 권한. 그래프/검색 기능까지 쓰려면 Neptune·OpenSearch 권한 |
| **AWS 자격증명** | 로컬에 `aws configure` 또는 환경변수로 설정돼 있어야 함 |

### AWS에서 미리 켜둘 것 (최소 = LLM만)

가장 기본인 **카탈로그 생성**에는 Bedrock만 있으면 됩니다.

1. **Bedrock 모델 활성화** (콘솔 → Bedrock → Model access):
   - `Claude` 계열 (기본값: `us.anthropic.claude-opus-4-8` — inference profile)
   - `Titan Text Embeddings V2` (`amazon.titan-embed-text-v2:0`)
2. 리전: 기본 `us-east-1` (다르면 `.env`에서 변경)

**아무것도 없는 빈 계정**에서 시작하는 것을 전제로 합니다. 필요한 AWS 리소스는 이 문서에서
직접 만듭니다 — 어떤 기능을 쓰느냐에 따라:

| 쓰려는 기능 | 만들 것 | 절차 | 필요 IAM |
|---|---|---|---|
| 카탈로그 생성 (필수) | 없음 (Bedrock만) | §1~5 | `bedrock:InvokeModel` |
| 스키마 그래프 | Neptune 그래프 (코드가 자동 생성) | §6-1 | `neptune-graph:*` |
| text2sql / 의미 검색 | OpenSearch Serverless 컬렉션 | §6-2 | `aoss:*` |
| 결과 영구 저장(공유) | RDS MySQL (메타스토어) | §7 | `rds:*`, `ec2:*Security*` |

> 그래프·검색·메타스토어는 **선택**입니다. 카탈로그 생성·열람만 할 거면 Bedrock만 있으면 됩니다.
> 권한은 관리자/PowerUser면 위 전부 충족됩니다.

---

## 1. 설치

```bash
git clone <repo-url> db2doc
cd db2doc/v2

# 가상환경 + 의존성
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

설치되는 것: `boto3`(AWS), `psycopg2-binary`(PostgreSQL), `fastapi`+`uvicorn`(웹앱),
`langgraph`+`langchain-aws`(text2sql), `opensearch-py`(의미 검색).

> 이후 명령은 모두 `db2doc/v2/` 디렉토리에서 `.venv/bin/python ...`으로 실행합니다.
> (가상환경을 `activate` 했다면 그냥 `python ...`)

---

## 2. 설정 (`.env`)

`v2/.env` 파일을 만들고 아래를 채웁니다. (repo 루트의 `.env`도 자동으로 읽히지만,
고객 환경은 `v2/.env`를 쓰는 걸 권장합니다.)

```bash
# --- AWS / LLM (필수) ---
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.anthropic.claude-opus-4-8
BEDROCK_EMBED_MODEL_ID=amazon.titan-embed-text-v2:0

# --- 분석할 DB는 .env에 안 적어도 됩니다 ---
# 웹 화면에서 연결 정보를 입력하면 됩니다(권장, 비밀번호 미저장).
# CLI로 쓸 때만 아래를 채우세요:
# PGHOST=...
# PGPORT=5432
# PGDATABASE=...
# PGSCHEMA=public
# PGUSER=...
# PGPASSWORD=...

# --- 선택 기능 (그래프/검색) — §6에서 설정 ---
# NEPTUNE_GRAPH_ID=     (런별로 자동 생성되므로 보통 비워둠)
# AOSS_ENDPOINT=        (OpenSearch Serverless 컬렉션 엔드포인트)

# --- 안전장치 (선택, 기본값 있음) ---
# V2_MAX_LLM_TOKENS=800000   # 런 전체 토큰 상한
# V2_MAX_LLM_CALLS=400       # 런 전체 LLM 호출 상한
```

**AWS 자격증명**은 `.env`가 아니라 표준 AWS 방식으로 둡니다:
```bash
aws configure          # 또는 AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY 환경변수
aws sts get-caller-identity   # 확인
```

연결 테스트(Bedrock):
```bash
.venv/bin/python - <<'PY'
import boto3, json
br = boto3.client("bedrock-runtime", region_name="us-east-1")
r = br.invoke_model(modelId="us.anthropic.claude-opus-4-8",
    body=json.dumps({"anthropic_version":"bedrock-2023-05-31","max_tokens":16,
                     "messages":[{"role":"user","content":"Reply OK"}]}))
print(json.loads(r["body"].read())["content"][0]["text"])   # -> OK
PY
```

---

## 3. 실행 — 웹앱 (권장)

```bash
.venv/bin/uvicorn webapp:app --port 8200
```

브라우저에서 **http://localhost:8200** 접속 →

1. **"새 DB 연결"** 폼에 분석할 DB 정보 입력 (호스트·포트·DB명·스키마·사용자·비밀번호)
2. **"연결 테스트"** — "연결 성공 — 테이블 N개" 확인
3. **"분석 시작"** — 백그라운드로 파이프라인 실행 (진행 상황 자동 갱신)
4. 완료되면 런 카드를 클릭 → **카탈로그**(트리로 테이블·컬럼·설명·신뢰도) 열람

> 비밀번호는 실행 프로세스에만 전달되고 디스크에 저장되지 않습니다.
> "고급 — 평가 모드"는 정답지가 있는 벤치마크 DB 전용이니 고객 DB에는 켜지 마세요.

분석에 걸리는 시간·비용은 테이블 수에 비례합니다 (대략 37테이블 기준 LLM 입력 ~270k /
출력 ~54k 토큰).

---

## 4. 실행 — CLI (선택)

> **전제: 메타스토어(MySQL)가 필수입니다.** 이 빌드는 결과를 파일이 아니라 MySQL에
> 저장합니다 — `.env`에 `METASTORE_*`를 먼저 채우세요(§7). 미설정 시 CLI·웹앱 모두
> 동작하지 않습니다.

`.env`에 PG*(분석 대상)와 METASTORE_*(결과 저장소) 값을 채운 뒤:

```bash
.venv/bin/python run.py --run-key mydb --name "내 DB"   # 카탈로그 생성·적재 (고객 DB)
.venv/bin/python run.py --run-key omop --with-truth     # OMOP eval (정답지 채점 포함)
```

파이프라인은 **단일 프로세스 인메모리 체인**으로 동작합니다 — 중간/최종 산출물을 디스크
파일로 쓰지 않습니다. 최종 결과는 모두 적재됩니다:
- **MySQL 메타스토어** — 카탈로그(테이블·컬럼·키·설명·신뢰도 + **원본 DB 주석**),
  AI 원본/검수본, 검수 이력, 온톨로지, text2sql 이력
- **Neptune** — 런별 전용 스키마 그래프 (§6-1)
- **OpenSearch** — 런별 메타데이터 벡터 인덱스 (§6-2)

> 이 솔루션은 **원본 DB를 절대 변경하지 않습니다** — 조회(SELECT)만 합니다.
> 원본 DB에 주석을 써넣는 SQL은 생성하지 않습니다.

---

## 5. 결과 활용

- **카탈로그 열람**: 웹 화면(`/runs/<id>`)에서 트리 탐색 (메타스토어에서 조회)
- **원본 주석 보존**: 원본 DB에 이미 주석이 있으면 그대로 **보존·표시**합니다
  (생성된 설명과 나란히 비교). 원본은 코드가 그대로 옮기며 LLM이 건드리지 않습니다.
- **사람 검수**: 웹 화면에서 각 설명의 ✎ 수정 버튼으로 직접 고칠 수 있습니다.
  AI 원본은 `descriptions.ai_text`에 보존되고 수정 이력은 `revisions`에 남습니다.
  신뢰도가 낮거나 `data_unverified` 표시된 항목부터 보면 됩니다.

---

## 6. 선택 기능 — 스키마 그래프 · 의미 검색 · text2sql (AWS 리소스 직접 생성)

카탈로그만 필요하면 여기는 건너뛰어도 됩니다. 아래는 **빈 AWS 계정에서 처음부터** 그래프 시각화와
자연어 질의(text2sql)를 켜는 절차입니다. (필요 IAM 권한: `neptune-graph:*`,
`aoss:*` + `iam:` 정책 읽기. 관리자/파워유저 권한이면 충분.)

### 6-1. 스키마 그래프 — AWS Neptune Analytics

그래프 자체는 **`graph.py`가 런마다 자동 생성**하므로 미리 만들 게 없습니다. IAM 권한
(`neptune-graph:CreateGraph/DeleteGraph/GetGraph/ExecuteQuery`)과 리전(`AWS_REGION`)만
맞으면 됩니다.

그래프 적재와 개념(온톨로지) 레이어는 **`run.py`가 파이프라인 안에서 자동 수행**합니다
(`graph.load_catalog_to_graph` + `concepts.load_concepts_to_graph`). 그래프를 생략하려면
`run.py --no-graph`.
→ 웹앱의 런 상세에서 "스키마 그래프" 탭. (그래프당 시간당 과금 — §8. 런 삭제 시 자동 삭제.)

### 6-2. 의미 검색 + text2sql — AWS OpenSearch Serverless

자연어 질문→SQL에는 메타데이터 벡터 검색이 필요합니다. OpenSearch Serverless는 자동 생성이
아니라 **컬렉션 + 보안정책 3종을 한 번 만들어야** 합니다. (`<ARN>`은 본인 IAM 사용자/역할
ARN — `aws sts get-caller-identity`의 `Arn`.)

```bash
REGION=us-east-1 ; NAME=db2doc-search ; ARN=$(aws sts get-caller-identity --query Arn --output text)

# (1) 암호화 정책 (AWS 소유 키)
aws opensearchserverless create-security-policy --region $REGION --name ${NAME}-enc --type encryption \
  --policy "{\"Rules\":[{\"ResourceType\":\"collection\",\"Resource\":[\"collection/${NAME}\"]}],\"AWSOwnedKey\":true}"

# (2) 네트워크 정책 (퍼블릭 접근)
aws opensearchserverless create-security-policy --region $REGION --name ${NAME}-net --type network \
  --policy "[{\"Rules\":[{\"ResourceType\":\"collection\",\"Resource\":[\"collection/${NAME}\"]},{\"ResourceType\":\"dashboard\",\"Resource\":[\"collection/${NAME}\"]}],\"AllowFromPublic\":true}]"

# (3) 데이터 접근 정책 (내 ARN에 인덱스/컬렉션 권한)
aws opensearchserverless create-access-policy --region $REGION --name ${NAME}-acc --type data \
  --policy "[{\"Rules\":[{\"ResourceType\":\"index\",\"Resource\":[\"index/${NAME}/*\"],\"Permission\":[\"aoss:*\"]},{\"ResourceType\":\"collection\",\"Resource\":[\"collection/${NAME}\"],\"Permission\":[\"aoss:*\"]}],\"Principal\":[\"${ARN}\"]}]"

# (4) 컬렉션 생성 (VECTORSEARCH) — ACTIVE까지 1~2분
aws opensearchserverless create-collection --region $REGION --name $NAME --type VECTORSEARCH

# (5) 엔드포인트 확인 → .env의 AOSS_ENDPOINT에 기입
aws opensearchserverless batch-get-collection --region $REGION --names $NAME \
  --query 'collectionDetails[0].collectionEndpoint' --output text
```

`.env`에 `AOSS_ENDPOINT=https://xxxx.us-east-1.aoss.amazonaws.com`를 기입하면, 이후
`run.py` 실행 시 카탈로그가 **런별 인덱스**(`db2doc-<run_key>`)로 자동 인덱싱됩니다
(생략하려면 `run.py --no-index`).
→ 웹앱의 "text2sql" 탭에서 자연어 질의. (인덱스는 **런별로 분리**되어 런 간 섞이지 않음.)

> 자세한 아키텍처·설계 근거는 [`GUIDE.md`](GUIDE.md), 기법 설명은 [`SOLUTION.md`](SOLUTION.md).

---

## 7. 메타스토어 (MySQL) — 결과 저장소 **(필수)**

> 이 단계는 **필수**이며 §4 실행보다 먼저 해야 합니다. 이 빌드는 결과를 파일이 아니라
> MySQL에 저장합니다 — 메타스토어가 단일 진실 공급원입니다. (메타스토어는 **분석 결과를
> 담는 곳**이고, 분석 대상 DB와는 별개입니다.)

메타스토어에는 카탈로그·설명(AI 원본 + 사람 검수본)·검수 이력·온톨로지·text2sql 이력이
영구 저장되어 여러 사용자·여러 머신에서 공유됩니다. 분석이 끝날 때 자동 적재되고, 웹에서
설명을 수정하면 검수 이력(누가·언제·이전→이후)이 `revisions`에 남습니다. AI 원본은 절대
덮어쓰지 않습니다(`descriptions.ai_text`).

### 7-1. MySQL 올리기 (빈 계정 기준, AWS RDS)

로컬 MySQL/RDS/Aurora 무엇이든 됩니다. AWS RDS를 처음부터 만드는 절차:

```bash
REGION=us-east-1

# (1) 보안그룹 생성 (default VPC). 이미 쓰는 SG가 있으면 이 단계 건너뛰고 그 ID 사용.
VPC=$(aws ec2 describe-vpcs --region $REGION --filters Name=isDefault,Values=true \
      --query 'Vpcs[0].VpcId' --output text)
SG=$(aws ec2 create-security-group --region $REGION --group-name db2doc-meta-sg \
     --description "db2doc metastore MySQL" --vpc-id $VPC --query GroupId --output text)

# (2) 내 IP에서 3306 인바운드 허용
MYIP=$(curl -s https://checkip.amazonaws.com)
aws ec2 authorize-security-group-ingress --region $REGION --group-id $SG \
  --protocol tcp --port 3306 --cidr ${MYIP}/32

# (3) RDS MySQL 인스턴스 생성 (~몇 분, available 까지 대기)
aws rds create-db-instance \
  --db-instance-identifier db2doc-meta \
  --db-instance-class db.t4g.micro \
  --engine mysql --engine-version 8.0 \
  --master-username db2doc --master-user-password '<강한-비밀번호>' \
  --allocated-storage 20 --storage-type gp3 \
  --db-name db2doc \
  --vpc-security-group-ids $SG \
  --publicly-accessible --backup-retention-period 0 --no-multi-az \
  --region $REGION
aws rds wait db-instance-available --db-instance-identifier db2doc-meta --region $REGION

# (4) 엔드포인트 확인 → .env METASTORE_HOST 에 기입
aws rds describe-db-instances --db-instance-identifier db2doc-meta --region $REGION \
  --query 'DBInstances[0].Endpoint.Address' --output text
```

> IP가 바뀌면(재택/사무실 전환 등) 다시 `authorize-security-group-ingress`로 새 IP의 3306을
> 열어야 연결됩니다. "연결 안 됨(2003)"이면 대부분 이 문제입니다.

### 7-2. `.env`에 접속 정보

```bash
METASTORE_HOST=db2doc-meta.xxxxxxxx.us-east-1.rds.amazonaws.com
METASTORE_PORT=3306
METASTORE_DB=db2doc
METASTORE_USER=db2doc
METASTORE_PASSWORD=<비밀번호>
# 또는 한 줄로: METASTORE_URL=mysql+pymysql://user:pw@host:3306/db2doc?charset=utf8mb4
```
이 설정이 없으면 CLI는 즉시 종료하고 웹앱은 503으로 응답합니다 (결과를 저장할 곳이 없음).

### 7-3. 스키마(DDL) 적용

두 방법 중 하나:

```bash
# (A) 코드가 테이블을 만들게 (가장 간단, 멱등)
.venv/bin/python -m store.sync init

# (B) DDL을 직접 확인·적용하고 싶으면 — store/schema.sql 사용
.venv/bin/python -m store.sync ddl > store/schema.sql   # DDL 미리보기/저장
mysql -h <host> -u db2doc -p db2doc < store/schema.sql   # 수동 적용
```

생성되는 테이블: `runs`(런), `cat_tables`/`cat_columns`(카탈로그+원본주석),
`descriptions`(AI 원본 + 검수본), `revisions`(검수 이력), `concepts`(온톨로지),
`t2sql_history`(text2sql 질의 이력), `sources`.

### 7-4. 사용

분석(`run.py`/웹앱)이 끝나면 결과가 자동으로 적재됩니다. 조회/관리:

```bash
.venv/bin/python -m store.sync list                        # DB의 런 목록
```

---

## 8. 비용 & 정리 (중요)

| 리소스 | 과금 | 정리 방법 |
|---|---|---|
| **Bedrock (LLM)** | 토큰당 (분석 시에만) | 자동 — 분석이 끝나면 과금 없음 |
| **Neptune Analytics 그래프** | **런별 그래프당 시간당 (~$0.48/hr)** | 웹앱에서 런 삭제(✕) → 그래프도 자동 삭제 |
| **OpenSearch Serverless** | 최소 OCU 시간당 | 콘솔에서 컬렉션 삭제 |
| **메타스토어 RDS MySQL** | 인스턴스 시간당 (db.t4g.micro ~$0.016/hr) | 다 쓰면 `aws rds delete-db-instance` |

- **Neptune은 런마다 그래프가 생기고 떠 있는 동안 계속 과금**됩니다. 안 쓰는 런은 웹앱에서
  삭제하세요 — 삭제 시 그래프도 함께 제거되어 과금이 멈춥니다 (자동 정리는 없음).
- 그래프/검색 기능을 안 쓰면 Neptune·OpenSearch는 만들지 않아도 됩니다(카탈로그는 LLM만으로 동작).
- 메타스토어 MySQL은 결과를 보존하려면 계속 띄워둡니다. PoC만 하고 끝낼 거면 삭제.

---

## 9. 문제 해결

| 증상 | 확인 |
|---|---|
| 연결 테스트 실패 | DB 호스트/포트/방화벽, 계정 권한. RDS면 보안그룹에 내 IP 허용 |
| `AccessDenied` (Bedrock) | 콘솔에서 해당 모델 access 활성화, IAM에 `bedrock:InvokeModel` |
| `temperature is deprecated` | Opus 계열은 temperature 미지원 — 코드가 자동 처리(별도 조치 불필요) |
| 그래프 탭이 비어 있음 | `graph.py load`를 그 런에 실행했는지, Neptune 권한 확인 |
| text2sql "개념 없음" | `metasearch.py index`(검색) + `concepts.py all`(개념) 선행 필요 |
| 분석이 멈춤/너무 오래 | `V2_MAX_LLM_TOKENS`/`V2_MAX_LLM_CALLS` 가드레일 도달 여부, 테이블 수 |
| 메타스토어 연결 안 됨 | `METASTORE_*` 값, MySQL 보안그룹 3306 허용, `store.sync init`로 테이블 생성 |
| `Unknown column ...` (MySQL) | 옛 스키마 잔존 — `store.sync init` 전에 충돌 테이블 정리 또는 새 DB 사용 |

---

## 부록 — 디렉토리 한눈에

```
v2/
  webapp.py       웹앱 (런 목록 + 새 DB 연결 + 카탈로그/그래프/text2sql) — 메타스토어 전용
  pipeline.py     인메모리 오케스트레이터 (profile→relations→describe→catalog→concepts → DB 적재)
  run.py          CLI 진입점 (pipeline.run_pipeline 래퍼)
  profiler.py     1. 통계 프로파일 (+ 기존 주석 단서)
  relations.py    2. PK/FK 복원 (선언키 우선)
  describe.py     3. 의미 추론 (한국어 description)
  catalog.py      4. 카탈로그 빌드 (읽기 전용, DDL 미생성)
  score.py        5. 정답지 채점 (평가 모드 전용; with_truth 런에서 인메모리 호출)
  graph.py        스키마 그래프 → Neptune (런별 전용 그래프)
  concepts.py     개념(온톨로지) 레이어
  metasearch.py   의미 검색 인덱싱 (OpenSearch)
  text2sql.py     자연어 → SQL (LangGraph)
  store/          메타스토어 (MySQL): models·db·repo·sync + schema.sql(DDL)
  .env            설정 (직접 작성)
```
결과는 모두 MySQL/Neptune/OpenSearch에 저장됩니다 — 로컬에 런별 산출물 디렉토리는
만들지 않습니다.
