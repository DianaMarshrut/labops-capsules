"""Checks for the puls capsule: manifests, skill frontmatter, zip, chat text, template."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "plugins/puls/skills/puls"
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "scripts"))

import build_sample_dashboard as bsd  # noqa: E402
import make_sample_xlsx as msx  # noqa: E402


def _frontmatter(text: str) -> dict[str, str]:
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    assert m, "SKILL.md has no frontmatter"
    return dict(line.split(": ", 1) for line in m.group(1).splitlines())


def test_manifests_are_valid_json() -> None:
    mp = json.loads((REPO / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    pl = json.loads((REPO / "plugins/puls/.claude-plugin/plugin.json").read_text(encoding="utf-8"))
    assert mp["plugins"][0]["source"] == "./plugins/puls"
    assert mp["plugins"][0]["name"] == pl["name"] == "puls"


def test_skill_frontmatter_limits() -> None:
    fm = _frontmatter((SKILL / "SKILL.md").read_text(encoding="utf-8"))
    assert fm["name"] == "puls" and len(fm["name"]) <= 64
    assert 0 < len(fm["description"]) <= 200  # claude.ai upload limit


def test_shipped_zip_matches_skill_and_checksum() -> None:
    """Check the committed dist/puls.zip as is, without rebuilding it."""
    zpath = REPO / "dist/puls.zip"
    listing = (REPO / "dist/puls.zip.txt").read_text(encoding="utf-8").split()
    assert listing[0] == "sha256"
    assert hashlib.sha256(zpath.read_bytes()).hexdigest() == listing[1]
    expected = sorted(f"puls/{f.relative_to(SKILL).as_posix()}"
                      for f in SKILL.rglob("*") if f.is_file())
    with zipfile.ZipFile(zpath) as zf:
        assert sorted(zf.namelist()) == expected == sorted(listing[2:])
        names = zf.namelist()
        assert all(n.startswith("puls/") for n in names)
        assert "puls/SKILL.md" in names
        fm = _frontmatter(zf.read("puls/SKILL.md").decode("utf-8"))
        assert fm["name"] == "puls"
        for f in SKILL.rglob("*"):
            if f.is_file():
                assert zf.read(f"puls/{f.relative_to(SKILL).as_posix()}") == f.read_bytes()


def test_build_zip_in_temp_dir(tmp_path: Path) -> None:
    import build  # scripts/build.py

    out = build.build_zip(SKILL, tmp_path / "puls.zip")
    with zipfile.ZipFile(out) as zf:
        assert all(n.startswith("puls/") for n in zf.namelist())


def test_chat_instruction_is_current(tmp_path: Path) -> None:
    import build

    fresh = build.build_chat_instruction(SKILL, tmp_path / "c.md").read_text(encoding="utf-8")
    assert fresh == (REPO / "chat-instruction.md").read_text(encoding="utf-8")


def test_chat_instruction_is_self_contained() -> None:
    text = (REPO / "chat-instruction.md").read_text(encoding="utf-8")
    assert "references/" not in text and "templates/" not in text
    assert 'id="puls-data"' in text
    assert "ПРОВЕРИТЬ" not in text


def test_template_payload_is_valid_json() -> None:
    html = (SKILL / "templates/dashboard.html").read_text(encoding="utf-8")
    a = html.index('<script id="puls-data" type="application/json">')
    a = html.index(">", a) + 1
    data = json.loads(html[a:html.index("</script>", a)])
    assert {"meta", "kpis", "charts", "tables", "attention"} <= data.keys()
    assert "http://" not in html.replace("http://www.w3.org/2000/svg", "")
    assert "https://" not in html


def _deal(stage: str, amount: float, created: date, closed: date | None = None,
          changed: date | None = None) -> bsd.Deal:
    return bsd.Deal(stage, amount, "M", created, closed, changed or closed or created)


def test_metrics_on_known_deals() -> None:
    today = date(2026, 10, 27)  # current period 30.09-27.10, previous 02.09-29.09
    deals = [
        _deal("Новая", 0, date(2026, 9, 1)),  # data starts before the previous period
        _deal("Успешно", 100_000, date(2026, 10, 1), date(2026, 10, 5)),
        _deal("Успешно", 300_000, date(2026, 10, 2), date(2026, 10, 20)),
        _deal("Провал", 50_000, date(2026, 10, 3), date(2026, 10, 10)),
        _deal("Успешно", 200_000, date(2026, 9, 5), date(2026, 9, 10)),
        _deal("Провал", 10_000, date(2026, 9, 6), date(2026, 9, 12)),
        _deal("Переговоры", 70_000, date(2026, 10, 1), changed=date(2026, 10, 2)),
    ]
    k = {x.label: x for x in bsd.compute(deals, today, date(2026, 9, 1)).kpis}
    rev = k["Выручка (успешные сделки)"]
    assert rev.value == bsd.money(400_000) and rev.delta_pct == 100.0
    assert k["Новые сделки"].value == "4" and k["Новые сделки"].delta_pct == 100.0
    assert k["Конверсия в успех"].value == "67%"
    assert k["Конверсия в успех"].delta_pct == round(200 / 3 - 50, 1)
    assert k["Средний чек"].value == bsd.money(200_000) and k["Средний чек"].delta_pct == 0.0
    assert k["Без движения > 14 дней"].value == "2"


def test_no_data_vs_zero() -> None:
    today = date(2026, 10, 27)
    recent = [_deal("Новая", 0, date(2026, 10, 20))]
    # Export starts inside the current period: both periods are "no data", chart too.
    dash = bsd.compute(recent, today, date(2026, 10, 15))
    k = {x.label: x for x in dash.kpis}
    assert k["Выручка (успешные сделки)"].value == bsd.NO_DATA
    weeks = dash.charts[0]["points"]
    assert len(weeks) == 4 and all(p["value"] is None for p in weeks[:3])
    assert all(p["label"] for p in weeks)
    assert dash.tables[0]["rows"] == [] and "нет данных" in dash.tables[0]["empty_note"]
    # Full export with only recent deals: revenue is a real zero, average check is "no data".
    dash = bsd.compute(recent, today, date(2026, 8, 1))
    k = {x.label: x for x in dash.kpis}
    assert k["Выручка (успешные сделки)"].value == bsd.money(0)
    assert k["Средний чек"].value == bsd.NO_DATA
    assert k["Конверсия в успех"].value == bsd.NO_DATA
    # Incomplete export that still contains an old deal: an old row proves nothing.
    old = recent + [_deal("Успешно", 9, date(2026, 8, 1), date(2026, 8, 2))]
    k = {x.label: x for x in bsd.compute(old, today, date(2026, 10, 15)).kpis}
    assert k["Выручка (успешные сделки)"].value == bsd.NO_DATA


def test_fill_escapes_script_close(tmp_path: Path) -> None:
    import build_edge_dashboard as bed

    out = bsd.fill(bsd.TEMPLATE, bed.edge_dashboard(), tmp_path / "e.html").read_text("utf-8")
    a = out.index('<script id="puls-data" type="application/json">')
    a = out.index(">", a) + 1
    block = out[a:out.index("</script>", a)]
    data = json.loads(block)
    assert data["attention"][0].startswith("</script><script>")
    assert "<" not in block


def test_sample_metrics(tmp_path: Path) -> None:
    xlsx = msx.build(tmp_path / "d.xlsx", today=date(2026, 10, 27))
    dash = bsd.compute(bsd.read_deals(xlsx), date(2026, 10, 27), date(2026, 8, 28))
    assert 3 <= len(dash.kpis) <= 7
    out = bsd.fill(bsd.TEMPLATE, dash, tmp_path / "p.html")
    assert "Выручка" in out.read_text(encoding="utf-8")


def test_bitrix_link_path_in_all_chats() -> None:
    """Bitrix24 webhook link is the main path in every chat; old 'Claude Code only' text is gone."""
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    src = (SKILL / "references/sources.md").read_text(encoding="utf-8")
    chat = (REPO / "chat-instruction.md").read_text(encoding="utf-8")
    for text in (skill, src, chat):
        assert "только Claude Code" not in text
        assert "не подключаем Битрикс24 напрямую" not in text
    assert "Ссылка вебхука — основной путь, в любом чате" in src
    assert "генераторе запросов" in src and "`next`" in src and "50 записей" in src
    assert "URLs you've shared" in src
    assert "только вручную" in skill  # step 7: links and files refresh manually


def test_versions_match() -> None:
    mp = json.loads((REPO / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    pl = json.loads((REPO / "plugins/puls/.claude-plugin/plugin.json").read_text(encoding="utf-8"))
    assert pl["version"] == mp["plugins"][0]["version"] == "0.2.0"
