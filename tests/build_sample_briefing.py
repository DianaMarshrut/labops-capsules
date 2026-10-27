"""Run the radar rules (references/briefing-rules.md) on sample JSON and print a briefing.

Mirrors what the AI does inside a chat: picks what is on fire, what to answer and
what is overdue from mail, calendar and Bitrix24 tasks, escapes foreign text and
fills templates/briefing.md. It exists only to test the rules end to end.

Usage: python3 tests/build_sample_briefing.py [sample.json] [out.md]
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)
REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "plugins/radar/skills/radar"
TEMPLATE = SKILL / "templates/briefing.md"
SAMPLE = REPO / "tests/sample/radar-sample.json"

MAX_ITEMS = 5
MAX_LEN = 80
URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.I)
MD_SPECIAL = "\\`*_[]<>#|~"
INJECTION_RE = re.compile(
    r"игнорируй|ignore (?:all |previous )?instructions|перешли|forward all|"
    r"(?:^|\W)(?:ИИ|AI)(?:-помощник|-ассистент)?\s*,", re.I)
DONE_STATUSES = {"5", "6"}  # Bitrix24 REAL_STATUS: 5 completed, 6 deferred
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


def clean(text: str) -> str:
    """Make foreign text safe to show as plain text in a chat (briefing-rules.md)."""
    text = " ".join(str(text).split())
    text = URL_RE.sub("«ссылка убрана»", text)
    if len(text) > MAX_LEN:
        text = text[:MAX_LEN].rstrip() + "…"
    return "".join("\\" + ch if ch in MD_SPECIAL else ch for ch in text)


def ago(delta: timedelta) -> str:
    """Human duration: hours under a day, otherwise whole days."""
    hours = int(delta.total_seconds() // 3600)
    return f"{hours} ч" if hours < 24 else f"{hours // 24} дн."


@dataclass
class Briefing:
    """Filled sections of the briefing."""

    now: datetime
    tz_label: str
    hot: list[str] = field(default_factory=list)
    meetings: list[str] = field(default_factory=list)
    reply: list[str] = field(default_factory=list)
    overdue: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    unread: dict[str, str] = field(default_factory=dict)  # source -> reason
    first_meeting: str = ""


def _dt(s: str, tz) -> datetime:
    return datetime.fromisoformat(s).astimezone(tz)


def mail_window_start(now: datetime, days: int) -> datetime:
    """Mail threads are read for the last N days, so yesterday's unanswered mail stays."""
    return now - timedelta(days=days)


def is_vip(sender: str, vip: list[str]) -> bool:
    s = sender.lower()
    return any(s == v.lower() or (v.startswith("@") and s.endswith(v.lower())) for v in vip)


def compute(data: dict) -> Briefing:
    """Apply briefing-rules.md to sample data."""
    now = datetime.fromisoformat(data["now"])
    tz = now.tzinfo
    cfg = data["settings"]
    src = data["sources"]
    b = Briefing(now=now, tz_label=data["tz_label"])
    for name, s in src.items():
        if not s.get("ok"):
            b.unread[name] = s.get("reason", "нет доступа")

    # Tasks (Bitrix24 tasks.task.list response).
    if "tasks" not in b.unread:
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=0)
        open_tasks = [t for t in data["tasks"]["result"]["tasks"]
                      if str(t.get("status")) not in DONE_STATUSES and t.get("deadline")]
        for t in sorted(open_tasks, key=lambda t: _dt(t["deadline"], tz)):
            dl = _dt(t["deadline"], tz)
            if dl < now:
                b.overdue.append(f"{clean(t['title'])} — просрочена на {ago(now - dl)}")
            elif dl <= today_end:
                b.hot.append(f"{clean(t['title'])} — срок сегодня в {dl:%H:%M}")

    # Calendar: today, not declined.
    if "calendar" not in b.unread:
        day = now.date()
        def today(e: dict) -> bool:
            last = _dt(e["end"], tz) - timedelta(seconds=1)  # end is exclusive
            return _dt(e["start"], tz).date() <= day <= last.date()

        events = [e for e in data["calendar"] if e.get("my_status") != "declined" and today(e)]
        all_day = [e for e in events if e.get("all_day")]
        timed = sorted((e for e in events if not e.get("all_day")),
                       key=lambda e: _dt(e["start"], tz))
        for e in all_day:
            b.meetings.append(f"весь день — {clean(e['title'])}")
        for e in timed:
            note = " (нет ответа на приглашение)" if e.get("my_status") == "needs_action" else ""
            b.meetings.append(f"{_dt(e['start'], tz):%H:%M}–{_dt(e['end'], tz):%H:%M} "
                              f"{clean(e['title'])}{note}")
        for i, a in enumerate(timed):  # every pair: a long meeting can cover several
            for c in timed[i + 1:]:
                a0, a1 = _dt(a["start"], tz), _dt(a["end"], tz)
                if _dt(c["start"], tz) < a1 and a0 < _dt(c["end"], tz):
                    b.hot.append(f"Пересекаются: {clean(a['title'])} и {clean(c['title'])}")
        if timed:
            b.first_meeting = f"{_dt(timed[0]['start'], tz):%H:%M}"

    # Mail.
    if "mail" not in b.unread:
        start = mail_window_start(now, cfg.get("mail_window_days", 7))
        wait = timedelta(hours=cfg["reply_after_hours"])
        for m in sorted(data["mail"], key=lambda m: m["received"]):
            got = _dt(m["received"], tz)
            sender = m["from"].lower()
            robot = m.get("newsletter") or sender.startswith(("noreply", "no-reply"))
            personal = cfg["me"].lower() in [x.lower() for x in m.get("to", [])]
            if got < start or robot or m.get("last_from_me") or not personal:
                continue
            who = clean(m.get("from_name") or m["from"])
            line = f"{who} — {clean(m['subject'])} (ждёт {ago(now - got)})"
            if INJECTION_RE.search(f"{m['subject']} {m.get('snippet', '')}"):
                b.reply.append(line + " — похоже на попытку управлять ИИ, проверь сам")
                continue
            vip = is_vip(m["from"], cfg["vip"]) or any(
                k.lower() in m["subject"].lower() for k in cfg["keywords"])
            if vip:
                b.hot.append(f"{line} — важное письмо без ответа")
            elif now - got >= wait:
                b.reply.append(line)  # important mail is already in "hot", not repeated
    return b


def _cap(items: list[str]) -> list[str]:
    if len(items) <= MAX_ITEMS:
        return items
    return items[:MAX_ITEMS] + [f"и ещё {len(items) - MAX_ITEMS}"]


def _section(items: list[str], needs: str, unread: dict[str, str], label: str) -> list[str]:
    missing = [n for n in needs.split(",") if n in unread]
    lines = [f"- не удалось прочитать: {label[n]} ({unread[n]})" for n in missing]
    if not items and not lines:
        return ["- нет"]
    return lines + [f"- {x}" for x in _cap(items)]


def render(b: Briefing) -> str:
    """Render the briefing in the section order of templates/briefing.md."""
    label = {"mail": "почта", "calendar": "календарь", "tasks": "задачи"}
    first = f", первая в {b.first_meeting}" if b.first_meeting else ""
    meet_n = "?" if "calendar" in b.unread else str(len(b.meetings))
    hot_n = f"не меньше {len(b.hot)}" if b.unread else str(len(b.hot))
    main = (f"- Встреч сегодня: {meet_n}{first}. Горит: {hot_n}. "
            f"Ответить: {'?' if 'mail' in b.unread else len(b.reply)}. "
            f"Просрочено: {'?' if 'tasks' in b.unread else len(b.overdue)}.")
    out = [
        f"**Радар · {b.now:%d.%m.%Y}, {WEEKDAYS[b.now.weekday()]}**",
        f"Сводка на {b.now:%H:%M} ({b.tz_label})",
        "", "**Главное**", main,
        "", "**Горит**", *_section(b.hot, "tasks,calendar,mail", b.unread, label),
        "", "**Встречи сегодня**", *_section(b.meetings, "calendar", b.unread, label),
        "", "**Ответить**", *_section(b.reply, "mail", b.unread, label),
        "", "**Просрочено**", *_section(b.overdue, "tasks", b.unread, label),
        "", "**Источники**", *[f"- {x}" for x in b.sources],
        "", "Обновить сейчас: напиши «радар».",
    ]
    return "\n".join(out) + "\n"


def template_headings() -> list[str]:
    """Section headings from the fenced block in templates/briefing.md."""
    text = TEMPLATE.read_text(encoding="utf-8")
    block = text.split("```text", 1)[1].split("```", 1)[0]
    return re.findall(r"^\*\*([^*·]+?)\*\*$", block, re.M)


def build(data: dict) -> str:
    """Compute and render, adding the sources line from the sample metadata."""
    b = compute(data)
    for name, s in data["sources"].items():
        b.sources.append(s["label"] + (" — прочитано" if s.get("ok")
                                       else f" — не удалось прочитать ({b.unread[name]})"))
    return render(b)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else SAMPLE
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO / "tests/out/radar-sample.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(build(json.loads(src.read_text(encoding="utf-8"))), encoding="utf-8")
    logger.info("Saved %s", dst)
