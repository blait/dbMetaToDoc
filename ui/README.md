# db2doc UI — 클릭 가능한 프로토타입

PoC 출력(`out/*.json`)을 그대로 내장한 **self-contained 단일 HTML** 프로토타입.
서버·의존성 없이 `file://`로 열린다. 제품 UX를 데모하기 위한 것 (실데이터 = 실제 생성 결과).

## 빌드 & 열기

```bash
.venv/bin/python ui/build_ui.py     # out/*.json -> ui/db2doc_ui.html
open ui/db2doc_ui.html
```

데모 증거 사본은 `results/db2doc_ui_demo.html`에 커밋되어 있다 (바로 열어볼 수 있음).

## 화면 (제품 UX 루프: Connect→Scan→Review→Publish→Use)

- **Sources** — 소스별 문서화율·검수 대기·AI 추론 도메인 현황 대시보드.
- **Review Queue ★** — 제품의 심장. **신뢰도 낮은 항목만** 사람에게 보여주고(triage),
  각 설명마다 **판단 근거**(샘플 top-k·distinct·null·range)를 함께 제시. Approve/Edit/Reject +
  ≥0.9 일괄 승인. (human-in-the-loop 신뢰 구축)
- **Catalog** — 복원된 데이터 딕셔너리, 검색, 테이블 상세(컬럼 설명·PK/FK·신뢰도).
- **Quality** — 정답지 대조 채점(컬럼 94% / 테이블 100% 등)을 그대로 시각화.

## 다음 단계 (실제 솔루션화)

이 프로토타입은 정적 데모다. 제품화하려면:
- 백엔드 API + 잡 큐(다수 DB 순회 스캔), 영구 Catalog 저장소
- 검수 결정 저장 + **학습 루프**(DBA 교정 → 유사 컬럼 재추론 few-shot)
- 보안: 고객 VPC 내 collector, 자기 계정 Bedrock, PII 마스킹, RBAC/감사로그
- 스키마 드리프트 감지 → 변경분만 재스캔
