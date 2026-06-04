#!/usr/bin/env python3
"""Render a GitHub-profile activity overview SVG from GitHub GraphQL data."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import textwrap
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "activity-overview.svg"
PROFILE_LOGIN = os.getenv("PROFILE_LOGIN", "Pluviobyte")
FOCUS_ORGS = [item.strip() for item in os.getenv("FOCUS_ORGS", "openclaw,n8n-io").split(",") if item.strip()]
GRAPHQL_URL = "https://api.github.com/graphql"


QUERY = """
query ProfileActivity($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    login
    name
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks {
          firstDay
          contributionDays {
            date
            weekday
            contributionCount
            color
          }
        }
      }
      totalCommitContributions
      totalIssueContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      commitContributionsByRepository(maxRepositories: 10) {
        repository { nameWithOwner url owner { login } }
        contributions { totalCount }
      }
      issueContributionsByRepository(maxRepositories: 10) {
        repository { nameWithOwner url owner { login } }
        contributions { totalCount }
      }
      pullRequestContributionsByRepository(maxRepositories: 10) {
        repository { nameWithOwner url owner { login } }
        contributions { totalCount }
      }
      pullRequestReviewContributionsByRepository(maxRepositories: 10) {
        repository { nameWithOwner url owner { login } }
        contributions { totalCount }
      }
    }
    repositoriesContributedTo(
      first: 100
      contributionTypes: [COMMIT, ISSUE, PULL_REQUEST, PULL_REQUEST_REVIEW]
    ) {
      totalCount
      nodes {
        nameWithOwner
        url
        owner { login }
      }
    }
  }
}
"""


MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def token() -> str:
    value = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if value:
        return value
    try:
        return subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    except Exception as exc:  # pragma: no cover - only used outside CI fallback
        raise SystemExit("Set GITHUB_TOKEN, GH_TOKEN, or authenticate gh before rendering.") from exc


def graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps({"query": query, "variables": variables}).encode()
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {token()}",
            "Content-Type": "application/json",
            "User-Agent": "profile-activity-overview-renderer",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
    if body.get("errors"):
        raise SystemExit(json.dumps(body["errors"], indent=2))
    return body["data"]


def pct(value: int, total: int) -> int:
    return round((value / total) * 100) if total else 0


def repo_summary(user: dict[str, Any]) -> tuple[list[str], int]:
    counts: defaultdict[str, int] = defaultdict(int)
    collection = user["contributionsCollection"]
    groups = [
        "commitContributionsByRepository",
        "issueContributionsByRepository",
        "pullRequestContributionsByRepository",
        "pullRequestReviewContributionsByRepository",
    ]
    for group in groups:
        for row in collection[group]:
            counts[row["repository"]["nameWithOwner"]] += row["contributions"]["totalCount"]

    contributed = user.get("repositoriesContributedTo") or {}
    known_names = [node["nameWithOwner"] for node in contributed.get("nodes") or []]
    for name in known_names:
        counts.setdefault(name, 0)

    preferred = ["openclaw/openclaw", "NousResearch/hermes-agent", "Wei-Shaw/sub2api"]
    ordered: list[str] = []
    for name in preferred:
        if name in counts:
            ordered.append(name)

    remaining = sorted(
        (name for name in counts if name not in ordered),
        key=lambda name: (-counts[name], name.lower()),
    )
    ordered.extend(remaining)

    total_count = max(contributed.get("totalCount") or 0, len(counts))
    return ordered[:3], max(0, total_count - 3)


def wrap_text(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)


def text(x: float, y: float, value: str, cls: str, anchor: str = "start") -> str:
    return f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" text-anchor="{anchor}">{escape(value)}</text>'


def heatmap_svg(weeks: list[dict[str, Any]], x0: int = 86, y0: int = 122) -> str:
    cell = 11
    gap = 4
    bits: list[str] = []
    last_month = None
    for week_index, week in enumerate(weeks):
        first_day = datetime.fromisoformat(week["firstDay"]).date()
        if first_day.month != last_month and week_index < 53:
            bits.append(text(x0 + week_index * (cell + gap), y0 - 18, MONTH_NAMES[first_day.month - 1], "month"))
            last_month = first_day.month
        for day in week["contributionDays"]:
            color = day.get("color") or "#ebedf0"
            weekday = int(day["weekday"])
            count = int(day["contributionCount"])
            date = day["date"]
            x = x0 + week_index * (cell + gap)
            y = y0 + weekday * (cell + gap)
            bits.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="3" fill="{color}">'
                f"<title>{escape(date)}: {count} contributions</title></rect>"
            )
    bits.extend(
        [
            text(32, y0 + 1 * (cell + gap) + 10, "Mon", "axis"),
            text(32, y0 + 3 * (cell + gap) + 10, "Wed", "axis"),
            text(32, y0 + 5 * (cell + gap) + 10, "Fri", "axis"),
            text(742, y0 + 7 * (cell + gap) + 20, "Less", "legend"),
            '<rect x="780" y="240" width="11" height="11" rx="3" fill="#ebedf0"/>',
            '<rect x="798" y="240" width="11" height="11" rx="3" fill="#9be9a8"/>',
            '<rect x="816" y="240" width="11" height="11" rx="3" fill="#40c463"/>',
            '<rect x="834" y="240" width="11" height="11" rx="3" fill="#30a14e"/>',
            '<rect x="852" y="240" width="11" height="11" rx="3" fill="#216e39"/>',
            text(870, y0 + 7 * (cell + gap) + 20, "More", "legend"),
        ],
    )
    return "\n".join(bits)


def chip(x: int, y: int, label: str, width: int) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="44" rx="10" fill="#ffffff" stroke="#d0d7de"/>'
        f'<text x="{x + 18}" y="{y + 29}" class="chip">@{escape(label)}</text>'
    )


def quadrant_svg(collection: dict[str, Any], x0: int = 800, y0: int = 512) -> str:
    commits = int(collection["totalCommitContributions"])
    issues = int(collection["totalIssueContributions"])
    prs = int(collection["totalPullRequestContributions"])
    reviews = int(collection["totalPullRequestReviewContributions"])
    total = commits + issues + prs + reviews
    values = {
        "commits": pct(commits, total),
        "issues": pct(issues, total),
        "prs": pct(prs, total),
        "reviews": pct(reviews, total),
    }

    max_len = 152
    left = max(10, max_len * values["commits"] / 100)
    right = max(10, max_len * values["issues"] / 100)
    down = max(10, max_len * values["prs"] / 100)
    up = max(10, max_len * values["reviews"] / 100)
    points = [
        (x0, y0 - up),
        (x0 + right, y0),
        (x0, y0 + down),
        (x0 - left, y0),
    ]
    point_attr = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    markers = "\n".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" class="dot"/>' for x, y in points)
    return "\n".join(
        [
            f'<line x1="{x0}" y1="{y0 - 165}" x2="{x0}" y2="{y0 + 165}" class="quad-axis"/>',
            f'<line x1="{x0 - 190}" y1="{y0}" x2="{x0 + 190}" y2="{y0}" class="quad-axis"/>',
            f'<polygon points="{point_attr}" class="shape"/>',
            markers,
            text(x0, y0 - 190, f'{values["reviews"]}%', "percent", "middle"),
            text(x0, y0 - 164, "Code review", "label", "middle"),
            text(x0 + 220, y0 - 3, f'{values["issues"]}%', "percent", "middle"),
            text(x0 + 220, y0 + 24, "Issues", "label", "middle"),
            text(x0, y0 + 196, f'{values["prs"]}%', "percent", "middle"),
            text(x0, y0 + 224, "Pull requests", "label", "middle"),
            text(x0 - 220, y0 - 3, f'{values["commits"]}%', "percent", "middle"),
            text(x0 - 220, y0 + 24, "Commits", "label", "middle"),
        ],
    )


def render(user: dict[str, Any], generated_at: datetime) -> str:
    collection = user["contributionsCollection"]
    calendar = collection["contributionCalendar"]
    repos, other_count = repo_summary(user)

    repo_lines: list[str] = []
    if repos:
        intro = "Contributed to " + ", ".join(repos[:3])
        repo_lines = wrap_text(intro, 42)
        if other_count:
            repo_lines.append(f"and {other_count} other repositories")
    else:
        repo_lines = ["No public repository contributions found"]

    chips = []
    x = 64
    for org in FOCUS_ORGS[:3]:
        width = max(122, 44 + len(org) * 10)
        chips.append(chip(x, 328, org, width))
        x += width + 12
    chips.append(chip(x, 328, "More", 112))

    repo_text = []
    y = 442
    for index, line in enumerate(repo_lines[:4]):
        cls = "activity-link" if index < 3 and "other repositories" not in line else "activity-copy"
        repo_text.append(text(118, y, line, cls))
        y += 30

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="760" viewBox="0 0 1080 760" role="img" aria-labelledby="title desc">
  <title id="title">{escape(PROFILE_LOGIN)} activity overview</title>
  <desc id="desc">GitHub contribution calendar and activity overview generated from public GraphQL contribution data.</desc>
  <defs>
    <style>
      .bg {{ fill: #ffffff; }}
      .card {{ fill: #ffffff; stroke: #d0d7de; stroke-width: 1.2; }}
      .divider {{ stroke: #d0d7de; stroke-width: 1; }}
      .title {{ fill: #24292f; font: 600 24px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
      .month {{ fill: #24292f; font: 500 14px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
      .axis, .legend {{ fill: #57606a; font: 500 13px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
      .chip {{ fill: #24292f; font: 700 15px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
      .section {{ fill: #24292f; font: 600 19px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
      .activity-copy {{ fill: #24292f; font: 500 18px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
      .activity-link {{ fill: #0969da; font: 700 18px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
      .quad-axis {{ stroke: #116329; stroke-width: 3; stroke-linecap: round; }}
      .shape {{ fill: #7ee787; fill-opacity: 0.58; stroke: #2da44e; stroke-width: 2; }}
      .dot {{ fill: #ffffff; stroke: #116329; stroke-width: 3; }}
      .percent {{ fill: #57606a; font: 600 17px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
      .label {{ fill: #57606a; font: 500 16px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
      .muted {{ fill: #6e7781; font: 500 12px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    </style>
  </defs>
  <rect class="bg" width="1080" height="760"/>
  {text(32, 48, f'{int(calendar["totalContributions"]):,} contributions in the last year', "title")}
  <rect x="32" y="74" width="1016" height="682" rx="8" class="card"/>
  {heatmap_svg(calendar["weeks"])}
  <line x1="32" y1="292" x2="928" y2="292" class="divider"/>
  {"".join(chips)}
  {text(64, 405, "Activity overview", "section")}
  <path d="M70 434h20v26H78l-8 7v-33Zm5 6v15h8v4l5-4h2v-15H75Z" fill="#57606a"/>
  {"".join(repo_text)}
  <line x1="548" y1="390" x2="548" y2="708" class="divider"/>
  {quadrant_svg(collection)}
  {text(64, 724, f'Generated {generated_at.strftime("%Y-%m-%d %H:%M UTC")} from GitHub GraphQL public contribution data.', "muted")}
</svg>
"""


def main() -> None:
    now = datetime.now(timezone.utc)
    data = graphql(
        QUERY,
        {
            "login": PROFILE_LOGIN,
            "from": (now - timedelta(days=365)).isoformat(),
            "to": now.isoformat(),
        },
    )
    user = data.get("user")
    if not user:
        raise SystemExit(f"GitHub user not found: {PROFILE_LOGIN}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(user, now), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
