"""Integration tests for the main window (offscreen Qt, no network)."""

from __future__ import annotations

from demo_data import DEMO_CONFIG, demo_events
from pollers import StatusEvent, WorkflowState


def test_empty_state_shown_without_workflows(app_env):
    win = app_env.make_window("workflows: []\n")
    assert win._empty_state is not None
    assert win._empty_state.isVisible()
    assert win._summary_lbl.text() == "No workflows monitored"


def test_branch_row_created_at_startup(app_env):
    win = app_env.make_window(DEMO_CONFIG)
    assert win._empty_state is None
    # Two branch-mode rows exist immediately; PR rows appear per event.
    assert (0, None) in win._rows
    assert (1, None) in win._rows
    assert len(win._rows) == 2


def test_events_render_rows_and_summary(app_env):
    win = app_env.make_window(DEMO_CONFIG)
    for ev in demo_events():
        app_env.push(win, ev)
    assert len(win._rows) == 4
    # 1 failed (production), 1 running (PR 4308), 2 passing
    assert win._summary_lbl.text() == "1 failed · 1 running · 2 passing"
    assert win._updated_lbl.text().startswith("Updated ")
    # Worst status escalates the summary dot to the failure colour
    from widgets import COLOUR
    assert COLOUR["failure"] in win._summary_dot.styleSheet()


def test_section_counts(app_env):
    win = app_env.make_window(DEMO_CONFIG)
    for ev in demo_events():
        app_env.push(win, ev)
    assert win._section_counts["Workflows"].text() == "2"
    assert win._section_counts["Acceptance/PR"].text() == "2"


def test_pr_row_removal(app_env):
    win = app_env.make_window(DEMO_CONFIG)
    events = demo_events()
    for ev in events:
        app_env.push(win, ev)
    sub_key = events[2].sub_key
    app_env.push(win, StatusEvent(2, events[2].new_state, sub_key=sub_key, removed=True))
    assert (2, sub_key) not in win._rows
    assert win._section_counts["Acceptance/PR"].text() == "1"
    assert win._summary_lbl.text() == "1 failed · 2 passing"


def test_snooze_toggle_and_summary_exclusion(app_env):
    win = app_env.make_window(DEMO_CONFIG)
    for ev in demo_events():
        app_env.push(win, ev)
    key = (1, None)  # the failing production row
    win._toggle_snooze(key)
    assert key in win._snoozed
    assert win._rows[key]._snoozed
    win._update_summary()
    assert win._summary_lbl.text() == "1 running · 2 passing"
    win._toggle_snooze(key)
    assert key not in win._snoozed
    assert not win._rows[key]._snoozed


def test_sort_menu_state(app_env):
    win = app_env.make_window(DEMO_CONFIG)
    for ev in demo_events():
        app_env.push(win, ev)
    win._set_sort("Workflows", "status_asc")
    assert win._sort_labels["Workflows"].text() == "Sort: Status ▲"
    # Persisted
    state = win._load_state()
    assert state["section_sort"]["Workflows"] == "status_asc"
    win._clear_sort("Workflows")
    assert win._sort_labels["Workflows"].text() == "Sort ▾"
    assert "section_sort" not in win._load_state()


def test_failed_row_info_line_is_red(app_env):
    win = app_env.make_window(DEMO_CONFIG)
    for ev in demo_events():
        app_env.push(win, ev)
    from widgets import COLOUR
    failed_row = win._rows[(1, None)]
    ok_row = win._rows[(0, None)]
    assert COLOUR["failure"] in failed_row._info_lbl.styleSheet()
    assert COLOUR["failure"] not in ok_row._info_lbl.styleSheet()


def test_error_state_renders(app_env):
    win = app_env.make_window(DEMO_CONFIG)
    app_env.push(win, StatusEvent(0, WorkflowState(
        name="Acceptance Merge", url="", branch="acceptance",
        status="failure", error="404 - repository not found. Check your token's repo scope.")))
    row = win._rows[(0, None)]
    assert "Error: 404" in row._info_lbl.text()


def test_beta_gating_off_by_default(app_env):
    win = app_env.make_window(DEMO_CONFIG)
    assert not win._settings_btn.isVisible()
    assert not win._footer_settings_lbl.isVisible()
    assert win._footer_config_lbl.isVisible()


def test_beta_gating_on(app_env):
    win = app_env.make_window("beta:\n  settings_ui: true\nworkflows: []\n")
    assert win._settings_btn.isVisible()
    assert win._footer_settings_lbl.isVisible()
    assert not win._footer_config_lbl.isVisible()


def test_beta_gating_follows_config_reload(app_env):
    win = app_env.make_window(DEMO_CONFIG)
    assert not win._settings_btn.isVisible()
    app_env.config_path.write_text(
        "beta:\n  settings_ui: true\n" + DEMO_CONFIG, encoding="utf-8")
    win._config_mgr._mtime = 0  # force mtime-diff so load() reports a change
    win._watch_config()
    assert win._settings_btn.isVisible()


# ---------------------------------------------------------------------------
# Screenshots (also run standalone via `task screenshots`)
# ---------------------------------------------------------------------------
def test_screenshot_main_empty(app_env, screenshot):
    win = app_env.make_window("workflows: []\n")
    win.resize(460, 420)
    screenshot(win, "main-empty")


def test_screenshot_main_populated(app_env, screenshot):
    win = app_env.make_window(DEMO_CONFIG)
    for ev in demo_events():
        app_env.push(win, ev)
    win.resize(620, 560)
    screenshot(win, "main-populated")


def test_screenshot_main_snoozed(app_env, screenshot):
    win = app_env.make_window(DEMO_CONFIG)
    events = demo_events()
    for ev in events:
        app_env.push(win, ev)
    win._toggle_snooze((2, events[3].sub_key))
    win.resize(620, 560)
    screenshot(win, "main-snoozed-row")
