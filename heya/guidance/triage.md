---
name: triage
description: Full triage workflow from intake to a paste-ready comment. Handles single issues and collections, and applies reproduction, diagnosis, and remediation in sequence.
---

# Triage workflow

Use this to take a bug report or a backlog from intake to a finished, paste-ready
answer. You produce files; you never post anything or change a ticket's state.
The human posts. Work only on a disposable Playground site or a development site
the user gives you, never on production.

## Two input shapes

The input decides the flow.

- Single issue: a pasted report, or a ticket you fetch (a Linear id or url, a
  GitHub issue url, or pasted text). Fetch it with the available tools (the
  context MCP linear or github provider, gh, or web_fetch), then run the full
  pipeline and produce one finished comment.
- Collection: a Linear view or label, or a list of issues. Rank the issues from
  their text alone first; build no environment yet. Produce a pick list. When the
  user confirms (for example "validate the top 3"), run those one at a time
  through the single-issue flow. Cap each confirmed batch at three.

## Single issue

1. Parse the report and call start_reproduction.
2. Reproduce on the disposable environment (read_guidance('reproduction')).
3. diagnose_issue (read_guidance('diagnosis')). Escalate if the evidence is thin.
4. If reproduced, propose and verify a fix (read_guidance('remediation')).
5. Call triage_report with the decision bar below. It writes triage-report.md and
   a paste-ready triage-comment.md. Tell the user where they are. Do not post.

## The decision bar

The comment is the product. A developer or product person should be able to set a
priority or close the ticket from it without re-investigating. Every report and
comment carries:

- A plain-language opening: what the shopper or merchant experiences, not what the
  code does.
- Impact: who is affected, under what conditions, the consequence for the store,
  and whether a workaround exists.
- A suggested priority with one line of reasoning, marked as a suggestion. Scale:
  high when money or data goes wrong or checkout is blocked with no workaround;
  medium when broken but a workaround exists or only non-default setups are hit;
  low when cosmetic or an easy-workaround edge case; close when the verdict is
  fixed-since-report or cannot-reproduce. You cannot suggest close for a
  reproduced or blocked issue; triage_report enforces this.
- The one-click repro link attached, not offered.
- A suggested next step.

## Collection

Rank each candidate from its text: spec completeness (steps, versions, expected
vs actual), complexity 1 to 10, staleness, impact, and whether it looks buildable.
Give each issue exactly one route:

- ready-to-fix: clear steps, low complexity, recent. Print the handoff command.
- triage-first: plausible but stale or unverified. Offer to validate it now.
- needs-info: missing steps or versions. Draft the needs-info note for the user.
- skip: already handled, security-sensitive, or too complex. State the reason.

Call record_pick_list with the ranked items. It writes pick-list.md. Then wait for
the user to pick before building anything.

## Hard rules

- No evidence, no verdict (inherited from reproduction).
- Never post a comment, never change status or labels. Produce the files; the
  human posts.
- Dev or disposable environments only. Never production.
