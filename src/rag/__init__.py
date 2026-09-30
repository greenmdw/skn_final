"""RAG 근거 검색 공통 컴포넌트.

지금은 인메모리 검색 두 갈래뿐이다 — PostgreSQL·pgvector 연동은 이 브랜치에 없다
(`src/repo/`에 `rag_repo.py`가 없다. `src/rag/embedding.py`의 `BedrockEmbedder` 등은 어디서도
import되지 않는 미사용 코드다).

- `evidence_search.py` — 데모 파이프라인(`src/pipeline.py`)이 시나리오 파일의 `corpus`를
  `load_mini_corpus()`로 주입한 인메모리 리스트에서, [3-C] 세트 검증의 **데모 경로**
  (`stage3c_verify.verify_set`)만 이 함수를 쓴다. 실경로(`verify_build`)는 이 함수를 부르지
  않고 카탈로그 스펙 출처(provenance)로 근거를 만든다(E5) — 문서 RAG는 아직 연결 전이라
  실경로 결과의 회색축에 "설명서·규격(RAG 미연결)"이 항상 남는다.
- `care_guides.py` — `data/pc_care_guides.json`(합성 작성, 18개 "구매 전 확인" 문서)을 프로세스
  시작 시 한 번 임베딩해(MOCK_MODE거나 키가 없으면 해시 임베딩, 아니면 OpenAI) 인메모리에 들고
  코사인 유사도로 찾는다. 소비처: `src/services/recommendation_service.py`(실경로 "구매 전 확인"),
  `src/engine/peripheral_payload.py`(E13 — 주변기기 4종은 `SLOT_GUIDE_IDS`에 빈 목록으로 등록돼
  있어 지금은 항상 빈 결과). 조립 가이드 기능(개발요청 1번)은 삭제됐다.

두 갈래 다 근거 0건이면 "검증 불가(회색)"로 다룬다. 옛 "검사AI↔변호인AI 디베이트"(축마다
공격·방어 근거 2트랙을 만드는 설계)는 걷혔다(기획서 §10-12) — 지금은 축마다 근거를 모아
중립 서술 쟁점 문장 1건만 만든다(`stage3c_verify.py` 참고).
"""
