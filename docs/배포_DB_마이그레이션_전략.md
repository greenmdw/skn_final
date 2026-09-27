# 배포 DB 마이그레이션 전략 (DEP-01)

2026-09-27 조사. AWS RDS에 실제로 접속해 확인하지는 못했다(접속 정보 없음) — git 이력과 `db/migrate.py` 동작만으로
문제를 재구성했고, 실행 전 팀 확인이 필요한 지점을 명시했다.

## 원인

`git log --diff-filter=D -- 'db/migrations/*.sql'`로 확인:

- 커밋 `39cfe10`("Remove obsolete code and files", 2026-09-22)가 기존 19개 마이그레이션 파일
  (`0000_prereq.sql` ~ `0018_pc_parts_compat_columns.sql`)을 지우고 지금의 4개 파일
  (`0000_schema.sql` ~ `0003_triggers.sql`)로 바꿨다.
- 새 4개 파일은 내용상 `pg_dump --schema-only` 출력 형태(`-- Name: X; Type: TABLE; Schema: Y; Owner: -`
  주석, 파일 끝 "PostgreSQL database dump complete")다 — 즉 **19개 파일을 순서대로 적용한 최종 스키마를
  덤프해서 4단계(테이블 전체 → 제약 전체 → 인덱스 전체 → 트리거 전체)로 다시 쪼갠 것**이다. 스키마 내용은
  기능적으로 같고, 파일 이름(버전 키)만 바뀌었다.
- `db/migrate.py`는 파일명(확장자 제외)을 버전 키로 써서 `_migrations.schema_migrations`에 적용 여부를
  기록한다(`_applied()`가 `version` 컬럼으로 대조, `main()`이 `f.stem`을 그 버전으로 씀).

**문제**: `39cfe10` 이전에 만들어진 뒤 그 이후 마이그레이션을 다시 실행한 적 없는 DB는
`_migrations.schema_migrations`에 `0000_prereq`, `0001_tables`, ... `0018_pc_parts_compat_columns`가
기록돼 있다. 지금 저장소의 `0000_schema` ~ `0003_triggers`는 그 DB 기준으로 **파일명이 완전히 다른
"새 마이그레이션"**으로 보인다. 이 상태에서 `python db/migrate.py up`을 그대로 돌리면 이미 있는
테이블·제약을 다시 `CREATE`하려다 `already exists` 오류로 실패한다 — 로컬 개발 중 실제로 겪은 증상과 같다.

**39cfe10 이후에 만들어진 DB**(신규 RDS를 새로 `setup_all.py`로 세팅)라면 처음부터 새 4개 파일의 버전 키로
기록됐을 것이므로 이 문제가 없다. **어느 쪽인지는 AWS RDS에 직접 접속해 확인해야 안다** — 이 저장소만 봐서는
알 수 없다.

## 확인 방법 (실행만 하면 됨, 파괴적이지 않음)

배포 서버(또는 그 DB에 접속 가능한 곳)에서:

```bash
DATABASE_URL=<AWS RDS DSN> python db/migrate.py status
```

- 4개 다 `[OK]`로 나오면 → **문제 없음.** 이미 새 베이스라인 기준으로 기록돼 있다. 전략 A·B 필요 없이 지금처럼
  `develop` 머지마다 재배포하면 된다(새 마이그레이션 파일이 생기면 `migrate.py up`이 정상적으로 forward-only
  적용한다).
- 4개 다 `[pending]`으로 나오는데 **테이블에 이미 데이터가 있으면**(`psql`로 `\dt planning.*` 등 확인) →
  아래 "전략 A"가 필요한 상황이다. 이 상태에서 `migrate.py up`을 그냥 돌리면 안 된다(=DEP-01 재배포가 그 순간
  실패한다).
- 4개 다 `[pending]`이고 **테이블도 비어 있으면**(신규 DB) → 그냥 `migrate.py up`(=`setup_all.py`)을 돌리면
  된다. 문제 상황이 아니다.

## 전략 A — 이미 옛 베이스라인으로 돌아간 실사용 DB (데이터를 지키는 경우)

스키마 내용 자체는 같으므로(pg_dump 재구성), **SQL을 다시 실행하지 않고 추적 테이블만 새 버전 키로
채운다("backfill")**. 실제 스키마를 조금이라도 바꾸지 않는 방법이라 가장 안전하다.

1. 실제 스키마가 새 4개 파일과 같은지 먼저 대조한다(다르면 이 전략을 쓰면 안 된다):
   ```bash
   pg_dump --schema-only --no-owner --no-privileges "$AWS_DSN" > live_schema.sql
   # db/migrations/0000_schema.sql ~ 0003_triggers.sql 를 합친 내용과 테이블/제약/인덱스/트리거 목록을 diff
   ```
2. 같다면, 새 4개 파일을 "이미 적용된 것"으로 표시하는 스크립트를 하나 만든다(아직 없음 — 만들어야 함):
   ```python
   # db/backfill_baseline.py (제안, 아직 없음)
   # db/migrate.py 의 _checksum·_ensure_tracking 을 그대로 재사용해서
   # 0000_schema.sql~0003_triggers.sql 의 (버전, 체크섬)을 SQL 실행 없이 INSERT 만 한다.
   ```
   이 스크립트는 `CREATE`/`ALTER`를 전혀 실행하지 않고 `_migrations.schema_migrations`에 행 4개만 추가한다.
3. 이후 `db/migrate.py status`가 4개 다 `[OK]`로 나오는지 확인.
4. 그 다음부터는 새 마이그레이션 파일(`0004_...`)이 생길 때마다 평소처럼 `migrate.py up`.

**팀 확인 필요**: 1번에서 실제로 스키마가 달라진 게 있으면(예: `39cfe10` 이후 누가 로컬에서만 걸어둔 임시
변경이 배포 DB에 반영돼 있다거나, 반대로 새 파일에만 있고 배포 DB엔 없는 컬럼이 있다거나) 전략 A를 쓸 수
없다 — 그 차이를 메우는 별도 마이그레이션 파일을 새로 써야 한다.

## 전략 B — 데이터를 안 지켜도 되는 경우 (해커톤 데모 등)

로컬에서 이미 한 번 했던 방식과 같다: DB를 지우고 `setup_all.py`로 새로 만든다.

```bash
DATABASE_URL=<AWS RDS DSN> python db/setup_all.py   # 마이그레이션 + 시드 + 카탈로그 전부 새로
```

**주의**: 이 경로는 그 DB의 회원가입 계정, 저장된 견적, 채팅 이력을 전부 지운다. 해커톤 제출용 데모
DB라면 문제 없지만, 실제로 가입한 사용자가 있다면(팀 내부 시연 참여자 등) 되돌릴 수 없다.

## 결정됨 (2026-09-27, 이태혁 확인)

**실사용 데이터가 없는 데모 DB** — 전략 B로 진행한다.

```bash
# 배포 서버(또는 AWS RDS에 접속 가능한 곳)에서
DATABASE_URL=<AWS RDS DSN> python db/setup_all.py
```

이 한 줄이 새 4개 마이그레이션(`0000_schema.sql`~`0003_triggers.sql`) 적용 + 시드 + 카탈로그·주변기기·
리뷰 요약 적재까지 순서대로 처리한다(`db/README.md` "한 번에(추천)" 절과 동일). 옛 19개 파일 이력이
남아 있어도 `migrate.py`가 새 파일명으로 처음부터 다시 적용하므로 문제되지 않는다 — 기존 테이블이
남아 있으면 `CREATE TABLE`이 실패할 수 있으니, **DB를 먼저 지우고**(스키마 `DROP ... CASCADE` 또는
RDS 인스턴스 자체를 재생성) 위 명령을 실행한다.

**전제 조건 확인**: `data/peripherals/*_processed.csv`(4개)와 `data/amazon23/pcparts_product_risk.json`은
git에 없다(팀 전달 원본, `.gitignore`) — 배포 서버 로컬에 이 파일들이 없으면 `setup_all.py`가 주변기기
카탈로그·리뷰 축 단계에서 완료되지 않는다. 배포 전 이 파일들을 배포 서버에 올려 뒀는지 먼저 확인한다.

**재배포 시점(DEP-01 "develop 머지마다 재배포")**: 새 마이그레이션 파일이 없는 한(지금은 없음) 매번
DB를 지우고 다시 만들 필요는 없다 — 코드만 새로 배포(Docker 이미지 갱신)하면 된다. DB를 다시 만들어야
하는 경우는 스키마가 바뀌는 새 마이그레이션이 추가될 때뿐이다(예: 이번에 논의 중인 ACC-02가 새 테이블이
필요하다고 결론 나면 그때).
