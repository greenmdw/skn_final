"""컴퓨터 부품 카탈로그 읽기 ([3-0] 후보 수집이 사용).

데모: data/parts_list.csv (부품 마스터) 를 읽고, 스펙/가격이 비어 있는 필드는
결정적 목값으로 채워 후보로 낸다. 실제 스펙·시세는 이후 parts_catalog.csv +
gen_parts_offers.py 로 대체한다 (기획서 §15-3 하이브리드).
"""
from __future__ import annotations

import csv
import hashlib
import re
from functools import lru_cache

from src.config import DATA_DIR
from src.dto import Candidate

_CSV = DATA_DIR / "parts_list.csv"
# 데모 촬영용 가격·성능 등급·호환 속성 override (docs 개발요청_데모영상_데이터정비.md 요청 R2).
# 없는 product_key 는 그대로 해시 기반 값을 쓴다 — 이 표는 선택적 보정일 뿐이다.
_OVERRIDES_CSV = DATA_DIR / "demo_part_overrides.csv"

# 부품군 → 리스트 패널 슬롯 이름
TYPE_TO_SLOT = {
    "cpu": "CPU", "gpu": "GPU", "ram": "RAM", "mainboard": "메인보드",
    "ssd": "저장장치", "psu": "파워", "case": "케이스", "cooler": "쿨러",
}

# 슬롯별 대표 시세(원) — base_price. 데모용 근사값, 지터는 _mock_price 가 부여.
_BASE_PRICE = {
    "CPU": 300_000, "GPU": 700_000, "RAM": 130_000, "메인보드": 220_000,
    "저장장치": 120_000, "파워": 110_000, "케이스": 90_000, "쿨러": 60_000,
}


def _seed(key: str) -> int:
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16)


@lru_cache(maxsize=1)
def _load_overrides() -> dict[str, dict]:
    """demo_part_overrides.csv → product_key 별 override dict. 파일이 없으면 빈 dict."""
    if not _OVERRIDES_CSV.exists():
        return {}
    out: dict[str, dict] = {}
    with _OVERRIDES_CSV.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (row.get("product_key") or "").strip()
            if key:
                out[key] = row
    return out


def _mock_price(product_key: str, slot: str) -> int:
    override = _load_overrides().get(product_key)
    if override and (override.get("price") or "").strip():
        return int(override["price"])
    base = _BASE_PRICE.get(slot, 100_000)
    jitter = (_seed(product_key) % 60) - 25          # -25% ~ +34%
    return int(base * (1 + jitter / 100) // 1000 * 1000)


def _mock_tier(product_key: str) -> int:
    override = _load_overrides().get(product_key)
    if override and (override.get("perf_tier") or "").strip():
        return int(override["perf_tier"])
    return 3 + _seed(product_key + "tier") % 7        # 3~9


def _compat_specs(product_key: str) -> dict:
    """override 표의 socket/mem_type/form_factor/supports_form_factors — 있는 것만.

    [4] 세트 최적화가 이 값으로 소켓·메모리 타입·폼팩터 호환을 비교한다(요청 R1).
    override 에 없는 부품은 빈 dict — "호환 정보 없음"이지 "호환 안 됨"이 아니다.
    """
    override = _load_overrides().get(product_key)
    if not override:
        return {}
    out: dict = {}
    if (override.get("socket") or "").strip():
        out["socket"] = override["socket"].strip()
    if (override.get("mem_type") or "").strip():
        out["mem_type"] = override["mem_type"].strip()
    if (override.get("form_factor") or "").strip():
        out["form_factor"] = override["form_factor"].strip()
    supports = (override.get("supports_form_factors") or "").strip()
    if supports:
        out["supports_form_factors"] = [x.strip() for x in supports.split(",") if x.strip()]
    return out


@lru_cache(maxsize=1)
def _load_rows() -> list[dict]:
    rows: list[dict] = []
    with _CSV.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("type,"):
                continue
            r = next(csv.reader([line]))
            if len(r) < 3:
                continue
            rows.append({"type": r[0].strip(), "name": r[1].strip(), "brand": r[2].strip()})
    return rows


def load_candidates_by_slot() -> dict[str, list[Candidate]]:
    """슬롯별 후보 리스트 (판정 전, verdict='Pass' 기본)."""
    out: dict[str, list[Candidate]] = {}
    for row in _load_rows():
        slot = TYPE_TO_SLOT.get(row["type"])
        if slot is None:
            continue
        pk = row["name"].lower().replace(" ", "-")
        cand = Candidate(
            product_key=pk,
            slot=slot,
            name=row["name"],
            brand=row["brand"],
            price=_mock_price(pk, slot),
            specs={"perf_tier": _mock_tier(pk), **_compat_specs(pk)},   # TODO: 실제 스펙으로 교체
        )
        out.setdefault(slot, []).append(cand)
    return out


# ── 실제 수집 카탈로그(catalog.*_spec, 0015_pc_parts_category_specs.sql) 경로 ──────
# 웹 추천은 이 DB 경로를 직접 사용한다. 콘솔 stage3_0_candidates.run()은
# CATALOG_SOURCE=mock 설정일 때 위 합성 카탈로그를 사용할 수 있다.
# specs 딕셔너리 키는 stage4_optimize.py의 _apply_mainboard_compat와
# build_computer()가 참조하는 이름(socket/mem_type/form_factor/supports_form_factors 및
# 물리·전력 체크용 length_mm/max_gpu_len_mm/height_mm/max_cooler_height_mm/tdp_w/power_w/
# wattage_w)에 맞춘다. perf_tier는 실측이 없어 수집된 제조사 등급(lineup)을 임시 티어로 쓴다
# (표는 config/computer_verification_rules.yaml 의 lineup_perf_tier). 표에 없는 등급이나
# 등급이 없는 행은 키를 넣지 않는다 — 없는 정보를 지어내지 않는다는 기존 철학 그대로.

PC_TYPE_TO_SLOT = {
    "cpu": "CPU", "gpu": "GPU", "ram": "RAM", "motherboard": "메인보드",
    "ssd": "저장장치", "psu": "파워", "case": "케이스", "cooler": "쿨러",
}


def pc_catalog_key(product_type: str, brand: str, model: str) -> str:
    """The stable key shared by imported candidates and the reviewed catalog map."""
    return f"{product_type}:{brand}:{model}".lower().replace(" ", "-")

# (스펙 컬럼 목록, 스펙 테이블) — WHERE/가격 조인은 _build_query가 공통으로 붙인다.
_SPEC_QUERIES: dict[str, tuple[str, str]] = {
    "cpu": ("s.socket, s.tdp_w, s.memory_type, s.lineup, s.max_power_w, s.family", "catalog.cpu_spec"),
    "motherboard": ("s.socket, s.memory_type, s.form_factor, s.supported_cpu_family, s.dimm_slots, s.max_memory_gb, "
                    "s.max_memory_speed_mts, s.m2_slots, s.m2_pcie_gen, s.sata_ports, s.min_bios", "catalog.mainboard_spec"),
    "ram": ("s.memory_type, s.total_capacity_gb, s.speed_mts, s.module_config, s.height_mm", "catalog.ram_spec"),
    "gpu": ("s.length_mm, s.power_w, s.vram_gb, s.lineup, s.recommended_psu_w, s.power_connector, s.aux_power, "
            "s.height_mm, s.slot_thickness", "catalog.gpu_spec"),
    "ssd": ("s.interface, s.protocol, s.form_factor, s.capacity_options", "catalog.ssd_spec"),
    "psu": ("s.wattage_w, s.efficiency_rating, s.form_factor, s.gpu_power_connector, s.length_mm, s.pcie_8pin_count, "
            "s.connector_12v2x6_count", "catalog.psu_spec"),
    "case": ("s.gpu_max_length_mm, s.cpu_cooler_height_mm, s.supported_motherboard, s.psu_form_factor, s.max_psu_length_mm, "
             "s.expansion_slots, s.radiator_front_mm, s.radiator_top_mm, s.radiator_rear_mm, s.color", "catalog.case_spec"),
    "cooler": ("s.cooler_height_mm, s.supported_socket, s.cooling_type, s.radiator_mm", "catalog.cooler_spec"),
}


def _build_query(product_type: str, spec_cols: str, spec_table: str) -> str:
    return f"""
        SELECT p.id, v.id AS variant_id, p.brand, p.model,
               obs.id AS offer_observation_id, obs.price, {spec_cols}
        FROM catalog.product p
        JOIN {spec_table} s ON s.product_id = p.id
        JOIN catalog.product_variant v ON v.product_id = p.id AND v.variant_key = 'default'
        JOIN catalog.offer o ON o.variant_id = v.id AND o.status = 'active'
        JOIN LATERAL (
            SELECT id, price FROM catalog.offer_observation
            WHERE offer_id = o.id AND quality_status = 'valid'
            ORDER BY observed_at DESC LIMIT 1
        ) obs ON true
        WHERE p.product_type = %(product_type)s
    """


def _parse_max_number(text) -> float | None:
    """"8 / 16" 같은 라인업 표기에서 가장 큰 숫자를 뽑는다(하드필터는 "이 라인업 중
    최대치가 요구를 만족하는가"로 본다 — 정확한 SKU까지는 모르니 관대하게)."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    nums = re.findall(r"\d+(?:\.\d+)?", str(text))
    return max(float(n) for n in nums) if nums else None


def _parse_max_capacity_gb(text) -> float | None:
    """"1TB / 2TB / 4TB" 같은 지원 용량 표기에서 최대 용량을 GB 단위로 뽑는다."""
    if not text:
        return None
    best: float | None = None
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(TB|GB)", str(text), re.IGNORECASE):
        gb = float(num) * (1000 if unit.upper() == "TB" else 1)
        best = gb if best is None else max(best, gb)
    return best


def _lineup_perf_tier(product_type: str, lineup) -> float | None:
    """제조사 등급(lineup) -> 1~10 임시 성능 티어. 표에 없으면 None(=정보 없음)."""
    if product_type not in ("cpu", "gpu") or not lineup:
        return None
    from src.engine.stage2_requirement import load_computer_rules  # 순환 import 회피용 지연 import

    table = (load_computer_rules()["requirements"].get("lineup_perf_tier") or {}).get(product_type) or {}
    label = re.sub(r"\s*\(.*?\)\s*$", "", str(lineup)).strip()   # "Flagship (Gaming)" -> "Flagship"
    tier = table.get(label)
    return float(tier) if tier is not None else None


def _specs_from_row(product_type: str, row: dict) -> dict:
    """DB 행 -> stage4 호환 체크가 읽는 specs 키. 없는 값은 아예 안 넣는다(=정보 없음,
    _compat_filter가 이미 그렇게 "통과"로 처리하는 것과 동일한 관례)."""
    specs: dict = {}
    tier = _lineup_perf_tier(product_type, row.get("lineup"))
    if tier is not None:
        specs["perf_tier"] = tier
    if product_type == "cpu":
        if row.get("socket"):
            specs["socket"] = row["socket"]
        if row.get("memory_type"):
            specs["mem_type"] = row["memory_type"]
        if row.get("tdp_w") is not None:
            specs["tdp_w"] = row["tdp_w"]
        if row.get("max_power_w") is not None:
            specs["max_power_w"] = row["max_power_w"]                # Intel MTP/PL2, AMD PPT — 있으면 전력 검사가 TDP 대신 쓴다
        if row.get("family"):
            specs["family"] = row["family"]
    elif product_type == "motherboard":
        if row.get("socket"):
            specs["socket"] = row["socket"]
        if row.get("memory_type"):
            specs["mem_type"] = row["memory_type"]
        if row.get("form_factor"):
            specs["form_factor"] = row["form_factor"]
        if row.get("supported_cpu_family"):
            specs["supported_cpu_family"] = row["supported_cpu_family"]
        for key in ("dimm_slots", "max_memory_gb", "max_memory_speed_mts", "m2_slots", "sata_ports"):
            if row.get(key) is not None:
                specs[key] = row[key]
        for key in ("m2_pcie_gen", "min_bios"):
            if row.get(key):
                specs[key] = row[key]
    elif product_type == "ram":
        if row.get("memory_type"):
            specs["mem_type"] = row["memory_type"]
        if row.get("total_capacity_gb") is not None:
            specs["capacity_gb"] = row["total_capacity_gb"]
        if row.get("speed_mts") is not None:
            specs["speed_mts"] = row["speed_mts"]
        if row.get("module_config"):
            specs["module_config"] = row["module_config"]            # "16GB × 2" — 모듈 개수를 슬롯 수와 비교한다
        if row.get("height_mm") is not None:
            specs["height_mm"] = float(row["height_mm"])
    elif product_type == "gpu":
        if row.get("length_mm") is not None:
            specs["length_mm"] = row["length_mm"]
        if row.get("power_w") is not None:
            specs["power_w"] = row["power_w"]
        if row.get("recommended_psu_w") is not None:
            specs["recommended_psu_w"] = row["recommended_psu_w"]   # 제조사 권장 파워 — 유지 파워와 직접 비교
        if row.get("power_connector"):
            specs["power_connector"] = row["power_connector"]        # "2× 8-pin", "1× 16-pin (12V-2x6)" …
        if row.get("aux_power"):
            specs["aux_power"] = row["aux_power"]                    # O/X — 보조 전원 필요 여부
        if row.get("height_mm") is not None:
            specs["height_mm"] = row["height_mm"]
        thickness = _parse_max_number(row.get("slot_thickness"))     # "2.5" — 차지하는 슬롯 두께
        if thickness is not None:
            specs["slot_thickness"] = thickness
        vram = _parse_max_number(row.get("vram_gb"))  # "8 / 16" 라인업 표기 대응
        if vram is not None:
            specs["vram_gb"] = vram
    elif product_type == "ssd":
        if row.get("interface"):
            specs["interface"] = row["interface"]
        if row.get("protocol"):
            specs["protocol"] = row["protocol"]
        if row.get("form_factor"):
            specs["form_factor"] = row["form_factor"]
        capacity = _parse_max_capacity_gb(row.get("capacity_options"))
        if capacity is not None:
            specs["capacity_gb"] = capacity
    elif product_type == "psu":
        if row.get("wattage_w") is not None:
            specs["wattage_w"] = row["wattage_w"]
        if row.get("efficiency_rating"):
            specs["efficiency_rating"] = row["efficiency_rating"]
        if row.get("form_factor"):
            specs["form_factor"] = row["form_factor"]                # ATX / SFX-L …
        if row.get("gpu_power_connector"):
            specs["gpu_power_connector"] = row["gpu_power_connector"]  # 파워가 제공하는 GPU 커넥터
        for key in ("length_mm", "pcie_8pin_count", "connector_12v2x6_count"):
            if row.get(key) is not None:
                specs[key] = row[key]                                # 길이·PCIe 8핀 커넥터 수·16핀 커넥터 수
    elif product_type == "case":
        if row.get("gpu_max_length_mm") is not None:
            specs["max_gpu_len_mm"] = row["gpu_max_length_mm"]
        if row.get("cpu_cooler_height_mm") is not None:
            specs["max_cooler_height_mm"] = row["cpu_cooler_height_mm"]
        supported = (row.get("supported_motherboard") or "").strip()
        if supported:
            # "ATX / mATX" 같은 원본 표기를 _apply_mainboard_compat가 읽는 리스트로.
            specs["supports_form_factors"] = [x.strip() for x in re.split(r"[/,]", supported) if x.strip()]
        if (row.get("psu_form_factor") or "").strip():
            specs["psu_form_factor"] = row["psu_form_factor"].strip()   # 케이스가 지원하는 파워 크기
        for key in ("max_psu_length_mm", "expansion_slots"):
            if row.get(key) is not None:
                specs[key] = row[key]
        for key in ("radiator_front_mm", "radiator_top_mm", "radiator_rear_mm", "color"):
            if (row.get(key) or "").strip():
                specs[key] = row[key].strip()                          # 라디에이터는 '120;140;240' 형식
    elif product_type == "cooler":
        if row.get("cooler_height_mm") is not None:
            specs["height_mm"] = row["cooler_height_mm"]
        if row.get("supported_socket"):
            specs["supported_socket"] = row["supported_socket"]
        if row.get("cooling_type"):
            specs["cooling_type"] = row["cooling_type"]   # 소음 대용값(휴리스틱)이 읽는다
        if row.get("radiator_mm") is not None:
            specs["radiator_mm"] = row["radiator_mm"]      # 수랭(AIO) 라디에이터 크기
    return specs


def load_candidates_by_slot_from_db(conn) -> dict[str, list[Candidate]]:
    """실제 수집 카탈로그(0015_pc_parts_category_specs.sql)에서 슬롯별 후보를 읽는다.
    가격 관측이 없는(quality_status='valid' 행이 없는) 상품은 후보에서 빠진다 —
    가격 없이 추천에 올리지 않는다는 원칙을 지킨다."""
    from psycopg.rows import dict_row

    out: dict[str, list[Candidate]] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        for product_type, (spec_cols, spec_table) in _SPEC_QUERIES.items():
            slot = PC_TYPE_TO_SLOT[product_type]
            cur.execute(_build_query(product_type, spec_cols, spec_table),
                        {"product_type": product_type})
            rows = cur.fetchall()
            for row in rows:
                price = row.get("price")
                if price is None:
                    continue
                pk = pc_catalog_key(product_type, row["brand"], row["model"])
                out.setdefault(slot, []).append(Candidate(
                    product_key=pk,
                    slot=slot,
                    name=f"{row['brand']} {row['model']}",
                    variant_id=str(row["variant_id"]),
                    offer_observation_id=str(row["offer_observation_id"]),
                    brand=row["brand"],
                    price=int(price),
                    specs=_specs_from_row(product_type, row),
                ))
    return out
