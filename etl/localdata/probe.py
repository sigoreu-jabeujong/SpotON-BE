"""One official-source GET with a safe summary; never collect, persist or open a DB."""

import argparse
import json
import math
import time
from dataclasses import asdict, dataclass
from typing import Literal, NoReturn

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from etl.localdata.client import (
    LocalDataClient,
    LocalDataContractError,
    Page,
    _suppress_http_url_logs,
)
from etl.localdata.constants import SEOUL_AUTHORITY_CODES, SOURCE_ENDPOINTS, Source

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
Phase = Literal[
    "arguments", "configuration", "request", "response", "contract", "completed", "cleanup"
]
Failure = Literal[
    "arguments",
    "configuration",
    "timeout",
    "transport",
    "http_status",
    "contract",
    "response_too_large",
    "interrupted",
    "operation_failed",
    "cleanup",
]
AuthorityCheck = Literal["matched", "partial_missing", "unverified", "empty"]


@dataclass
class ProbeResult:
    operation: Literal["localdata_source_probe"] = "localdata_source_probe"
    source: Source | None = None
    scope: Literal["single_seoul_authority_first_page"] = "single_seoul_authority_first_page"
    page_no: int = 1
    requested_rows: int | None = None
    read_timeout_seconds: float | None = None
    phase: Phase = "arguments"
    attempts: int = 0
    http_status: int | None = None
    elapsed_ms: int | None = None
    total_count: int | None = None
    row_count: int | None = None
    authority_check: AuthorityCheck | None = None
    error: Failure | None = None


class ArgumentsError(ValueError):
    pass


class ConfigurationError(ValueError):
    pass


class ResponseTooLarge(ValueError):
    pass


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse's message may contain an untrusted argument or a supplied secret.
        raise ArgumentsError


def _response_page(response: httpx.Response) -> Page:
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type.lower():
        raise LocalDataContractError
    length = response.headers.get("content-length")
    if length is not None and length.isascii() and length.isdigit():
        if len(length) > 20 or int(length) > MAX_RESPONSE_BYTES:
            raise ResponseTooLarge
    parts: list[bytes] = []
    received = 0
    # A decoded chunk may already be large. This is a parser/accumulation limit,
    # not a strict peak-memory bound or an overall HTTP deadline.
    for chunk in response.iter_bytes():
        received += len(chunk)
        if received > MAX_RESPONSE_BYTES:
            raise ResponseTooLarge
        parts.append(chunk)
    # iter_bytes has decoded content: do not copy Content-Encoding and decode twice.
    checked = httpx.Response(200, headers={"content-type": content_type}, content=b"".join(parts))
    return LocalDataClient._parse_page(checked, 1)


def _authority_check(page: Page, authority_code: str) -> AuthorityCheck:
    if any(row.authority_code not in {None, authority_code} for row in page.rows):
        raise LocalDataContractError
    if not page.rows:
        return "empty"
    missing = sum(row.authority_code is None for row in page.rows)
    if missing == len(page.rows):
        return "unverified"
    return "partial_missing" if missing else "matched"


def run_probe(
    source: Source,
    authority_code: str,
    *,
    rows: int = 100,
    read_timeout: float = 20,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> ProbeResult:
    result = ProbeResult()
    active: httpx.Client | None = None
    response: httpx.Response | None = None
    owned = client is None
    started: float | None = None
    # Cover construction, streaming, exception conversion and cleanup URL logs.
    with _suppress_http_url_logs():
        try:
            if (
                not isinstance(source, Source)
                or type(authority_code) is not str
                or authority_code not in SEOUL_AUTHORITY_CODES
                or type(rows) is not int
                or rows not in (1, 100)
                or type(read_timeout) not in (int, float)
                or not math.isfinite(read_timeout)
                or not 0.1 <= read_timeout <= 30
            ):
                raise ArgumentsError
            result.source = source
            result.requested_rows = rows
            result.read_timeout_seconds = float(read_timeout)
            result.phase = "configuration"
            config = settings if settings is not None else Settings()
            key = config.data_go_kr_service_key
            if key is None or not key.get_secret_value().strip():
                raise ConfigurationError
            timeout = httpx.Timeout(10, connect=5, read=float(read_timeout), write=10, pool=5)
            active = client if client is not None else httpx.Client(timeout=timeout)
            params = {
                "serviceKey": key.get_secret_value(),
                "pageNo": "1",
                "numOfRows": str(rows),
                "returnType": "JSON",
                "cond[OPN_ATMY_GRP_CD::EQ]": authority_code,
            }
            result.phase = "request"
            result.attempts = 1
            started = time.monotonic()
            request = active.build_request(
                "GET", SOURCE_ENDPOINTS[source], params=params, timeout=timeout
            )
            response = active.send(request, stream=True, follow_redirects=False, auth=None)
            result.phase = "response"
            result.http_status = response.status_code
            if response.status_code != 200:
                result.error = "http_status"
            else:
                page = _response_page(response)
                result.phase = "contract"
                if len(page.rows) != min(page.total_count, rows):
                    raise LocalDataContractError
                authority = _authority_check(page, authority_code)
                result.total_count = page.total_count
                result.row_count = len(page.rows)
                result.authority_check = authority
                result.phase = "completed"
        except ArgumentsError:
            result.error = "arguments"
        except ConfigurationError:
            result.error = "configuration"
        except ValidationError:
            result.error = "configuration" if result.phase == "configuration" else "contract"
        except httpx.TimeoutException:
            result.error = "timeout"
        except (httpx.DecodingError, LocalDataContractError):
            result.error = "contract"
        except httpx.TransportError:
            result.error = "transport"
        except ResponseTooLarge:
            result.error = "response_too_large"
        except KeyboardInterrupt:
            result.error = "interrupted"
        except Exception:
            result.error = (
                "configuration" if result.phase == "configuration" else "operation_failed"
            )
        finally:
            for close in (
                response.close if response is not None else None,
                active.close if owned and active is not None else None,
            ):
                if close is None:
                    continue
                try:
                    close()
                except KeyboardInterrupt:
                    if result.error is None:
                        result.phase, result.error = "cleanup", "interrupted"
                except Exception:
                    if result.error is None:
                        result.phase, result.error = "cleanup", "cleanup"
            if started is not None:
                result.elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
            if result.error is not None:
                result.total_count = result.row_count = None
                result.authority_check = None
    return result


def main(argv: list[str] | None = None) -> int:
    parser = SafeParser(
        description="One read-only official-source diagnostic GET", allow_abbrev=False
    )
    parser.add_argument("--source", type=Source, choices=list(Source), required=True)
    parser.add_argument("--authority-code", choices=list(SEOUL_AUTHORITY_CODES), required=True)
    parser.add_argument("--rows", type=int, choices=(1, 100), default=100)
    parser.add_argument("--read-timeout", type=float, default=20)
    try:
        args = parser.parse_args(argv)
    except ArgumentsError:
        result = ProbeResult(error="arguments")
    except KeyboardInterrupt:
        result = ProbeResult(error="interrupted")
    else:
        result = run_probe(
            args.source, args.authority_code, rows=args.rows, read_timeout=args.read_timeout
        )
    payload = asdict(result)
    payload["error"] = "localdata_probe:" + result.error if result.error else None
    print(json.dumps(payload, allow_nan=False, separators=(",", ":")), flush=True)
    if result.error == "interrupted":
        return 130
    return 2 if result.error in {"arguments", "configuration"} else int(result.error is not None)


if __name__ == "__main__":
    raise SystemExit(main())
