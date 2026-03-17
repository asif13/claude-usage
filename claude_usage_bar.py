#!/usr/bin/env python3
"""
Claude Code Usage — macOS Menu Bar App

Reads ~/.claude/stats-cache.json and displays live usage stats in the menu bar.

Requirements:
    pip install rumps "pyobjc-framework-Cocoa>=10.0"

Run:
    python3 claude_usage_bar.py
"""

import json
import rumps
from datetime import date, datetime, timedelta
from pathlib import Path

STATS_PATH = Path.home() / ".claude" / "stats-cache.json"
PROJECTS_DIR = Path.home() / ".claude" / "projects"
REFRESH_INTERVAL = 60  # seconds


# ── Helpers ────────────────────────────────────────────────────────────────────

def fmt_tokens(n: int) -> str:
    """Format large token counts with K/M suffix."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def shorten_model(name: str) -> str:
    """claude-sonnet-4-6 → sonnet-4-6"""
    return name.replace("claude-", "")


def fmt_hour(h: int) -> str:
    """24h int → 12h string: 17 → '5pm'"""
    if h == 0:
        return "12am"
    if h < 12:
        return f"{h}am"
    if h == 12:
        return "12pm"
    return f"{h - 12}pm"


# ── Data loading ───────────────────────────────────────────────────────────────

def read_live_sessions(since_date: date) -> dict:
    """
    Scan all session JSONL files and return per-date counts.
    Returns: {date_str: {"messageCount": int, "toolCallCount": int, "sessionCount": int}}

    stats-cache.json lags by 1-2 days; this reads the raw session files directly
    so today's (and recent days') activity is always current.
    """
    since_str = since_date.isoformat()
    daily: dict[str, dict] = {}

    for jsonl_path in PROJECTS_DIR.glob("*/*.jsonl"):
        # Subagent files live at:  projects/PROJECT/SESSION_ID/subagents/agent-xxx.jsonl
        # Main session files at:   projects/PROJECT/SESSION_ID.jsonl
        is_subagent = "subagents" in jsonl_path.parts

        try:
            for line in jsonl_path.read_text(errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts = obj.get("timestamp", "")
                if not ts or ts[:10] < since_str:
                    continue

                day = ts[:10]
                if day not in daily:
                    daily[day] = {"messageCount": 0, "toolCallCount": 0, "sessions": set()}

                t = obj.get("type", "")
                if t == "user":
                    daily[day]["messageCount"] += 1
                elif t == "assistant":
                    # Tool uses are nested inside assistant message content
                    content = obj.get("message", {}).get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "tool_use":
                                daily[day]["toolCallCount"] += 1

                if not is_subagent:
                    sid = obj.get("sessionId")
                    if sid:
                        daily[day]["sessions"].add(sid)

        except (OSError, PermissionError):
            continue

    return {
        day: {
            "messageCount": v["messageCount"],
            "toolCallCount": v["toolCallCount"],
            "sessionCount": len(v["sessions"]),
        }
        for day, v in daily.items()
    }


def load_stats() -> dict | None:
    """
    Load usage stats from two sources:
    - stats-cache.json: historical totals and older daily data
    - raw JSONL session files: live data for the last 7 days (overrides cache)
    Returns None only if both sources are unavailable.
    """
    # Layer 1: stats-cache.json (may be stale)
    try:
        raw = json.loads(STATS_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        raw = {}

    # Layer 2: live session files (always current)
    week_cutoff = date.today() - timedelta(days=6)
    live = read_live_sessions(week_cutoff)

    if not raw and not live:
        return None

    # Merge: live data wins for any date it covers
    cache_daily = {e["date"]: e for e in raw.get("dailyActivity", [])}
    merged_daily = {**cache_daily, **live}  # live overwrites cache for same dates

    today_str = date.today().isoformat()
    today = merged_daily.get(today_str, {"messageCount": 0, "sessionCount": 0, "toolCallCount": 0})

    week_cutoff_str = week_cutoff.isoformat()
    week_entries = [
        {"date": d, **v}
        for d, v in merged_daily.items()
        if d >= week_cutoff_str
    ]

    # All-time totals from stats-cache (best source for historical aggregates)
    model_usage = raw.get("modelUsage", {})
    total_output = sum(v.get("outputTokens", 0) for v in model_usage.values())
    total_cache_read = sum(v.get("cacheReadInputTokens", 0) for v in model_usage.values())

    # Peak hour — hourCounts is a sparse dict with string keys
    hour_counts = {int(k): v for k, v in raw.get("hourCounts", {}).items()}
    peak_hour = max(hour_counts, key=hour_counts.get) if hour_counts else None
    peak_count = hour_counts.get(peak_hour, 0) if peak_hour is not None else 0

    last_computed = raw.get("lastComputedDate", "")
    try:
        stale_days = (date.today() - date.fromisoformat(last_computed)).days
    except ValueError:
        stale_days = 0

    first_dt = raw.get("firstSessionDate", "")
    try:
        first_date = datetime.fromisoformat(first_dt.replace("Z", "+00:00")).date()
    except (ValueError, AttributeError):
        first_date = None

    ls = raw.get("longestSession", {})

    return {
        "today": today,
        "week_entries": week_entries,
        "week_msgs": sum(e["messageCount"] for e in week_entries),
        "week_tools": sum(e["toolCallCount"] for e in week_entries),
        "total_sessions": raw.get("totalSessions", 0),
        "total_messages": raw.get("totalMessages", 0),
        "peak_hour": peak_hour,
        "peak_count": peak_count,
        "total_output_tokens": total_output,
        "total_cache_read": total_cache_read,
        "models_used": list(model_usage.keys()),
        "longest_ms": ls.get("duration", 0),
        "longest_msgs": ls.get("messageCount", 0),
        "first_date": first_date,
        "stale_days": stale_days,
        "last_computed": last_computed,
    }


# ── Display helpers ────────────────────────────────────────────────────────────

def build_title(stats: dict | None) -> str:
    if stats is None:
        return "◆ ––"
    t = stats["today"]
    msgs = t["messageCount"]
    tools = t["toolCallCount"]
    if msgs == 0:
        return "◆ 0m"
    if tools > 0:
        return f"◆ {msgs}m {tools}t"
    return f"◆ {msgs}m"


def build_menu_items(stats: dict | None) -> list:
    """Return list of rumps.MenuItem objects (or None for separators)."""
    items = []

    if stats is None:
        items.append(rumps.MenuItem("Could not read ~/.claude/stats-cache.json"))
        return items

    today_str = date.today().strftime("%Y-%m-%d")
    t = stats["today"]

    # ── TODAY ──────────────────────────────────────────────────────────────────
    items.append(rumps.MenuItem(f"TODAY  ({today_str})"))
    items.append(rumps.MenuItem(f"  Messages:    {t['messageCount']}"))
    items.append(rumps.MenuItem(f"  Tool Calls:  {t['toolCallCount']}"))
    items.append(rumps.MenuItem(f"  Sessions:    {t['sessionCount']}"))
    items.append(None)

    # ── THIS WEEK ──────────────────────────────────────────────────────────────
    week_start = (date.today() - timedelta(days=6)).strftime("%b %d")
    week_end = date.today().strftime("%b %d")
    active_days = len(stats["week_entries"])
    items.append(rumps.MenuItem(f"THIS WEEK  ({week_start} \u2013 {week_end})"))
    items.append(rumps.MenuItem(f"  Messages:    {stats['week_msgs']}"))
    items.append(rumps.MenuItem(f"  Tool Calls:  {stats['week_tools']}"))
    items.append(rumps.MenuItem(f"  Active days: {active_days} of 7"))
    items.append(None)

    # ── ALL TIME ───────────────────────────────────────────────────────────────
    models_short = ", ".join(shorten_model(m) for m in stats["models_used"])

    peak_str = "N/A"
    if stats["peak_hour"] is not None:
        peak_str = f"{fmt_hour(stats['peak_hour'])} ({stats['peak_count']} sessions)"

    first_str = "N/A"
    if stats["first_date"]:
        days_ago = (date.today() - stats["first_date"]).days
        first_str = f"{stats['first_date'].strftime('%b %d, %Y')}  ({days_ago}d ago)"

    longest_h = stats["longest_ms"] / 3_600_000
    longest_str = f"{longest_h:.0f}h  ({stats['longest_msgs']} messages)"

    items.append(rumps.MenuItem("ALL TIME"))
    items.append(rumps.MenuItem(f"  Total Sessions:   {stats['total_sessions']}"))
    items.append(rumps.MenuItem(f"  Total Messages:   {stats['total_messages']:,}"))
    items.append(rumps.MenuItem(f"  Output Tokens:    {fmt_tokens(stats['total_output_tokens'])}"))
    items.append(rumps.MenuItem(f"  Cache Read:       {fmt_tokens(stats['total_cache_read'])}"))
    items.append(rumps.MenuItem(f"  Models:           {models_short}"))
    items.append(rumps.MenuItem(f"  Peak hour:        {peak_str}"))
    items.append(rumps.MenuItem(f"  Longest session:  {longest_str}"))
    items.append(rumps.MenuItem(f"  First session:    {first_str}"))
    items.append(None)

    # ── STATUS ─────────────────────────────────────────────────────────────────
    stale = stats["stale_days"]
    stale_label = f"  Last updated: {stats['last_computed']}"
    if stale >= 1:
        stale_label += f"  \u26a0 {stale}d ago"
    items.append(rumps.MenuItem(stale_label))

    return items


# ── App ────────────────────────────────────────────────────────────────────────

class ClaudeUsageApp(rumps.App):
    def __init__(self):
        super().__init__("◆ ––", quit_button=None)
        self._refresh_menu()
        self.timer = rumps.Timer(lambda _: self._refresh_menu(), REFRESH_INTERVAL)
        self.timer.start()

    def _refresh_menu(self):
        stats = load_stats()
        self.title = build_title(stats)
        self.menu.clear()
        for item in build_menu_items(stats):
            if item is None:
                self.menu.add(rumps.separator)
            else:
                self.menu.add(item)
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Refresh Now", callback=lambda _: self._refresh_menu()))
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Quit", callback=rumps.quit_application))


if __name__ == "__main__":
    ClaudeUsageApp().run()
