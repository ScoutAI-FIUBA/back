"""The startup backfill runs in a daemon thread, so it can never hold up startup or health checks."""

from __future__ import annotations

import threading

from src.interfaces.http.main import start_player_stats_catch_up


class _CatchUp:
    def __init__(self, gate: threading.Event | None = None) -> None:
        self.started, self.gate = threading.Event(), gate

    def execute(self) -> int:
        self.started.set()
        if self.gate is not None:
            self.gate.wait(30)
        return 0


def test_the_startup_catch_up_is_a_daemon_thread_that_does_not_block_the_caller() -> None:
    gate = threading.Event()
    catch_up = _CatchUp(gate)
    thread = start_player_stats_catch_up(catch_up)  # returns although execute is still running
    assert thread is not None and thread.daemon and catch_up.started.wait(5) and thread.is_alive()
    gate.set()
    thread.join(5)
    assert not thread.is_alive()


def test_failing_to_start_the_thread_is_swallowed(monkeypatch) -> None:
    def refuse(*_args, **_kwargs):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", refuse)
    assert start_player_stats_catch_up(_CatchUp()) is None
