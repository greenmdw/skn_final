from src.categories import load_category
from src.services.session_service import _canonicalize_answer_values


def _question(question_id):
    return next(q for q in load_category("computer")["question_sets"] if q["id"] == question_id)


def test_answer_labels_are_restored_to_their_values():
    assert _canonicalize_answer_values(_question("q_purpose"), ["게임"]) == ["game"]
    assert _canonicalize_answer_values(_question("q_purpose"), ["game"]) == ["game"]
    assert _canonicalize_answer_values(_question("q_resolution"), ["QHD 165Hz"]) == ["QHD_165"]


def test_string_values_stay_strings_for_the_psu_chip():
    # owned_psu_w 의 값은 전부 문자열이다(시드가 JSON sort_keys 로 저장하므로 숫자와 섞이면 안 된다)
    assert _canonicalize_answer_values(_question("q_owned_psu"), ["500"]) == ["500"]
    assert _canonicalize_answer_values(_question("q_owned_psu"), ["500~650W"]) == ["500"]
