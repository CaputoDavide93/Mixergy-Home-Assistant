#!/usr/bin/env python3
"""Draw this repository's diagrams as SVG, one file per colour scheme.

  docs/assets/<name>-light.svg
  docs/assets/<name>-dark.svg

House diagram kit (canonical copy: ~/.claude/skills/new-repo/assets/gen_diagram.py,
first built for InkFrame-Immich). The engine below the "diagrams" line is shared
verbatim across repos; only the diagram functions and DIAGRAMS change per repo.

GitHub sanitises SVG in markdown: no <style>, no <script>, no web font, no
<foreignObject>. Everything is a presentation attribute and the type is a system
stack. Each pair is served from one <picture>, which GitHub switches on
prefers-color-scheme. Layout is explicit rather than solved.

House rules: a slate scale, a single accent on the one thing that matters in each
picture, drawn icons rather than emoji, monospace for anything literally typed,
text contrast at or above 4.5:1 in both schemes.

  python3 tools/gen_diagram.py          # write the SVGs
  python3 tools/gen_diagram.py --check  # exit 1 if any SVG is stale (for CI)
"""
from __future__ import annotations

import pathlib
from xml.sax.saxutils import escape

ROOT = pathlib.Path(__file__).resolve().parents[1]
SANS = "system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,monospace"

SCHEMES = {
    "light": dict(card="#ffffff", border="#d8dee4", title="#0f172a", sub="#5b6673",
                  accent="#2b59c3", on_accent="#ffffff", soft="#f1f4f9",
                  line="#94a3b8", rule="#e6e9ee", chip="#475569",
                  warn="#9a3412", warn_soft="#fff4ed", group="#f7f9fb"),
    "dark":  dict(card="#161b22", border="#30363d", title="#e6edf3", sub="#9aa4b0",
                  accent="#4c7ef3", on_accent="#ffffff", soft="#1b2230",
                  line="#6b7684", rule="#232a33", chip="#aeb7c2",
                  warn="#ffa657", warn_soft="#2a1d14", group="#11151b"),
}

# Stroked glyphs on a 24x24 grid, drawn rather than typed.
ICONS = {
    "library":  "M3 7h13v11H3z M6 4h13v11 M7 14l3-3 2.5 2.5L15 11l2 2.5",
    "chip":     "M8 8h8v8H8z M5 5h14v14H5z M10 2v3 M14 2v3 M10 19v3 M14 19v3 M2 10h3 M2 14h3 M19 10h3 M19 14h3",
    "frame":    "M3 5h18v12H3z M9 20h6 M12 17v3 M6 13l3.5-4 2.5 3 2-2.5L18 13",
    "house":    "M4 11 12 4l8 7 M6 10v9h12v-9 M10 19v-5h4v5",
    "moon":     "M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5z",
    "bolt":     "M13 2 4 14h7l-1 8 9-12h-7z",
    "server":   "M4 4h16v6H4z M4 14h16v6H4z M7 7h.01 M7 17h.01 M11 7h6 M11 17h6",
    "database": "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3z M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6 M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
    "cloud":    "M7 18h10a4 4 0 0 0 .5-7.97A6 6 0 0 0 6.1 9.5 4.3 4.3 0 0 0 7 18z",
    "laptop":   "M5 5h14v10H5z M2 19h20 M9 19l1-2h4l1 2",
    "phone":    "M8 2h8a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z M11 18h2",
    "mail":     "M3 6h18v12H3z M3 7l9 6 9-6",
    "clock":    "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 7v5l3 2",
    "shield":   "M12 3 4 6v6c0 4.5 3.4 8.3 8 9 4.6-.7 8-4.5 8-9V6z M9 12l2 2 4-4",
    "box":      "M12 3 3 7.5v9L12 21l9-4.5v-9z M3 7.5 12 12l9-4.5 M12 12v9",
    "user":     "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M4 21c0-4 3.6-6 8-6s8 2 8 6",
    "users":    "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z M2 20c0-3.5 3-5.5 7-5.5s7 2 7 5.5 M16 4.5a3.5 3.5 0 0 1 0 6.5 M18 14.8c2.4.6 4 2.3 4 5.2",
    "key":      "M14 10a4 4 0 1 0-3.2 3.9L13 16h2v2h2v2h3v-3l-5.1-5.1c.1-.3.1-.6.1-.9z M8 9h.01",
    "camera":   "M3 8h4l2-3h6l2 3h4v11H3z M12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
    "chart":    "M4 20V4 M4 20h16 M8 16v-5 M12 16V8 M16 16v-3",
    "api":      "M8 7 3 12l5 5 M16 7l5 5-5 5 M14 4l-4 16",
    "bell":     "M6 16V11a6 6 0 1 1 12 0v5l2 2H4z M10 21h4",
    "chat":     "M4 5h16v11H9l-5 4z",
    "gear":     "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M19.4 13a7.6 7.6 0 0 0 0-2l2-1.6-2-3.4-2.4 1a7.4 7.4 0 0 0-1.7-1L15 3.5h-4l-.4 2.5a7.4 7.4 0 0 0-1.7 1l-2.4-1-2 3.4 2 1.6a7.6 7.6 0 0 0 0 2l-2 1.6 2 3.4 2.4-1a7.4 7.4 0 0 0 1.7 1l.4 2.5h4l.4-2.5a7.4 7.4 0 0 0 1.7-1l2.4 1 2-3.4z",
    "code":     "M4 4h16v16H4z M9 9l-3 3 3 3 M15 9l3 3-3 3",
    "tv":       "M3 5h18v12H3z M8 21h8",
    "play":     "M6 4l14 8-14 8z",
    "file":     "M6 2h8l5 5v15H6z M14 2v5h5 M9 13h6 M9 17h6",
    "lock":     "M6 11h12v10H6z M8 11V7a4 4 0 0 1 8 0v4",
    "globe":    "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M3 12h18 M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9 M12 3c-2.5 2.7-3.8 5.7-3.8 9s1.3 6.3 3.8 9",
    "wifi":     "M2 9a15 15 0 0 1 20 0 M5.5 12.5a10 10 0 0 1 13 0 M9 16a5 5 0 0 1 6 0 M12 19.5h.01",
    "disk":     "M3 6h18v12H3z M7 14h.01 M11 14h6",
    "terminal": "M3 5h18v14H3z M7 10l3 2.5L7 15 M12.5 15h4.5",
    "calendar": "M4 6h16v15H4z M4 10h16 M8 3v5 M16 3v5 M8 14h2 M14 14h2 M8 17.5h2",
    "refresh":  "M20 12a8 8 0 1 1-2.3-5.7 M20 4v4.5h-4.5",
    "search":   "M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 1 0 0-13z M15.5 15.5 20 20",
    "filter":   "M4 5h16l-6 7.5V19l-4 1.5v-8z",
    "send":     "M21 3 3 10.5l7.5 3 3 7.5z M10.5 13.5 21 3",
    "alert":    "M12 3 22 20H2z M12 10v4 M12 17h.01",
    "archive":  "M3 4h18v4H3z M5 8v12h14V8 M10 12h4",
    "tag":      "M3 3h8l10 10-8 8L3 11z M7.5 7.5h.01",
    "user_plus":  "M10 11a4 4 0 1 0 0-8 4 4 0 1 0 0 8z M3 21c0-4 3-7 7-7s7 3 7 7 M19 8v6 M16 11h6",
    "user_x":     "M10 11a4 4 0 1 0 0-8 4 4 0 1 0 0 8z M3 21c0-4 3-7 7-7s7 3 7 7 M16.5 8.5l5 5 M21.5 8.5l-5 5",
    "user_check": "M10 11a4 4 0 1 0 0-8 4 4 0 1 0 0 8z M3 21c0-4 3-7 7-7s7 3 7 7 M16 11l2 2 4-4",
    "bucket":   "M4 6h16l-2 14H6z M4 6c0-1.5 3.6-2.5 8-2.5s8 1 8 2.5",
    "download": "M12 3v12 M7 10l5 5 5-5 M4 20h16",
    "wrench":   "M14.7 6.3a4 4 0 0 1 5-1.5l-2.6 2.6.5 2 2 .5 2.6-2.6a4 4 0 0 1-5.4 5.1L10 19.2",
    "bug":      "M9 7a3 3 0 0 1 6 0 M7 9h10v5a5 5 0 0 1-10 0z M12 9v10 M3 12h4 M17 12h4",
    "pulse":    "M3 12h4l2.5-6 5 12 2.5-6h4",
    "sliders":  "M4 6h9 M17 6h3 M4 12h3 M11 12h9 M4 18h11 M19 18h1 M15 4v4 M9 10v4 M17 16v4",
    "heart":    "M12 20s-7.5-4.6-7.5-10A4.5 4.5 0 0 1 12 7a4.5 4.5 0 0 1 7.5 3c0 5.4-7.5 10-7.5 10z",
    "sparkle":  "M11 3l1.9 5.6L18.5 10.5l-5.6 1.9L11 18l-1.9-5.6L3.5 10.5l5.6-1.9z",
    "rewind":   "M11 6 4 12l7 6z M20 6l-7 6 7 6z",
}


class Canvas:
    """Parts plus a size. No layout engine, on purpose."""

    def __init__(self, w: int, h: int, scheme: str, label: str) -> None:
        self.w, self.h, self.c, self.label = w, h, SCHEMES[scheme], label
        self.parts: list[str] = []

    def add(self, *svg: str) -> "Canvas":
        self.parts.extend(svg)
        return self

    # ── primitives ────────────────────────────────────────────────────────
    def icon(self, name, x, y, colour, size=21):
        s = size / 24
        return (f'<g transform="translate({x:.1f},{y:.1f}) scale({s:.4f})" fill="none" '
                f'stroke="{colour}" stroke-width="1.7" stroke-linecap="round" '
                f'stroke-linejoin="round"><path d="{ICONS[name]}"/></g>')

    def text(self, x, y, s, *, size=13, colour=None, font=None, weight=None,
             anchor="start", opacity=None):
        c = colour or self.c["sub"]
        extra = (f' font-weight="{weight}"' if weight else "") + \
                (f' opacity="{opacity}"' if opacity else "")
        return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{font or SANS}" '
                f'font-size="{size}" fill="{c}" text-anchor="{anchor}"{extra}>'
                f'{escape(s)}</text>')

    def box(self, x, y, w, h, title, subs=(), *, icon=None, tone="plain", rx=10):
        c = self.c
        fill, edge, tt = c["card"], c["border"], c["title"]
        st, op = c["sub"], ""
        if tone == "accent":
            fill = edge = c["accent"]; tt = st = c["on_accent"]; op = "0.85"
        elif tone == "soft":
            fill = c["soft"]
        elif tone == "warn":
            fill, edge, tt, st = c["warn_soft"], c["warn"], c["warn"], c["warn"]
        out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
               f'stroke="{edge}" stroke-width="1"/>']
        tx = x + 16
        ty = y + (28 if subs else h / 2 + 5)
        if icon:
            out.append(self.icon(icon, x + 16, y + (13 if subs else h / 2 - 10), tt))
            tx = x + 47
        out.append(self.text(tx, ty, title, size=15 if subs else 14,
                             colour=tt, weight="600"))
        for i, s in enumerate(subs):
            out.append(self.text(x + 16, y + 52 + i * 18, s, size=12.5,
                                 colour=st, opacity=op or None))
        return "".join(out)

    def diamond(self, cx, cy, w, h, lines):
        c = self.c
        pts = f"{cx},{cy - h/2} {cx + w/2},{cy} {cx},{cy + h/2} {cx - w/2},{cy}"
        out = [f'<polygon points="{pts}" fill="{c["soft"]}" stroke="{c["border"]}" '
               f'stroke-width="1"/>']
        n = len(lines)
        for i, s in enumerate(lines):
            out.append(self.text(cx, cy - (n - 1) * 7 + i * 14 + 4, s, size=12,
                                 colour=c["title"], anchor="middle"))
        return "".join(out)

    def pill(self, cx, cy, text, *, tone="plain", pad=16, size=13):
        c = self.c
        w = len(text) * size * 0.58 + pad * 2
        h = 32
        fill, edge, col = c["card"], c["border"], c["title"]
        if tone == "accent":
            fill = edge = c["accent"]; col = c["on_accent"]
        elif tone == "soft":
            fill = c["soft"]
        return (f'<rect x="{cx - w/2:.1f}" y="{cy - h/2}" width="{w:.1f}" height="{h}" '
                f'rx="{h/2}" fill="{fill}" stroke="{edge}" stroke-width="1"/>'
                + self.text(cx, cy + 4.5, text, size=size, colour=col, anchor="middle",
                            weight="500")), w

    def edge(self, pts, *, label=None, dash=False, both=False, label_at=0.5,
             label_dy=-9, label_anchor="middle", mono=True):
        c = self.c
        d = ' stroke-dasharray="5 4"' if dash else ""
        path = " ".join(f"{x},{y}" for x, y in pts)
        out = [f'<polyline points="{path}" fill="none" stroke="{c["line"]}" '
               f'stroke-width="1.5"{d} marker-end="url(#a)"'
               + (' marker-start="url(#b)"' if both else "") + "/>"]
        if label:
            (x1, y1), (x2, y2) = pts[0], pts[-1]
            lx = x1 + (x2 - x1) * label_at
            ly = y1 + (y2 - y1) * label_at
            out.append(self.text(lx, ly + label_dy, label, size=11.5,
                                 colour=c["chip"], font=MONO if mono else SANS,
                                 anchor=label_anchor))
        return "".join(out)

    def group(self, x, y, w, h, title):
        c = self.c
        return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" '
                f'fill="{c["group"]}" stroke="{c["border"]}" stroke-width="1" '
                f'stroke-dasharray="6 5"/>'
                + self.text(x + 18, y + 24, title, size=12, colour=c["sub"],
                            weight="600"))

    def footer(self, note):
        return (f'<line x1="24" y1="{self.h - 52}" x2="{self.w - 24}" y2="{self.h - 52}" '
                f'stroke="{self.c["rule"]}" stroke-width="1"/>'
                + self.text(24, self.h - 26, note, size=12.5, colour=self.c["sub"]))

    def render(self) -> str:
        c = self.c
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" '
            f'width="{self.w}" height="{self.h}" role="img" aria-label="{escape(self.label)}">'
            f'<defs>'
            f'<marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
            f'markerHeight="6" orient="auto-start-reverse">'
            f'<path d="M0 0 10 5 0 10z" fill="{c["line"]}"/></marker>'
            f'<marker id="b" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="6" '
            f'markerHeight="6" orient="auto">'
            f'<path d="M10 0 0 5 10 10z" fill="{c["line"]}"/></marker>'
            f'</defs>' + "".join(self.parts) + "</svg>"
        )

# ── the diagrams ──────────────────────────────────────────────────────────
# Replace this example with the repository's real architecture. Keep one accent
# (the component this repo IS), label every edge with what actually crosses it,
# and say in the footer the one fact a reader must not miss.

def architecture(scheme):
    k = Canvas(1180, 440, scheme,
               "The Mixergy tank reports to the Mixergy cloud. The integration's coordinator "
               "polls the cloud API over HTTPS and feeds the Home Assistant entities, which "
               "supply the Energy Dashboard. Services and controls write back to the cloud.")
    c = k.c
    top, H = 76, 108
    mid = top + H / 2
    bot, BH = 240, 92
    k.add(
        k.group(640, 40, 520, 316, "HOME ASSISTANT"),
        k.box(24, top, 184, H, "Mixergy tank", ["Reports to the cloud", "about every 60 s"], icon="bolt"),
        k.box(284, top, 232, H, "Mixergy cloud", ["www.mixergy.io/api/v2", "REST, HATEOAS links"], icon="cloud"),
        k.box(660, top, 220, H, "Coordinator", ["One per tank, polls every", "60 s (30 to 300 s)"], icon="server", tone="accent"),
        k.box(928, top, 208, H, "Entities", ["8 platforms, from sensors", "to the water heater"], icon="chip"),
        k.box(660, bot, 220, BH, "Services, controls", ["3 services, plus number,", "switch and select entities"], icon="gear"),
        k.box(928, bot, 208, BH, "Energy dashboard", ["Individual devices"], icon="chart"),
        # Tank and cloud talk to each other; Home Assistant never reaches the tank.
        k.edge([(208 + 8, mid), (284 - 8, mid)], both=True, label="reports"),
        k.text(246, mid + 20, "commands", size=11.5, font=MONO, colour=c["chip"], anchor="middle"),
        k.edge([(516 + 8, mid), (660 - 8, mid)], label="3 GETs / poll"),
        k.text(588, mid + 20, "HTTPS, bearer", size=11.5, font=MONO, colour=c["chip"], anchor="middle"),
        k.edge([(880 + 8, mid), (928 - 8, mid)]),
        k.edge([(1032, top + H + 8), (1032, bot - 8)]),
        k.text(1042, (top + H + bot) / 2 + 4, "kWh totals", size=11.5, font=MONO, colour=c["chip"]),
        # Writes go straight to the cloud, then ask the coordinator to refresh.
        k.edge([(660 - 8, bot + BH / 2), (400, bot + BH / 2), (400, top + H + 8)]),
        k.text(526, bot + BH / 2 - 9, "PUT, then refresh", size=11.5, font=MONO,
               colour=c["chip"], anchor="middle"),
        k.footer("Cloud only: nothing talks to the tank locally. Energy totals are integrated "
                 "from polled power, so they approximate the Mixergy app."),
    )
    return k.render()


DIAGRAMS = {
    "architecture": architecture,
}


def main() -> None:
    import sys
    check = "--check" in sys.argv[1:]
    out = ROOT / "docs" / "assets"
    out.mkdir(parents=True, exist_ok=True)
    stale = []
    for name, fn in DIAGRAMS.items():
        for scheme in SCHEMES:
            path = out / f"{name}-{scheme}.svg"
            svg = fn(scheme)
            if check:
                if not path.exists() or path.read_text(encoding="utf-8") != svg:
                    stale.append(str(path.relative_to(ROOT)))
            else:
                path.write_text(svg, encoding="utf-8")
    if check:
        if stale:
            print("stale diagrams (run python3 tools/gen_diagram.py):\n  " + "\n  ".join(stale))
            sys.exit(1)
        print(f"{len(DIAGRAMS) * len(SCHEMES)} diagram files up to date")
        return
    print(f"{len(DIAGRAMS)} diagrams x {len(SCHEMES)} schemes -> docs/assets/")


if __name__ == "__main__":
    main()
