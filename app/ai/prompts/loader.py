"""프롬프트 파일 읽기·검증·지문 계산.

검증 실패는 앱 시작이 아니라 처음 사용할 때 PromptError로 드러난다. 메시지에는 파일 이름과
사유만 넣고 프롬프트 내용은 넣지 않는다.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.resources import files
from importlib.resources.abc import Traversable
from string import Template

from app.ai.prompts.version import PROMPT_VERSION

SYSTEM_FILE = "system.md"
USER_FILE = "user.md"
PROMPT_FILES = (SYSTEM_FILE, USER_FILE)
USER_TEMPLATE_IDENTIFIERS = frozenset({"context_json"})


class PromptError(Exception):
    """프롬프트 파일이 없거나 형식이 잘못됨."""


@dataclass(frozen=True)
class PromptBundle:
    version: str
    sha256: str
    system_instruction: str = field(repr=False)
    user_template: Template = field(repr=False)


def normalize_prompt_text(text: str) -> str:
    """줄바꿈을 LF로 맞추고 앞뒤 공백을 지운다. OS·편집기 차이로 지문이 바뀌지 않게 한다."""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def compute_prompt_sha256(contents: Mapping[str, str]) -> str:
    """파일 이름 순서로 `이름\\0내용\\0`을 이어 붙인 SHA-256. 내용은 정규화된 값이어야 한다."""
    digest = hashlib.sha256()
    for name in sorted(contents):
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(contents[name].encode("utf-8") + b"\0")
    return digest.hexdigest()


def _read(directory: Traversable, name: str) -> str:
    path = directory / name
    if not path.is_file():
        raise PromptError(f"{name}: 프롬프트 파일이 없습니다")
    try:
        text = normalize_prompt_text(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        raise PromptError(f"{name}: UTF-8로 읽을 수 없습니다") from None
    if not text:
        raise PromptError(f"{name}: 프롬프트 내용이 비어 있습니다")
    return text


def read_prompt_bundle(directory: Traversable) -> PromptBundle:
    contents = {name: _read(directory, name) for name in PROMPT_FILES}

    system = Template(contents[SYSTEM_FILE])
    if not system.is_valid():
        raise PromptError(f"{SYSTEM_FILE}: 잘못된 $ 표기가 있습니다")
    if system.get_identifiers():
        raise PromptError(f"{SYSTEM_FILE}: 시스템 지침에는 치환 변수를 둘 수 없습니다")

    user = Template(contents[USER_FILE])
    if not user.is_valid():
        raise PromptError(f"{USER_FILE}: 잘못된 $ 표기가 있습니다")
    if set(user.get_identifiers()) != USER_TEMPLATE_IDENTIFIERS:
        raise PromptError(f"{USER_FILE}: 치환 변수는 $context_json 하나여야 합니다")

    return PromptBundle(
        version=PROMPT_VERSION,
        sha256=compute_prompt_sha256(contents),
        system_instruction=contents[SYSTEM_FILE],
        user_template=user,
    )


def packaged_prompt_directory() -> Traversable:
    return files("app.ai.prompts") / "risk_interpret"


@lru_cache(maxsize=1)
def load_prompt_bundle() -> PromptBundle:
    return read_prompt_bundle(packaged_prompt_directory())
