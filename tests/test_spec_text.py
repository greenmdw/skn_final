"""사양 텍스트 규칙 기반 파서(src.engine.spec_text) — LLM 추출이 꺼졌을 때의 fallback."""
from __future__ import annotations

from src.engine.spec_text import parse_spec_text


def test_reads_all_eight_slot_keys_including_storage():
    text = ("CPU: i5-13600K\nGPU: RTX 3060\nRAM: DDR4 16GB\n메인보드: AM4 DDR4\n"
            "저장장치: Samsung 990 PRO 1TB\n파워: 650W\n케이스: 미들타워\n쿨러: 순정\n")
    assert parse_spec_text(text) == {
        "CPU": "i5-13600K", "GPU": "RTX 3060", "RAM": "DDR4 16GB", "메인보드": "AM4 DDR4",
        "저장장치": "Samsung 990 PRO 1TB", "파워": "650W", "케이스": "미들타워", "쿨러": "순정",
    }


def test_english_and_korean_aliases_map_to_the_same_slot():
    assert parse_spec_text("SSD: 990 PRO") == {"저장장치": "990 PRO"}
    assert parse_spec_text("Storage: 990 PRO") == {"저장장치": "990 PRO"}
    assert parse_spec_text("그래픽카드: RTX 4070") == {"GPU": "RTX 4070"}
    assert parse_spec_text("Power: 750W") == {"파워": "750W"}


def test_free_flowing_sentences_are_not_recognised():
    # 이게 이 파서의 한계다 — LLM 추출(spec_extraction_agent)이 우선인 이유.
    assert parse_spec_text("라이젠 7800X3D에 4070 SUPER 얹었어요") == {}
    assert parse_spec_text("아무 말\n") == {}
    assert parse_spec_text("") == {}
