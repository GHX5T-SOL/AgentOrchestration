import sys

from src.cli import main as cli_main


def test_deploy_dry_run_reports_redacted_manifest_diff(
    monkeypatch,
    tmp_path,
    capsys,
):
    previous = tmp_path / "previous.yaml"
    candidate = tmp_path / "candidate.yaml"
    previous.write_text(
        "name: agent\n"
        "image: repo/agent:1\n"
        "replicas: 1\n"
        "env:\n"
        "  API_TOKEN: old-secret\n",
        encoding="utf-8",
    )
    candidate.write_text(
        "name: agent\n"
        "image: repo/agent:2\n"
        "replicas: 2\n"
        "env:\n"
        "  API_TOKEN: new-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ao",
            "deploy",
            str(candidate),
            "--dry-run",
            "--previous",
            str(previous),
        ],
    )

    exit_code = cli_main.cli()

    output = capsys.readouterr()
    assert exit_code == 0
    assert "Dry-run manifest validation passed." in output.out
    assert "image: 'repo/agent:1' -> 'repo/agent:2'" in output.out
    assert "old-secret" not in output.out
    assert "new-secret" not in output.out


def test_deploy_dry_run_rejects_invalid_manifest(
    monkeypatch,
    tmp_path,
    capsys,
):
    candidate = tmp_path / "candidate.yaml"
    candidate.write_text("name: agent\nimage: ''\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["ao", "deploy", str(candidate), "--dry-run"],
    )

    exit_code = cli_main.cli()

    output = capsys.readouterr()
    assert exit_code == 1
    assert "Manifest validation failed:" in output.err
