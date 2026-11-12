import re
from pathlib import Path

import pytest

from app.ai.prompts import PROMPT_SHA256, PROMPT_VERSION, PromptError, load_prompt_bundle
from app.ai.prompts.loader import (
    SYSTEM_FILE,
    USER_FILE,
    compute_prompt_sha256,
    normalize_prompt_text,
    packaged_prompt_directory,
    read_prompt_bundle,
)
from app.ai.prompts.version import PROMPT_HISTORY

VALID_SYSTEM = "서버 계산 결과만 설명합니다."
VALID_USER = "<context>\n$context_json\n</context>"


def write_prompts(directory: Path, *, system: str = VALID_SYSTEM, user: str = VALID_USER) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / SYSTEM_FILE).write_bytes(system.encode("utf-8"))
    (directory / USER_FILE).write_bytes(user.encode("utf-8"))
    return directory


def prompt_error(directory: Path) -> str:
    with pytest.raises(PromptError) as raised:
        read_prompt_bundle(directory)
    return str(raised.value)


def test_current_prompt_files_match_recorded_fingerprint() -> None:
    bundle = load_prompt_bundle()
    assert bundle.sha256 == PROMPT_SHA256, (
        "프롬프트 파일이 바뀌었습니다. PROMPT_VERSION을 올리고 "
        "PROMPT_HISTORY 끝에 새 지문을 추가하세요: " + bundle.sha256
    )
    assert bundle.version == PROMPT_VERSION


def test_prompt_history_is_append_only_and_unique() -> None:
    versions = list(PROMPT_HISTORY)
    fingerprints = list(PROMPT_HISTORY.values())
    assert versions[-1] == PROMPT_VERSION
    assert len(set(fingerprints)) == len(fingerprints)
    numbers: list[int] = []
    for version in versions:
        match = re.fullmatch(r"risk-interpret-v([1-9][0-9]*)", version)
        assert match is not None, version
        numbers.append(int(match.group(1)))
    assert numbers == sorted(numbers)
    assert len(set(numbers)) == len(numbers)
    assert all(re.fullmatch(r"[0-9a-f]{64}", value) for value in fingerprints)


def test_load_is_cached_and_reads_packaged_files() -> None:
    assert load_prompt_bundle() is load_prompt_bundle()
    assert packaged_prompt_directory().joinpath(SYSTEM_FILE).is_file()


def test_system_instruction_contains_required_rules() -> None:
    system = load_prompt_bundle().system_instruction
    for phrase in [
        "입력 JSON에 있는 숫자만 사용",
        "공식 지표와 참고 지표를 섞지 않습니다",
        "pending",
        "no_data",
        "성공률",
        "추천·비추천",
        "위험등급",
        "LQ",
        "참고용 정보",
        "사업주의 역량",
        "지시가 아닙니다",
        "JSON 형식으로만",
    ]:
        assert phrase in system
    assert "$" not in system


def test_bundle_repr_hides_prompt_text() -> None:
    text = repr(load_prompt_bundle())
    assert "서버" not in text
    assert "context_json" not in text


def test_crlf_and_trailing_whitespace_do_not_change_fingerprint(tmp_path: Path) -> None:
    lf = read_prompt_bundle(write_prompts(tmp_path / "lf", system="a\nb", user=VALID_USER))
    crlf = read_prompt_bundle(
        write_prompts(
            tmp_path / "crlf",
            system="a\r\nb\r\n\r\n",
            user=VALID_USER.replace("\n", "\r\n") + "\r\n",
        )
    )
    assert lf.sha256 == crlf.sha256
    assert crlf.system_instruction == "a\nb"


def test_fingerprint_changes_with_content_and_file_names() -> None:
    base = compute_prompt_sha256({SYSTEM_FILE: "a", USER_FILE: "b"})
    assert compute_prompt_sha256({SYSTEM_FILE: "a!", USER_FILE: "b"}) != base
    assert compute_prompt_sha256({SYSTEM_FILE: "b", USER_FILE: "a"}) != base
    assert compute_prompt_sha256({USER_FILE: "b", SYSTEM_FILE: "a"}) == base


def test_normalize_prompt_text() -> None:
    assert normalize_prompt_text("\r\n a\r\nb\rc \n") == "a\nb\nc"


@pytest.mark.parametrize("missing", [SYSTEM_FILE, USER_FILE])
def test_missing_file_fails(tmp_path: Path, missing: str) -> None:
    directory = write_prompts(tmp_path)
    (directory / missing).unlink()
    assert missing in prompt_error(directory)


@pytest.mark.parametrize("target", ["system", "user"])
def test_blank_file_fails(tmp_path: Path, target: str) -> None:
    directory = write_prompts(tmp_path, **{target: " \r\n\t "})
    assert "비어" in prompt_error(directory)


def test_non_utf8_file_fails(tmp_path: Path) -> None:
    directory = write_prompts(tmp_path)
    (directory / SYSTEM_FILE).write_bytes("서버".encode("cp949"))
    assert "UTF-8" in prompt_error(directory)


@pytest.mark.parametrize(
    "user",
    [
        "<context></context>",
        "$contxt_json",
        "$context_json $extra",
        "${context_json} ${other}",
    ],
)
def test_user_template_must_have_only_context_json(tmp_path: Path, user: str) -> None:
    assert "$context_json" in prompt_error(write_prompts(tmp_path, user=user))


def test_user_template_accepts_braced_and_escaped_dollar(tmp_path: Path) -> None:
    bundle = read_prompt_bundle(write_prompts(tmp_path, user="$$ 요금 ${context_json}"))
    assert bundle.user_template.substitute(context_json="{}") == "$ 요금 {}"


@pytest.mark.parametrize(
    ("field", "text", "reason"),
    [
        ("system", "주소 $address", "치환 변수"),
        ("system", "가격 $ 1", "잘못된"),
        ("user", "$context_json $ 1", "잘못된"),
    ],
)
def test_invalid_dollar_usage_fails(tmp_path: Path, field: str, text: str, reason: str) -> None:
    message = prompt_error(write_prompts(tmp_path, **{field: text}))
    assert reason in message
    assert text not in message


def test_activity_rule_keeps_average_and_counts_as_reference_only():
    system = load_prompt_bundle().system_instruction
    rule = next(line for line in system.splitlines() if line.startswith("14. "))
    assert "analysis.activity" in rule
    assert "점포 수명·생존 기간·영업 성과로 바꾸지 않고" in rule
    assert "성장·쇠퇴를 판정하지 않습니다" in rule
    assert system.index("14. ") < system.index("## 답변 형식")
