"""Reusable fake config + StatusEvents for tests and screenshot captures."""

from __future__ import annotations

from pollers import (ST_FAILURE, ST_RUNNING, ST_SUCCESS, StatusEvent,
                     WorkflowState)

DEMO_CONFIG = """\
jira_base_url: "https://mycompany.atlassian.net"
workflows:
  - url: https://github.com/your-org/your-repo/actions/workflows/acceptance-merge.yml
    name: "Acceptance Merge"
    polling_rate: 30
    branch: acceptance
  - url: https://github.com/your-org/your-repo/actions/workflows/production-merge.yml
    name: "Production Merge"
    polling_rate: 30
    branch: production
  - url: https://github.com/your-org/your-repo/actions/workflows/acceptance-pr.yml
    name: "Acceptance/PR"
    mode: "pr"
    polling_rate: 45
"""

DEMO_CONFIG_BETA = "beta:\n  settings_ui: true\n" + DEMO_CONFIG


def demo_events() -> list[StatusEvent]:
    """One green branch row, one red branch row, two PR rows (running + approved)."""
    return [
        StatusEvent(0, WorkflowState(
            name="Acceptance Merge",
            url="https://github.com/your-org/your-repo/actions/workflows/acceptance-merge.yml",
            branch="acceptance", status=ST_SUCCESS, run_id=1, run_number=3951,
            run_url="https://github.com/your-org/your-repo/actions/runs/1",
            started_at="2026-04-29T12:14:00Z")),
        StatusEvent(1, WorkflowState(
            name="Production Merge",
            url="https://github.com/your-org/your-repo/actions/workflows/production-merge.yml",
            branch="production", status=ST_FAILURE, run_id=2, run_number=386,
            run_url="https://github.com/your-org/your-repo/actions/runs/2",
            started_at="2026-04-29T12:46:00Z")),
        StatusEvent(2, WorkflowState(
            name="Acceptance/PR",
            url="https://github.com/your-org/your-repo/actions/workflows/acceptance-pr.yml",
            branch=None, status=ST_RUNNING, run_id=3, run_number=4415,
            head_branch="EDU-9303-consolidate-usecase-error-handling",
            branch_short="EDU-9303-consolidate-usecase-error-handling",
            branch_prefix="chore",
            pr_number=4308,
            pr_title="EDU-9303: Consolidate UseCaseError handling and fix log severity",
            pr_url="https://github.com/your-org/your-repo/pull/4308",
            is_draft=True, has_conflict=True, review_status="pending",
            pr_target="acceptance", jira_key="EDU-9303",
            started_at="2026-04-29T12:39:00Z",
        ), sub_key="EDU-9303-consolidate-usecase-error-handling#4308"),
        StatusEvent(2, WorkflowState(
            name="Acceptance/PR",
            url="https://github.com/your-org/your-repo/actions/workflows/acceptance-pr.yml",
            branch=None, status=ST_SUCCESS, run_id=4, run_number=4392,
            head_branch="EDU-9350-interrupt-stuck-bulk-mails",
            branch_short="EDU-9350-interrupt-stuck-bulk-mails",
            branch_prefix="hotfix",
            pr_number=4321,
            pr_title="EDU-9350 HOTFIX | PROD: Fix BulkMailSender non-performant query",
            pr_url="https://github.com/your-org/your-repo/pull/4321",
            review_status="approved",
            pr_target="production", jira_key="EDU-9350",
            staleness_level="moderately_stale",
            pr_updated_at="2026-04-28T07:12:00Z",
            started_at="2026-04-28T07:12:00Z",
        ), sub_key="EDU-9350-interrupt-stuck-bulk-mails#4321"),
    ]
