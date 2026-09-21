# 참조 스펙 수집 템플릿

[스키마 초안](../part_reference_schema_draft.md) §7 참고. 헤더는 임포터(미구현)가 읽는 이름이다.

- `aliases`, `memory_types`는 `;`로 구분한다. 공백·하이픈만 다른 별칭은 하나로 합쳐지므로 겹쳐 적어도 된다.
- `spec_confidence`: `verified`(실물·복수 출처) / `vendor_spec`(제조사 공개 사양) / `estimated`(확인 전 임시).
- 모르는 칸은 **비워 둔다**(추정값으로 채우지 않는다). `source_url`·`verified_at`은 필수.
- GPU `length_mm_max`는 호환 판정에 쓰는 보수적 값이다(임포터가 `gpu_spec.length_mm`에 넣는다).
- 예시 행은 형식 안내이며 실제 값이 아니다. **완성된 원본 CSV는 저장소에 커밋하지 않는다**(로컬 보관, `.gitignore` 정책 참고).
