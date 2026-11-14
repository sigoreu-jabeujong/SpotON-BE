import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, NoReturn

from etl.brands.catalog import canonical, parse_json

RULE_VERSION = "chain-membership-estimate-v1"
POLICY_VERSION = "franchised-direct-small-chains-v1"


class ChainsError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise ChainsError("chains:" + code) from None


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def read_json(path: Path, limit: int) -> Any:
    try:
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            fail("file_size")
        return parse_json(raw)
    except (OSError, ValueError):
        fail("file_contract")


def external_path(path: Path) -> Path:
    resolved = path.resolve()
    repo = Path(__file__).resolve().parents[2]
    # Also reject any nested/other Git checkout, including linked worktrees.
    if resolved.is_relative_to(repo) or any((p / ".git").exists() for p in resolved.parents):
        fail("repository_path")
    return resolved


def save_new(path: Path, payload: Any, limit: int) -> None:
    path = external_path(path)
    raw = canonical(payload)
    if len(raw) > limit:
        fail("file_size")
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".chains-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        # Same-directory hard-link publication is atomic and fails if the target exists.
        # A consumer can never observe a partially written final snapshot/plan file.
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)
