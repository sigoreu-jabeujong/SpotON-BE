from pathlib import Path

from pydantic import ValidationError

from etl.chains.common import digest, external_path, fail, read_json, save_new
from etl.chains.semas import MAX_BYTES, Snapshot, validate_snapshot


def save_snapshot(path: Path, snapshot: Snapshot) -> None:
    validate_snapshot(snapshot)
    payload = snapshot.model_dump(mode="json")
    save_new(path, dict(payload=payload, sha256=digest(payload)), MAX_BYTES)


def load_snapshot(path: Path) -> Snapshot:
    value = read_json(external_path(path), MAX_BYTES)
    if (
        type(value) is not dict
        or set(value) != {"payload", "sha256"}
        or digest(value["payload"]) != value["sha256"]
    ):
        fail("snapshot_integrity")
    try:
        snapshot = Snapshot.model_validate(value["payload"])
    except ValidationError:
        fail("snapshot_contract")
    return validate_snapshot(snapshot)
