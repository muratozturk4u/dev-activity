#!/usr/bin/env python3
"""
dev-activity-scan.py — local git activity scanner

Walks every git repository on this machine, finds the commits YOU authored and
aggregates them by date. The output is fully anonymous:

  INCLUDED : commit counts, dates, hours, active-day count, NUMBER of repositories
  EXCLUDED : repository names, folder paths, commit messages, file names, code,
             branch names

Usage
-----
  # 1) First, see which author e-mails exist in your repositories:
  python3 dev-activity-scan.py --list-emails ~/projects

  # 2) Scan with the e-mails that are yours:
  python3 dev-activity-scan.py --email you@company.com --email you@gmail.com ~/projects

  # You can pass more than one root folder:
  python3 dev-activity-scan.py --email you@gmail.com ~/projects ~/Documents ~/work
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

# Never descend into these (speed, and they are dependency trees, not your work)
SKIP_DIRS = {
    "node_modules", "vendor", ".venv", "venv", "env", "__pycache__",
    ".cache", ".npm", ".nvm", ".gradle", ".m2", "target", "dist", "build",
    ".terraform", "Pods", ".pub-cache", ".cargo", "site-packages",
}

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ----------------------------------------------------------- finding repos

def find_repos(roots: list[str], max_depth: int,
               exclude: list[str] | None = None) -> list[str]:
    """Find every git repository under the given root folders."""
    repos: list[str] = []
    seen: set[str] = set()
    skip = {os.path.realpath(os.path.expanduser(e)) for e in (exclude or [])}

    for root in roots:
        root = os.path.abspath(os.path.expanduser(root))
        if not os.path.isdir(root):
            print(f"  ! skipped (no such folder): {root}", file=sys.stderr)
            continue

        root_depth = root.rstrip(os.sep).count(os.sep)

        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
            depth = dirpath.count(os.sep) - root_depth
            if depth >= max_depth:
                dirnames[:] = []
                continue

            # .git is a folder in a normal repo, a file in a worktree/submodule
            if ".git" in dirnames or ".git" in filenames:
                real = os.path.realpath(dirpath)
                if any(real == x or real.startswith(x + os.sep) for x in skip):
                    dirnames[:] = []
                    continue
                if real not in seen:
                    seen.add(real)
                    repos.append(dirpath)
                # Do not walk into the repo itself; submodules already arrive via --all
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and d != ".git"]
                continue

            dirnames[:] = [
                d for d in dirnames
                if d not in SKIP_DIRS and not d.startswith(".")
            ]

    return repos


def git(repo: str, *args: str, timeout: int = 120) -> str:
    """Run a git command in the repo; return an empty string on any failure."""
    try:
        out = subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""
    return out.stdout if out.returncode == 0 else ""


# --------------------------------------------------------------- e-mail list

def list_emails(repos: list[str]) -> None:
    """List every author e-mail found in the repositories, with commit counts."""
    counter: Counter[str] = Counter()
    names: dict[str, set[str]] = defaultdict(set)

    for i, repo in enumerate(repos, 1):
        print(f"\r  scanning {i}/{len(repos)}", end="", file=sys.stderr)
        log = git(repo, "log", "--all", "--pretty=format:%ae\t%an")
        for line in log.splitlines():
            if "\t" not in line:
                continue
            email, name = line.split("\t", 1)
            email = email.strip().lower()
            if email:
                counter[email] += 1
                names[email].add(name.strip())

    print("\r" + " " * 40 + "\r", end="", file=sys.stderr)
    print(f"\nAuthors found across {len(repos)} repositories (by commit count):\n")
    print(f"  {'COMMITS':>8}  {'E-MAIL':<44} NAME")
    print(f"  {'-' * 8}  {'-' * 44} {'-' * 24}")
    for email, count in counter.most_common(60):
        who = ", ".join(sorted(names[email]))[:40]
        print(f"  {count:>8}  {email:<44} {who}")
    print("\nPass the ones that are yours with --email, e.g.:")
    top = [e for e, _ in counter.most_common(2)]
    print("  python3 dev-activity-scan.py " + " ".join(f"--email {e}" for e in top) + " ~/projects\n")


# ------------------------------------------------------------------ collect

def collect(repos: list[str], emails: set[str], include_merges: bool) -> tuple[dict, int]:
    """Collect commits, de-duplicated by hash, so a repository cloned or forked
    into two places is never counted twice."""
    seen_hashes: set[str] = set()
    stamps: list[datetime] = []
    # The same repository may exist in several places (backup, submodule, old copy).
    # The root commit hash is used as the repository identity, so the repository
    # count does not get inflated.
    repo_identities: set[str] = set()

    fmt = "--pretty=format:%H%x09%aI"
    base = ["log", "--all", fmt]
    if not include_merges:
        base.append("--no-merges")

    for i, repo in enumerate(repos, 1):
        print(f"\r  scanning {i}/{len(repos)}", end="", file=sys.stderr)
        args = list(base)
        for e in emails:
            args += ["--author", e]

        log = git(repo, *args)
        found = 0
        for line in log.splitlines():
            if "\t" not in line:
                continue
            h, iso = line.split("\t", 1)
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            try:
                stamps.append(datetime.fromisoformat(iso.strip()))
            except ValueError:
                continue
            found += 1
        if found:
            roots = git(repo, "rev-list", "--max-parents=0", "--all").split()
            repo_identities.add(min(roots) if roots else os.path.realpath(repo))

    print("\r" + " " * 40 + "\r", end="", file=sys.stderr)
    return {"stamps": stamps}, len(repo_identities)


def streaks(days: set[date]) -> tuple[int, int]:
    """Longest and current run of consecutive active days."""
    if not days:
        return 0, 0
    ordered = sorted(days)
    longest = current = 1
    for prev, cur in zip(ordered, ordered[1:]):
        if (cur - prev).days == 1:
            current += 1
        else:
            current = 1
        longest = max(longest, current)

    today = date.today()
    running = 0
    cursor = today
    if cursor not in days:
        cursor = today - timedelta(days=1)  # there may be no commit yet today
    while cursor in days:
        running += 1
        cursor -= timedelta(days=1)

    return longest, running


def build(stamps: list[datetime], repo_count: int, emails: set[str]) -> dict:
    by_date: Counter[str] = Counter()
    by_month: Counter[str] = Counter()
    by_year: Counter[str] = Counter()
    by_weekday: Counter[str] = Counter()
    by_hour: Counter[str] = Counter()

    for ts in stamps:
        d = ts.date()
        by_date[d.isoformat()] += 1
        by_month[f"{d.year:04d}-{d.month:02d}"] += 1
        by_year[str(d.year)] += 1
        by_weekday[WEEKDAYS[d.weekday()]] += 1
        by_hour[f"{ts.hour:02d}"] += 1

    days = {date.fromisoformat(d) for d in by_date}
    longest, current = streaks(days)

    today = date.today()
    cutoff = today - timedelta(days=365)
    last365 = {d: c for d, c in by_date.items() if date.fromisoformat(d) >= cutoff}

    first = min(days).isoformat() if days else None
    last = max(days).isoformat() if days else None
    span_years = round((max(days) - min(days)).days / 365.25, 1) if len(days) > 1 else 0.0

    return {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": "local git repositories",
        "identity_count": len(emails),
        "totals": {
            "commits": len(stamps),
            "active_days": len(days),
            "repositories": repo_count,
            "first_commit": first,
            "last_commit": last,
            "span_years": span_years,
        },
        "streaks": {"longest_days": longest, "current_days": current},
        "last_365": {
            "commits": sum(last365.values()),
            "active_days": len(last365),
            "by_date": dict(sorted(last365.items())),
        },
        "by_date": dict(sorted(by_date.items())),
        "by_month": dict(sorted(by_month.items())),
        "by_year": dict(sorted(by_year.items())),
        "by_weekday": {d: by_weekday.get(d, 0) for d in WEEKDAYS},
        "by_hour": {f"{h:02d}": by_hour.get(f"{h:02d}", 0) for h in range(24)},
    }


# --------------------------------------------------------------------- main

def main() -> int:
    p = argparse.ArgumentParser(
        description="Produce an anonymous activity summary from local git repositories.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("roots", nargs="*", default=["~/projects"],
                   help="folders to scan (default: ~/projects)")
    p.add_argument("--email", action="append", default=[],
                   help="an e-mail address that is yours (may be given more than once)")
    p.add_argument("--list-emails", action="store_true",
                   help="list every author e-mail found in the repositories and exit")
    p.add_argument("--out", default="activity.json", help="output file")
    p.add_argument("--max-depth", type=int, default=6, help="folder scan depth")
    p.add_argument("--exclude", action="append", default=[],
                   help="folder to keep out of the scan (may be given more than once). "
                        "Pass the publishing repo here, otherwise its own cron commits "
                        "get counted as your activity.")
    p.add_argument("--include-merges", action="store_true",
                   help="count merge commits as well (default: do not)")
    args = p.parse_args()

    roots = args.roots or ["~/projects"]

    print(f"Looking for repositories in: {', '.join(roots)}", file=sys.stderr)
    repos = find_repos(roots, args.max_depth, args.exclude)
    print(f"  found {len(repos)} git repositories", file=sys.stderr)

    if not repos:
        print("No git repositories found. Check that the folder you passed is right.",
              file=sys.stderr)
        return 1

    if args.list_emails:
        list_emails(repos)
        return 0

    emails = {e.strip().lower() for e in args.email if e.strip()}
    if not emails:
        cfg = subprocess.run(["git", "config", "--global", "user.email"],
                             capture_output=True, text=True, check=False).stdout.strip()
        if cfg:
            emails = {cfg.lower()}
            print(f"  no --email given, using the global git setting: {cfg}", file=sys.stderr)
        else:
            print("No e-mail given. Run --list-emails first, then pass --email.",
                  file=sys.stderr)
            return 1

    print(f"  identities searched for: {', '.join(sorted(emails))}", file=sys.stderr)
    data, repo_count = collect(repos, emails, args.include_merges)
    stamps = data["stamps"]

    if not stamps:
        print("No commits found for these e-mails. Check them with --list-emails.",
              file=sys.stderr)
        return 1

    result = build(stamps, repo_count, emails)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    t = result["totals"]
    print(f"""
  Total commits      : {t['commits']:,}
  Active days        : {t['active_days']:,}
  Repositories       : {t['repositories']:,}
  First / last commit: {t['first_commit']} -> {t['last_commit']}  ({t['span_years']} years)
  Longest streak     : {result['streaks']['longest_days']} days
  Last 12 months     : {result['last_365']['commits']:,} commits / {result['last_365']['active_days']} active days

  Written to: {os.path.abspath(args.out)}
""", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
