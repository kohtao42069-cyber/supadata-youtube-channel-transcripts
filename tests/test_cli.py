import pytest

from channel_transcripts.cli import main
from tests.fakes import FakeClient


@pytest.fixture
def secret():
    return "sd_test_secret_value_should_not_leak"


def test_missing_key_does_not_construct_client(monkeypatch):
    monkeypatch.delenv("SUPADATA_API_KEY", raising=False)

    def boom(*_args, **_kwargs):
        raise AssertionError("Supadata client should not be constructed")

    monkeypatch.setattr("channel_transcripts.cli.Supadata", boom)
    assert main(["list", "@ExampleChannel"]) == 2


def test_invalid_limit_exits_before_client(monkeypatch):
    monkeypatch.setenv("SUPADATA_API_KEY", "present-but-not-used")

    def boom(*_args, **_kwargs):
        raise AssertionError("Supadata client should not be constructed")

    monkeypatch.setattr("channel_transcripts.cli.Supadata", boom)
    assert main(["fetch", "@ExampleChannel", "--limit", "0"]) == 2
    assert main(["fetch", "@ExampleChannel", "--max-credits", "-1"]) == 2


def test_unknown_type_is_rejected():
    with pytest.raises(SystemExit) as caught:
        main(["list", "@ExampleChannel", "--type", "movie"])
    assert caught.value.code == 2


def test_fetch_uses_env_key_and_hides_it(monkeypatch, tmp_path, capsys, secret):
    monkeypatch.setenv("SUPADATA_API_KEY", secret)
    client = FakeClient()
    seen = {}

    def factory(api_key, base_url="https://api.supadata.ai/v1"):
        seen["api_key"] = api_key
        seen["base_url"] = base_url
        return client

    client.transcript_impl = lambda **_kwargs: (_ for _ in ()).throw(
        RuntimeError(f"upstream included {secret}")
    )
    monkeypatch.setattr("channel_transcripts.cli.Supadata", factory)
    code = main(
        [
            "fetch",
            "UCexamplechannelid",
            "--output",
            str(tmp_path),
            "--limit",
            "1",
            "--type",
            "video",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert seen["api_key"] == secret
    assert secret not in captured.out
    assert secret not in captured.err
    assert "[REDACTED]" in captured.err
    assert "calls_made: 2" in captured.out
    assert "errors: 1" in captured.out
    assert "https://supadata.ai/pricing" in captured.out
    assert client.video_calls[0]["id"] == "UCexamplechannelid"
    assert client.video_calls[0]["type"] == "video"


def test_list_command_prints_ids(monkeypatch, capsys, secret):
    monkeypatch.setenv("SUPADATA_API_KEY", secret)
    client = FakeClient()
    monkeypatch.setattr("channel_transcripts.cli.Supadata", lambda api_key: client)
    code = main(["list", "@ExampleChannel", "--limit", "2"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.splitlines()[0] == "aaaaaaaaaaa"
    assert "listed: 1" in captured.out
    assert "calls_made: 1" in captured.out
    assert secret not in captured.out + captured.err


def test_quota_exit_code(monkeypatch, tmp_path, secret):
    from supadata.errors import SupadataError

    monkeypatch.setenv("SUPADATA_API_KEY", secret)
    client = FakeClient()

    def transcript(**_kwargs):
        raise SupadataError(
            error="limit-exceeded",
            message="Limit Exceeded",
            details="Plan usage limit was exceeded.",
        )

    client.transcript_impl = transcript
    monkeypatch.setattr("channel_transcripts.cli.Supadata", lambda api_key: client)
    code = main(["fetch", "@ExampleChannel", "--output", str(tmp_path)])
    assert code == 1


def test_dry_run_from_cli_writes_nothing(monkeypatch, tmp_path, capsys, secret):
    monkeypatch.setenv("SUPADATA_API_KEY", secret)
    client = FakeClient()
    monkeypatch.setattr("channel_transcripts.cli.Supadata", lambda api_key: client)
    code = main(
        [
            "fetch",
            "@ExampleChannel",
            "--output",
            str(tmp_path),
            "--dry-run",
            "--max-credits",
            "5",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "would_fetch aaaaaaaaaaa" in captured.out
    assert "would_fetch: 1" in captured.out
    assert client.transcript_calls == []
    assert list(tmp_path.glob("*.md")) == []
    assert not (tmp_path / "manifest.json").exists()
