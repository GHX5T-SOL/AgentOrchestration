import sys

from src.cli import main as cli_main


def test_status_watch_interrupt_returns_130_without_traceback(monkeypatch, capsys):
    def raise_keyboard_interrupt():
        raise KeyboardInterrupt

    monkeypatch.setattr(sys, "argv", ["ao", "status", "--watch"])
    monkeypatch.setattr(cli_main, "watch_status", raise_keyboard_interrupt)

    exit_code = cli_main.cli()

    captured = capsys.readouterr()
    assert exit_code == cli_main.INTERRUPTED_EXIT_CODE
    assert "Status watch interrupted." in captured.err
    assert "Traceback" not in captured.err


def test_status_without_watch_exits_successfully(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["ao", "status"])

    exit_code = cli_main.cli()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Checking agent status..." in captured.out
