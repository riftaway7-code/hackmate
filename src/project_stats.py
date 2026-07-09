"""Live HackMate project stats (stars, downloads, issues) for the welcome screen sidebar."""

import json
import ssl
import urllib.request
import urllib.error

REPO = "riftaway7-code/hackmate"
STATS_URL = "https://riftaway7-code.github.io/hackmate/stats.json"
API_ROOT = f"https://api.github.com/repos/{REPO}"


def _fetch_json(url, timeout=6):
    req = urllib.request.Request(url, headers={"User-Agent": "HackMate/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except (ssl.SSLError, urllib.error.URLError):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
            return json.loads(r.read())


def fetch_project_stats():
    """Returns a dict of live project stats, or None if both sources are unreachable."""
    try:
        stats = _fetch_json(STATS_URL)
    except Exception:
        stats = {}

    try:
        repo = _fetch_json(API_ROOT)
    except Exception:
        repo = {}

    if not stats and not repo:
        return None

    latest_tag = None
    try:
        releases = _fetch_json(API_ROOT + "/releases")
        if releases:
            latest_tag = releases[0].get("tag_name")
    except Exception:
        pass

    return {
        "stars": repo.get("stargazers_count", stats.get("stars", 0)),
        "total_downloads": stats.get("total_downloads", 0),
        "open_issues": repo.get("open_issues_count", 0),
        "latest_tag": latest_tag,
    }


def _bar(n, total, width=14):
    filled = min(width, round(width * n / total)) if total else 0
    return "[#ffd866]" + "█" * filled + "[/][#2a2a2a]" + "░" * (width - filled) + "[/]"


def format_stats_panel(data):
    """Rich-markup lines for the Textual sidebar Static widget."""
    if data is None:
        return "[#888888]stats unavailable[/]\n[#888888](offline?)[/]"

    stars = data["stars"]
    downloads = data["total_downloads"]
    issues = data["open_issues"]
    tag = data.get("latest_tag") or "?"

    star_step = 50 if stars < 500 else 100
    next_stars = ((stars // star_step) + 1) * star_step

    lines = [
        "[#444444]── project ──[/]",
        f"[#ffd866]★[/] [bold]{stars:,}[/bold] [#666666]stars[/]",
        f"[#00ff88]↓[/] [bold]{downloads:,}[/bold] [#666666]downloads[/]",
        f"[#5599ff]⚑[/] [bold]{issues}[/bold] [#666666]open issues[/]",
        "",
        "[#666666]next star milestone[/]",
        f"{_bar(stars, next_stars)}",
        f"[#888888]{stars}/{next_stars}[/]",
        "",
        "[#666666]latest release[/]",
        f"[#cccccc]{tag}[/]",
    ]
    return "\n".join(lines)
