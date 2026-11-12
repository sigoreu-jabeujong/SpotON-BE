import json

import pytest

from etl.brands import apply
from etl.brands.matching import Matcher
from tests.etl.brands_helpers import catalog, item


@pytest.mark.parametrize("args", [[], ["--snapshot"], ["--unknown", "PRIVATE_CANARY"]])
def test_apply_arguments_never_echo_private_values(args, capsys):
    with pytest.raises(SystemExit) as error:
        apply.main(args)
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.err == "invalid arguments\n" and "PRIVATE" not in captured.out


def test_source_error_precedes_db_setup_and_has_no_private_values(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("DB must not open")

    monkeypatch.setattr(apply, "create_db_engine", forbidden)
    assert apply.main(["--snapshot", str(tmp_path / "PRIVATE_CANARY.json")]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"error": "brands:operation_failed"}
    assert "PRIVATE_CANARY" not in captured.out + captured.err


def test_matcher_never_treats_external_brand_identifier_as_automatic():
    matcher = Matcher(catalog([item("001", "Unique Name")]))
    assert matcher.classify(dict(name="Unique Name", is_franchise=None, brand_id=1)) == (
        "existing_classification",
        None,
    )
    assert matcher.classify(dict(name="Unique Name", is_franchise=False, brand_id=None)) == (
        "existing_classification",
        None,
    )
