# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues in `eliancanul/iot-indoor-positioning`. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `gh issue edit <number> --remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

Infer the repo from `git remote -v`; `gh` does this automatically when run inside a clone.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## Wayfinding operations

Used by `/wayfinder`. The map is a single issue with child issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. Create it with `gh issue create --label wayfinder:map`.
- **Child ticket**: create an issue linked to the map as a GitHub sub-issue where supported. Where sub-issues are unavailable, add `Part of #<map>` at the top of the child body and maintain the relationship in the map.
- **Blocking**: use GitHub's native issue dependencies when available. Add an edge with `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric database id, not its issue number or node id. If dependencies are unavailable, use a `Blocked by: #<n>` line in the child body.
- **Frontier query**: list the map's open children, remove any with open blockers or an assignee, and take the first remaining ticket in map order.
- **Claim**: `gh issue edit <n> --add-assignee @me`, before any work on the ticket.
- **Resolve**: post the answer as a comment, close the issue, then append a context pointer to the map's Decisions-so-far.
