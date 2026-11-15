"""Read-only B2 connection check; preview never reads process credentials or uses HTTP."""

import json
import math
import os
import re
import stat
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from etl.operation_logs import archive
from etl.operation_logs.__main__ import ArgumentsError, SafeParser
from etl.operation_logs.validation import Rejected, _constant, _pairs

RULE = "b2-preflight-v1"
AUTHORIZE = "https://api.backblazeb2.com/b2api/v4/b2_authorize_account"
MAX_CONFIG, MAX_BODY, MAX_TOTAL = 16384, 1024**2, 2 * 1024**2
SECONDS = 30
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}")
BUCKET = re.compile(r"[A-Za-z0-9.-]{6,63}")
REGION = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
PREFIX = re.compile(r"[A-Za-z0-9._/-]{2,128}")
API_HOST = re.compile(r"api[0-9]{3}\.backblazeb2\.com")
BACKUP_CAPS = frozenset({"listBuckets", "listFiles", "readFiles", "writeFiles", "deleteFiles"})
ALLOWED_CAPS = BACKUP_CAPS | {
    "readBuckets",
    "readBucketEncryption",
    "readBucketRetentions",
    "readFileRetentions",
    "readFileLegalHolds",
    "readBucketReplications",
    "readBucketNotifications",
    "shareFiles",
}
ERRORS = frozenset(
    {
        "credentials",
        "authentication",
        "provider_denied_or_cap",
        "rate_limit",
        "redirect",
        "http",
        "timeout",
        "network",
        "network_budget",
        "response_limit",
        "payload",
        "api_url",
        "region",
        "scope",
        "capability",
        "bucket_mismatch",
        "bucket_not_private",
        "request_limit",
        "internal",
    }
)


class PreflightError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason if reason in ERRORS else "internal"
        super().__init__(self.reason)


@dataclass(frozen=True, repr=False)
class Config:
    bucket_name: str
    region: str
    prefix: str


@dataclass(frozen=True, repr=False)
class Credentials:
    key_id: SecretStr
    key: SecretStr


@dataclass(frozen=True, repr=False)
class Authorization:
    account_id: str
    bucket_id: str
    api_url: str
    token: SecretStr
    backup_capabilities_complete: bool


@dataclass
class Result:
    status: str = "ok"
    error: str | None = None
    mode: str = "dry_run"
    phase: str = "validation"
    rule_version: str = RULE
    config_verified: bool = False
    credentials_read_attempted: bool = False
    credentials_validated: bool = False
    requests_attempted: int = 0
    authorization_verified: bool = False
    key_scope_verified: bool = False
    region_verified: bool = False
    bucket_private_verified: bool = False
    backup_capabilities_complete: bool = False
    connection_verified: bool = False
    backup_objects_modified: bool = False
    bucket_settings_modified: bool = False
    billing_verified: bool = False
    retention_verified: bool = False
    remote_backup_verified: bool = False


def _float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise PreflightError("payload")
    return number


def _json(raw: bytes) -> Any:
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=_constant,
            parse_float=_float,
        )
    except (ValueError, UnicodeError, RecursionError):
        raise PreflightError("payload") from None


def _fingerprint(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink


def read_config(path: Path) -> Config:
    try:
        identity = archive.validate_file_path(path, suffix=".json")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            before = os.fstat(fd)
            if (
                (before.st_dev, before.st_ino) != identity
                or before.st_nlink != 1
                or not stat.S_ISREG(before.st_mode)
                or not 0 < before.st_size <= MAX_CONFIG
            ):
                raise ArgumentsError
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(MAX_CONFIG + 1)
            if (
                len(raw) > MAX_CONFIG
                or _fingerprint(os.fstat(fd)) != _fingerprint(before)
                or archive._identity(path) != identity
            ):
                raise ArgumentsError
        finally:
            os.close(fd)
        data = _json(raw)
        if (
            type(data) is not dict
            or set(data) != {"bucket_name", "region", "prefix"}
            or any(type(v) is not str for v in data.values())
        ):
            raise ArgumentsError
        name, region, prefix = data["bucket_name"], data["region"], data["prefix"]
        if (
            not BUCKET.fullmatch(name)
            or name.startswith(".")
            or name.endswith(".")
            or ".." in name
            or name.lower().startswith("b2-")
            or re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", name)
            or not REGION.fullmatch(region)
            or not PREFIX.fullmatch(prefix)
            or not prefix.endswith("/")
            or any(p in {"", ".", ".."} for p in prefix[:-1].split("/"))
        ):
            raise ArgumentsError
        return Config(name, region, prefix)
    except (archive.ArchiveError, OSError, ValueError, Rejected):
        raise ArgumentsError from None


def _credentials() -> Credentials:
    key_id = os.getenv("B2_APPLICATION_KEY_ID", "")
    key = os.getenv("B2_APPLICATION_KEY", "")
    if not IDENTIFIER.fullmatch(key_id) or not _printable(key, 512):
        raise PreflightError("credentials")
    return Credentials(SecretStr(key_id), SecretStr(key))


def _printable(value: object, maximum: int) -> bool:
    return (
        type(value) is str and 0 < len(value) <= maximum and all(33 <= ord(c) <= 126 for c in value)
    )


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PreflightError("payload")
    return value


def _identifier(value: Any) -> str:
    if type(value) is not str or not IDENTIFIER.fullmatch(value):
        raise PreflightError("payload")
    return value


def _same_bucket_name(value: Any, expected: str) -> bool:
    return (
        type(value) is str and bool(BUCKET.fullmatch(value)) and value.lower() == expected.lower()
    )


def parse_authorization(data: Any, config: Config) -> Authorization:
    root = _object(data)
    account = _identifier(root.get("accountId"))
    token = root.get("authorizationToken")
    if type(token) is not str or not _printable(token, 1024):
        raise PreflightError("payload")
    storage = _object(_object(root.get("apiInfo")).get("storageApi"))
    url = storage.get("apiUrl")
    if type(url) is not str or len(url) > 128:
        raise PreflightError("api_url")
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        base = "https://" + host
        if (
            parsed.scheme != "https"
            or not API_HOST.fullmatch(host)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.query
            or parsed.fragment
            or url not in {base, base + "/"}
        ):
            raise PreflightError("api_url")
    except ValueError:
        raise PreflightError("api_url") from None
    if storage.get("s3ApiUrl") != "https://s3." + config.region + ".backblazeb2.com":
        raise PreflightError("region")
    allowed = _object(storage.get("allowed"))
    buckets = allowed.get("buckets")
    if type(buckets) is not list or len(buckets) != 1:
        raise PreflightError("scope")
    bucket = _object(buckets[0])
    name = bucket.get("name")
    if (
        not _same_bucket_name(name, config.bucket_name)
        or allowed.get("namePrefix") != config.prefix
    ):
        raise PreflightError("scope")
    bucket_id = _identifier(bucket.get("id"))
    caps = allowed.get("capabilities")
    if (
        type(caps) is not list
        or not 0 < len(caps) <= 64
        or any(type(v) is not str or not 0 < len(v) <= 64 for v in caps)
    ):
        raise PreflightError("payload")
    capabilities = set(caps)
    if len(capabilities) != len(caps):
        raise PreflightError("payload")
    if "listBuckets" not in capabilities or not capabilities <= ALLOWED_CAPS:
        raise PreflightError("capability")
    return Authorization(account, bucket_id, base, SecretStr(token), BACKUP_CAPS <= capabilities)


def check_bucket(data: Any, config: Config, auth: Authorization) -> None:
    buckets = _object(data).get("buckets")
    if type(buckets) is not list or len(buckets) != 1:
        raise PreflightError("bucket_mismatch")
    bucket = _object(buckets[0])
    name = bucket.get("bucketName")
    if (
        bucket.get("accountId") != auth.account_id
        or bucket.get("bucketId") != auth.bucket_id
        or not _same_bucket_name(name, config.bucket_name)
    ):
        raise PreflightError("bucket_mismatch")
    if bucket.get("bucketType") != "allPrivate":
        raise PreflightError("bucket_not_private")


class Reader:
    def __init__(self, client: httpx.Client, result: Result) -> None:
        self.client, self.result = client, result
        self.deadline = time.monotonic() + SECONDS
        self.total = 0

    def check(self) -> None:
        if time.monotonic() >= self.deadline:
            raise PreflightError("network_budget")

    def request(
        self,
        method: str,
        url: str,
        *,
        auth: httpx.Auth | None = None,
        token: SecretStr | None = None,
        body: dict[str, str] | None = None,
    ) -> Any:
        self.check()
        if self.result.requests_attempted >= 2:
            raise PreflightError("request_limit")
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        if token is not None:
            headers["Authorization"] = token.get_secret_value()
        self.result.requests_attempted += 1
        timeout = max(0.001, min(5, self.deadline - time.monotonic()))
        with self.client.stream(
            method,
            url,
            auth=auth,
            headers=headers,
            json=body,
            timeout=timeout,
            follow_redirects=False,
        ) as response:
            status = response.status_code
            if status != 200:
                reason = (
                    "authentication"
                    if status == 401
                    else "provider_denied_or_cap"
                    if status == 403
                    else "rate_limit"
                    if status == 429
                    else "redirect"
                    if 300 <= status < 400
                    else "http"
                )
                raise PreflightError(reason)
            if (
                response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                != "application/json"
                or response.headers.get("content-encoding", "identity").lower() != "identity"
            ):
                raise PreflightError("payload")
            length = response.headers.get("content-length")
            if length is not None:
                if not re.fullmatch(r"[0-9]{1,20}", length):
                    raise PreflightError("payload")
                if int(length) > MAX_BODY:
                    raise PreflightError("response_limit")
            raw = bytearray()
            for chunk in response.iter_bytes(chunk_size=8192):
                self.check()
                self.total += len(chunk)
                if len(raw) + len(chunk) > MAX_BODY or self.total > MAX_TOTAL:
                    raise PreflightError("response_limit")
                raw.extend(chunk)
        self.check()
        value = _json(bytes(raw))
        self.check()
        return value


def _client() -> httpx.Client:
    return httpx.Client(
        transport=httpx.HTTPTransport(retries=0, verify=True, trust_env=False),
        trust_env=False,
        verify=True,
        follow_redirects=False,
        timeout=5,
    )


def _run(
    path: Path,
    result: Result,
    *,
    execute: bool,
    client_factory: Callable[[], httpx.Client] | None = None,
) -> None:
    result.mode = "execute" if execute else "dry_run"
    try:
        config = read_config(path)
        result.config_verified = True
        if not execute:
            result.phase = "preview"
            return
        result.phase = "credentials"
        result.credentials_read_attempted = True
        credentials = _credentials()
        result.credentials_validated = True
        with (client_factory or _client)() as client:
            reader = Reader(client, result)
            result.phase = "authorize"
            data = reader.request(
                "GET",
                AUTHORIZE,
                auth=httpx.BasicAuth(
                    credentials.key_id.get_secret_value(), credentials.key.get_secret_value()
                ),
            )
            result.phase = "scope"
            auth = parse_authorization(data, config)
            result.authorization_verified = result.key_scope_verified = result.region_verified = (
                True
            )
            result.backup_capabilities_complete = auth.backup_capabilities_complete
            result.phase = "bucket"
            check_bucket(
                reader.request(
                    "POST",
                    auth.api_url + "/b2api/v4/b2_list_buckets",
                    token=auth.token,
                    body={"accountId": auth.account_id, "bucketName": config.bucket_name},
                ),
                config,
                auth,
            )
            result.bucket_private_verified = True
        result.connection_verified = True
        result.phase = "completed"
    except ArgumentsError:
        result.status, result.error = "failed", "arguments"
    except PreflightError as exc:
        result.status, result.error = "failed", exc.reason
    except httpx.TimeoutException:
        result.status, result.error = "failed", "timeout"
    except httpx.HTTPError:
        result.status, result.error = "failed", "network"
    except KeyboardInterrupt:
        result.status, result.error = "interrupted", "interrupted"
    except Exception:
        result.status, result.error = "failed", "internal"


def run(
    path: Path, *, execute: bool = False, client_factory: Callable[[], httpx.Client] | None = None
) -> Result:
    result = Result()
    _run(path, result, execute=execute, client_factory=client_factory)
    return result


def main(argv: list[str] | None = None) -> int:
    result = Result()
    try:
        parser = SafeParser(prog="python -m etl.operation_logs.b2_preflight", allow_abbrev=False)
        parser.add_argument("--config", required=True, type=Path)
        parser.add_argument("--execute", action="store_true")
        args = parser.parse_args(argv)
        result.mode = "execute" if args.execute else "dry_run"
        _run(args.config, result, execute=args.execute)
    except ArgumentsError:
        result.status, result.error = "failed", "arguments"
    except KeyboardInterrupt:
        result.status, result.error = "interrupted", "interrupted"
    except Exception:
        result.status, result.error = "failed", "internal"
    print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
    return (
        0
        if result.status == "ok"
        else 130
        if result.status == "interrupted"
        else 2
        if (result.error == "arguments")
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
