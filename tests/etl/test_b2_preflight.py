import base64
import json
import os
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest

from etl.operation_logs import b2_preflight as b2

CANARY = "PRIVATE_B2_CANARY"
KEY_ID, KEY = "fake-key-id", "FAKE_KEY_CANARY"
TOKEN, ACCOUNT, BUCKET_ID = "FAKE_TOKEN_CANARY", "FAKE_ACCOUNT_CANARY", "FAKE_BUCKET_CANARY"
VALUES = dict(bucket_name="SpotON.Test-Logs", region="us-west-001", prefix="spoton-operation-logs/")
CAPS = ["listBuckets", "listFiles", "readFiles", "writeFiles", "deleteFiles"]


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "b2-target.json"
    path.write_text(json.dumps(VALUES), encoding="utf-8")
    return path


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setenv("B2_APPLICATION_KEY_ID", KEY_ID)
    monkeypatch.setenv("B2_APPLICATION_KEY", KEY)


def auth_data():
    return dict(
        accountId=ACCOUNT,
        authorizationToken=TOKEN,
        apiInfo=dict(
            storageApi=dict(
                apiUrl="https://api001.backblazeb2.com",
                s3ApiUrl="https://s3.us-west-001.backblazeb2.com",
                allowed=dict(
                    buckets=[dict(id=BUCKET_ID, name=VALUES["bucket_name"].lower())],
                    namePrefix=VALUES["prefix"],
                    capabilities=CAPS[:],
                ),
            )
        ),
    )


def bucket_data():
    return dict(
        buckets=[
            dict(
                accountId=ACCOUNT,
                bucketId=BUCKET_ID,
                bucketName=VALUES["bucket_name"].upper(),
                bucketType="allPrivate",
            )
        ]
    )


def fake_client(handler=None, data=None):
    state = dict(created=0, closed=False, requests=[])
    data = data if data is not None else [auth_data(), bucket_data()]

    def dispatch(request):
        state["requests"].append(request)
        if handler is not None:
            return handler(request, len(state["requests"]))
        return httpx.Response(200, json=data[len(state["requests"]) - 1])

    class Transport(httpx.MockTransport):
        def close(self):
            state["closed"] = True

    def factory():
        state["created"] += 1
        # Deliberately hostile defaults: Reader must override auth/redirect/encoding.
        return httpx.Client(
            transport=Transport(dispatch),
            follow_redirects=True,
            auth=("DEFAULT_ID_CANARY", "DEFAULT_KEY_CANARY"),
            headers={"Accept-Encoding": "gzip"},
        )

    return factory, state


def safe_result(result):
    value = asdict(result)
    assert all(
        v not in json.dumps(value)
        for v in (KEY, TOKEN, ACCOUNT, BUCKET_ID, CANARY, VALUES["bucket_name"], VALUES["prefix"])
    )
    assert not any(
        value[n]
        for n in (
            "backup_objects_modified",
            "bucket_settings_modified",
            "billing_verified",
            "retention_verified",
            "remote_backup_verified",
        )
    )
    assert value["error"] is None or value["error"] in b2.ERRORS | {"arguments", "interrupted"}


def test_error_vocabulary_is_fixed():
    assert b2.ERRORS == frozenset(
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


@pytest.mark.parametrize("stage", ["scope", "bucket"])
def test_non_ascii_bucket_name_cannot_match_by_unicode_lowercase(config, credentials, stage):
    name = "spoton-kelvin-logs"
    confusable = "spoton-\u212aelvin-logs"
    assert confusable.lower() == name
    config.write_text(json.dumps(VALUES | {"bucket_name": name}), encoding="utf-8")
    auth, bucket = auth_data(), bucket_data()
    auth["apiInfo"]["storageApi"]["allowed"]["buckets"][0]["name"] = (
        confusable if stage == "scope" else name
    )
    bucket["buckets"][0]["bucketName"] = confusable if stage == "bucket" else name
    factory, state = fake_client(data=[auth, bucket])
    result = b2.run(config, execute=True, client_factory=factory)
    assert result.error == ("scope" if stage == "scope" else "bucket_mismatch")
    assert result.requests_attempted == (1 if stage == "scope" else 2)
    assert not result.connection_verified and state["closed"]
    assert result.key_scope_verified == (stage == "bucket")
    safe_result(result)


def test_two_read_operations_have_separate_auth_and_verified_scope(config, credentials):
    factory, state = fake_client()
    before = config.read_bytes()
    result = b2.run(config, execute=True, client_factory=factory)
    assert result.status == "ok" and result.connection_verified and result.requests_attempted == 2
    assert (
        result.config_verified
        and result.credentials_read_attempted
        and result.credentials_validated
    )
    assert result.authorization_verified and result.key_scope_verified and result.region_verified
    assert result.bucket_private_verified and result.backup_capabilities_complete
    assert state["created"] == 1 and state["closed"] and config.read_bytes() == before
    first, second = state["requests"]
    assert (first.method, str(first.url)) == ("GET", b2.AUTHORIZE)
    assert (
        first.headers["Authorization"]
        == "Basic " + base64.b64encode((KEY_ID + ":" + KEY).encode()).decode()
    )
    assert not first.content
    assert (second.method, str(second.url)) == (
        "POST",
        "https://api001.backblazeb2.com/b2api/v4/b2_list_buckets",
    )
    assert second.headers["Authorization"] == TOKEN
    assert json.loads(second.content) == dict(accountId=ACCOUNT, bucketName=VALUES["bucket_name"])
    for request in state["requests"]:
        assert request.headers["Accept-Encoding"] == "identity"
        assert all(0 < value <= 5 for value in request.extensions["timeout"].values())
    safe_result(result)


def test_preview_does_not_read_credentials_or_construct_http(config, monkeypatch):
    original = os.getenv

    def getenv(name, *args):
        if name.startswith("B2_"):
            pytest.fail("preview must not read credentials")
        return original(name, *args)

    def forbidden(*args, **kwargs):
        pytest.fail("preview must not construct HTTP objects")

    monkeypatch.setattr(os, "getenv", getenv)
    monkeypatch.setattr(b2.httpx, "Client", forbidden)
    monkeypatch.setattr(b2.httpx, "HTTPTransport", forbidden)
    before = {p.name: p.read_bytes() for p in config.parent.iterdir()}
    result = b2.run(config)
    assert result.status == "ok" and result.phase == "preview" and result.config_verified
    assert not result.credentials_read_attempted and result.requests_attempted == 0
    assert not result.connection_verified
    assert before == {p.name: p.read_bytes() for p in config.parent.iterdir()}
    safe_result(result)


@pytest.mark.parametrize(
    "changes",
    [
        {"bucket_name": "tiny"},
        {"bucket_name": "a" * 64},
        {"bucket_name": "bad_name"},
        {"bucket_name": ".bad-bucket"},
        {"bucket_name": "bad..bucket"},
        {"bucket_name": "b2-reserved"},
        {"bucket_name": "192.168.5.4"},
        {"region": "UPPER"},
        {"region": "-invalid"},
        {"region": "x" * 64},
        {"prefix": "/root/"},
        {"prefix": "logs//"},
        {"prefix": "logs/../"},
        {"prefix": "logs/./"},
        {"prefix": "logs"},
        {"prefix": "a" * 128 + "/"},
        {"prefix": "logs/\u0000/"},
        {"prefix": 1},
        {"application_key": CANARY},
    ],
)
def test_bad_metadata_fails_before_credentials_or_network(config, changes, monkeypatch):
    config.write_text(json.dumps(VALUES | changes), encoding="utf-8")

    def forbidden(*args, **kwargs):
        pytest.fail("invalid config must stop before credentials/client")

    monkeypatch.setattr(b2, "_credentials", forbidden)
    before = config.read_bytes()
    result = b2.run(config, execute=True, client_factory=forbidden)
    assert result.error == "arguments" and not result.credentials_read_attempted
    assert result.requests_attempted == 0 and config.read_bytes() == before
    safe_result(result)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"bucket_name":"first","bucket_name":"second"}',
        b'{"bucket_name":NaN}',
        b"\xff",
        b" " * 16385,
    ],
)
def test_malformed_and_oversized_metadata_is_rejected(config, raw):
    config.write_bytes(raw)
    result = b2.run(config, execute=True)
    assert result.error == "arguments" and not result.credentials_read_attempted


@pytest.mark.parametrize("kind", ["missing", "relative", "git", "hardlink", "directory"])
def test_config_filesystem_guards(config, tmp_path, kind):
    path = config
    if kind == "missing":
        path = tmp_path / "missing.json"
    elif kind == "relative":
        path = Path("relative.json")
    elif kind == "git":
        path = Path(__file__).resolve().parents[2] / "b2-target.json"
    elif kind == "hardlink":
        os.link(config, tmp_path / "linked.json")
    else:
        path = tmp_path / "directory.json"
        path.mkdir()
    result = b2.run(path, execute=True)
    assert result.error == "arguments" and not result.credentials_read_attempted


def test_symlink_metadata_is_rejected(config, tmp_path):
    linked = tmp_path / "linked.json"
    try:
        linked.symlink_to(config)
    except OSError:
        pytest.skip("OS account lacks symlink creation privilege")
    assert b2.run(linked, execute=True).error == "arguments"


def test_metadata_changed_during_read_is_rejected_before_credentials(config, monkeypatch):
    original = os.fdopen

    @contextmanager
    def fdopen(*args, **kwargs):
        with original(*args, **kwargs) as stream:

            class ChangingReader:
                def read(self, n):
                    raw = stream.read(n)
                    config.write_bytes(raw + b" ")
                    return raw

            yield ChangingReader()

    monkeypatch.setattr(os, "fdopen", fdopen)
    result = b2.run(config, execute=True)
    assert result.error == "arguments" and not result.credentials_read_attempted


@pytest.mark.parametrize(
    "key_id,key",
    [
        (None, None),
        ("", KEY),
        (KEY_ID, ""),
        ("id:boundary", KEY),
        (KEY_ID, "bad\nkey"),
        (KEY_ID, "\u2603"),
        (KEY_ID, "x" * 513),
    ],
)
def test_missing_or_invalid_credentials_make_zero_requests(config, monkeypatch, key_id, key):
    for name, value in (("B2_APPLICATION_KEY_ID", key_id), ("B2_APPLICATION_KEY", key)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)

    def forbidden():
        pytest.fail("invalid keys must not construct a client")

    result = b2.run(config, execute=True, client_factory=forbidden)
    assert result.error == "credentials" and result.requests_attempted == 0
    assert result.credentials_read_attempted and not result.credentials_validated
    safe_result(result)


@pytest.mark.parametrize(
    "kind,error",
    [
        ("unrestricted", "scope"),
        ("multiple", "scope"),
        ("null_name", "scope"),
        ("wrong_name", "scope"),
        ("prefix", "scope"),
        ("null_prefix", "scope"),
        ("missing_cap", "capability"),
        ("admin_cap", "capability"),
        ("unknown_cap", "capability"),
        ("duplicate_cap", "payload"),
        ("bad_token", "payload"),
        ("bad_account", "payload"),
    ],
)
def test_authorized_scope_must_be_bounded_before_token_is_forwarded(
    config, credentials, kind, error
):
    data = auth_data()
    allowed = data["apiInfo"]["storageApi"]["allowed"]
    if kind == "unrestricted":
        allowed["buckets"] = None
    elif kind == "multiple":
        allowed["buckets"] *= 2
    elif kind == "null_name":
        allowed["buckets"][0]["name"] = None
    elif kind == "wrong_name":
        allowed["buckets"][0]["name"] = "other-bucket"
    elif kind in {"prefix", "null_prefix"}:
        allowed["namePrefix"] = "broader/" if kind == "prefix" else None
    elif kind == "missing_cap":
        allowed["capabilities"] = ["readBuckets"]
    elif kind in {"admin_cap", "unknown_cap", "duplicate_cap"}:
        allowed["capabilities"].append(
            {"admin_cap": "writeKeys", "unknown_cap": "newPower", "duplicate_cap": "listFiles"}[
                kind
            ]
        )
    elif kind == "bad_token":
        data["authorizationToken"] = "token\r\nInjected: yes"
    else:
        data["accountId"] = True
    factory, state = fake_client(data=[data])
    result = b2.run(config, execute=True, client_factory=factory)
    assert result.error == error and result.requests_attempted == 1
    assert len(state["requests"]) == 1 and state["closed"] and not result.connection_verified
    safe_result(result)


@pytest.mark.parametrize(
    "url",
    [
        "http://api001.backblazeb2.com",
        "https://api001.backblazeb2.com.evil.invalid",
        "https://user:pass@api001.backblazeb2.com",
        "https://api001.backblazeb2.com:443",
        "https://api001.backblazeb2.com/path",
        "https://api001.backblazeb2.com?",
        "https://api001.backblazeb2.com#x",
        "https://127.0.0.1",
        "https://api001.backblazeb2.com.",
    ],
)
def test_untrusted_provider_url_does_not_receive_the_token(config, credentials, url):
    data = auth_data()
    data["apiInfo"]["storageApi"]["apiUrl"] = url
    factory, state = fake_client(data=[data])
    result = b2.run(config, execute=True, client_factory=factory)
    assert result.error == "api_url" and len(state["requests"]) == 1
    safe_result(result)


def test_region_mismatch_is_rejected_without_using_s3_endpoint(config, credentials):
    data = auth_data()
    data["apiInfo"]["storageApi"]["s3ApiUrl"] = "https://s3.other-region.backblazeb2.com"
    factory, state = fake_client(data=[data])
    result = b2.run(config, execute=True, client_factory=factory)
    assert result.error == "region" and len(state["requests"]) == 1


def test_readonly_capabilities_connect_but_do_not_prove_backup_ready(config, credentials):
    data = auth_data()
    data["apiInfo"]["storageApi"]["apiUrl"] += "/"
    data["apiInfo"]["storageApi"]["allowed"]["capabilities"] = ["listBuckets"]
    factory, state = fake_client(data=[data, bucket_data()])
    result = b2.run(config, execute=True, client_factory=factory)
    assert result.status == "ok" and result.connection_verified
    assert not result.backup_capabilities_complete
    assert state["requests"][1].url.path == "/b2api/v4/b2_list_buckets"
    safe_result(result)


@pytest.mark.parametrize(
    "kind,error",
    [
        ("account", "bucket_mismatch"),
        ("id", "bucket_mismatch"),
        ("name", "bucket_mismatch"),
        ("empty", "bucket_mismatch"),
        ("multiple", "bucket_mismatch"),
        ("public", "bucket_not_private"),
    ],
)
def test_bucket_result_must_match_exact_authorized_private_target(config, credentials, kind, error):
    data = bucket_data()
    if kind in {"account", "id", "name"}:
        data["buckets"][0][
            {"account": "accountId", "id": "bucketId", "name": "bucketName"}[kind]
        ] = CANARY
    elif kind == "empty":
        data["buckets"] = []
    elif kind == "multiple":
        data["buckets"] *= 2
    else:
        data["buckets"][0]["bucketType"] = "allPublic"
    factory, state = fake_client(data=[auth_data(), data])
    result = b2.run(config, execute=True, client_factory=factory)
    assert result.error == error and result.requests_attempted == 2 and state["closed"]
    assert result.authorization_verified and not result.bucket_private_verified
    safe_result(result)


@pytest.mark.parametrize(
    "status,error",
    [
        (301, "redirect"),
        (307, "redirect"),
        (401, "authentication"),
        (403, "provider_denied_or_cap"),
        (429, "rate_limit"),
        (500, "http"),
    ],
)
def test_http_errors_are_not_retried_or_followed_and_bodies_are_not_read(
    config, credentials, status, error
):
    class ForbiddenBody(httpx.SyncByteStream):
        def __iter__(self):
            pytest.fail("error body must not be read")
            yield b""

    def handler(request, index):
        return httpx.Response(
            status, headers={"Location": "https://evil.invalid/"}, stream=ForbiddenBody()
        )

    factory, state = fake_client(handler)
    result = b2.run(config, execute=True, client_factory=factory)
    assert result.error == error and len(state["requests"]) == 1 and state["closed"]
    safe_result(result)


@pytest.mark.parametrize(
    "failure,error",
    [
        (httpx.ReadTimeout, "timeout"),
        (httpx.ConnectError, "network"),
        (KeyboardInterrupt, "interrupted"),
        (RuntimeError, "internal"),
        (b2.PreflightError, "internal"),
    ],
)
def test_transport_and_unexpected_errors_preserve_attempts_without_raw_messages(
    config, credentials, failure, error
):
    def handler(request, index):
        raise failure(CANARY)

    factory, state = fake_client(handler)
    result = b2.run(config, execute=True, client_factory=factory)
    assert result.error == error and result.requests_attempted == 1 and state["closed"]
    safe_result(result)


@pytest.mark.parametrize(
    "kind,error",
    [
        ("mime", "payload"),
        ("gzip", "payload"),
        ("length", "response_limit"),
        ("body", "response_limit"),
        ("duplicate", "payload"),
        ("nan", "payload"),
        ("infinite", "payload"),
        ("utf8", "payload"),
    ],
)
def test_response_guards_are_bounded_and_fail_before_second_request(
    config, credentials, kind, error
):
    headers = {"Content-Type": "application/json"}
    body = json.dumps(auth_data()).encode()
    if kind == "mime":
        headers["Content-Type"] = "text/plain"
    elif kind == "gzip":
        headers["Content-Encoding"] = "gzip"
    elif kind == "length":
        headers["Content-Length"] = str(1024**2 + 1)
    elif kind == "body":
        body = b" " * (1024**2 + 1)
    elif kind == "duplicate":
        body = b'{"accountId":"one","accountId":"two"}'
    elif kind == "nan":
        body = b'{"unused":NaN}'
    elif kind == "infinite":
        body = b'{"unused":1e400}'
    else:
        body = b"\xff"

    def handler(request, index):
        return httpx.Response(200, headers=headers, stream=httpx.ByteStream(body))

    factory, state = fake_client(handler)
    result = b2.run(config, execute=True, client_factory=factory)
    assert result.error == error and len(state["requests"]) == 1 and state["closed"]
    safe_result(result)


def test_budget_expiration_and_remaining_phase_timeout(config, credentials, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(b2.time, "monotonic", lambda: now[0])
    original = b2.parse_authorization

    def spend_time(*args):
        answer = original(*args)
        now[0] = 29.0
        return answer

    monkeypatch.setattr(b2, "parse_authorization", spend_time)
    factory, state = fake_client()
    assert b2.run(config, execute=True, client_factory=factory).status == "ok"
    assert all(v <= 1 for v in state["requests"][1].extensions["timeout"].values())
    now[0] = 0.0

    def exhausted(*args):
        now[0] = 31.0
        return original(*args)

    monkeypatch.setattr(b2, "parse_authorization", exhausted)
    factory, state = fake_client()
    result = b2.run(config, execute=True, client_factory=factory)
    assert result.error == "network_budget" and len(state["requests"]) == 1


def test_default_client_disables_proxy_ssl_environment_and_retries(
    config, credentials, monkeypatch
):
    original_client = httpx.Client
    seen = {}
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=auth_data() if len(requests) == 1 else bucket_data())

    def transport(**kwargs):
        seen["transport"] = kwargs
        return httpx.MockTransport(handler)

    def client(**kwargs):
        seen["client"] = kwargs
        return original_client(**kwargs)

    monkeypatch.setenv("HTTPS_PROXY", "http://PROXY_CANARY.invalid:9999")
    monkeypatch.setattr(b2.httpx, "HTTPTransport", transport)
    monkeypatch.setattr(b2.httpx, "Client", client)
    result = b2.run(config, execute=True)
    assert result.status == "ok" and len(requests) == 2
    assert seen["transport"] == dict(retries=0, verify=True, trust_env=False)
    assert seen["client"]["trust_env"] is False and seen["client"]["verify"] is True
    assert seen["client"]["follow_redirects"] is False


def test_cli_shared_report_survives_outer_interrupt_and_never_echoes_keys(
    config, credentials, monkeypatch, capsys
):
    factory, state = fake_client()
    original = b2._run

    def escaped(path, result, **kwargs):
        original(path, result, client_factory=factory, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(b2, "_run", escaped)
    assert b2.main(["--config", str(config), "--execute"]) == 130
    out = capsys.readouterr()
    data = json.loads(out.out)
    assert data["mode"] == "execute" and data["requests_attempted"] == 2
    assert data["connection_verified"] and data["status"] == "interrupted"
    assert not out.err and all(v not in out.out for v in (KEY, TOKEN, str(config), ACCOUNT, CANARY))
    assert len(state["requests"]) == 2
    assert b2.main(["--unknown", CANARY]) == 2
    assert CANARY not in capsys.readouterr().out


def test_cli_preview_and_credentials_missing_exit_codes(config, monkeypatch, capsys):
    monkeypatch.delenv("B2_APPLICATION_KEY_ID", raising=False)
    monkeypatch.delenv("B2_APPLICATION_KEY", raising=False)
    assert b2.main(["--config", str(config)]) == 0
    assert json.loads(capsys.readouterr().out)["requests_attempted"] == 0
    assert b2.main(["--config", str(config), "--execute"]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "credentials"
    assert b2.main(["--config", str(config.parent / "missing.json")]) == 2
    capsys.readouterr()


def test_reader_has_an_independent_request_ceiling(config, credentials):
    factory, state = fake_client(data=[auth_data(), auth_data()])
    result = b2.Result()
    with factory() as client:
        reader = b2.Reader(client, result)
        reader.request("GET", b2.AUTHORIZE)
        reader.request("GET", b2.AUTHORIZE)
        with pytest.raises(b2.PreflightError, match="request_limit"):
            reader.request("GET", b2.AUTHORIZE)
    assert result.requests_attempted == len(state["requests"]) == 2


def test_aggregate_body_limit_stops_bucket_response(config, credentials, monkeypatch):
    data = [auth_data(), bucket_data()]
    sizes = [len(httpx.Response(200, json=item).content) for item in data]
    monkeypatch.setattr(b2, "MAX_TOTAL", sum(sizes) - 1)
    factory, state = fake_client(data=data)
    result = b2.run(config, execute=True, client_factory=factory)
    assert result.error == "response_limit" and result.requests_attempted == 2
    assert result.authorization_verified and not result.connection_verified and state["closed"]
