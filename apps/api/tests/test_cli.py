import json

import pytest

from app.cli import main


def test_openapi_prints_the_schema_the_web_types_are_generated_from(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["openapi"]) == 0

    schema = json.loads(capsys.readouterr().out)
    assert "/api/v1/trains" in schema["paths"]
    assert "TrainOut" in schema["components"]["schemas"]
