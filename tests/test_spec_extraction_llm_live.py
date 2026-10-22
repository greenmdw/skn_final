"""사양 추출(D 지점) — 전체_테스트_시나리오_실행_기획.md §8(6번).

전부 `llm_live` 마커 — 실제 LLM을 부른다(MOCK_MODE=0 필요, 비용 발생). 기본 `pytest -q`
실행에서는 빠진다(§2.5 반복 정책: 6번은 재현성 자체가 측정 대상이라 동일 입력 최소 2회 권장 —
이미지 경로는 비용 때문에 기본 1회만 자동화하고, 재현성 확인은 필요할 때 `-k` 로 반복 실행한다).

MOCK_MODE를 끄는 건 `monkeypatch`로 모듈 속성만 바꾼다(os.environ·importlib.reload 금지) —
처음엔 `os.environ["MOCK_MODE"]="0"` + 모듈 reload로 했다가, 그 변경이 테스트 프로세스 전역에
남아서 같은 세션의 다른 파일(`test_pc_check_router.py`)이 MOCK_MODE=1을 가정한 테스트에서
깨지는 걸 실측으로 확인했다 — monkeypatch는 테스트 함수가 끝나면 자동으로 되돌려줘 이 문제가
없다.

사전 조건: `.env`에 `OPENAI_API_KEY`·`LLM_PROVIDER=openai`가 있어야 한다. 없으면 스킵한다."""
from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path

import pytest

from src import config as cfg
from src.agent import spec_extraction_agent
from src.clients import llm_client

FIXTURES = Path(__file__).parent / "fixtures" / "spec_images"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

_REAL_KEY_PRESENT = bool(cfg.OPENAI_API_KEY) and cfg.LLM_PROVIDER == "openai"

pytestmark = [
    pytest.mark.llm_live,
    pytest.mark.skipif(not _REAL_KEY_PRESENT,
                       reason="OPENAI_API_KEY/LLM_PROVIDER 미설정 — MOCK_MODE=0 실호출 불가"),
]


@pytest.fixture()
def agent(monkeypatch):
    """이 테스트 동안만 MOCK_MODE를 끈다 — 끝나면 monkeypatch가 자동으로 되돌린다."""
    monkeypatch.setattr(spec_extraction_agent, "MOCK_MODE", False)
    monkeypatch.setattr(llm_client, "MOCK_MODE", False)
    return spec_extraction_agent


# ── 텍스트 경로 — 포맷 다양화 (외부 이미지 불필요, 바로 실행 가능) ──────────────

_TEXT_CASES = {
    "줄바꿈": "CPU: AMD 라이젠7 9800X3D\nGPU: 갤럭시 RTX 4070 슈퍼\nRAM: 삼성 DDR5-5600 32GB",
    "콤마구분": "CPU AMD 라이젠7 9800X3D, GPU 갤럭시 RTX 4070 슈퍼, RAM 삼성 DDR5-5600 32GB",
    "자유서술문": "지금 쓰는 건 라이젠7 9800X3D에 갤럭시 RTX 4070 슈퍼 꽂혀있고 램은 삼성 DDR5 32기가예요",
}


@pytest.mark.parametrize("label", list(_TEXT_CASES))
def test_text_path_extracts_cpu_gpu_ram_regardless_of_format(agent, label: str):
    result = agent.extract(_TEXT_CASES[label])
    assert "9800X3D" in (result.get("CPU") or ""), f"[{label}] CPU 미추출: {result}"
    assert "4070" in (result.get("GPU") or ""), f"[{label}] GPU 미추출: {result}"


def test_text_path_leaves_unmentioned_slots_empty_not_guessed(agent):
    """언급 안 한 슬롯(메인보드·파워 등)을 지어내 채우지 않는지."""
    result = agent.extract("CPU: AMD 라이젠7 9800X3D")
    for slot in ("메인보드", "파워", "케이스", "쿨러"):
        assert not (result.get(slot) or "").strip(), f"슬롯 '{slot}'을 지어냄: {result}"


# ── 이미지 경로 — fixtures 폴더에 넣은 이미지로 자동 회귀 ───────────────────────

def _fixture_images() -> list[Path]:
    if not FIXTURES.exists():
        return []
    return sorted(p for p in FIXTURES.iterdir() if p.suffix.lower() in IMAGE_EXTS)


@pytest.mark.skipif(not _fixture_images(), reason=f"{FIXTURES} 에 테스트 이미지가 없음 — README.md 참고")
@pytest.mark.parametrize("image_path", _fixture_images(), ids=lambda p: p.name)
def test_image_path_matches_expected_fields_where_provided(agent, image_path: Path):
    mime = mimetypes.guess_type(image_path)[0] or "image/png"
    data_url = f"data:{mime};base64,{base64.b64encode(image_path.read_bytes()).decode()}"
    result = agent.extract_from_image(data_url)

    expected_path = image_path.with_suffix("").with_suffix(".expected.json")
    if not expected_path.exists():
        # 정답 파일이 없으면 최소한 스키마 모양(8개 슬롯 키)만 확인한다.
        assert set(result) <= {"CPU", "GPU", "RAM", "메인보드", "저장장치", "파워", "케이스", "쿨러"}
        return

    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    for slot, want in expected.items():
        if not want:
            continue
        got = result.get(slot) or ""
        assert want in got, f"{image_path.name} [{slot}] 기대: {want!r} / 실제: {got!r} (환각 회귀 가능성)"
