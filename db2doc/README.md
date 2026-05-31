# db2doc — metastore product

문서 없는 DB들을 등록·연결하고, 스키마+샘플만으로 의미 설명을 **자동 추론**한 뒤
사람이 **수정·검수**하고, 전부 **MySQL 메타스토어에 영구 저장**하는 데이터 카탈로그/메타스토어.

PoC(`profile/ recover/ document/ render/ eval/`)의 로직을 라이브러리로 추출해
**다중 DBMS(SQLAlchemy)** 에서 동작하도록 일반화하고, REST API + 동적 UI를 얹은 것.

## 구조
```
db2doc/
  config.py        env 설정 (METASTORE_*, DB2DOC_SECRET_KEY, AWS_*)
  bedrock.py       common.py의 Opus 4.8 헬퍼 재노출
  targets/         대상 DB 추상화: engine / inspect / stats / quoting
  pipeline/        profiler · relations · describe · render (engine 인자 주입)
  store/           메타스토어 ORM(models) · db · repo · crypto(Fernet)
  jobs/            executor(ThreadPool) · runner(run_scan/run_infer)
  api/             FastAPI: routers/{sources,scans,jobs,catalog,descriptions,export}
  web/             동적 SPA(index.html + app.js) — fetch /api
```

## 실행
```bash
# 1) 메타스토어 MySQL (새 RDS): infra/create_metastore_rds.sh
#    → .env 에 METASTORE_HOST/USER/PASSWORD 등 기입
# 2) 의존성
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# 3) 서버
set -a; source .env; set +a
.venv/bin/uvicorn db2doc.api.main:app --host 127.0.0.1 --port 8077
#  UI : http://127.0.0.1:8077/app/
#  API: http://127.0.0.1:8077/docs
```

## 사용 흐름 (UI)
1. **Sources** → "소스 추가"(dialect/host/db/schema/user/pw) → `test` 연결확인
2. **Scan+Infer** → 백그라운드 잡(프로파일→관계복원→설명생성), 진행률 폴링
3. **Catalog** → 테이블·컬럼 설명 확인, 인라인 수정(blur 저장)
4. **Review Queue** → 신뢰도 낮은 항목 검수(approve/reject), ≥0.9 일괄 승인
5. **Export** → COMMENT SQL / Markdown / CSV / Mermaid 내려받기

## 보안
- 대상 DB 비밀번호는 **Fernet 대칭암호화**로 `sources.secret_ref`에 저장(평문 금지).
  마스터키 = env `DB2DOC_SECRET_KEY` 또는 `secrets/master.key`(0600, gitignore).
- API 응답에 비밀번호 미포함. LLM은 자기 AWS 계정 Bedrock 호출.

## 다중 DBMS
`targets/`가 SQLAlchemy Inspector+Core로 dialect 차이를 흡수 → PostgreSQL/MySQL 동일 코드.
COMMENT export만 dialect 분기(PG `COMMENT ON`, MySQL `ALTER TABLE ... COMMENT`).
