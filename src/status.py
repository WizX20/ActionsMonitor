"""Shared status constants — single source of truth for the seven workflow
states. Kept pure (no PIL / Qt / requests) so any module can import without
pulling heavy deps. pollers, icons, and widgets all source ST_* from here.
"""

from __future__ import annotations

from typing import Optional


ST_UNKNOWN    = "unknown"
ST_QUEUED     = "queued"
ST_RUNNING    = "in_progress"
ST_SUCCESS    = "success"
ST_FAILURE    = "failure"
ST_CANCELLED  = "cancelled"
ST_SKIPPED    = "skipped"


# Sort priority: higher = more urgent (used for status-based row sorting,
# pollers' "representative run" picker, and `_worst_status` aggregation).
_STATUS_PRIORITY = {
    ST_FAILURE: 6, ST_RUNNING: 5, ST_QUEUED: 4, ST_CANCELLED: 3,
    ST_SUCCESS: 2, ST_SKIPPED: 1, ST_UNKNOWN: 0,
}


CONCLUSION_MAP = {
    "success":          ST_SUCCESS,
    "failure":          ST_FAILURE,
    "timed_out":        ST_FAILURE,
    "action_required":  ST_FAILURE,
    "startup_failure":  ST_FAILURE,
    "cancelled":        ST_CANCELLED,
    "stale":            ST_CANCELLED,
    "skipped":          ST_SKIPPED,
    "neutral":          ST_SUCCESS,
    None:               ST_RUNNING,
}


def _resolve_status(api_status: str, conclusion: Optional[str]) -> str:
    """Map GitHub API status/conclusion fields to an internal status constant."""
    if api_status == "completed":
        return CONCLUSION_MAP.get(conclusion, ST_UNKNOWN)
    if api_status == "in_progress":
        return ST_RUNNING
    if api_status in ("queued", "waiting", "pending", "requested"):
        return ST_QUEUED
    return ST_UNKNOWN
