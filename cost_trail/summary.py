"""Spend-to-date, month-end forecast, and the unattributed remainder by folder."""

import calendar
import os
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class Spend:
    today: date
    month_to_date: float
    days_elapsed: int
    days_in_month: int
    forecast_month_pace: float    # month-to-date pace carried to month end
    forecast_7day_pace: float     # month-to-date + last 7 full days' average for the rest
    last_month: float
    daily_this_month: list        # [(date, dollars)] for every day so far, zeros included
    earliest_log: date
    by_model_this_month: list     # [("Opus 5.5", dollars)], biggest first
    by_model_last_month: list


def spend(daily, today=None, daily_by_model=None):
    today = today or date.today()
    first = today.replace(day=1)
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    days = [(first + timedelta(i)) for i in range(today.day)]
    series = [(d, daily.get(d, 0.0)) for d in days]
    mtd = sum(v for _, v in series)
    last7 = sum(daily.get(today - timedelta(i), 0.0) for i in range(1, 8)) / 7
    remaining = days_in_month - today.day
    prev_last = first - timedelta(1)
    last_month = sum(v for d, v in daily.items() if d.year == prev_last.year and d.month == prev_last.month)
    return Spend(
        today=today,
        month_to_date=mtd,
        days_elapsed=today.day,
        days_in_month=days_in_month,
        forecast_month_pace=mtd / today.day * days_in_month if today.day else 0.0,
        forecast_7day_pace=mtd + last7 * remaining,
        last_month=last_month,
        daily_this_month=series,
        earliest_log=min(daily) if daily else today,
        by_model_this_month=_month_totals(daily_by_model, today.year, today.month),
        by_model_last_month=_month_totals(daily_by_model, prev_last.year, prev_last.month),
    )


def _month_totals(daily_by_model, year, month):
    out = []
    for label, days in (daily_by_model or {}).items():
        dollars = sum(v for d, v in days.items() if d.year == year and d.month == month)
        if dollars > 0.005:
            out.append((label, dollars))
    return sorted(out, key=lambda kv: -kv[1])


def folder_label(cwd):
    """A readable name for a session's working folder."""
    if not cwd:
        return "(unknown folder)"
    if cwd.startswith("("):
        return cwd
    if "scratch-workspaces" in cwd:
        return "(no folder: scratch sessions)"
    for marker in ("/.claude/worktrees/", "/.worktrees/"):
        if marker in cwd:
            cwd = cwd.split(marker)[0]
    home = os.path.expanduser("~")
    if cwd.rstrip("/") == home:
        return "~ (home folder)"
    return os.path.basename(cwd.rstrip("/")) or cwd


def session_titles(logs):
    """session_id -> its /rename title, else the first line of its first prompt."""
    first = {}
    for p in logs.prompts.values():
        if p.text and p.start and (p.session_id not in first or p.start < first[p.session_id][0]):
            first[p.session_id] = (p.start, p.text.splitlines()[0][:70])
    out = {}
    for sid, s in logs.sessions.items():
        out[sid] = s.title or (first[sid][1] if sid in first else sid[:8])
    return out
