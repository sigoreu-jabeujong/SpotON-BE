import ast
import gzip
import json
import logging
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from etl.localdata import probe
from etl.localdata.client import LocalDataClient
from etl.localdata.constants import Source
from tests.etl.test_localdata_client import envelope, row

CODE = "3130000"
CANARY = "PRIVATE-KEY-ROW-URL-CANARY"
ARGS = ["--source", "general_restaurant", "--authority-code", CODE]


def settings(**changes):
    return Settings(_env_file=None, data_go_kr_service_key=SecretStr(CANARY), **changes)


def payload(rows=None, total=None, page=1):
    rows = [row(CODE, 1)] if rows is None else rows
    return envelope(page=page, total=len(rows) if total is None else total, rows=rows)


def call(handler, **kwargs):
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe.run_probe(
            Source.GENERAL_RESTAURANT, CODE, settings=settings(), client=client, **kwargs
        )
        assert not client.is_closed
        return result


@pytest.mark.parametrize("source", list(Source))
@pytest.mark.parametrize("key", [CANARY, " key+/= %25 "])
def test_request_matches_collector_contract_without_collecting_other_pages(source, key):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=payload(total=1))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = LocalDataClient(SecretStr(key), client=client, max_requests=1)
        collector._fetch_page(source, CODE, 1)
        config = Settings(_env_file=None, data_go_kr_service_key=SecretStr(key))
        result = probe.run_probe(source, CODE, settings=config, client=client)
    assert len(requests) == 2
    assert requests[0].url == requests[1].url
    assert requests[1].url.params["serviceKey"] == key
    assert requests[1].method == "GET" and requests[1].url.scheme == "https"
    assert requests[1].extensions["timeout"] == {"connect": 5, "read": 20, "write": 10, "pool": 5}
    assert result.error is None and result.attempts == 1 and result.row_count == 1
    assert result.total_count == 1 and result.authority_check == "matched"
    assert result.phase == "completed" and result.elapsed_ms >= 0
    assert CANARY not in repr(result)


def test_one_row_read_timeout_is_local_to_probe_and_logs_are_restored(caplog):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=payload(total=900))

    caplog.set_level(logging.DEBUG, logger="httpx")
    caplog.set_level(logging.ERROR, logger="httpcore")
    result = call(handler, rows=1, read_timeout=30)
    assert result.error is None and result.total_count == 900 and result.row_count == 1
    assert requests[0].url.params["numOfRows"] == "1"
    assert requests[0].extensions["timeout"]["read"] == 30
    assert logging.getLogger("httpx").level == logging.DEBUG
    assert logging.getLogger("httpcore").level == logging.ERROR
    assert CANARY not in caplog.text and CODE not in caplog.text


@pytest.mark.parametrize("status", [301, 307, 401, 429, 500, 503])
def test_non_200_never_retries_follows_redirects_or_auth_challenges(status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status,
            headers={
                "location": "https://example.invalid/" + CANARY,
                "www-authenticate": 'Digest realm="test", nonce="test", qop="auth"',
                "retry-after": "1",
            },
            content=CANARY,
        )

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        auth=httpx.DigestAuth(CANARY, CANARY),
    ) as client:
        result = probe.run_probe(
            Source.GENERAL_RESTAURANT, CODE, settings=settings(), client=client
        )
    assert len(requests) == result.attempts == 1
    assert "authorization" not in requests[0].headers
    assert result.error == "http_status" and result.http_status == status
    assert result.total_count is None and result.row_count is None
    assert CANARY not in repr(result)


@pytest.mark.parametrize(
    "exception,error",
    [
        (httpx.ConnectTimeout, "timeout"),
        (httpx.ReadTimeout, "timeout"),
        (httpx.WriteTimeout, "timeout"),
        (httpx.PoolTimeout, "timeout"),
        (httpx.ConnectError, "transport"),
        (httpx.RemoteProtocolError, "transport"),
        (httpx.RequestError, "operation_failed"),
        (KeyboardInterrupt, "interrupted"),
        (RuntimeError, "operation_failed"),
    ],
)
def test_failure_classification_does_not_echo_exception_or_request(exception, error, caplog):
    requests = []

    def handler(request):
        requests.append(request)
        raise exception(CANARY)

    result = call(handler)
    assert result.error == error and result.attempts == 1 and len(requests) == 1
    assert result.http_status is None and result.total_count is None
    assert CANARY not in repr(result) + caplog.text


@pytest.mark.parametrize(
    "value",
    [
        {},
        payload(page=2),
        payload([row(CODE, 1)], total=2),
        payload([row(CODE, 1), row(CODE, 2)], total=1),
        payload([row("3000000", 1)]),
        {"response": {"header": {"resultCode": CANARY}, "body": {}}},
    ],
)
def test_response_contract_mismatches_fail_without_partial_counts(value):
    result = call(lambda _: httpx.Response(200, json=value))
    assert result.error == "contract" and result.http_status == 200
    assert result.total_count is result.row_count is result.authority_check is None
    assert CANARY not in repr(result)


def test_single_object_item_is_not_silently_normalized():
    value = payload()
    value["response"]["body"]["items"]["item"] = row(CODE, 1)
    result = call(lambda _: httpx.Response(200, json=value), rows=1)
    assert result.error == "contract" and result.http_status == 200


@pytest.mark.parametrize(
    "codes,expected",
    [([], "empty"), ([CODE], "matched"), ([CODE, None], "partial_missing"), ([None], "unverified")],
)
def test_empty_and_missing_authority_codes_do_not_claim_filter_verification(codes, expected):
    result = call(
        lambda _: httpx.Response(200, json=payload([row(c, i) for i, c in enumerate(codes)]))
    )
    assert result.error is None and result.authority_check == expected
    assert result.row_count == result.total_count == len(codes)


class Stream(httpx.SyncByteStream):
    def __init__(self, chunks, failure=None, close_failure=None):
        self.chunks = chunks
        self.failure = failure
        self.close_failure = close_failure
        self.closed = False

    def __iter__(self):
        yield from self.chunks
        if self.failure:
            raise self.failure(CANARY)

    def close(self):
        self.closed = True
        if self.close_failure:
            raise self.close_failure(CANARY)


def test_stream_timeout_closes_response_and_never_parses_partial_records():
    stream = Stream([b'{"PRIVATE":'], failure=httpx.ReadTimeout)
    result = call(
        lambda _: httpx.Response(200, headers={"content-type": "application/json"}, stream=stream)
    )
    assert result.error == "timeout" and result.http_status == 200 and stream.closed
    assert result.row_count is None and CANARY not in repr(result)


@pytest.mark.parametrize("declared", [False, True])
def test_oversize_body_is_rejected_before_parser_even_if_cleanup_fails(monkeypatch, declared):
    stream = Stream([b"x" * (probe.MAX_RESPONSE_BYTES + 1)], close_failure=RuntimeError)
    headers = {"content-type": "application/json"}
    if declared:
        headers["content-length"] = str(probe.MAX_RESPONSE_BYTES + 1)
    parse = Mock(side_effect=AssertionError("parser must not run"))
    monkeypatch.setattr(LocalDataClient, "_parse_page", parse)
    result = call(lambda _: httpx.Response(200, headers=headers, stream=stream))
    assert result.error == "response_too_large" and stream.closed
    parse.assert_not_called()


@pytest.mark.parametrize("corrupt", [False, True])
def test_compressed_response_is_decoded_once_or_safely_rejected(corrupt):
    content = CANARY.encode() if corrupt else gzip.compress(json.dumps(payload()).encode())
    stream = Stream([content])
    result = call(
        lambda _: httpx.Response(
            200,
            headers={"content-type": "application/json", "content-encoding": "gzip"},
            stream=stream,
        )
    )
    assert result.error == ("contract" if corrupt else None)
    assert stream.closed and CANARY not in repr(result)


@pytest.mark.parametrize(
    "content_type,content", [("text/html", CANARY), ("application/json", CANARY)]
)
def test_bad_json_or_content_type_is_safe(content_type, content):
    result = call(
        lambda _: httpx.Response(200, headers={"content-type": content_type}, content=content)
    )
    assert result.error == "contract" and CANARY not in repr(result)


def test_small_compressed_body_cannot_bypass_decoded_size_limit(monkeypatch):
    monkeypatch.setattr(probe, "MAX_RESPONSE_BYTES", 1024)
    compressed = gzip.compress(json.dumps(payload()).encode() + b" " * 2048)
    assert len(compressed) < 1024
    stream = Stream([compressed])
    result = call(
        lambda _: httpx.Response(
            200,
            headers={
                "content-type": "application/json",
                "content-encoding": "gzip",
                "content-length": str(len(compressed)),
            },
            stream=stream,
        )
    )
    assert result.error == "response_too_large" and stream.closed


@pytest.mark.parametrize(
    "changes",
    [
        {"source": "PRIVATE-KEY-ROW-URL-CANARY"},
        {"authority_code": "PRIVATE-KEY-ROW-URL-CANARY"},
        {"rows": True},
        {"rows": 10},
        {"read_timeout": True},
        {"read_timeout": float("nan")},
        {"read_timeout": float("inf")},
        {"read_timeout": 0},
        {"read_timeout": 30.1},
    ],
)
def test_direct_invalid_inputs_do_not_load_configuration(changes, monkeypatch):
    configure = Mock(side_effect=AssertionError("must not load settings"))
    monkeypatch.setattr(probe, "Settings", configure)
    result = probe.run_probe(
        **{"source": Source.GENERAL_RESTAURANT, "authority_code": CODE, **changes}
    )
    assert result.error == "arguments" and result.attempts == 0
    assert CANARY not in repr(result)
    configure.assert_not_called()


def test_configuration_construction_failure_has_no_raw_exception(monkeypatch, caplog):
    monkeypatch.setattr(probe, "Settings", Mock(side_effect=ValueError(CANARY)))
    result = probe.run_probe(Source.GENERAL_RESTAURANT, CODE)
    assert result.error == "configuration" and result.attempts == 0
    assert CANARY not in repr(result) + caplog.text


def test_interrupt_while_parsing_arguments_is_summarized(monkeypatch, capsys):
    monkeypatch.setattr(probe.SafeParser, "parse_args", Mock(side_effect=KeyboardInterrupt(CANARY)))
    assert probe.main(ARGS) == 130
    captured = capsys.readouterr()
    value = json.loads(captured.out)
    assert value["error"] == "localdata_probe:interrupted" and value["attempts"] == 0
    assert CANARY not in captured.out + captured.err


@pytest.mark.parametrize("key", [None, "", "   "])
def test_missing_key_is_configuration_without_network(key):
    client = Mock(spec=httpx.Client)
    config = Settings(
        _env_file=None, data_go_kr_service_key=SecretStr(key) if key is not None else None
    )
    result = probe.run_probe(Source.GENERAL_RESTAURANT, CODE, settings=config, client=client)
    assert result.error == "configuration" and result.attempts == 0 and result.elapsed_ms is None
    client.send.assert_not_called()


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
@pytest.mark.parametrize("http_status", [200, 503])
def test_owned_client_cleanup_failure_preserves_primary_error(monkeypatch, failure, http_status):
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(http_status, json=payload()))
    )
    original = client.close

    def close():
        original()
        raise failure(CANARY)

    monkeypatch.setattr(client, "close", close)
    factory = Mock(return_value=client)
    monkeypatch.setattr(probe.httpx, "Client", factory)
    result = probe.run_probe(Source.GENERAL_RESTAURANT, CODE, settings=settings())
    assert client.is_closed and factory.call_count == 1
    expected = (
        "http_status"
        if http_status == 503
        else ("cleanup" if failure is RuntimeError else "interrupted")
    )
    assert result.error == expected and result.row_count is None and CANARY not in repr(result)


@pytest.mark.parametrize(
    "extra",
    [
        ["--url", CANARY],
        ["--source", CANARY],
        ["--authority-code", CANARY],
        ["--rows", "2"],
        ["--read-timeout", "nan"],
        ["--read-timeout", "inf"],
        ["--read-timeout", "31"],
        ["--read-timeout", "0"],
    ],
)
def test_invalid_cli_never_loads_settings_or_echoes_input(extra, monkeypatch, capsys):
    configure = Mock(side_effect=AssertionError("must not load settings"))
    monkeypatch.setattr(probe, "Settings", configure)
    assert probe.main(ARGS + extra) == 2
    captured = capsys.readouterr()
    body = json.loads(captured.out)
    assert body["error"] == "localdata_probe:arguments" and body["attempts"] == 0
    assert captured.out.count("\n") == 1 and not captured.err
    assert CANARY not in captured.out
    configure.assert_not_called()


@pytest.mark.parametrize(
    "error,exit_code",
    [(None, 0), ("configuration", 2), ("timeout", 1), ("contract", 1), ("interrupted", 130)],
)
def test_cli_exit_status_and_summary_are_stable(error, exit_code, monkeypatch, capsys):
    monkeypatch.setattr(probe, "run_probe", Mock(return_value=probe.ProbeResult(error=error)))
    assert probe.main(ARGS) == exit_code
    captured = capsys.readouterr()
    assert json.loads(captured.out)["error"] == ("localdata_probe:" + error if error else None)
    assert captured.out.count("\n") == 1 and not captured.err


def test_help_is_zero_without_network_and_probe_has_no_persistence_dependencies(
    monkeypatch, capsys
):
    execute = Mock()
    monkeypatch.setattr(probe, "run_probe", execute)
    with pytest.raises(SystemExit) as raised:
        probe.main(["--help"])
    assert raised.value.code == 0 and "--authority-code" in capsys.readouterr().out
    execute.assert_not_called()
    tree = ast.parse(Path(probe.__file__).read_text(encoding="utf-8"))
    imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any(
        name.startswith(
            (
                "app.db",
                "sqlalchemy",
                "etl.localdata.runner",
                "etl.localdata.repository",
                "etl.localdata.snapshot",
            )
        )
        for name in imports
    )
