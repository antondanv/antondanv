#!/usr/bin/env python3
"""Draws the profile README as a terminal session about antondanv, from live GitHub data.

    pip install -r scripts/requirements.txt
    python3 scripts/build.py      # token from GITHUB_TOKEN or `gh auth token`

Writes assets/terminal.svg: neofetch, about.md, the skills tree, the stack,
achievements and stats, typed out and printed line by line. Text is turned
into outlines (shaped by HarfBuzz), because an SVG shown through <img> can't
load fonts; tree connectors, dots and bars are drawn on the character grid.
"""

import datetime as dt
import hashlib
import json
import math
import os
import re
import subprocess
import urllib.request
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / 'assets'
LOGIN = 'antondanv'
PROMPT_COLS = 4  # '~ $ '

C = {
    'window': '#0d1117',
    'bar': '#161b22',
    'border': '#30363d',
    'text': '#e6edf3',
    'muted': '#9198a1',
    'rule': '#7d8590',
    'dim': '#21262d',
    'green': '#7ee2a8',
    'blue': '#8ab4ff',
    'amber': '#ffcf70',
    'cyan': '#62d0e0',
    'violet': '#d2a8ff',
    'red': '#ff7b72',
}

# ── what the session says ────────────────────────────────────────────────────

ART_COLS, ART_ROWS = 20, 12  # room for the neofetch logo, in character cells

# the logo is Treeyard's mark (docs/mark.svg): a branch with two leaves, a lone leaf, one trunk
MARK = (
    '<g fill="none" stroke="#7ee2a8" stroke-width="7" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M8 10V38H72V10"/><path d="M40 38V66"/><path d="M136 10V66"/><path d="M40 66H136"/><path d="M88 66V108"/></g>'
    '<circle cx="8" cy="8" r="9" fill="#5fd38d"/><circle cx="72" cy="8" r="9" fill="#8ab4ff"/>'
    '<circle cx="136" cy="8" r="9" fill="#ffcf70"/>'
)
MARK_BOX = (-1, -1, 146, 112)  # x, y, width, height of what the mark draws

ABOUT = [
    'College student at Sirius College, Russia, majoring in Programming',
    'and Information Systems. I build and support commercial websites,',
    'automation scripts and AI-based tools.',
    'Ask me about Python, web development, parsing and AI automation.',
]

# (directory, [(name, what it is, status)]); statuses colour the dot the way Treeyard does
SKILLS = [
    ('agents', [
        ('research-agent', 'plans, searches, writes the report', 'done'),
        ('writer-agents', 'from a headline to a longread', 'done'),
        ('multi-agent-sandbox', 'AutoGen, Docker, Gradio', 'done'),
        ('goal-trees', 'a done-when on every node', 'active'),
    ]),
    ('automation', [
        ('price-parsers', '10+ scripts, 4 hours down to 15 minutes', 'done'),
        ('telegram-bots', 'aiogram: news, feedback, moderation', 'done'),
        ('ai-workflows', 'n8n, CrewAI, LangGraph, OpenAI Agents SDK', 'done'),
    ]),
    ('web', [
        ('commercial-sites', 'built and kept running', 'done'),
        ('integrations', 'web resources for business needs', 'done'),
    ]),
    ('study', [
        ('sirius-college', 'Programming and Information Systems', 'active'),
    ]),
    ('next', [
        ('sber-internship', 'AI agent developer intern at Sber', 'active'),
    ]),
]
STATUS = {'done': 'green', 'active': 'blue', 'waiting': 'amber'}

STACK = [
    ('python', 'blue'), ('javascript', 'blue'), ('kotlin', 'blue'),
    ('html', 'blue'), ('css', 'blue'), ('node', 'green'), ('react', 'green'), ('aiogram', 'green'),
    ('n8n', 'green'), ('crewai', 'green'), ('langgraph', 'green'), ('ollama', 'green'), ('docker', 'text'),
    ('git', 'text'), ('linux', 'text'), ('vscode', 'text'),
]

ACHIEVEMENTS = [
    ('2024', 'Winner, All-Russian Informatics Olympiad (Yandex)'),
    ('2023', 'Certificate, Python Parser Development (Innopolis University)'),
]

# ── the grid ─────────────────────────────────────────────────────────────────

W = 880
FS = 17.5  # font size
LH = 25.5  # line height
PAD = 28
BAR = 40


def n(x):
    s = f'{x:.2f}'.rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


class Face:
    """A font that sets text as outlines: each glyph is defined once and <use>d."""

    def __init__(self, key, file):
        self.key = key
        path = HERE / 'fonts' / file
        self.tt = TTFont(path)
        self.glyphs = self.tt.getGlyphSet()
        self.upm = self.tt['head'].unitsPerEm
        self.hb = hb.Font(hb.Face(hb.Blob.from_file_path(str(path))))

    def shape(self, text):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hb, buf, {'liga': False, 'calt': False})
        return [(i.codepoint, p.x_advance) for i, p in zip(buf.glyph_infos, buf.glyph_positions)]

    def outline(self, gid):
        pen = SVGPathPen(self.glyphs, ntos=lambda v: str(round(v)))
        self.glyphs[self.tt.getGlyphName(gid)].draw(pen)
        return pen.getCommands()


REGULAR = Face('r', 'JetBrainsMono-Regular.ttf')
BOLD = Face('b', 'JetBrainsMono-Bold.ttf')
CW = REGULAR.shape('m')[0][1] * FS / REGULAR.upm  # one character cell
COLS = int((W - 2 * PAD) / CW)


def baseline(row):
    return BAR + 22 + FS * 0.8 + row * LH


def mid(row):
    return baseline(row) - FS * 0.3


def cx(col):
    return PAD + col * CW


def row_top(row):
    return mid(row) - LH / 2


def row_bottom(row):
    return mid(row) + LH / 2


def cursor_y(row):
    return baseline(row) - FS * 0.82


class Session:
    """Everything is drawn at once; a clip reveals it over time, the way it would be typed and printed.

    Two SMIL-animated rects make the clip: one grows down over the lines already printed, the other
    widens along the line being typed. A browser that runs no animation simply shows it all.
    """

    def __init__(self):
        self.defs = {}
        self.body = []
        self.row = 0
        self.t = 0.3
        self.printed = [(0.0, 0.0)]  # (time, bottom edge of what is shown in full)
        self.typing = [(0.0, (0.0, 0.0))]  # (time, (top, right edge) of the line being typed)
        self.cursor = [(0.0, (cx(PROMPT_COLS), cursor_y(0), 0))]  # (time, (x, y, opacity))

    def text(self, col, text, color, bold=False, size=FS, x=None, y=None):
        """Text at a character column of the current row (or at x, y), as outlines."""
        face = BOLD if bold else REGULAR
        k = size / face.upm
        uses, pen = [], 0
        for gid, adv in face.shape(text):
            key = f'{face.key}{gid}'
            if key not in self.defs:
                self.defs[key] = face.outline(gid)
            if self.defs[key]:
                uses.append(f'<use href="#{key}" x="{pen}"/>')
            pen += adv
        x = cx(col) if x is None else x
        y = baseline(self.row) if y is None else y
        return f'<g fill="{C[color]}" transform="translate({n(x)} {n(y)}) scale({k:.5f} {-k:.5f})">{"".join(uses)}</g>'

    def parts(self, parts, col=0):
        out = ''
        for text, color, bold in parts:
            out += self.text(col, text, color, bold)
            col += len(text)
        return out

    def emit(self, markup, step=0.016, rows=1):
        """Output: printed whole, a line (or a few) at a time."""
        self.body.append(markup)
        self.row += rows
        self.printed.append((self.t, row_bottom(self.row - 1)))
        self.t += step

    def blank(self):
        self.row += 1

    def prompt(self):
        return self.parts([('~', 'blue', True), (' $', 'green', True)])

    def command(self, text, per_char=0.035, think=0.2):
        """A prompt, then the command typed a character at a time."""
        top, cy = row_top(self.row), cursor_y(self.row)
        self.body.append(self.prompt() + self.text(PROMPT_COLS, text, 'text'))
        self.typing.append((self.t, (top, cx(PROMPT_COLS))))
        self.cursor.append((self.t, (cx(PROMPT_COLS), cy, 1)))
        for j in range(len(text)):
            at = self.t + think + j * per_char
            self.typing.append((at, (top, cx(PROMPT_COLS + j + 1))))
            self.cursor.append((at, (cx(PROMPT_COLS + j + 1), cy, 1)))
        done = self.t + think + len(text) * per_char + 0.15
        self.printed.append((done, row_bottom(self.row)))
        self.cursor.append((done, (cx(PROMPT_COLS + len(text)), cy, 0)))
        self.t = done + 0.05
        self.row += 1

    def wait(self):
        """The last prompt, with the cursor left blinking on it."""
        self.body.append(self.prompt())
        self.typing.append((self.t, (row_top(self.row), cx(PROMPT_COLS))))
        self.cursor.append((self.t, (cx(PROMPT_COLS), cursor_y(self.row), 1)))
        self.row += 1

    def dot(self, col, color, hollow=False, r=4.4):
        x, y = cx(col) + CW / 2, mid(self.row)
        if hollow:
            return f'<circle cx="{n(x)}" cy="{n(y)}" r="{n(r - 0.4)}" fill="none" stroke="{C[color]}" stroke-width="1.8"/>'
        return f'<circle cx="{n(x)}" cy="{n(y)}" r="{n(r)}" fill="{C[color]}"/>'

    def blocks(self, col, cells, filled, color):
        """A bar of character cells, the filled ones in colour: like ████░░░░ but crisp."""
        y, h = mid(self.row) - FS * 0.3, FS * 0.6
        out = ''
        for i in range(cells):
            fill = C[color] if i < filled else C['dim']
            out += f'<rect x="{n(cx(col + i) + 0.8)}" y="{n(y)}" width="{n(CW - 1.6)}" height="{n(h)}" rx="1" fill="{fill}"/>'
        return out


# ── data ─────────────────────────────────────────────────────────────────────

QUERY = """query($login: String!) {
  user(login: $login) {
    createdAt
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 12, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name } } }
      }
    }
  }
}"""


def token():
    for key in ('GITHUB_TOKEN', 'GH_TOKEN'):
        if os.environ.get(key):
            return os.environ[key]
    return subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True, check=True).stdout.strip()


def fetch():
    body = json.dumps({'query': QUERY, 'variables': {'login': LOGIN}}).encode()
    request = urllib.request.Request(
        'https://api.github.com/graphql',
        data=body,
        headers={'Authorization': f'bearer {token()}', 'Content-Type': 'application/json', 'User-Agent': LOGIN},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if payload.get('errors'):
        raise SystemExit(f'GitHub said: {payload["errors"]}')
    return payload['data']['user']


def summarize(user):
    calendar = user['contributionsCollection']['contributionCalendar']
    days = [d for week in calendar['weeks'] for d in week['contributionDays']]
    longest = run = 0
    for d in days:
        run = run + 1 if d['contributionCount'] else 0
        longest = max(longest, run)
    months = {}
    for d in days:
        months[d['date'][:7]] = months.get(d['date'][:7], 0) + d['contributionCount']
    languages = {}
    for repo in user['repositories']['nodes']:
        for edge in repo['languages']['edges']:
            languages[edge['node']['name']] = languages.get(edge['node']['name'], 0) + edge['size']
    today = dt.date.fromisoformat(days[-1]['date'])
    since = dt.date.fromisoformat(user['createdAt'][:10])
    months_on = (today.year - since.year) * 12 + today.month - since.month - (today.day < since.day)
    return {
        'total': calendar['totalContributions'],
        'longest': longest,
        'best': max(d['contributionCount'] for d in days),
        'months': list(months.items())[-12:],
        'stars': sum(r['stargazerCount'] for r in user['repositories']['nodes']),
        'repos': user['repositories']['totalCount'],
        'languages': sorted(languages.items(), key=lambda kv: -kv[1]),
        'uptime': (months_on // 12, months_on % 12),
        'today': today,
    }


def plural(count, word):
    return f'{count} {word}' + ('' if count == 1 else 's')


# ── the session ──────────────────────────────────────────────────────────────


def neofetch(s, stats):
    years, months = stats['uptime']
    uptime = plural(years, 'year') + (f', {plural(months, "month")}' if months else '') + ' on GitHub'
    info = [
        [(LOGIN, 'green', True)],
        [('-' * len(LOGIN), 'muted', False)],
        [('Study', 'green', True), (': Sirius College, Russia', 'text', False)],
        [('Major', 'green', True), (': Programming and Information Systems', 'text', False)],
        [('Focus', 'green', True), (': AI agents, automation, web', 'text', False)],
        [('Langs', 'green', True), (': Python, JavaScript', 'text', False)],
        [('Uptime', 'green', True), (f': {uptime}', 'text', False)],
        [('Activity', 'green', True), (f': {stats["total"]} contributions in the last year', 'text', False)],
        [('Streak', 'green', True), (f': {plural(stats["longest"], "day")}, best day {stats["best"]}', 'text', False)],
        [('Stars', 'green', True), (f': {stats["stars"]} across {stats["repos"]} public repos', 'text', False)],
        [('Status', 'green', True), (': ', 'text', False), ('AI agent developer intern at Sber', 'amber', False)],
        [],
    ]
    info_col = ART_COLS + 4
    for r in range(max(ART_ROWS, len(info) + 1)):
        markup = ''
        if r == 0:
            mx, my, mw, mh = MARK_BOX
            k = (ART_COLS * CW - 16) / mw
            x = cx(0) + 8 - mx * k
            y = row_top(s.row) + (ART_ROWS * LH - mh * k) / 2 - my * k
            markup += f'<g transform="translate({n(x)} {n(y)}) scale({k:.4f})">{MARK}</g>'
        if r < len(info):
            markup += s.parts(info[r], info_col)
        elif r == len(info):
            for i, color in enumerate(('red', 'green', 'amber', 'blue', 'violet', 'cyan', 'text', 'muted')):
                x = cx(info_col + i * 3)
                markup += f'<rect x="{n(x)}" y="{n(mid(s.row) - LH * 0.42)}" width="{n(CW * 3)}" height="{n(LH * 0.84)}" fill="{C[color]}"/>'
        s.emit(markup, 0.02)


def about(s):
    s.emit(s.parts([('# ', 'muted', False), ('about', 'text', True)]))
    for line in ABOUT:
        s.emit(s.text(0, line, 'text'))


def skills(s):
    s.emit(s.text(0, 'skills', 'blue', True))
    rule = C['rule']
    files = 0
    for bi, (directory, items) in enumerate(SKILLS):
        last_dir = bi == len(SKILLS) - 1
        x0 = cx(0) + CW / 2
        top, bottom = mid(s.row) - LH / 2 - 0.6, mid(s.row) + LH / 2 + 0.6
        conn = f'M{n(x0)} {n(top)}V{n(mid(s.row) if last_dir else bottom)}M{n(x0)} {n(mid(s.row))}H{n(cx(3.2))}'
        s.emit(f'<path d="{conn}" stroke="{rule}" stroke-width="1.7" fill="none"/>' + s.text(4, directory, 'blue', True))
        for li, (name, what, status) in enumerate(items):
            last = li == len(items) - 1
            top, bottom = mid(s.row) - LH / 2 - 0.6, mid(s.row) + LH / 2 + 0.6
            x1 = cx(4) + CW / 2
            conn = '' if last_dir else f'M{n(x0)} {n(top)}V{n(bottom)}'
            conn += f'M{n(x1)} {n(top)}V{n(mid(s.row) if last else bottom)}M{n(x1)} {n(mid(s.row))}H{n(cx(7.2))}'
            waiting = status == 'waiting'
            markup = f'<path d="{conn}" stroke="{rule}" stroke-width="1.7" fill="none"/>'
            markup += s.dot(8, STATUS[status], hollow=waiting)
            markup += s.text(10, name, 'amber' if waiting else 'text')
            markup += s.text(32, what, 'amber' if waiting else 'muted')
            s.emit(markup)
            files += 1
    s.emit(s.text(0, f'{plural(len(SKILLS), "directory").replace("directorys", "directories")}, {plural(files, "file")}', 'muted'))


def stack(s):
    per_row, width = 5, 15
    for r in range(0, len(STACK), per_row):
        markup = ''
        for i, (name, color) in enumerate(STACK[r:r + per_row]):
            markup += s.text(i * width, name, color, bold=color == 'blue')
        s.emit(markup)


def achievements(s):
    for year, what in ACHIEVEMENTS:
        s.emit(s.parts([(f'[{year}] ', 'amber', False), (what, 'text', False)]))


def gh_stats(s, stats):
    s.emit(s.text(0, 'languages in public repos', 'muted'))
    langs = stats['languages']
    total = sum(size for _, size in langs) or 1
    shown = [(name, size) for name, size in langs if size / total >= 0.02][:5]
    palette = ['blue', 'green', 'amber', 'violet', 'cyan']
    cells = 40
    for i, (name, size) in enumerate(shown):
        share = size / total
        markup = s.text(0, name, 'text')
        markup += s.blocks(13, cells, max(1, round(share * cells)), palette[i])
        markup += s.text(13 + cells + 2, f'{share * 100:>3.0f}%', 'muted')
        s.emit(markup)
    s.blank()
    s.emit(s.text(0, 'contributions by month, log scale', 'muted'))
    s.blank()
    # a three-line chart: one bar per month
    months = stats['months']
    chart_rows = 3
    top = mid(s.row) - LH / 2 + 3
    bottom = top + chart_rows * LH - 6
    peak = max(v for _, v in months) or 1
    markup = ''
    for i, (month, value) in enumerate(months):
        col = i * 4
        x = cx(col) + 1
        if value:
            h = max(3, (bottom - top) * math.log1p(value) / math.log1p(peak))
            markup += f'<rect x="{n(x)}" y="{n(bottom - h)}" width="{n(CW * 3 - 2)}" height="{n(h)}" rx="1.5" fill="{C["green"]}"/>'
        else:
            markup += f'<rect x="{n(x)}" y="{n(bottom - 2)}" width="{n(CW * 3 - 2)}" height="2" fill="{C["dim"]}"/>'
        label = dt.date.fromisoformat(month + '-01').strftime('%b').lower()
        markup += s.text(0, label, 'muted', x=cx(col) + (CW * 3 - CW * 3) / 2, y=bottom + LH * 0.82)
        markup += s.text(0, str(value), 'muted', size=FS * 0.72, x=x + 1, y=bottom - (h if value else 2) - 5) if value else ''
    s.emit(markup, 0.1, rows=chart_rows + 1)


def build(stats):
    s = Session()
    s.command('neofetch')
    neofetch(s, stats)
    s.blank()
    s.command('cat about.md')
    about(s)
    s.blank()
    s.command('cd skills && treeyard')
    skills(s)
    s.blank()
    s.command('ls stack/')
    stack(s)
    s.blank()
    s.command('cat achievements.txt')
    achievements(s)
    s.blank()
    s.command('gh stats')
    gh_stats(s, stats)
    s.blank()
    s.wait()

    height = round(baseline(s.row - 1) + 26)
    title = f'{LOGIN} — zsh'
    k = 13 / REGULAR.upm
    title_w = len(title) * 13 * 0.6
    uses, pen = [], 0
    for gid, adv in REGULAR.shape(title):
        key = f'r{gid}'
        if key not in s.defs:
            s.defs[key] = REGULAR.outline(gid)
        if s.defs[key]:
            uses.append(f'<use href="#{key}" x="{pen}"/>')
        pen += adv
    window = (
        f'<rect x=".5" y=".5" width="{W - 1}" height="{height - 1}" rx="12" fill="{C["window"]}" stroke="{C["border"]}"/>'
        f'<path d="M.5 {BAR}V12.5A12 12 0 0 1 12.5 .5H{W - 12.5}A12 12 0 0 1 {W - 0.5} 12.5V{BAR}Z" fill="{C["bar"]}"/>'
        f'<path d="M1 {BAR}H{W - 1}" stroke="{C["border"]}"/>'
        + ''.join(f'<circle cx="{22 + i * 20}" cy="{BAR / 2}" r="6" fill="{C["border"]}"/>' for i in range(3))
        + f'<g fill="{C["muted"]}" transform="translate({n((W - title_w) / 2)} {n(BAR / 2 + 4.6)}) scale({k:.5f} {-k:.5f})">{"".join(uses)}</g>'
    )
    total = s.t + 0.05

    def animate(attr, events, pick):
        times = ';'.join(f'{min(t / total, 1):.4f}' for t, _ in events)
        values = ';'.join(n(pick(v)) for _, v in events)
        return (f'<animate attributeName="{attr}" dur="{total:.2f}s" fill="freeze" calcMode="discrete" '
                f'keyTimes="{times}" values="{values}"/>')

    # with no animation the full height shows everything, and the typing rect stays empty
    screen = (
        f'<clipPath id="screen"><rect width="{W}" height="{height}">{animate("height", s.printed, lambda v: v)}</rect>'
        f'<rect width="0" height="{n(LH)}">{animate("y", s.typing, lambda v: v[0])}'
        f'{animate("width", s.typing, lambda v: v[1])}</rect></clipPath>'
    )
    last = s.cursor[-1][1]
    cursor = (
        f'<rect x="{n(last[0] + 1)}" y="{n(last[1])}" width="{n(CW - 1)}" height="{n(FS * 1.08)}" '
        f'fill="{C["green"]}" fill-opacity=".85">'
        f'{animate("x", s.cursor, lambda v: v[0] + 1)}{animate("y", s.cursor, lambda v: v[1])}'
        f'{animate("opacity", s.cursor, lambda v: v[2])}'
        f'<animate attributeName="fill-opacity" values=".85;0" dur="1.1s" begin="{total:.2f}s" '
        f'repeatCount="indefinite" calcMode="discrete"/></rect>'
    )
    label = (
        f'A terminal session about {LOGIN}: college student at Sirius College, Russia, Programming and Information '
        f'Systems; builds AI agents, automation and websites; AI agent developer intern at Sber; {stats["total"]} contributions in '
        f'the last year, {stats["stars"]} stars.'
    )
    defs = ''.join(f'<path id="{key}" d="{d}"/>' for key, d in s.defs.items())
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" viewBox="0 0 {W} {height}" '
        f'role="img" aria-label="{label}"><title>{label}</title><defs>{defs}{screen}</defs>'
        f'{window}<g clip-path="url(#screen)">{"".join(s.body)}</g>{cursor}</svg>\n'
    )


RAW = f'https://raw.githubusercontent.com/{LOGIN}/{LOGIN}/main/assets/terminal.svg'


def main():
    ASSETS.mkdir(exist_ok=True)
    svg = build(summarize(fetch()))
    (ASSETS / 'terminal.svg').write_text(svg)
    # GitHub lets browsers keep an image for five minutes; a new address for every new picture
    # (an absolute URL goes through GitHub's image proxy, query and all) shows it at once
    version = hashlib.sha1(svg.encode()).hexdigest()[:10]
    readme = HERE.parent / 'README.md'
    text = re.sub(r'src="[^"]*terminal\.svg[^"]*"', f'src="{RAW}?v={version}"', readme.read_text())
    readme.write_text(text)
    print(f'terminal.svg {len(svg) / 1024:.1f} KB, {COLS} columns, v={version}')


if __name__ == '__main__':
    main()
