from hivemind.gui.launcher import ledger_news


def test_the_watchdogs_reasons_reach_the_window(tmp_path):
    log = tmp_path / "attempts.log"
    log.write_text("[watchdog] attempt 1 starting 2026-10-19 16:11:44 -> run-001.log\n")
    news, at = ledger_news(log, 0)
    assert news == []                                   # a start is not news
    with log.open("a") as f:
        f.write("[watchdog] game guard: you're playing Roblox (your own) — stopping (STOP set)\n")
        f.write("[watchdog] not enough memory to start the game: 0.7 GB available of 16\n")
    news, at = ledger_news(log, at)
    assert news[0].startswith("game guard: you're playing Roblox")
    assert news[1].startswith("not enough memory")
    assert ledger_news(log, at)[0] == []                # read once
    assert ledger_news(tmp_path / "missing.log", 5) == ([], 5)


def test_the_start_failure_reason_is_found(tmp_path):
    from hivemind.gui.launcher import last_failure
    (tmp_path / "run-002.log").write_text("  === bootstrap ===\n  FAILED: RuntimeError: on Windows the bot joins by link only\n")
    assert last_failure(tmp_path).startswith("RuntimeError: on Windows the bot joins by link only")
    assert last_failure(tmp_path / "none") == ""
