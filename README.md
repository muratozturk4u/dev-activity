# dev-activity

An anonymous developer activity summary, generated from local git history.

It contains aggregate numbers only — no repository names, project details, commit
messages or code. Most of the work behind these numbers lives in private
repositories, so the figures here will not match the contribution graph on any
profile page.

## What is in this repository

| File | What it is |
|---|---|
| `activity.json` | The dataset: totals, streaks, and commit counts by date, month, year, weekday and hour. |
| `card.svg` | A profile card rendered from that dataset, embedded in the GitHub profile README. |
| `dev-activity-scan.py` | The scanner that produces `activity.json`, published so the method can be audited. |

## How it works

`dev-activity-scan.py` walks the git repositories on a local machine, selects the
commits authored by a given set of e-mail addresses, de-duplicates them by commit
hash and aggregates them by timestamp. Nothing beyond those aggregates is read or
written. Repositories are identified by their root commit hash, so the same project
cloned into two folders is counted once.

`activity.json` and `card.svg` are refreshed automatically several times a day.

## Caveats

These numbers are self-reported: they come from a machine, not from a hosting
provider, so they cannot be independently verified from the outside. What can be
verified is the method — the scanner is in this repository — and the daily trail
in this repository's commit history.

Commit counts measure activity, not value. A day with forty small commits is not
four times better than a day with ten.
