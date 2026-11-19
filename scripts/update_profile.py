#!/usr/bin/env python3
"""Erzeugt die dynamischen Teile des GitHub-Profils im SWISSNAND-Design (Akzent #004984).

- assets/stats.svg       GitHub-Zahlen (Beiträge, Commits, Streak, Repos, Sterne, PRs)
- assets/languages.svg   meistgenutzte Sprachen
- assets/activity.svg    Beiträge der letzten 12 Monate als Heatmap
- assets/course-N.svg    zufällige Kurse von Knowledge Forge (jeden Tag andere)
- README.md              Kurs-Block zwischen <!-- KF:START --> und <!-- KF:END -->

Läuft täglich als GitHub Action. Nur Python-Standardbibliothek.

Umgebungsvariablen:
  GH_TOKEN   Token für die GitHub-API (in der Action automatisch gesetzt)
  GH_USER    GitHub-Benutzername (Standard: swissnand)
  KF_URL     Adresse von Knowledge Forge
  KF_COUNT   Anzahl Kurse im Profil (Standard: 3)

Lokal testen ohne Internet:  python scripts/update_profile.py --mock
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import random
import re
import sys
import urllib.request
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
README = ROOT / "README.md"

USER = os.environ.get("GH_USER", "swissnand")
TOKEN = os.environ.get("GH_TOKEN", "")
KF_URL = os.environ.get("KF_URL", "https://knowledge-forge.swissnand.com").rstrip("/")
KF_COUNT = int(os.environ.get("KF_COUNT", "3"))
UA = {"User-Agent": f"{USER}-profile-bot"}

FONT = "'Segoe UI',-apple-system,'SF Pro Display',Helvetica,Arial,sans-serif"
MONO = "'SF Mono',Menlo,Consolas,monospace"
# SWISSNAND-Palette (Namen aus der alten Version beibehalten)
CYAN, VIOLET, ORANGE, GREEN = "#5aaaf0", "#2f86d0", "#9ccbf5", "#3ccf96"
BRAND = "#004984"
TEXT, MUTED = "#f2f7fb", "#8fa3b8"


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def readable(color: str) -> str:
    """Zu dunkle Sprachfarben aufhellen, damit sie auf dem dunklen Hintergrund sichtbar sind."""
    try:
        r, g, b = (int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return MUTED
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    if lum >= 90:
        return color
    k = 0.55
    return "#%02x%02x%02x" % tuple(int(c + (255 - c) * k) for c in (r, g, b))


def fmt(n: int) -> str:
    return f"{n:,}".replace(",", "'")


# --------------------------------------------------------------------------- GitHub

QUERY = """
query($login: String!) {
  user(login: $login) {
    name
    followers { totalCount }
    pullRequests { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100, orderBy: {field: PUSHED_AT, direction: DESC}) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name color } } }
      }
    }
    contributionsCollection {
      totalCommitContributions
      restrictedContributionsCount
      totalPullRequestContributions
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def github_data() -> dict:
    if not TOKEN:
        sys.exit("GH_TOKEN fehlt. In der GitHub Action wird er automatisch gesetzt.")
    body = json.dumps({"query": QUERY, "variables": {"login": USER}}).encode()
    req = urllib.request.Request("https://api.github.com/graphql", data=body,
                                 headers={**UA, "Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.load(r)
    if "errors" in res:
        sys.exit(f"GitHub-API-Fehler: {res['errors']}")
    u = res["data"]["user"]
    cc = u["contributionsCollection"]
    days = [d for w in cc["contributionCalendar"]["weeks"] for d in w["contributionDays"]]
    langs: dict[str, dict] = {}
    for repo in u["repositories"]["nodes"]:
        for e in repo["languages"]["edges"]:
            n = e["node"]["name"]
            langs.setdefault(n, {"size": 0, "color": readable(e["node"]["color"] or MUTED)})["size"] += e["size"]
    return {
        "contributions": cc["contributionCalendar"]["totalContributions"],
        "commits": cc["totalCommitContributions"] + cc["restrictedContributionsCount"],
        "prs": u["pullRequests"]["totalCount"],
        "repos": u["repositories"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in u["repositories"]["nodes"]),
        "followers": u["followers"]["totalCount"],
        "days": days,
        "languages": langs,
    }


def mock_github() -> dict:
    rnd = random.Random(7)
    start = dt.date.today() - dt.timedelta(days=364 + dt.date.today().isoweekday() % 7)
    days = []
    for i in range(371):
        d = start + dt.timedelta(days=i)
        if d > dt.date.today():
            break
        base = 0 if rnd.random() < 0.35 else rnd.choice([1, 1, 2, 3, 4, 6, 9, 14])
        days.append({"date": d.isoformat(), "contributionCount": base if i > 250 else base // 2})
    return {"contributions": sum(d["contributionCount"] for d in days), "commits": 412, "prs": 9, "repos": 6,
            "stars": 3, "followers": 4, "days": days,
            "languages": {"TypeScript": {"size": 900_000, "color": "#3178c6"}, "Python": {"size": 420_000, "color": "#3572A5"},
                          "PowerShell": {"size": 60_000, "color": readable("#012456")}, "CSS": {"size": 45_000, "color": "#563d7c"},
                          "Shell": {"size": 12_000, "color": "#89e051"}, "MQL5": {"size": 9_000, "color": "#4A76B8"}}}


def streaks(days: list[dict]) -> tuple[int, int]:
    counts = [d["contributionCount"] for d in sorted(days, key=lambda d: d["date"])]
    longest = run = 0
    for c in counts:
        run = run + 1 if c > 0 else 0
        longest = max(longest, run)
    cur = 0
    i = len(counts) - 1
    if i >= 0 and counts[i] == 0:  # heute noch nichts? Streak zählt ab gestern
        i -= 1
    while i >= 0 and counts[i] > 0:
        cur += 1
        i -= 1
    return cur, longest


# --------------------------------------------------------------------------- SVG-Bausteine

def defs(w: int, h: int, a1: str, a2: str, rid: str = "") -> str:
    return f"""<defs>
<linearGradient id="bg{rid}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#070c12"/><stop offset="1" stop-color="#0c1722"/></linearGradient>
<radialGradient id="g1{rid}"><stop offset="0" stop-color="{a1}" stop-opacity=".55"/><stop offset="1" stop-color="{a1}" stop-opacity="0"/></radialGradient>
<radialGradient id="g2{rid}"><stop offset="0" stop-color="{a2}" stop-opacity=".45"/><stop offset="1" stop-color="{a2}" stop-opacity="0"/></radialGradient>
<linearGradient id="edge{rid}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".5"/><stop offset=".5" stop-color="#fff" stop-opacity=".06"/><stop offset="1" stop-color="#fff" stop-opacity=".3"/></linearGradient>
<filter id="b{rid}" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="24"/></filter>
<clipPath id="c{rid}"><rect width="{w}" height="{h}" rx="22"/></clipPath>
<style>
text{{font-family:{FONT}}} .mono{{font-family:{MONO}}}
.drift{{animation:drift 14s ease-in-out infinite alternate}}
@keyframes drift{{to{{transform:translate(-80px,30px)}}}}
@media (prefers-reduced-motion:reduce){{.rise,.drift{{animation:none}}}}
.rise{{animation:rise .8s ease-out backwards}}
@keyframes rise{{from{{opacity:0;transform:translateY(6px)}}to{{opacity:1;transform:none}}}}
</style></defs>"""


def frame(w: int, h: int, a1: str, a2: str, body: str, rid: str = "") -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
{defs(w, h, a1, a2, rid)}
<g clip-path="url(#c{rid})">
<rect width="{w}" height="{h}" fill="url(#bg{rid})"/>
<g filter="url(#b{rid})"><circle class="drift" cx="{w - 110}" cy="40" r="130" fill="url(#g1{rid})"/><circle cx="80" cy="{h}" r="100" fill="url(#g2{rid})"/></g>
<rect x="1" y="1" width="{w - 2}" height="{h - 2}" rx="21" fill="#fff" fill-opacity=".05" stroke="url(#edge{rid})" stroke-width="1.5"/>
{body}
</g></svg>"""


def stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=1))).strftime("%d.%m.%Y")


# --------------------------------------------------------------------------- Karten

def stats_svg(g: dict) -> str:
    cur, longest = streaks(g["days"])
    tiles = [
        ("Beiträge (12 Mt.)", fmt(g["contributions"]), CYAN),
        ("Commits (12 Mt.)", fmt(g["commits"]), VIOLET),
        ("Streak aktuell", f"{cur} T", ORANGE),
        ("Längster Streak", f"{longest} T", ORANGE),
        ("Repos", fmt(g["repos"]), CYAN),
        ("Sterne · PRs", f"{fmt(g['stars'])} · {fmt(g['prs'])}", VIOLET),
    ]
    w, h = 580, 230
    body = [f'<text x="28" y="44" font-size="19" font-weight="700" fill="{TEXT}">GitHub in Zahlen</text>',
            f'<text x="{w - 28}" y="44" font-size="12" fill="{MUTED}" text-anchor="end">Stand {stamp()}</text>']
    tw, th, gx, gy, x0, y0 = 166, 70, 13, 12, 28, 66
    for i, (label, value, color) in enumerate(tiles):
        x, y = x0 + (i % 3) * (tw + gx), y0 + (i // 3) * (th + gy)
        body.append(f'<g class="rise" style="animation-delay:{i * 0.12:.2f}s">'
                    f'<rect x="{x}" y="{y}" width="{tw}" height="{th}" rx="14" fill="#fff" fill-opacity=".05" stroke="#fff" stroke-opacity=".1"/>'
                    f'<rect x="{x}" y="{y + 18}" width="3" height="{th - 36}" rx="1.5" fill="{color}"/>'
                    f'<text x="{x + 16}" y="{y + 34}" font-size="23" font-weight="700" fill="{TEXT}">{esc(value)}</text>'
                    f'<text x="{x + 16}" y="{y + 55}" font-size="12" fill="{MUTED}">{esc(label)}</text></g>')
    return frame(w, h, CYAN, VIOLET, "\n".join(body), "s")


def languages_svg(g: dict) -> str:
    w, h = 580, 230
    langs = sorted(g["languages"].items(), key=lambda kv: -kv[1]["size"])
    total = sum(v["size"] for _, v in langs) or 1
    top = langs[:6]
    body = [f'<text x="28" y="44" font-size="19" font-weight="700" fill="{TEXT}">Meistgenutzte Sprachen</text>',
            f'<text x="{w - 28}" y="44" font-size="12" fill="{MUTED}" text-anchor="end">{len(langs)} Sprachen</text>',
            '<clipPath id="bar"><rect x="28" y="66" width="524" height="12" rx="6"/></clipPath><g clip-path="url(#bar)">',
            '<rect x="28" y="66" width="524" height="12" fill="#fff" fill-opacity=".08"/>']
    x = 28.0
    for name, v in top:
        bw = 524 * v["size"] / total
        body.append(f'<rect x="{x:.1f}" y="66" width="{bw:.1f}" height="12" fill="{v["color"]}"/>')
        x += bw
    body.append("</g>")
    for i, (name, v) in enumerate(top):
        cx, cy = 28 + (i % 2) * 270, 112 + (i // 2) * 36
        pct = v["size"] / total * 100
        body.append(f'<g class="rise" style="animation-delay:{i * 0.1:.2f}s"><circle cx="{cx + 6}" cy="{cy - 5}" r="6" fill="{v["color"]}"/>'
                    f'<text x="{cx + 22}" y="{cy}" font-size="15" fill="{TEXT}">{esc(name)}</text>'
                    f'<text x="{cx + 245}" y="{cy}" font-size="14" fill="{MUTED}" text-anchor="end" class="mono">{pct:.1f} %</text></g>')
    if not top:
        body.append(f'<text x="28" y="130" font-size="15" fill="{MUTED}">Noch keine Daten</text>')
    return frame(w, h, VIOLET, CYAN, "\n".join(body), "l")


def activity_svg(g: dict) -> str:
    w, h = 1200, 250
    days = sorted(g["days"], key=lambda d: d["date"])[-371:]
    mx = max([d["contributionCount"] for d in days] + [1])
    cell, gap = 15, 4
    grid_w = 53 * (cell + gap)
    x0 = (w - grid_w) // 2 + 20
    y0 = 78
    first = dt.date.fromisoformat(days[0]["date"]) if days else dt.date.today()
    offset = first.isoweekday() % 7  # Sonntag = 0 wie bei GitHub
    rects, months = [], {}
    for i, d in enumerate(days):
        k = i + offset
        col, row = k // 7, k % 7
        if col > 52:
            break
        c = d["contributionCount"]
        x, y = x0 + col * (cell + gap), y0 + row * (cell + gap)
        if c == 0:
            fill, op = "#ffffff", 0.06
        else:
            q = min(1.0, (c / mx) ** 0.5)
            fill, op = (CYAN if q < 0.75 else VIOLET), 0.25 + 0.75 * q
        rects.append(f'<rect class="rise" style="animation-delay:{col * 0.025:.3f}s" x="{x}" y="{y}" width="{cell}" height="{cell}" rx="4" fill="{fill}" fill-opacity="{op:.2f}"><title>{d["date"]}: {c}</title></rect>')
        dd = dt.date.fromisoformat(d["date"])
        if dd.day <= 7 and row == 0:
            months[col] = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"][dd.month - 1]
    labels = [f'<text x="{x0 + c * (cell + gap)}" y="{y0 - 10}" font-size="11" fill="{MUTED}">{m}</text>' for c, m in months.items()]
    days_lbl = [f'<text x="{x0 - 10}" y="{y0 + r * (cell + gap) + 12}" font-size="10" fill="{MUTED}" text-anchor="end">{t}</text>'
                for r, t in ((1, "Mo"), (3, "Mi"), (5, "Fr"))]
    total = sum(d["contributionCount"] for d in days)
    body = (f'<text x="32" y="42" font-size="19" font-weight="700" fill="{TEXT}">Aktivität</text>'
            f'<text x="{w - 32}" y="42" font-size="13" fill="{MUTED}" text-anchor="end">{fmt(total)} Beiträge in 12 Monaten · Stand {stamp()}</text>'
            + "".join(labels) + "".join(days_lbl) + "".join(rects))
    return frame(w, h, CYAN, VIOLET, body, "a")


# --------------------------------------------------------------------------- Knowledge Forge

LEVELS = ("Einsteiger", "Fortgeschritten", "Profi")


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def course_urls() -> list[str]:
    xml = fetch(f"{KF_URL}/sitemap.xml")
    root = ElementTree.fromstring(xml)
    locs = [e.text.strip() for e in root.iter() if e.tag.endswith("loc") and e.text]
    return [u for u in locs if re.search(r"/kurse/[^/?#]+$", u)]


def parse_course(page: str, url: str) -> dict:
    """Liest Titel, Untertitel, Niveau, Preis, Lektionen, Dauer und Kategorie aus der Kursseite."""
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    title = h1.group(1) if h1 else (re.search(r"<title>(.*?)</title>", page, re.S) or [None, url])[1]
    title = html.unescape(re.sub(r"<[^>]+>", "", title)).split(" · Knowledge Forge")[0].strip()
    desc = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]*)"', page) or \
        re.search(r'<meta[^>]+content="([^"]*)"[^>]+name="description"', page)
    cat = re.search(r'href="/kurse\?kategorie=[^"]*"[^>]*>(.*?)</a>', page, re.S)
    # Kennzahlen stehen nach Titel UND Untertitel (der Untertitel kann z. B. «200 Lektionen» enthalten)
    sub_p = re.compile(r"\s*<p[^>]*>.*?</p>", re.S).match(page, h1.end()) if h1 else None
    after = page[(sub_p.end() if sub_p else h1.end()):] if h1 else page
    text = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<!--.*?-->", "", after, flags=re.S))))
    lvl = next((m for m in re.findall(r"\b(" + "|".join(LEVELS) + r")\b", text)), None)
    lessons = re.search(r"(\d+)\s+Lektionen", text)
    minutes = re.search(r"ca\.\s*(\d+)\s*Min\.", text)
    price = re.search(r"(CHF\s?[\d'’.,]+|Kostenlos)", text)
    return {
        "url": url, "slug": url.rstrip("/").rsplit("/", 1)[-1], "title": title,
        "subtitle": html.unescape(desc.group(1)).strip() if desc else "",
        "category": html.unescape(re.sub(r"<[^>]+>", "", cat.group(1))).strip() if cat else "Kurs",
        "level": lvl, "lessons": int(lessons.group(1)) if lessons else None,
        "minutes": int(minutes.group(1)) if minutes else None,
        "price": price.group(1).replace("’", "'") if price else None,
    }


def kf_courses() -> list[dict]:
    out = []
    for u in course_urls():
        try:
            out.append(parse_course(fetch(u), u))
        except Exception as e:  # einzelne kaputte Seite soll nicht alles stoppen
            print(f"  Kurs übersprungen ({u}): {e}")
    return out


def mock_courses() -> list[dict]:
    return [
        {"url": f"{KF_URL}/kurse/it-basics", "slug": "it-basics", "title": "IT-Basics: Computer, Internet und Sicherheit verstehen",
         "subtitle": "Der grosse Einsteigerkurs: Wie Computer, Betriebssysteme, Netzwerke und Sicherheit wirklich funktionieren – mit vielen Übungen",
         "category": "IT-Grundlagen", "level": "Einsteiger", "lessons": 64, "minutes": 1680, "price": "CHF 19"},
        {"url": f"{KF_URL}/kurse/kubernetes-masterclass", "slug": "kubernetes-masterclass", "title": "Kubernetes Masterclass: Vom Einsteiger zum Profi",
         "subtitle": "Über 200 Lektionen, eigenes Lab, vier grosse Praxisprojekte – Kubernetes so lernen, dass du es im Beruf einsetzen kannst",
         "category": "Cloud & DevOps", "level": "Fortgeschritten", "lessons": 224, "minutes": 5520, "price": "CHF 149"},
    ]


def wrap(text: str, max_chars: int, max_lines: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for wd in words:
        if len(cur) + len(wd) + (1 if cur else 0) <= max_chars:
            cur = f"{cur} {wd}".strip()
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" ,.:;–-")[: max_chars - 1] + "…"
    return lines


PALETTES = [("#0a5fa3", BRAND), (BRAND, "#1a6aa8"), ("#0d66ad", "#003561"), ("#1a6aa8", BRAND)]


def course_svg(c: dict, i: int) -> str:
    w, h = 400, 270
    rid = f"k{i}"
    a1, a2 = PALETTES[int(hashlib.md5(c["slug"].encode()).hexdigest(), 16) % len(PALETTES)]
    chips, x = [], 24
    for label, col in ((c["category"], ORANGE), (c["level"], "#fff")):
        if not label:
            continue
        cw = int(len(label) * 7.1 + 24)
        chips.append(f'<rect x="{x}" y="22" width="{cw}" height="26" rx="13" fill="{col}" fill-opacity="{.18 if col == ORANGE else .08}" stroke="{col}" stroke-opacity=".45"/>'
                     f'<text x="{x + cw / 2}" y="39.5" font-size="12" font-weight="600" fill="{"#cfe6fb" if col == ORANGE else "#e2e8f0"}" text-anchor="middle">{esc(label)}</text>')
        x += cw + 8
    tl = wrap(c["title"], 30, 2)
    title = "".join(f'<text x="24" y="{86 + j * 27}" font-size="21" font-weight="700" fill="{TEXT}">{esc(t)}</text>' for j, t in enumerate(tl))
    sy = 86 + len(tl) * 27 + 6
    sub = "".join(f'<text x="24" y="{sy + j * 20}" font-size="13.5" fill="#cbd5e1">{esc(t)}</text>' for j, t in enumerate(wrap(c["subtitle"], 50, 3)))
    meta = []
    if c.get("lessons"):
        meta.append(f"{c['lessons']} Lektionen")
    if c.get("minutes"):
        hrs = c["minutes"] / 60
        meta.append(f"ca. {hrs:.0f} Std." if hrs >= 1.5 else f"ca. {c['minutes']} Min.")
    foot = (f'<line x1="24" y1="{h - 58}" x2="{w - 24}" y2="{h - 58}" stroke="#fff" stroke-opacity=".1"/>'
            f'<text x="24" y="{h - 26}" font-size="13" fill="{MUTED}">{esc(" · ".join(meta))}</text>'
            f'<text x="{w - 24}" y="{h - 26}" font-size="17" font-weight="700" fill="{ORANGE}" text-anchor="end">{esc(c.get("price") or "")}</text>')
    return frame(w, h, a1, a2, "".join(chips) + title + sub + foot, rid)


def pick(courses: list[dict], n: int) -> list[dict]:
    """Jeden Tag eine andere Auswahl, am selben Tag immer dieselbe."""
    rnd = random.Random(dt.date.today().isoformat())
    return rnd.sample(courses, min(n, len(courses)))


def readme_block(chosen: list[dict]) -> str:
    width = {1: "60%", 2: "49%"}.get(len(chosen), "32%")
    imgs = "\n".join(f'  <a href="{esc(c["url"])}"><img src="./assets/course-{i + 1}.svg" width="{width}" alt="{esc(c["title"])}"/></a>'
                     for i, c in enumerate(chosen))
    return (f'<div align="center">\n{imgs}\n</div>\n\n<div align="center">\n\n'
            f'[![Alle Kurse](https://img.shields.io/badge/Alle_Kurse_ansehen-%E2%86%92-004984?style=for-the-badge&labelColor=0b1520)]({KF_URL}/kurse)\n'
            f'[![Pro-Abo](https://img.shields.io/badge/Pro--Abo-alle_Kurse_inklusive-1a6aa8?style=for-the-badge&labelColor=0b1520)]({KF_URL}/pro)\n\n'
            f'<sub>Jeden Tag eine neue Auswahl · Stand {stamp()}</sub>\n\n</div>')


def update_readme(block: str):
    s = README.read_text(encoding="utf-8")
    new = re.sub(r"(<!-- KF:START -->).*?(<!-- KF:END -->)", lambda m: m.group(1) + "\n" + block + "\n" + m.group(2), s, flags=re.S)
    if new == s and "<!-- KF:START -->" not in s:
        print("  Hinweis: Marker <!-- KF:START --> fehlt im README")
    README.write_text(new, encoding="utf-8")


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="Beispieldaten statt Internet (zum Testen)")
    args = ap.parse_args()
    ASSETS.mkdir(exist_ok=True)

    print("GitHub-Statistik …")
    try:
        g = mock_github() if args.mock else github_data()
        (ASSETS / "stats.svg").write_text(stats_svg(g), encoding="utf-8")
        (ASSETS / "languages.svg").write_text(languages_svg(g), encoding="utf-8")
        (ASSETS / "activity.svg").write_text(activity_svg(g), encoding="utf-8")
        print(f"  ok: {g['contributions']} Beiträge, {len(g['languages'])} Sprachen")
    except SystemExit:
        raise
    except Exception as e:
        print(f"  Fehler, alte Karten bleiben: {e}")

    print("Knowledge-Forge-Kurse …")
    try:
        courses = mock_courses() if args.mock else kf_courses()
        if not courses:
            raise RuntimeError("keine Kurse in der Sitemap gefunden")
        chosen = pick(courses, KF_COUNT)
        for old in ASSETS.glob("course-*.svg"):
            old.unlink()
        for i, c in enumerate(chosen):
            (ASSETS / f"course-{i + 1}.svg").write_text(course_svg(c, i), encoding="utf-8")
        update_readme(readme_block(chosen))
        print(f"  ok: {len(courses)} Kurse gefunden, gezeigt: {', '.join(c['slug'] for c in chosen)}")
    except Exception as e:
        print(f"  Fehler, alte Kurse bleiben: {e}")


if __name__ == "__main__":
    main()
