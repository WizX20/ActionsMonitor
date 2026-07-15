"""Shared fixtures for the integration test suite.

Runs the real Qt UI on the `offscreen` platform plugin — no display needed,
no network: poller threads are prevented from starting and poll results are
simulated by injecting `StatusEvent`s straight into the event queue.

Screenshots land in `artifacts/screenshots/` (gitignored) via the
`screenshot` fixture; `task screenshots` runs only the screenshot tests.
"""

from __future__ import annotations

import os
import queue
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

import pytest
from PySide6.QtWidgets import QApplication

SCREENSHOT_DIR = _ROOT / "artifacts" / "screenshots"


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    # Production parity: main() applies the dark stylesheet app-wide.
    import main as m
    app.setStyleSheet(m.DARK_STYLESHEET)
    yield app


@pytest.fixture
def screenshot(qapp):
    """Save a widget screenshot as artifacts/screenshots/<name>.png."""
    def _shot(widget, name: str) -> Path:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        qapp.processEvents()
        path = SCREENSHOT_DIR / f"{name}.png"
        ok = widget.grab().save(str(path))
        assert ok, f"could not save screenshot {name}"
        return path
    return _shot


@pytest.fixture
def app_env(qapp, tmp_path, monkeypatch):
    """Isolated app environment: per-test config/state files, no poller
    threads, no network. Returns a factory that builds a MainWindow from a
    config.yaml text."""
    import main as m
    import pollers
    import settings_ui

    monkeypatch.setattr(m, "CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr(m, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(m, "APP_ICO", tmp_path / "app.ico")
    monkeypatch.setattr(m, "_FOCUS_SIGNAL", tmp_path / "_focus_signal")
    monkeypatch.setattr(m, "_FOCUS_VBS", tmp_path / "_focus.vbs")
    monkeypatch.setattr(settings_ui, "CONFIG_FILE", tmp_path / "config.yaml")
    # Keep poller threads dormant — tests drive the queue directly.
    monkeypatch.setattr(pollers.WorkflowPoller, "start", lambda self: None)

    windows: list = []

    class Env:
        main = m
        config_path = tmp_path / "config.yaml"
        state_path = tmp_path / "state.json"

        def make_window(self, config_text: str = "workflows: []\n"):
            self.config_path.write_text(config_text, encoding="utf-8")
            cfg = m.ConfigManager()
            win = m.MainWindow(cfg, queue.Queue())
            # Timers would keep firing between tests — stop them; tests call
            # _drain_queue() explicitly.
            win._drain_timer.stop()
            win._config_timer.stop()
            windows.append(win)
            win.show()
            qapp.processEvents()
            return win

        @staticmethod
        def push(win, event):
            win._event_queue.put(event)
            win._drain_queue()
            qapp.processEvents()

    yield Env()

    for win in windows:
        try:
            win._stop_all_pollers()
            if win._tray:
                win._tray.hide()
            win.close()
            win.deleteLater()
        except RuntimeError:
            pass
    qapp.processEvents()
