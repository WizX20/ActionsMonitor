"""In-app Settings window (beta, gated by `beta.settings_ui`).

Implements the Settings Window design from
`design/actions-monitor-improvement-designs/`: left nav with five pages
(Workflows, Notifications, PR rules, GitHub account, Raw YAML). Changes are
written to config.yaml immediately; the main window's 5s mtime watcher picks
them up and hot-reloads the pollers, so this dialog never has to touch
MainWindow directly.

Self-contained — no compile-time imports from main (PyInstaller re-executes
the entry script as both `__main__` and `main`, so `from main import ...`
would trigger a circular reload). main.py calls `configure(...)` once during
module init to inject the config-file path and the open-in-editor callable.

Writes go through ruamel.yaml when available so user comments in config.yaml
survive round-trips; falls back to PyYAML (comments lost) otherwise.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Callable, Optional

import requests
import yaml

try:
    from ruamel.yaml import YAML as _RuamelYAML
    _HAVE_RUAMEL = True
except ImportError:
    _HAVE_RUAMEL = False

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from gh_api import _gh_headers, parse_workflow_url, parse_actor_url
from widgets import (BG_DARK, BG_FOOTER, BG_ROW, BORDER,
    FG_FAINT, FG_LINK, FG_MUTED, FG_TEXT, FG_TITLE)
from pollers import parse_duration

# Injected by main.configure() — placeholders so the module imports standalone.
CONFIG_FILE: Optional[Path] = None
OPEN_IN_EDITOR: Optional[Callable[[], None]] = None
APP_NAME = "Actions Monitor"


def configure(*, config_file: Path, open_in_editor: Callable[[], None],
              app_name: str = "Actions Monitor"):
    """One-shot injection of per-process paths/callables from main."""
    global CONFIG_FILE, OPEN_IN_EDITOR, APP_NAME
    CONFIG_FILE = config_file
    OPEN_IN_EDITOR = open_in_editor
    APP_NAME = app_name


# ---------------------------------------------------------------------------
# config.yaml round-trip (comment-preserving when ruamel is available)
# ---------------------------------------------------------------------------
def _ruamel() -> "_RuamelYAML":
    y = _RuamelYAML()
    y.preserve_quotes = True
    y.width = 4096  # never wrap long URLs
    return y


def load_raw_config() -> dict:
    """Load config.yaml as a mutable mapping (ruamel round-trip type when
    available, plain dict otherwise). Returns {} when missing/broken."""
    if CONFIG_FILE is None or not CONFIG_FILE.exists():
        return {}
    text = CONFIG_FILE.read_text(encoding="utf-8")
    try:
        if _HAVE_RUAMEL:
            return _ruamel().load(text) or {}
        return yaml.safe_load(text) or {}
    except Exception:
        return {}


def save_raw_config(data: dict) -> bool:
    if CONFIG_FILE is None:
        return False
    try:
        if _HAVE_RUAMEL:
            import io
            buf = io.StringIO()
            _ruamel().dump(data, buf)
            CONFIG_FILE.write_text(buf.getvalue(), encoding="utf-8")
        else:
            CONFIG_FILE.write_text(
                yaml.safe_dump(data, default_flow_style=False, sort_keys=False),
                encoding="utf-8")
        return True
    except Exception as exc:
        print(f"[Settings] Save error: {exc}")
        return False


# ---------------------------------------------------------------------------
# Small styled-widget helpers
# ---------------------------------------------------------------------------
_INPUT_CSS = (
    f"QLineEdit {{ background: #262220; border: 1px solid #3B3734; border-radius: 6px; "
    f"color: {FG_TEXT}; font-size: 12px; padding: 8px 12px; }} "
    f"QLineEdit:focus {{ border-color: {FG_LINK}; }}")
_MONO_INPUT_CSS = (
    f"QLineEdit {{ background: #262220; border: 1px solid #3B3734; border-radius: 6px; "
    f"color: {FG_TEXT}; font-size: 12px; padding: 8px 12px; "
    f"font-family: Consolas, monospace; }} "
    f"QLineEdit:focus {{ border-color: {FG_LINK}; }}")
_COMBO_CSS = (
    f"QComboBox {{ background: #262220; border: 1px solid #3B3734; border-radius: 6px; "
    f"color: {FG_TEXT}; font-size: 12px; padding: 6px 10px; min-width: 90px; }} "
    f"QComboBox QAbstractItemView {{ background: {BG_ROW}; color: {FG_TEXT}; "
    f"selection-background-color: #4A3728; }}")
_PRIMARY_BTN_CSS = (
    f"QPushButton {{ background: {FG_LINK}; color: {BG_DARK}; font-size: 12px; "
    f"font-weight: 600; padding: 7px 16px; border-radius: 6px; border: none; }} "
    f"QPushButton:hover {{ background: #F59E0B; }} "
    f"QPushButton:disabled {{ background: #3D3530; color: {FG_FAINT}; }}")
_SECONDARY_BTN_CSS = (
    f"QPushButton {{ background: #33302D; color: {FG_TEXT}; font-size: 12px; "
    f"font-weight: 600; padding: 7px 14px; border-radius: 6px; border: none; }} "
    f"QPushButton:hover {{ background: #3D3530; color: {FG_LINK}; }}")
_CARD_CSS = (f"QWidget#card {{ background: {BG_FOOTER}; border: 1px solid #292524; "
             f"border-radius: 8px; }}")

_MODE_BADGE = {
    "branch": ("BRANCH", "#33302D", "#A8A29E"),
    "pr":     ("PR",     "#3D3530", "#FBBF24"),
    "actor":  ("ACTOR",  "#1C2A3A", "#60A5FA"),
    "url":    ("URL",    "#302830", "#A78BFA"),
}


def _heading(title: str, sub: str = "") -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    t = QLabel(title)
    t.setStyleSheet(f"color: {FG_TITLE}; font-size: 15px; font-weight: 600;")
    lay.addWidget(t)
    if sub:
        s = QLabel(sub)
        s.setStyleSheet(f"color: {FG_FAINT}; font-size: 11px;")
        s.setWordWrap(True)
        lay.addWidget(s)
    return w


def _card() -> tuple[QWidget, QVBoxLayout]:
    w = QWidget()
    w.setObjectName("card")
    w.setStyleSheet(_CARD_CSS)
    lay = QVBoxLayout(w)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(10)
    return w, lay


def _field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {FG_MUTED}; font-size: 11px; font-weight: 600;")
    return lbl


def _line_edit(value: str = "", mono: bool = False, width: int = 0) -> QLineEdit:
    e = QLineEdit(value)
    e.setStyleSheet(_MONO_INPUT_CSS if mono else _INPUT_CSS)
    if width:
        e.setFixedWidth(width)
    return e


def _link_label(text: str, handler) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"QLabel {{ color: {FG_FAINT}; font-size: 11px; }} "
        f"QLabel:hover {{ color: {FG_LINK}; text-decoration: underline; }}")
    lbl.setCursor(Qt.CursorShape.PointingHandCursor)
    lbl.mousePressEvent = lambda e: handler()
    return lbl


# ---------------------------------------------------------------------------
# Workflow entry helpers
# ---------------------------------------------------------------------------
def detect_mode(url: str) -> tuple[Optional[str], str]:
    """Best-effort mode detection for a pasted GitHub URL.

    Returns (mode | None, hint). Mode None means the URL wasn't recognised.
    Workflow-file URLs default to branch mode — the user can flip to PR mode.
    """
    url = (url or "").strip()
    if not url:
        return None, "Paste a GitHub Actions URL to auto-detect the mode."
    try:
        _o, _r, wf_file, branch = parse_workflow_url(url)
        hint = f"Workflow file detected ({wf_file})"
        if branch:
            hint += f" — branch filter: {branch}"
        return "branch", hint + ". Pick Branch or PR mode below."
    except ValueError:
        pass
    try:
        _o, _r, actor = parse_actor_url(url)
        if actor:
            return "actor", f"Actions run list filtered by actor:{actor} — Actor mode."
        return "actor", "Actions run list URL — Actor mode (uses your own login)."
    except ValueError:
        pass
    if "q=" in url or "is%3Apr" in url or "is:pr" in url or "/search" in url or "/pulls" in url:
        return "url", "Search query detected — Search URL mode."
    return None, "Unrecognised URL — expected a workflow, actions, or search URL."


def extract_query(url: str) -> str:
    """Pull a search query string out of a pasted /search or /pulls URL."""
    from urllib.parse import parse_qs, unquote, urlparse
    qs = parse_qs(urlparse(url).query)
    for key in ("q", "query"):
        if key in qs:
            return unquote(qs[key][0])
    return ""


def entry_to_yaml(entry: dict) -> str:
    """Render a single workflows[] entry as the YAML that will be appended."""
    return yaml.safe_dump([entry], default_flow_style=False, sort_keys=False,
                          allow_unicode=True)


def _entry_summary(entry: dict) -> str:
    mode = entry.get("mode", "branch")
    if mode == "url":
        return entry.get("query", "") or entry.get("url", "")
    url = entry.get("url", "")
    try:
        owner, repo, wf_file, url_branch = parse_workflow_url(url)
        bits = [f"{owner}/{repo}", wf_file]
        branch = entry.get("branch") or url_branch
        if mode == "branch" and branch:
            bits.append(f"branch: {branch}")
        if mode == "pr":
            if entry.get("max_prs"):
                bits.append(f"max {entry['max_prs']} PRs")
            extra = entry.get("extra_workflows") or []
            if extra:
                bits.append(f"+{len(extra)} extra workflows")
        return " · ".join(bits)
    except ValueError:
        return url


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------
class SettingsDialog(QDialog):
    _NAV = [
        ("workflows",     "Workflows"),
        ("notifications", "Notifications"),
        ("rules",         "PR rules"),
        ("github",        "GitHub account"),
        ("yaml",          "Raw YAML"),
    ]

    def __init__(self, config_mgr, parent=None):
        super().__init__(parent)
        self._config_mgr = config_mgr
        self.setWindowTitle(f"{APP_NAME} - Settings")
        self.setMinimumSize(780, 600)
        self.setStyleSheet(f"QDialog {{ background: {BG_DARK}; }}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Title bar strip
        titlebar = QWidget()
        tb = QHBoxLayout(titlebar)
        tb.setContentsMargins(16, 12, 16, 12)
        tb.setSpacing(10)
        t = QLabel("Settings")
        t.setStyleSheet(f"color: {FG_TITLE}; font-size: 14px; font-weight: 600;")
        tb.addWidget(t)
        tb.addStretch()
        dot = QLabel()
        dot.setFixedSize(7, 7)
        dot.setStyleSheet("background: #4ADE80; border-radius: 3px;")
        tb.addWidget(dot)
        sync = QLabel("Synced with config.yaml · hot-reload on")
        sync.setStyleSheet(f"color: {FG_FAINT}; font-size: 11px;")
        tb.addWidget(sync)
        outer.addWidget(titlebar)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {BORDER};")
        outer.addWidget(sep)

        body = QWidget()
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)
        outer.addWidget(body, 1)

        # Left nav
        nav = QWidget()
        nav.setFixedWidth(172)
        nav.setStyleSheet(f"border-right: 1px solid #292524;")
        nav_lay = QVBoxLayout(nav)
        nav_lay.setContentsMargins(8, 10, 8, 10)
        nav_lay.setSpacing(2)
        self._nav_labels: dict[str, QLabel] = {}
        for key, label in self._NAV:
            lbl = QLabel(label)
            lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            lbl.mousePressEvent = lambda e, k=key: self._select_tab(k)
            nav_lay.addWidget(lbl)
            self._nav_labels[key] = lbl
        nav_lay.addStretch()
        open_cfg = _link_label("Open config.yaml ↗",
                               lambda: OPEN_IN_EDITOR and OPEN_IN_EDITOR())
        nav_lay.addWidget(open_cfg)
        body_lay.addWidget(nav)

        # Stacked content
        self._stack = QStackedWidget()
        self._pages: dict[str, QWidget] = {}
        for key, builder in (
            ("workflows",     self._build_workflows_page),
            ("notifications", self._build_notifications_page),
            ("rules",         self._build_rules_page),
            ("github",        self._build_github_page),
            ("yaml",          self._build_yaml_page),
        ):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            page = builder()
            wrap = QWidget()
            wrap_lay = QVBoxLayout(wrap)
            wrap_lay.setContentsMargins(24, 20, 24, 24)
            wrap_lay.setSpacing(16)
            wrap_lay.addWidget(page)
            wrap_lay.addStretch()
            scroll.setWidget(wrap)
            self._pages[key] = scroll
            self._stack.addWidget(scroll)
        body_lay.addWidget(self._stack, 1)

        self._select_tab("workflows")

    # ------------------------------------------------------------------
    def _select_tab(self, key: str):
        for k, lbl in self._nav_labels.items():
            active = k == key
            lbl.setStyleSheet(
                "padding: 8px 12px; border-radius: 6px; font-size: 12px; border: none; "
                + (f"background: #292524; color: {FG_LINK}; font-weight: 600;"
                   if active else f"color: {FG_MUTED}; background: transparent;"))
        self._stack.setCurrentWidget(self._pages[key])
        if key == "workflows":
            self._refresh_workflow_list()
        elif key == "yaml":
            self._load_yaml_text()

    def _raw(self) -> dict:
        return load_raw_config()

    def _save(self, data: dict):
        if not save_raw_config(data):
            QMessageBox.warning(self, "Settings", "Could not write config.yaml.")
        # Pick the change up immediately instead of waiting for the 5s watcher.
        self._config_mgr.load()

    # ==================================================================
    # Workflows page
    # ==================================================================
    def _build_workflows_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        head_row = QHBoxLayout()
        head_row.setSpacing(12)
        head_row.addWidget(_heading(
            "Workflows",
            "Everything you monitor. Changes are written to config.yaml immediately."), 1)
        add_btn = QPushButton("+ Add workflow")
        add_btn.setStyleSheet(_PRIMARY_BTN_CSS)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(lambda: self._open_workflow_form(None))
        head_row.addWidget(add_btn, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head_row)

        self._wf_list = QWidget()
        self._wf_list_lay = QVBoxLayout(self._wf_list)
        self._wf_list_lay.setContentsMargins(0, 0, 0, 0)
        self._wf_list_lay.setSpacing(4)
        lay.addWidget(self._wf_list)

        tip = QLabel("Tip: you can still edit config.yaml by hand — the app "
                     "hot-reloads it and this list stays in sync.")
        tip.setStyleSheet(f"color: #57534E; font-size: 11px;")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        return page

    def _refresh_workflow_list(self):
        while self._wf_list_lay.count():
            item = self._wf_list_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        workflows = self._raw().get("workflows") or []
        if not workflows:
            empty = QLabel("No workflows configured yet — add one above.")
            empty.setStyleSheet(f"color: {FG_FAINT}; font-size: 12px; padding: 12px;")
            self._wf_list_lay.addWidget(empty)
            return
        for idx, entry in enumerate(workflows):
            self._wf_list_lay.addWidget(self._workflow_list_row(idx, dict(entry)))

    def _workflow_list_row(self, idx: int, entry: dict) -> QWidget:
        row = QWidget()
        row.setStyleSheet(
            f"QWidget {{ background: {BG_ROW}; border-radius: 6px; }}")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)

        info = QVBoxLayout()
        info.setSpacing(3)
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name = QLabel(entry.get("name") or entry.get("url") or "(unnamed)")
        name.setStyleSheet(f"color: {FG_TITLE}; font-size: 13px; background: transparent;")
        name_row.addWidget(name)
        mode = entry.get("mode", "branch")
        text, bg, fg = _MODE_BADGE.get(mode, _MODE_BADGE["branch"])
        badge = QLabel(text)
        badge.setStyleSheet(
            f"background: {bg}; color: {fg}; font-size: 10px; font-weight: 600; "
            f"padding: 2px 6px; border-radius: 3px;")
        name_row.addWidget(badge)
        if entry.get("notifications"):
            dot = QLabel()
            dot.setFixedSize(6, 6)
            dot.setStyleSheet(f"background: {FG_LINK}; border-radius: 3px;")
            dot.setToolTip("Has notification overrides")
            name_row.addWidget(dot)
        name_row.addStretch()
        info.addLayout(name_row)
        summary = QLabel(_entry_summary(entry))
        mono = " font-family: Consolas, monospace;" if mode == "url" else ""
        summary.setStyleSheet(
            f"color: {FG_FAINT}; font-size: 11px; background: transparent;{mono}")
        summary.setWordWrap(True)
        info.addWidget(summary)
        lay.addLayout(info, 1)

        rate = QLabel(f"{entry.get('polling_rate', 60)}s")
        rate.setStyleSheet(f"color: {FG_FAINT}; font-size: 11px; background: transparent;")
        lay.addWidget(rate)

        edit = _link_label("Edit", lambda i=idx: self._open_workflow_form(i))
        edit.setStyleSheet(
            f"QLabel {{ color: {FG_MUTED}; font-size: 11px; background: transparent; }} "
            f"QLabel:hover {{ color: {FG_LINK}; text-decoration: underline; }}")
        lay.addWidget(edit)
        remove = _link_label("Remove", lambda i=idx: self._remove_workflow(i))
        remove.setStyleSheet(
            f"QLabel {{ color: {FG_FAINT}; font-size: 11px; background: transparent; }} "
            f"QLabel:hover {{ color: #F87171; text-decoration: underline; }}")
        lay.addWidget(remove)
        return row

    def _remove_workflow(self, idx: int):
        data = self._raw()
        workflows = data.get("workflows") or []
        if idx >= len(workflows):
            return
        entry = workflows[idx]
        name = entry.get("name") or entry.get("url") or f"entry {idx + 1}"
        answer = QMessageBox.question(
            self, "Remove workflow",
            f"Remove “{name}” from config.yaml?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        del workflows[idx]
        self._save(data)
        self._refresh_workflow_list()

    def _open_workflow_form(self, idx: Optional[int]):
        entry = None
        if idx is not None:
            workflows = self._raw().get("workflows") or []
            if idx < len(workflows):
                entry = dict(workflows[idx])
        dlg = WorkflowFormDialog(entry, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_entry:
            data = self._raw()
            workflows = data.setdefault("workflows", [])
            if idx is None:
                workflows.append(dlg.result_entry)
            else:
                workflows[idx] = dlg.result_entry
            self._save(data)
            self._refresh_workflow_list()

    # ==================================================================
    # Notifications page
    # ==================================================================
    _NOTIF_TYPES = [
        ("new_run", "New run started", "A run begins on a monitored workflow"),
        ("failure", "Run failed", "Failure, time-out, or action required"),
        ("success", "Run succeeded", "A run completes successfully"),
    ]

    def _sound_names(self) -> list[str]:
        names = ["none", "default"]
        try:
            from notifications import _NAMED_SOUNDS
            names += [n for n in sorted(_NAMED_SOUNDS) if n not in names]
        except Exception:
            pass
        return names

    def _build_notifications_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        lay.addWidget(_heading(
            "Notifications",
            "Global defaults. Individual workflows can override these."))

        notif = (self._raw().get("notifications") or {})
        sounds = self._sound_names()

        card, card_lay = _card()
        self._notif_controls: dict[str, tuple[QCheckBox, QComboBox]] = {}
        for i, (key, label, sub) in enumerate(self._NOTIF_TYPES):
            row = QHBoxLayout()
            row.setSpacing(12)
            text_col = QVBoxLayout()
            text_col.setSpacing(1)
            l1 = QLabel(label)
            l1.setStyleSheet(f"color: {FG_TEXT}; font-size: 12px; background: transparent;")
            l2 = QLabel(sub)
            l2.setStyleSheet(f"color: {FG_FAINT}; font-size: 11px; background: transparent;")
            text_col.addWidget(l1)
            text_col.addWidget(l2)
            row.addLayout(text_col, 1)

            combo = QComboBox()
            combo.setStyleSheet(_COMBO_CSS)
            combo.addItems(sounds)
            cur = (notif.get(key) or {})
            combo.setCurrentText(str(cur.get("sound", "none")))
            row.addWidget(combo)

            cb = QCheckBox()
            cb.setChecked(bool(cur.get("enabled", True)))
            row.addWidget(cb)

            self._notif_controls[key] = (cb, combo)
            cb.toggled.connect(lambda _v, k=key: self._save_notif_type(k))
            combo.currentTextChanged.connect(lambda _v, k=key: self._save_notif_type(k))
            card_lay.addLayout(row)
            if i < len(self._NOTIF_TYPES) - 1:
                line = QFrame()
                line.setFixedHeight(1)
                line.setStyleSheet("background: #292524; border: none;")
                card_lay.addWidget(line)
        lay.addWidget(card)

        # Delivery card
        card2, card2_lay = _card()
        head = QLabel("Delivery")
        head.setStyleSheet(f"color: {FG_TEXT}; font-size: 12px; font-weight: 600; background: transparent;")
        card2_lay.addWidget(head)
        deliver_row = QHBoxLayout()
        deliver_row.setSpacing(14)

        batch_col = QVBoxLayout()
        batch_col.setSpacing(6)
        batch_col.addWidget(_field_label("Batch window (sec)"))
        self._batch_edit = _line_edit(str(notif.get("batch_window", 1)), width=100)
        batch_col.addWidget(self._batch_edit)
        deliver_row.addLayout(batch_col)

        age_col = QVBoxLayout()
        age_col.setSpacing(6)
        age_col.addWidget(_field_label("Suppress older than"))
        self._age_edit = _line_edit(str(notif.get("max_notification_age", "1h")), width=120)
        age_col.addWidget(self._age_edit)
        deliver_row.addLayout(age_col)

        dur_col = QVBoxLayout()
        dur_col.setSpacing(6)
        dur_col.addWidget(_field_label("Toast duration"))
        self._dur_combo = QComboBox()
        self._dur_combo.setStyleSheet(_COMBO_CSS)
        self._dur_combo.addItems(["short", "long"])
        self._dur_combo.setCurrentText(str(notif.get("duration", "short")))
        dur_col.addWidget(self._dur_combo)
        deliver_row.addLayout(dur_col)
        deliver_row.addStretch()
        card2_lay.addLayout(deliver_row)
        note = QLabel("Batching combines near-simultaneous events into one toast. "
                      "Suppression prevents a flood after waking from sleep.")
        note.setStyleSheet("color: #57534E; font-size: 11px; background: transparent;")
        note.setWordWrap(True)
        card2_lay.addWidget(note)
        lay.addWidget(card2)

        self._batch_edit.editingFinished.connect(self._save_delivery)
        self._age_edit.editingFinished.connect(self._save_delivery)
        self._dur_combo.currentTextChanged.connect(lambda _v: self._save_delivery())

        # PR-mode overrides card
        card3, card3_lay = _card()
        pr = (notif.get("pr") or {})
        head3_row = QHBoxLayout()
        head3 = QLabel("PR-mode overrides")
        head3.setStyleSheet(f"color: {FG_TEXT}; font-size: 12px; font-weight: 600; background: transparent;")
        head3_row.addWidget(head3, 1)
        card3_lay.addLayout(head3_row)

        pr_row1 = QHBoxLayout()
        pr_lbl1 = QLabel("New run sound")
        pr_lbl1.setStyleSheet(f"color: {FG_MUTED}; font-size: 11px; background: transparent;")
        pr_row1.addWidget(pr_lbl1, 1)
        self._pr_sound_combo = QComboBox()
        self._pr_sound_combo.setStyleSheet(_COMBO_CSS)
        self._pr_sound_combo.addItems(["(inherit)"] + self._sound_names())
        pr_new = (pr.get("new_run") or {})
        self._pr_sound_combo.setCurrentText(str(pr_new.get("sound", "(inherit)")))
        pr_row1.addWidget(self._pr_sound_combo)
        card3_lay.addLayout(pr_row1)

        pr_row2 = QHBoxLayout()
        pr_lbl2 = QLabel("Notify on success")
        pr_lbl2.setStyleSheet(f"color: {FG_MUTED}; font-size: 11px; background: transparent;")
        pr_row2.addWidget(pr_lbl2, 1)
        self._pr_success_cb = QCheckBox()
        pr_success = (pr.get("success") or {})
        self._pr_success_cb.setTristate(True)
        if "enabled" in pr_success:
            self._pr_success_cb.setCheckState(
                Qt.CheckState.Checked if pr_success["enabled"] else Qt.CheckState.Unchecked)
        else:
            self._pr_success_cb.setCheckState(Qt.CheckState.PartiallyChecked)
        self._pr_success_cb.setToolTip("Half-checked = inherit the global setting")
        pr_row2.addWidget(self._pr_success_cb)
        card3_lay.addLayout(pr_row2)

        self._pr_sound_combo.currentTextChanged.connect(lambda _v: self._save_pr_overrides())
        self._pr_success_cb.stateChanged.connect(lambda _v: self._save_pr_overrides())
        lay.addWidget(card3)
        return page

    def _save_notif_type(self, key: str):
        cb, combo = self._notif_controls[key]
        data = self._raw()
        notif = data.setdefault("notifications", {})
        sub = notif.setdefault(key, {})
        sub["enabled"] = cb.isChecked()
        sub["sound"] = combo.currentText()
        self._save(data)

    def _save_delivery(self):
        data = self._raw()
        notif = data.setdefault("notifications", {})
        try:
            notif["batch_window"] = max(0, int(self._batch_edit.text().strip() or "1"))
        except ValueError:
            pass
        age = self._age_edit.text().strip()
        if age:
            try:
                parse_duration(age)
                notif["max_notification_age"] = age
            except (ValueError, TypeError):
                pass
        notif["duration"] = self._dur_combo.currentText()
        self._save(data)

    def _save_pr_overrides(self):
        data = self._raw()
        notif = data.setdefault("notifications", {})
        pr = notif.setdefault("pr", {})
        sound = self._pr_sound_combo.currentText()
        if sound == "(inherit)":
            (pr.get("new_run") or {}).pop("sound", None)
            if not pr.get("new_run"):
                pr.pop("new_run", None)
        else:
            pr.setdefault("new_run", {})["sound"] = sound
        state = self._pr_success_cb.checkState()
        if state == Qt.CheckState.PartiallyChecked:
            (pr.get("success") or {}).pop("enabled", None)
            if not pr.get("success"):
                pr.pop("success", None)
        else:
            pr.setdefault("success", {})["enabled"] = state == Qt.CheckState.Checked
        if not pr:
            notif.pop("pr", None)
        self._save(data)

    # ==================================================================
    # PR rules page
    # ==================================================================
    _STALE_LEVELS = [
        ("slightly_stale",   "slightly stale",   "#3D3520", "#EAB308"),
        ("moderately_stale", "moderately stale", "#3A2A1C", "#F97316"),
        ("very_stale",       "very stale",       "#3A1C1C", "#EF4444"),
    ]

    def _build_rules_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        lay.addWidget(_heading(
            "PR rules",
            "Staleness badges and how branch names are interpreted."))

        data = self._raw()
        thresholds = data.get("staleness_thresholds") or {}
        defaults = {"slightly_stale": "1d", "moderately_stale": "3d", "very_stale": "5d"}

        card, card_lay = _card()
        head = QLabel("Staleness thresholds")
        head.setStyleSheet(f"color: {FG_TEXT}; font-size: 12px; font-weight: 600; background: transparent;")
        card_lay.addWidget(head)
        note = QLabel("Time since the PR was last updated. Accepts 30m, 12h, 1d, 2d12h…")
        note.setStyleSheet("color: #57534E; font-size: 11px; background: transparent;")
        card_lay.addWidget(note)
        self._stale_edits: dict[str, QLineEdit] = {}
        for key, label, bg, fg in self._STALE_LEVELS:
            row = QHBoxLayout()
            row.setSpacing(12)
            edit = _line_edit(str(thresholds.get(key, defaults[key])), width=70)
            edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            edit.editingFinished.connect(self._save_thresholds)
            self._stale_edits[key] = edit
            row.addWidget(edit)
            badge = QLabel(f"STALE {thresholds.get(key, defaults[key])}")
            badge.setStyleSheet(
                f"background: {bg}; color: {fg}; font-size: 10px; font-weight: 600; "
                f"padding: 2px 6px; border-radius: 3px;")
            row.addWidget(badge)
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {FG_FAINT}; font-size: 11px; background: transparent;")
            row.addWidget(lbl)
            row.addStretch()
            card_lay.addLayout(row)
        lay.addWidget(card)

        # Jira card
        card2, card2_lay = _card()
        head2 = QLabel("Jira")
        head2.setStyleSheet(f"color: {FG_TEXT}; font-size: 12px; font-weight: 600; background: transparent;")
        card2_lay.addWidget(head2)
        card2_lay.addWidget(_field_label(
            "Base URL — ticket IDs in branch names become clickable badges"))
        self._jira_edit = _line_edit(str(data.get("jira_base_url", "") or ""), mono=True)
        self._jira_edit.setPlaceholderText("https://mycompany.atlassian.net")
        self._jira_edit.editingFinished.connect(self._save_rules_fields)
        card2_lay.addWidget(self._jira_edit)
        lay.addWidget(card2)

        # Bot reviewers card
        card3, card3_lay = _card()
        head3 = QLabel("Bot reviewers")
        head3.setStyleSheet(f"color: {FG_TEXT}; font-size: 12px; font-weight: 600; background: transparent;")
        card3_lay.addWidget(head3)
        card3_lay.addWidget(_field_label(
            "Regex — matching logins get the robot glyph on review badges"))
        self._bot_edit = _line_edit(str(data.get("bot_pattern", r"\[bot\]$") or ""), mono=True)
        self._bot_edit.editingFinished.connect(self._save_rules_fields)
        card3_lay.addWidget(self._bot_edit)
        presets_row = QHBoxLayout()
        presets_row.setSpacing(5)
        presets_lbl = QLabel("Presets:")
        presets_lbl.setStyleSheet("color: #57534E; font-size: 11px; background: transparent;")
        presets_row.addWidget(presets_lbl)
        for preset in (r"\[bot\]$", r"(?i)(\[bot\]|-bot$)", r"(?i)bot"):
            chip = QLabel(preset)
            chip.setStyleSheet(
                f"QLabel {{ background: #33302D; color: {FG_MUTED}; font-size: 11px; "
                f"padding: 3px 8px; border-radius: 4px; font-family: Consolas, monospace; }} "
                f"QLabel:hover {{ color: {FG_LINK}; }}")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.mousePressEvent = lambda e, p=preset: self._apply_bot_preset(p)
            presets_row.addWidget(chip)
        presets_row.addStretch()
        card3_lay.addLayout(presets_row)
        lay.addWidget(card3)
        return page

    def _apply_bot_preset(self, preset: str):
        self._bot_edit.setText(preset)
        self._save_rules_fields()

    def _save_thresholds(self):
        data = self._raw()
        thresholds = data.setdefault("staleness_thresholds", {})
        for key, edit in self._stale_edits.items():
            value = edit.text().strip()
            if not value:
                continue
            try:
                parse_duration(value)
            except (ValueError, TypeError):
                continue
            thresholds[key] = value
        self._save(data)

    def _save_rules_fields(self):
        data = self._raw()
        jira = self._jira_edit.text().strip()
        if jira:
            data["jira_base_url"] = jira
        else:
            data.pop("jira_base_url", None)
        pattern = self._bot_edit.text().strip()
        if pattern:
            try:
                re.compile(pattern)
                data["bot_pattern"] = pattern
            except re.error:
                pass
        self._save(data)

    # ==================================================================
    # GitHub page
    # ==================================================================
    def _build_github_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        lay.addWidget(_heading(
            "GitHub account",
            "A classic personal access token with the repo scope. "
            "Required for private repositories."))

        card, card_lay = _card()
        card_lay.addWidget(_field_label("Personal access token"))
        token_row = QHBoxLayout()
        token_row.setSpacing(8)
        self._token_edit = _line_edit(
            str(self._raw().get("github_token", "") or ""), mono=True)
        self._token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._token_edit.editingFinished.connect(self._save_token)
        token_row.addWidget(self._token_edit, 1)
        test_btn = QPushButton("Test token")
        test_btn.setStyleSheet(_SECONDARY_BTN_CSS)
        test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        test_btn.clicked.connect(self._test_token)
        token_row.addWidget(test_btn)
        card_lay.addLayout(token_row)
        self._token_status = QLabel("")
        self._token_status.setStyleSheet(f"color: {FG_FAINT}; font-size: 11px; background: transparent;")
        card_lay.addWidget(self._token_status)
        lay.addWidget(card)

        card2, card2_lay = _card()
        head2 = QLabel("How to create one")
        head2.setStyleSheet(f"color: {FG_TEXT}; font-size: 12px; font-weight: 600; background: transparent;")
        card2_lay.addWidget(head2)
        steps = QLabel(
            "1. Open github.com/settings/tokens\n"
            "2. Generate new token (classic)\n"
            "3. Enable the top-level repo scope\n"
            "4. Paste it above — it is stored only in your local config.yaml")
        steps.setStyleSheet(f"color: {FG_FAINT}; font-size: 11px; background: transparent;")
        card2_lay.addWidget(steps)
        open_tokens = _link_label("Open github.com/settings/tokens ↗",
                                  lambda: __import__("webbrowser").open(
                                      "https://github.com/settings/tokens"))
        card2_lay.addWidget(open_tokens)
        lay.addWidget(card2)
        return page

    def _save_token(self):
        data = self._raw()
        token = self._token_edit.text().strip()
        if token:
            data["github_token"] = token
        else:
            data.pop("github_token", None)
        self._save(data)

    def _test_token(self):
        token = self._token_edit.text().strip()
        self._token_status.setText("Testing…")
        self._token_status.setStyleSheet(f"color: {FG_FAINT}; font-size: 11px; background: transparent;")
        result: dict = {}

        def _worker():
            try:
                resp = requests.get("https://api.github.com/user",
                                    headers=_gh_headers(token), timeout=10)
                if resp.status_code == 200:
                    remaining = resp.headers.get("X-RateLimit-Remaining", "?")
                    limit = resp.headers.get("X-RateLimit-Limit", "?")
                    result["ok"] = (f"Authenticated as {resp.json().get('login', '?')}"
                                    f" · {remaining} / {limit} requests remaining this hour")
                elif resp.status_code == 401:
                    result["err"] = "Invalid token (401). Generate a new classic token with the repo scope."
                else:
                    result["err"] = f"Unexpected response: HTTP {resp.status_code}"
            except requests.RequestException as exc:
                result["err"] = f"Network error: {exc}"

        def _poll():
            if not result:
                QTimer.singleShot(200, _poll)
                return
            if "ok" in result:
                self._token_status.setText("● " + result["ok"])
                self._token_status.setStyleSheet(
                    "color: #4ADE80; font-size: 11px; background: transparent;")
            else:
                self._token_status.setText("● " + result["err"])
                self._token_status.setStyleSheet(
                    "color: #F87171; font-size: 11px; background: transparent;")

        threading.Thread(target=_worker, daemon=True, name="token-test").start()
        QTimer.singleShot(200, _poll)

    # ==================================================================
    # Raw YAML page
    # ==================================================================
    def _build_yaml_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        head_row = QHBoxLayout()
        head_row.setSpacing(12)
        head_row.addWidget(_heading(
            "config.yaml",
            "The file behind everything in this window. Edit it here or in your "
            "own editor — changes hot-reload either way."), 1)
        open_lbl = _link_label("Open in editor ↗",
                               lambda: OPEN_IN_EDITOR and OPEN_IN_EDITOR())
        open_lbl.setStyleSheet(
            f"QLabel {{ color: {FG_LINK}; font-size: 11px; font-weight: 600; }} "
            f"QLabel:hover {{ text-decoration: underline; }}")
        head_row.addWidget(open_lbl, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head_row)

        self._yaml_edit = QPlainTextEdit()
        self._yaml_edit.setStyleSheet(
            f"QPlainTextEdit {{ background: #171412; border: 1px solid #292524; "
            f"border-radius: 8px; color: {FG_MUTED}; font-size: 11px; padding: 10px; }}")
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._yaml_edit.setFont(mono)
        self._yaml_edit.setMinimumHeight(340)
        lay.addWidget(self._yaml_edit, 1)

        btn_row = QHBoxLayout()
        self._yaml_status = QLabel("")
        self._yaml_status.setStyleSheet(f"color: {FG_FAINT}; font-size: 11px;")
        btn_row.addWidget(self._yaml_status, 1)
        save_btn = QPushButton("Save")
        save_btn.setStyleSheet(_PRIMARY_BTN_CSS)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._save_yaml_text)
        btn_row.addWidget(save_btn)
        lay.addLayout(btn_row)
        return page

    def _load_yaml_text(self):
        if CONFIG_FILE and CONFIG_FILE.exists():
            self._yaml_edit.setPlainText(CONFIG_FILE.read_text(encoding="utf-8"))
        self._yaml_status.setText("")

    def _save_yaml_text(self):
        text = self._yaml_edit.toPlainText()
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as exc:
            self._yaml_status.setText(f"Invalid YAML: {exc}")
            self._yaml_status.setStyleSheet("color: #F87171; font-size: 11px;")
            return
        if CONFIG_FILE:
            CONFIG_FILE.write_text(text, encoding="utf-8")
            self._config_mgr.load()
            self._yaml_status.setText("Saved.")
            self._yaml_status.setStyleSheet("color: #4ADE80; font-size: 11px;")


# ---------------------------------------------------------------------------
# Add / edit workflow form
# ---------------------------------------------------------------------------
class WorkflowFormDialog(QDialog):
    _MODES = [("branch", "Branch"), ("pr", "PR"), ("actor", "Actor"), ("url", "Search URL")]

    def __init__(self, entry: Optional[dict], parent=None):
        super().__init__(parent)
        self._editing = entry is not None
        entry = entry or {}
        self.result_entry: Optional[dict] = None
        self.setWindowTitle("Edit workflow" if self._editing else "Add workflow")
        self.setMinimumSize(620, 620)
        self.setStyleSheet(f"QDialog {{ background: {BG_DARK}; }}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        lay.addWidget(_heading("Edit workflow" if self._editing else "Add workflow"))

        # URL
        url_col = QVBoxLayout()
        url_col.setSpacing(6)
        url_col.addWidget(_field_label("GitHub URL"))
        self._url_edit = _line_edit(str(entry.get("url", "") or ""), mono=True)
        self._url_edit.setPlaceholderText(
            "https://github.com/your-org/your-repo/actions/workflows/ci.yml")
        self._url_edit.textChanged.connect(self._on_url_changed)
        url_col.addWidget(self._url_edit)
        hint_row = QHBoxLayout()
        hint_row.setSpacing(6)
        self._detect_dot = QLabel()
        self._detect_dot.setFixedSize(6, 6)
        self._detect_dot.setStyleSheet(f"background: {FG_FAINT}; border-radius: 3px;")
        hint_row.addWidget(self._detect_dot)
        self._detect_lbl = QLabel("Paste a GitHub Actions URL to auto-detect the mode.")
        self._detect_lbl.setStyleSheet(f"color: {FG_FAINT}; font-size: 11px;")
        self._detect_lbl.setWordWrap(True)
        hint_row.addWidget(self._detect_lbl, 1)
        url_col.addLayout(hint_row)
        lay.addLayout(url_col)

        # Mode segmented
        mode_col = QVBoxLayout()
        mode_col.setSpacing(6)
        mode_col.addWidget(_field_label("Mode"))
        seg = QWidget()
        seg.setObjectName("seg")
        seg.setStyleSheet(
            "QWidget#seg { background: #262220; border: 1px solid #3B3734; border-radius: 6px; }")
        seg_lay = QHBoxLayout(seg)
        seg_lay.setContentsMargins(3, 3, 3, 3)
        seg_lay.setSpacing(2)
        self._mode = entry.get("mode", "branch")
        self._mode_labels: dict[str, QLabel] = {}
        for key, label in self._MODES:
            lbl = QLabel(label)
            lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            lbl.mousePressEvent = lambda e, k=key: self._set_mode(k)
            seg_lay.addWidget(lbl)
            self._mode_labels[key] = lbl
        seg.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        mode_col.addWidget(seg)
        self._mode_hint = QLabel("")
        self._mode_hint.setStyleSheet("color: #57534E; font-size: 11px;")
        self._mode_hint.setWordWrap(True)
        mode_col.addWidget(self._mode_hint)
        lay.addLayout(mode_col)

        # Name + polling
        np_row = QHBoxLayout()
        np_row.setSpacing(14)
        name_col = QVBoxLayout()
        name_col.setSpacing(6)
        name_col.addWidget(_field_label("Display name"))
        self._name_edit = _line_edit(str(entry.get("name", "") or ""))
        name_col.addWidget(self._name_edit)
        np_row.addLayout(name_col, 1)
        rate_col = QVBoxLayout()
        rate_col.setSpacing(6)
        rate_col.addWidget(_field_label("Polling rate (sec)"))
        self._rate_edit = _line_edit(str(entry.get("polling_rate", 60)), width=150)
        rate_col.addWidget(self._rate_edit)
        np_row.addLayout(rate_col, 0)
        lay.addLayout(np_row)

        # Branch-mode options
        self._branch_box, branch_lay = _card()
        branch_head = QLabel("Branch-mode options")
        branch_head.setStyleSheet(f"color: {FG_TEXT}; font-size: 12px; font-weight: 600; background: transparent;")
        branch_lay.addWidget(branch_head)
        branch_lay.addWidget(_field_label("Branch (optional — parsed from the URL when set there)"))
        self._branch_edit = _line_edit(str(entry.get("branch", "") or ""), width=220)
        branch_lay.addWidget(self._branch_edit)
        lay.addWidget(self._branch_box)

        # PR-mode options
        self._pr_box, pr_lay = _card()
        pr_head = QLabel("PR-mode options")
        pr_head.setStyleSheet(f"color: {FG_TEXT}; font-size: 12px; font-weight: 600; background: transparent;")
        pr_lay.addWidget(pr_head)
        pr_nums = QHBoxLayout()
        pr_nums.setSpacing(14)
        maxpr_col = QVBoxLayout()
        maxpr_col.setSpacing(6)
        maxpr_col.addWidget(_field_label("Max PR rows"))
        self._maxpr_edit = _line_edit(str(entry.get("max_prs", "") or ""), width=130)
        maxpr_col.addWidget(self._maxpr_edit)
        pr_nums.addLayout(maxpr_col)
        stale_col = QVBoxLayout()
        stale_col.setSpacing(6)
        stale_col.addWidget(_field_label("Remove stale rows after"))
        self._stale_edit = _line_edit(str(entry.get("pr_stale_after", "") or ""), width=170)
        self._stale_edit.setPlaceholderText("5m")
        stale_col.addWidget(self._stale_edit)
        pr_nums.addLayout(stale_col)
        pr_nums.addStretch()
        pr_lay.addLayout(pr_nums)
        pr_lay.addWidget(_field_label(
            "Aggregate status from extra workflows (comma-separated .yml files)"))
        extra = entry.get("extra_workflows") or []
        self._extra_edit = _line_edit(", ".join(str(x) for x in extra), mono=True)
        self._extra_edit.setPlaceholderText("integration-tests.yml, lint.yml")
        pr_lay.addWidget(self._extra_edit)
        pr_lay.addWidget(_field_label(
            "Ignore noisy workflows (comma-separated .yml files)"))
        ignore = entry.get("ignore_workflows") or []
        self._ignore_edit = _line_edit(
            ", ".join(x if isinstance(x, str) else str(x.get("file", "")) for x in ignore),
            mono=True)
        self._ignore_edit.setPlaceholderText("shadow-it-check.yml")
        pr_lay.addWidget(self._ignore_edit)
        lay.addWidget(self._pr_box)

        # Actor-mode options
        self._actor_box, actor_lay = _card()
        actor_head = QLabel("Actor-mode options")
        actor_head.setStyleSheet(f"color: {FG_TEXT}; font-size: 12px; font-weight: 600; background: transparent;")
        actor_lay.addWidget(actor_head)
        actor_lay.addWidget(_field_label("Filter"))
        self._filter_combo = QComboBox()
        self._filter_combo.setStyleSheet(_COMBO_CSS)
        self._filter_combo.addItems(["(all runs)", "failed"])
        if entry.get("filter") == "failed":
            self._filter_combo.setCurrentText("failed")
        actor_lay.addWidget(self._filter_combo)
        lay.addWidget(self._actor_box)

        # URL-mode options
        self._query_box, query_lay = _card()
        query_head = QLabel("Search-URL options")
        query_head.setStyleSheet(f"color: {FG_TEXT}; font-size: 12px; font-weight: 600; background: transparent;")
        query_lay.addWidget(query_head)
        query_lay.addWidget(_field_label("Search query (@me = your login)"))
        self._query_edit = _line_edit(str(entry.get("query", "") or ""), mono=True)
        self._query_edit.setPlaceholderText("is:pr is:open review-requested:@me")
        query_lay.addWidget(self._query_edit)
        lay.addWidget(self._query_box)

        # YAML preview
        preview_col = QVBoxLayout()
        preview_col.setSpacing(6)
        preview_head = QHBoxLayout()
        preview_head.setSpacing(8)
        preview_head.addWidget(_field_label("config.yaml preview"))
        preview_note = QLabel("— this entry will be written to your file")
        preview_note.setStyleSheet("color: #57534E; font-size: 11px;")
        preview_head.addWidget(preview_note)
        preview_head.addStretch()
        preview_col.addLayout(preview_head)
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setStyleSheet(
            f"QPlainTextEdit {{ background: #171412; border: 1px solid #292524; "
            f"border-radius: 6px; color: {FG_MUTED}; font-size: 11px; padding: 8px; }}")
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._preview.setFont(mono)
        self._preview.setFixedHeight(150)
        preview_col.addWidget(self._preview)
        lay.addLayout(preview_col)

        # Actions
        actions = QHBoxLayout()
        actions.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(_SECONDARY_BTN_CSS)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(cancel_btn)
        self._ok_btn = QPushButton("Save" if self._editing else "Add workflow")
        self._ok_btn.setStyleSheet(_PRIMARY_BTN_CSS)
        self._ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ok_btn.clicked.connect(self._accept)
        actions.addWidget(self._ok_btn)
        lay.addLayout(actions)

        # Live preview updates
        for w in (self._url_edit, self._name_edit, self._rate_edit, self._branch_edit,
                  self._maxpr_edit, self._stale_edit, self._extra_edit,
                  self._ignore_edit, self._query_edit):
            w.textChanged.connect(self._update_preview)
        self._filter_combo.currentTextChanged.connect(lambda _v: self._update_preview())

        self._set_mode(self._mode, detect=False)
        if entry.get("url"):
            self._on_url_changed(entry["url"])
        self._update_preview()

    # ------------------------------------------------------------------
    def _set_mode(self, mode: str, detect: bool = True):
        self._mode = mode
        for key, lbl in self._mode_labels.items():
            active = key == mode
            lbl.setStyleSheet(
                "padding: 5px 14px; border-radius: 4px; font-size: 12px; "
                + (f"background: #3D3530; color: {FG_LINK}; font-weight: 600;"
                   if active else f"color: {FG_MUTED};"))
        hints = {
            "branch": "One fixed row for this workflow on a branch.",
            "pr":     "PR mode shows one row per open pull request you authored on this workflow.",
            "actor":  "One row per recent workflow run by you across the whole repo.",
            "url":    "One row per PR returned by a GitHub search query (spans repos).",
        }
        self._mode_hint.setText(hints.get(mode, ""))
        self._branch_box.setVisible(mode == "branch")
        self._pr_box.setVisible(mode == "pr")
        self._actor_box.setVisible(mode == "actor")
        self._query_box.setVisible(mode == "url")
        if detect:
            self._update_preview()

    def _on_url_changed(self, text: str):
        mode, hint = detect_mode(text)
        ok = mode is not None
        self._detect_dot.setStyleSheet(
            f"background: {'#4ADE80' if ok else '#F87171'}; border-radius: 3px;")
        self._detect_lbl.setText(hint)
        if mode == "actor" and self._mode not in ("actor",):
            self._set_mode("actor")
        elif mode == "url" and self._mode not in ("url",):
            self._set_mode("url")
            query = extract_query(text)
            if query and not self._query_edit.text().strip():
                self._query_edit.setText(query)
        elif mode == "branch" and self._mode not in ("branch", "pr"):
            self._set_mode("branch")
        self._update_preview()

    def _build_entry(self) -> Optional[dict]:
        entry: dict = {}
        mode = self._mode
        url = self._url_edit.text().strip()
        query = self._query_edit.text().strip()
        if mode == "url":
            if not query and url:
                query = extract_query(url)
            if not query:
                return None
            entry["query"] = query
        else:
            if not url:
                return None
            entry["url"] = url
        name = self._name_edit.text().strip()
        if name:
            entry["name"] = name
        if mode != "branch":
            entry["mode"] = mode
        try:
            rate = int(self._rate_edit.text().strip())
            if rate > 0:
                entry["polling_rate"] = rate
        except ValueError:
            pass
        if mode == "branch":
            branch = self._branch_edit.text().strip()
            if branch:
                entry["branch"] = branch
        elif mode == "pr":
            try:
                max_prs = int(self._maxpr_edit.text().strip())
                if max_prs > 0:
                    entry["max_prs"] = max_prs
            except ValueError:
                pass
            stale = self._stale_edit.text().strip()
            if stale:
                try:
                    parse_duration(stale)
                    entry["pr_stale_after"] = stale
                except (ValueError, TypeError):
                    pass
            extra = [x.strip() for x in self._extra_edit.text().split(",") if x.strip()]
            if extra:
                entry["extra_workflows"] = extra
            ignore = [x.strip() for x in self._ignore_edit.text().split(",") if x.strip()]
            if ignore:
                entry["ignore_workflows"] = ignore
        elif mode == "actor":
            if self._filter_combo.currentText() == "failed":
                entry["filter"] = "failed"
        return entry

    def _update_preview(self):
        entry = self._build_entry()
        if entry is None:
            key = "search query" if self._mode == "url" else "GitHub URL"
            self._preview.setPlainText(f"# Enter a {key} above to preview the entry")
            self._ok_btn.setEnabled(False)
            return
        self._ok_btn.setEnabled(True)
        self._preview.setPlainText(entry_to_yaml(entry).rstrip())

    def _accept(self):
        entry = self._build_entry()
        if entry is None:
            return
        self.result_entry = entry
        self.accept()
