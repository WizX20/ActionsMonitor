<!--
Thanks for the PR! Fill in the sections below — the checklist at the bottom catches the things that bounce most often in review.
-->

## What

<!-- One or two sentences on the change. -->

## Why

<!-- The user-facing problem or use case. Link the issue if there is one: `Fixes #123`. -->

## How it works

<!-- Brief technical note on the approach if non-obvious. Skip for trivial changes. -->

## Testing

<!-- How you verified this. -->

- [ ] Tested on Windows
- [ ] Tested on Linux (only required if the change touches Linux paths, notifications, tray, or update flow)
- [ ] Exercised the affected mode(s): <!-- branch / PR / actor / URL --> 

## Screenshots / recordings

<!-- Required for any UI change. Drag-and-drop into this box. Delete the section otherwise. -->

## Checklist

- [ ] `CHANGELOG.md` has a new dated entry at the top of the list (user-visible changes only).
- [ ] `config.template.yaml` updated and commented if a config option was added or changed.
- [ ] No new top-level dependency added without prior discussion.
- [ ] All GitHub API calls go through `_github_api_get` / `_gh_headers` (no direct `requests.get` against `api.github.com`).
- [ ] No widget calls from poller threads — pollers emit `StatusEvent`s on the queue.
- [ ] Commits follow the conventions in [CONTRIBUTING.md](../CONTRIBUTING.md) (imperative subject ≤72 chars, new commits not amends, hooks not skipped).
