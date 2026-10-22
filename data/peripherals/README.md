# 부속기기 원본 CSV

팀원이 전달한 `mouse_processed.csv`, `monitor_processed.csv`, `speaker_processed.csv`,
`keyboard_processed.csv`의 내용을 수정하지 않고 복사했다. `db/seed_peripherals.py`가
이 파일들을 읽어 4종 카탈로그 스펙과 가격 스냅샷을 만든다.

원본에는 가격의 판매처와 관측일이 없다. 따라서 가격 숫자는
`catalog.peripheral_price_snapshot`에 보존하고 `price_observed_at`은 NULL로 둔다.
`catalog.offer`/`offer_observation`에 넣지 않아 구매 가능한 최신 가격으로 사용되지 않는다.
상품 URL은 제조사 규격/지원 페이지일 수 있어 구매 링크로 간주하지 않는다.

`-`·빈 칸·`미표기`·`해당없음`은 해당 스펙에서 NULL로 저장한다.
다만 포트 개수의 `없음`은 0으로, 키보드 래피드 트리거의 `O`/`X`는
true/false로 저장한다. 기타 원본 문구(예: `HDMI 버전`의 `2`, 스피커 출력 구성)는
추측해 바꾸지 않는다. 상대경로 설명서 파일명 2개도 원본 참조 문자열로 보존한다.

검증만 실행하려면 `python db/seed_peripherals.py --dry-run`을 사용한다.
