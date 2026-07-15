"""Integration tests for the Settings window (offscreen Qt, no network)."""

from __future__ import annotations

import pytest

import settings_ui
from settings_ui import (SettingsDialog, WorkflowFormDialog, detect_mode,
                         extract_query, load_raw_config, save_raw_config)

BASE_CONFIG = """\
# user comment — must survive settings writes
github_token: ""
beta:
  settings_ui: true
workflows:
  - url: https://github.com/o/r/actions/workflows/ci.yml
    name: CI
    polling_rate: 30
    branch: main
"""


@pytest.fixture
def dialog(app_env, qapp):
    def _make(config_text: str = BASE_CONFIG) -> SettingsDialog:
        app_env.config_path.write_text(config_text, encoding="utf-8")
        cfg = app_env.main.ConfigManager()
        dlg = SettingsDialog(cfg)
        dlg.show()
        qapp.processEvents()
        return dlg
    return _make


# ---------------------------------------------------------------------------
# Mode detection
# ---------------------------------------------------------------------------
def test_detect_mode_workflow_url():
    mode, hint = detect_mode("https://github.com/o/r/actions/workflows/ci.yml")
    assert mode == "branch"
    assert "ci.yml" in hint


def test_detect_mode_actor_url():
    assert detect_mode("https://github.com/o/r/actions?query=actor%3Ame")[0] == "actor"


def test_detect_mode_search_url():
    assert detect_mode("https://github.com/pulls?q=is%3Apr+is%3Aopen")[0] == "url"
    assert extract_query("https://github.com/pulls?q=is%3Apr+is%3Aopen") == "is:pr is:open"


def test_detect_mode_garbage():
    assert detect_mode("https://example.com/nope")[0] is None


# ---------------------------------------------------------------------------
# Workflow form
# ---------------------------------------------------------------------------
def test_form_builds_pr_entry(app_env, qapp):
    form = WorkflowFormDialog(None)
    form._url_edit.setText("https://github.com/o/r/actions/workflows/pr.yml")
    form._set_mode("pr")
    form._name_edit.setText("Acceptance/PR")
    form._rate_edit.setText("45")
    form._maxpr_edit.setText("5")
    form._stale_edit.setText("5m")
    form._extra_edit.setText("integration-tests.yml, lint.yml")
    form._ignore_edit.setText("shadow-it-check.yml")
    entry = form._build_entry()
    assert entry == {
        "url": "https://github.com/o/r/actions/workflows/pr.yml",
        "name": "Acceptance/PR",
        "mode": "pr",
        "polling_rate": 45,
        "max_prs": 5,
        "pr_stale_after": "5m",
        "extra_workflows": ["integration-tests.yml", "lint.yml"],
        "ignore_workflows": ["shadow-it-check.yml"],
    }
    assert "mode: pr" in form._preview.toPlainText()


def test_form_url_paste_switches_to_search_mode(app_env, qapp):
    form = WorkflowFormDialog(None)
    form._url_edit.setText("https://github.com/pulls?q=is%3Apr+review-requested%3A%40me")
    assert form._mode == "url"
    assert form._query_edit.text() == "is:pr review-requested:@me"
    entry = form._build_entry()
    assert entry["mode"] == "url"
    assert entry["query"] == "is:pr review-requested:@me"
    assert "url" not in entry


def test_form_requires_url(app_env, qapp):
    form = WorkflowFormDialog(None)
    assert form._build_entry() is None
    assert not form._ok_btn.isEnabled()


# ---------------------------------------------------------------------------
# Settings pages write config.yaml (comments preserved)
# ---------------------------------------------------------------------------
def test_workflow_list_shows_entries(dialog):
    dlg = dialog()
    dlg._select_tab("workflows")
    labels = [w.text() for w in dlg._wf_list.findChildren(type(dlg._nav_labels["workflows"]))]
    assert any("CI" == t for t in labels)


def test_threshold_save_preserves_comments(dialog, app_env):
    dlg = dialog()
    dlg._select_tab("rules")
    dlg._stale_edits["slightly_stale"].setText("2d")
    dlg._save_thresholds()
    text = app_env.config_path.read_text(encoding="utf-8")
    assert "# user comment — must survive settings writes" in text
    assert "slightly_stale: 2d" in text


def test_threshold_rejects_invalid_duration(dialog, app_env):
    dlg = dialog()
    dlg._select_tab("rules")
    dlg._stale_edits["very_stale"].setText("banana")
    dlg._save_thresholds()
    assert "banana" not in app_env.config_path.read_text(encoding="utf-8")


def test_token_save(dialog, app_env):
    dlg = dialog()
    dlg._select_tab("github")
    dlg._token_edit.setText("ghp_test123")
    dlg._save_token()
    assert "ghp_test123" in app_env.config_path.read_text(encoding="utf-8")


def test_notification_toggle_save(dialog, app_env):
    dlg = dialog()
    dlg._select_tab("notifications")
    cb, combo = dlg._notif_controls["success"]
    combo.setCurrentText("default")
    text = app_env.config_path.read_text(encoding="utf-8")
    assert "success" in text and "sound: default" in text


def test_remove_workflow(dialog, app_env, monkeypatch, qapp):
    dlg = dialog()
    dlg._select_tab("workflows")
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    dlg._remove_workflow(0)
    data = load_raw_config()
    assert not (data.get("workflows") or [])


def test_yaml_page_rejects_invalid_yaml(dialog, app_env):
    dlg = dialog()
    dlg._select_tab("yaml")
    before = app_env.config_path.read_text(encoding="utf-8")
    dlg._yaml_edit.setPlainText("workflows: [unclosed")
    dlg._save_yaml_text()
    assert "Invalid YAML" in dlg._yaml_status.text()
    assert app_env.config_path.read_text(encoding="utf-8") == before


def test_yaml_page_saves_valid_yaml(dialog, app_env):
    dlg = dialog()
    dlg._select_tab("yaml")
    dlg._yaml_edit.setPlainText("workflows: []\n")
    dlg._save_yaml_text()
    assert dlg._yaml_status.text() == "Saved."
    assert app_env.config_path.read_text(encoding="utf-8") == "workflows: []\n"


def test_raw_roundtrip_without_ruamel(app_env, monkeypatch):
    monkeypatch.setattr(settings_ui, "_HAVE_RUAMEL", False)
    app_env.config_path.write_text("workflows: []\n", encoding="utf-8")
    data = load_raw_config()
    data.setdefault("workflows", []).append({"url": "https://x", "name": "X"})
    assert save_raw_config(data)
    text = app_env.config_path.read_text(encoding="utf-8")
    assert "https://x" in text


# ---------------------------------------------------------------------------
# Screenshots
# ---------------------------------------------------------------------------
def test_screenshot_settings_pages(dialog, screenshot):
    dlg = dialog()
    for tab in ("workflows", "notifications", "rules", "github", "yaml"):
        dlg._select_tab(tab)
        screenshot(dlg, f"settings-{tab}")


def test_screenshot_workflow_form(app_env, qapp, screenshot):
    form = WorkflowFormDialog(None)
    form._url_edit.setText("https://github.com/your-org/your-repo/actions/workflows/acceptance-pr.yml")
    form._set_mode("pr")
    form._name_edit.setText("Acceptance/PR")
    form._maxpr_edit.setText("5")
    form._extra_edit.setText("integration-tests.yml, lint.yml")
    form.show()
    qapp.processEvents()
    screenshot(form, "settings-add-workflow")
