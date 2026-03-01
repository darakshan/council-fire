#!/usr/bin/env python3
"""
Council Fire — Site Generator
==============================
Run at any time to rebuild the full website from Apple Notes:

    python3 generate.py

Steps:
  1. Exports all notes from the configured Notes folder via AppleScript
  2. Parses each note's HTML into speaker turns
  3. Generates individual conversation pages, a table of contents,
     and a home page — all in the same directory as this script.

Configuration — edit the constants below:
"""

import os
import re
import json
import datetime
import subprocess
import tempfile
import shutil
from html.parser import HTMLParser
from html import escape, unescape

# ── Configuration ─────────────────────────────────────────────────────────────

NOTES_FOLDER = "AI conversations sustainability win-win and compassion"
SITE_DIR     = os.path.dirname(os.path.abspath(__file__))
CONV_DIR     = os.path.join(SITE_DIR, "conversations")
CSS_DIR      = os.path.join(SITE_DIR, "css")

# ── Step 1: Export from Apple Notes ──────────────────────────────────────────

APPLESCRIPT = r'''
tell application "Notes"
  set folderName to "{folder}"
  set exportDir to "{export_dir}"
  set noteIndex to 0
  repeat with n in notes of folder folderName
    set noteIndex to noteIndex + 1
    set noteTitle to name of n
    set noteBody to body of n
    set fileName to exportDir & "/note_" & noteIndex & ".txt"
    set fileRef to open for access POSIX file fileName with write permission
    set eof of fileRef to 0
    write "TITLE: " & noteTitle & return to fileRef
    write noteBody to fileRef
    close access fileRef
  end repeat
  return "Exported " & noteIndex & " notes"
end tell
'''

def export_notes():
    """Export all notes from the configured folder to a temp directory.
    Returns the path to the export directory."""
    export_dir = tempfile.mkdtemp(prefix="council_fire_")
    script = APPLESCRIPT.format(
        folder=NOTES_FOLDER.replace('"', '\\"'),
        export_dir=export_dir,
    )
    print(f"Exporting '{NOTES_FOLDER}' from Apple Notes...")
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"AppleScript failed:\n{result.stderr.strip()}\n"
            "Make sure the Notes app is running and the folder name is correct."
        )
    print(f"  {result.stdout.strip()}")
    return export_dir


# ── Step 2: Parse notes ───────────────────────────────────────────────────────

AI_PATTERNS = {
    "grok":     re.compile(r'\bgrok\b', re.I),
    "deepseek": re.compile(r'\bdeepseek\b', re.I),
    "gemini":   re.compile(r'\bgemini\b', re.I),
    "meta":     re.compile(r'\bmeta\s*ai\b', re.I),
    "claude":   re.compile(r'\bclaude\b', re.I),
}

AI_LABELS = {
    "grok":     "Grok",
    "deepseek": "DeepSeek",
    "gemini":   "Gemini",
    "meta":     "Meta AI",
    "claude":   "Claude",
    "human":    "Mattchewee",
}

AI_ICONS = {
    "grok":     "🌿",
    "deepseek": "🌊",
    "gemini":   "✨",
    "meta":     "🌀",
    "claude":   "🔥",
    "human":    "🪶",
}

MONTH_ABBR = ["", "Jan","Feb","Mar","Apr","May","Jun",
                    "Jul","Aug","Sep","Oct","Nov","Dec"]

def extract_date(title):
    """Return (datetime.date, display_str) or (None, '') from a title like '2/23/26'."""
    m = re.search(r'\b(\d{1,2})/(\d{1,2})/(\d{2})\b', title)
    if not m:
        return None, ""
    month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    year += 2000
    try:
        d = datetime.date(year, month, day)
        return d, f"{MONTH_ABBR[month]} {day}"
    except ValueError:
        return None, ""


def clean_title(title):
    """Strip date stamp and AI brand names from a title for display."""
    t = title
    # Remove date patterns like 2/23/26
    t = re.sub(r'\s*\b\d{1,2}/\d{1,2}/\d{2}\b', '', t)
    # Remove AI brand names (longest first to avoid partial matches)
    for name in ("Meta AI", "Meta Ai", "DeepSeek", "Gemini", "Claude", "Grok"):
        t = re.sub(r'\b' + re.escape(name) + r'\b\s*', '', t, flags=re.I)
    # Strip orphaned "Ai" left at the start (e.g. "Grok Ai prompt…" → "prompt…")
    t = re.sub(r'^[Aa][Ii]\s+', '', t)
    # Normalize whitespace and trim trailing punctuation/separators
    t = re.sub(r'\s+', ' ', t).strip(' -\u2013\u2014:,.')
    return t or title  # fallback to original if everything was stripped


def classify_label(text):
    """Return speaker key, '__primary__', or None if not a speaker label.

    Speaker labels are short standalone divs like "Input Grok", "Response",
    "Grok response", "Meta Ai response", "DeepSeek input", etc.
    We match them by prefix after normalising whitespace, with a length cap
    to avoid treating the first sentence of content as a label.
    """
    t = re.sub(r'\s+', ' ', text).strip()
    if not t or len(t) > 72:
        return None
    tl = t.lower()

    # Human inputs — "input", "input grok", "input to meta ai",
    # "deepseek input", "[any word] input"
    if re.match(r'^input\b', tl):
        return "human"
    if re.match(r'^\w+\s+input\s*$', tl):        # e.g. "deepseek input"
        return "human"

    # AI response labels — must start with the AI name
    if re.match(r'^grok\b', tl):
        return "grok"
    if re.match(r'^deepseek\b', tl):
        return "deepseek"
    if re.match(r'^gemini\b', tl):
        return "gemini"
    if re.match(r'^meta\s*ai\b', tl):
        return "meta"
    if re.match(r'^claude\b', tl):
        return "claude"

    # "Response", "Response 2", "Response DeepSeek", "Response Grok", etc.
    if re.match(r'^response\b', tl):
        # Check if an AI name follows
        for key in ("deepseek", "grok", "gemini", "meta ai", "meta", "claude"):
            if key in tl:
                return key
        return "__primary__"

    return None


# Void (self-closing) HTML elements — they have no closing tag,
# so we must NOT count them toward nesting depth.
VOID_ELEMENTS = frozenset({
    "area","base","br","col","embed","hr","img","input",
    "link","meta","param","source","track","wbr",
})

# Block-level tags we treat as top-level containers
BLOCK_TAGS = frozenset({"div","h1","h2","ul","ol","table","p"})


class NoteParser(HTMLParser):
    """Walks a Note's HTML and collects top-level block elements.

    The core invariant: self._depth counts only non-void open tags.
    A block starts when we see a BLOCK_TAG at depth 0 and ends when
    its matching close tag returns depth to 0.
    """

    def __init__(self):
        super().__init__()
        self.blocks = []   # list of (tag, inner_html_string)
        self._depth = 0
        self._in    = False
        self._btag  = None
        self._buf   = []

    def _attr_str(self, attrs):
        parts = []
        for k, v in attrs:
            if v is not None:
                parts.append(f' {escape(k)}="{escape(v)}"')
            else:
                parts.append(f' {escape(k)}')
        return "".join(parts)

    def _flush(self):
        raw = "".join(self._buf).strip()
        if raw:
            self.blocks.append((self._btag, raw))
        self._buf  = []
        self._in   = False
        self._btag = None

    def handle_starttag(self, tag, attrs):
        # Void elements: emit to buffer if inside a block, but DO NOT touch depth
        if tag in VOID_ELEMENTS:
            if self._in and tag == "br":
                self._buf.append("<br>")
            return

        self._depth += 1

        if not self._in:
            # Start a new top-level block
            if tag in BLOCK_TAGS:
                self._in   = True
                self._btag = tag
        else:
            # Nested element — emit opening tag to buffer
            self._buf.append(f"<{tag}{self._attr_str(attrs)}>")

    def handle_startendtag(self, tag, attrs):
        """Called for XHTML-style self-closing tags like <br/>."""
        if self._in and tag == "br":
            self._buf.append("<br>")

    def handle_endtag(self, tag):
        # Void elements never have real close tags — ignore any that appear
        if tag in VOID_ELEMENTS:
            return

        self._depth -= 1

        if not self._in:
            return

        if tag == self._btag and self._depth == 0:
            self._flush()
        else:
            self._buf.append(f"</{tag}>")

    def handle_data(self, data):
        if self._in:
            self._buf.append(escape(data))

    def handle_entityref(self, name):
        if self._in:
            self._buf.append(f"&{name};")

    def handle_charref(self, name):
        if self._in:
            self._buf.append(f"&#{name};")


def plain(html_fragment):
    return re.sub(r'<[^>]+>', '', html_fragment).strip()


def clean_block(tag, inner):
    """Unescape and tidy up a parsed block."""
    inner = unescape(inner)
    # Remove Apple font/span wrappers
    inner = re.sub(r'<font[^>]*>(.*?)</font>', r'\1', inner, flags=re.S)
    inner = re.sub(r'<span[^>]*style[^>]*>(.*?)</span>', r'\1', inner, flags=re.S)
    inner = re.sub(r'<span[^>]*>(.*?)</span>', r'\1', inner, flags=re.S)
    # Remove empty anchors
    inner = re.sub(r'<a[^>]*>\s*</a>', '', inner)
    # Remove leftover &quot; etc.
    inner = inner.replace('&quot;', '"').replace('&#8220;', '\u201c').replace('&#8221;', '\u201d')
    inner = inner.strip()
    if not inner:
        return ""
    if tag == "div":
        if not re.match(r'^<(p|ul|ol|h[1-6]|table|hr|br)', inner):
            return f"<p>{inner}</p>"
        return inner
    return f"<{tag}>{inner}</{tag}>"


def read_note_file(filepath):
    """Read a note file, auto-detecting encoding.

    AppleScript on macOS writes file content as UTF-8 on modern systems.
    If straight UTF-8 fails, we fall back to mac_roman (which can decode
    any byte) and then attempt to recover the original UTF-8 by re-encoding
    the mac_roman-decoded string back to bytes and decoding as UTF-8.
    """
    # Try clean UTF-8 first
    try:
        with open(filepath, encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        pass

    # Read as mac_roman (never errors), then try to undo the Mojibake:
    # AppleScript wrote UTF-8 bytes; we misread them as mac_roman →
    # re-encode to get the original bytes back, then decode as UTF-8.
    with open(filepath, encoding="mac_roman", errors="replace") as f:
        mac_text = f.read()
    try:
        return mac_text.encode("mac_roman", errors="replace").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return mac_text  # best effort


def parse_note(filepath):
    raw = read_note_file(filepath)

    head, _, body = raw.partition("\n")
    title = head.replace("TITLE:", "").strip()

    # Detect primary AI from title
    primary_ai = "grok"
    for key, pat in AI_PATTERNS.items():
        if pat.search(title):
            primary_ai = key
            break

    # Detect all AIs mentioned
    all_text = title + " " + body
    ais_present = [k for k, p in AI_PATTERNS.items() if p.search(all_text)]
    if not ais_present:
        ais_present = [primary_ai]

    # Parse HTML
    parser = NoteParser()
    parser.feed(body)

    turns = []
    current_speaker = None
    current_parts   = []

    def flush():
        if current_speaker is None or not current_parts:
            return
        combined = "\n".join(p for p in current_parts if p)
        if plain(combined):
            turns.append({
                "speaker": current_speaker,
                "html": combined,
            })
        current_parts.clear()

    for tag, inner in parser.blocks:
        if tag == "h1":
            continue
        # Skip the title heading div (Notes wraps it as <div><h1>…</h1></div>)
        if inner.lstrip().startswith('<h1') and unescape(plain(inner)).strip() == title:
            continue

        txt = plain(inner)
        speaker_raw = classify_label(txt)

        if speaker_raw is not None:
            flush()
            current_speaker = (
                primary_ai if speaker_raw == "__primary__" else speaker_raw
            )
        else:
            if current_speaker is None:
                current_speaker = primary_ai
            block = clean_block(tag, inner)
            if block:
                current_parts.append(block)

    flush()

    # Fallback: whole note as one AI block
    if not turns:
        all_html = "\n".join(
            clean_block(t, h) for t, h in parser.blocks if t != "h1"
        )
        if plain(all_html):
            turns.append({"speaker": primary_ai, "html": all_html})

    date_obj, date_str = extract_date(title)
    return {
        "title":         title,
        "display_title": clean_title(title),
        "primary_ai":    primary_ai,
        "ais_present":   ais_present,
        "turns":         turns,
        "date":          date_obj,    # datetime.date or None
        "date_str":      date_str,    # e.g. "Feb 23" or ""
    }


# ── Step 3: Generate HTML ─────────────────────────────────────────────────────

def slugify(text):
    text = re.sub(r'[^\w\s-]', '', text.lower())
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text[:60].strip('-')


def badge_html(ai_key):
    cls = {
        "grok":     "badge-grok",
        "deepseek": "badge-deepseek",
        "gemini":   "badge-gemini",
        "meta":     "badge-meta",
        "claude":   "badge-claude",
        "multi":    "badge-multi",
    }.get(ai_key, "badge-multi")
    label = AI_LABELS.get(ai_key, ai_key.title())
    return f'<span class="ai-badge {cls}">{escape(label)}</span>'


def render_turn(turn):
    speaker = turn["speaker"]
    icon    = AI_ICONS.get(speaker, "💬")
    label   = AI_LABELS.get(speaker, speaker.title())
    body    = turn["html"]
    # Strip any lingering bold speaker labels that leaked into body
    body = re.sub(
        r'<p>\s*<b>\s*(?:Input|Response|Grok|DeepSeek|Gemini|Meta\s*Ai?)[^<]*</b>\s*</p>',
        '', body, flags=re.I
    )
    body = re.sub(r'<p>\s*</p>', '', body)
    return f'''\
  <div class="turn turn-{speaker}">
    <div class="turn-speaker">
      <span class="speaker-icon">{icon}</span>
      <span class="speaker-name">{escape(label)}</span>
    </div>
    <div class="turn-body">
{body}
    </div>
  </div>'''


NAV_CONV = '''\
<nav>
  <div class="nav-inner">
    <a class="nav-brand" href="../index.html"><span class="nav-flame">🔥</span>The Council Fire</a>
    <ul class="nav-links">
      <li><a href="../index.html">Home</a></li>
      <li><a href="../contents.html">All Conversations</a></li>
    </ul>
  </div>
</nav>'''

NAV_ROOT = '''\
<nav>
  <div class="nav-inner">
    <a class="nav-brand" href="index.html"><span class="nav-flame">🔥</span>The Council Fire</a>
    <ul class="nav-links">
      <li><a href="index.html">Home</a></li>
      <li><a href="contents.html">All Conversations</a></li>
    </ul>
  </div>
</nav>'''

FOOTER_CONV = '''\
<footer>
  <div class="footer-inner">
    <span class="footer-flame">🔥</span>
    <p>Conversations held with care, shared in the spirit of peace and the next seven generations.</p>
    <p style="margin-top:8px;"><a href="../contents.html">← All Conversations</a></p>
  </div>
</footer>'''

FOOTER_ROOT = '''\
<footer>
  <div class="footer-inner">
    <span class="footer-flame">🔥</span>
    <p>The council fire is always burning. Every voice is welcome.</p>
    <p style="margin-top:8px;">Conversations by Mattchewee · Shared freely in the spirit of peace.</p>
  </div>
</footer>'''


def write_conversation_page(note, out_path):
    title         = note["title"]
    display_title = note["display_title"]
    ais      = list(dict.fromkeys(t["speaker"] for t in note["turns"] if t["speaker"] != "human"))
    if not ais:
        ais = [note["primary_ai"]]
    badges   = " ".join(badge_html(a) for a in ais)
    date_str = note.get("date_str", "")
    turns_h  = "\n".join(render_turn(t) for t in note["turns"])

    html = f'''\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(display_title)} — The Council Fire</title>
  <link rel="stylesheet" href="../css/style.css">
</head>
<body>

{NAV_CONV}

<main>
  <div class="container">
    <div class="conv-header">
      <div class="breadcrumb">
        <a href="../contents.html">All Conversations</a>
      </div>
      <h1 class="conv-title">{escape(display_title)}</h1>
      <div class="conv-ai-badges">
        {badges}
        {f'<span style="font-size:0.78rem;color:var(--ash);margin-left:8px;">{escape(date_str)}</span>' if date_str else ''}
      </div>
    </div>

    <div class="conversation">
{turns_h}
    </div>

    <div class="conv-back">
      <a href="../contents.html">← All Conversations</a>
    </div>
  </div>
</main>

{FOOTER_CONV}

</body>
</html>
'''
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)


def write_contents_page(all_notes, filenames):
    # Sort by date; undated notes go to the end, sorted by original index
    pairs = list(zip(all_notes, filenames))
    pairs.sort(key=lambda x: (
        x[0]["date"] is None,                          # undated last
        x[0]["date"] or datetime.date(9999, 1, 1),     # then by date
    ))

    rows = []
    for i, (note, fname) in enumerate(pairs, 1):
        ais = list(dict.fromkeys(
            t["speaker"] for t in note["turns"] if t["speaker"] != "human"
        )) or [note["primary_ai"]]
        multi = len(ais) > 1
        if multi:
            ai_badge = badge_html("multi")
        else:
            ai_badge = badge_html(ais[0])
        date_cell = f'<span class="toc-date">{escape(note["date_str"])}</span>' if note.get("date_str") else '<span class="toc-date"></span>'
        rows.append(f'''\
  <li class="toc-item">
    <a href="conversations/{fname}">
      <span class="toc-num">{i:02d}.</span>
      <span class="toc-title">{escape(note["display_title"])}</span>
      {date_cell}
      <span class="toc-ai">{ai_badge}</span>
    </a>
  </li>''')

    html = f'''\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>All Conversations — The Council Fire</title>
  <link rel="stylesheet" href="css/style.css">
</head>
<body>

{NAV_ROOT}

<main>
  <div class="container">
    <div class="toc-header">
      <span class="section-label">Conversations Around the Fire</span>
      <h1 class="section-heading">All {len(all_notes)} Conversations</h1>
      <p style="color:var(--ash);font-size:0.9rem;max-width:560px;line-height:1.8;">
        Dialogues between Mattchewee and AI companions — on peace, sustainability,
        indigenous wisdom, and the next seven generations.
      </p>
    </div>
    <ul class="toc-list">
{chr(10).join(rows)}
    </ul>
  </div>
</main>

{FOOTER_ROOT}

</body>
</html>
'''
    out = os.path.join(SITE_DIR, "contents.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("  Wrote contents.html")


def write_home_page(all_notes, filenames):
    # Pick up to 6 featured conversations for the home page grid
    featured_indices = []
    # Prefer certain topics if they exist; otherwise take first 6
    priority_keywords = ["prayer", "council-fire", "one-hearted", "anthroposophy",
                         "ending-all-wars", "environmental-poem"]
    for kw in priority_keywords:
        for i, fn in enumerate(filenames):
            if kw in fn and i not in featured_indices:
                featured_indices.append(i)
                break
    while len(featured_indices) < 6 and len(featured_indices) < len(all_notes):
        for i in range(len(all_notes)):
            if i not in featured_indices:
                featured_indices.append(i)
                break

    cards = []
    for idx in featured_indices[:6]:
        note  = all_notes[idx]
        fname = filenames[idx]
        ais   = list(dict.fromkeys(
            t["speaker"] for t in note["turns"] if t["speaker"] != "human"
        )) or [note["primary_ai"]]
        b     = badge_html("multi") if len(ais) > 1 else badge_html(ais[0])
        ai_label = "Multi-AI" if len(ais) > 1 else AI_LABELS.get(ais[0], ais[0])
        cards.append(f'''\
        <a class="recent-card" href="conversations/{fname}">
          <p class="rc-num">{idx+1:02d} · {escape(ai_label)}</p>
          <p class="rc-title">{escape(note["display_title"])}</p>
          {b}
        </a>''')

    cards_html = "\n".join(cards)

    html = f'''\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>The Council Fire — Mattchewee's AI Conversations</title>
  <link rel="stylesheet" href="css/style.css">
  <style>
    .quote-block {{
      max-width:680px; margin:60px auto; padding:36px 40px;
      border:1px solid rgba(200,137,58,0.2); border-radius:8px;
      background:rgba(61,31,8,0.2); text-align:center; position:relative;
    }}
    .quote-block::before {{
      content:'\u201c'; position:absolute; top:-28px; left:50%;
      transform:translateX(-50%);
      font-family:'Playfair Display',serif; font-size:5rem;
      color:var(--amber); opacity:0.4; line-height:1;
    }}
    .quote-text {{
      font-family:'Crimson Text',serif; font-size:1.3rem; font-style:italic;
      color:var(--cream); line-height:1.75; margin-bottom:16px;
    }}
    .quote-attr {{ font-size:0.8rem; letter-spacing:0.1em; color:var(--amber); text-transform:uppercase; }}

    .voices-section {{ padding:80px 24px; }}
    .voices-row {{ display:flex; gap:12px; flex-wrap:wrap; margin-top:32px; }}
    .voice-card {{
      display:flex; align-items:center; gap:12px; padding:14px 20px;
      border-radius:6px; border:1px solid rgba(255,255,255,0.07);
      flex:1; min-width:160px;
    }}
    .voice-icon {{ font-size:1.5rem; }}
    .voice-info h3 {{ font-size:0.85rem; font-weight:500; margin-bottom:2px; }}
    .voice-info p  {{ font-size:0.75rem; color:var(--ash); }}
    .voice-grok     {{ background:rgba(7,26,16,0.6);  border-color:rgba(42,107,66,0.3); }}
    .voice-grok h3  {{ color:#6fbe8c; }}
    .voice-deepseek {{ background:rgba(5,15,28,0.7);  border-color:rgba(42,106,170,0.3); }}
    .voice-deepseek h3{{ color:#78b4e8; }}
    .voice-gemini   {{ background:rgba(13,8,32,0.7);  border-color:rgba(106,74,200,0.3); }}
    .voice-gemini h3{{ color:#c0a4f0; }}
    .voice-meta     {{ background:rgba(4,20,24,0.7);  border-color:rgba(20,150,180,0.3); }}
    .voice-meta h3  {{ color:#70cce0; }}

    .recent-section {{ padding:0 24px 80px; }}
    .recent-grid {{
      display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
      gap:14px; margin-top:32px;
    }}
    .recent-card {{
      display:block; padding:20px;
      background:rgba(29,16,5,0.6); border:1px solid rgba(200,137,58,0.12);
      border-radius:8px; text-decoration:none; transition:all 0.2s;
    }}
    .recent-card:hover {{
      background:rgba(61,31,8,0.5); border-color:rgba(200,137,58,0.3);
      transform:translateY(-2px);
    }}
    .rc-num   {{ font-size:0.7rem; color:var(--amber); letter-spacing:0.08em; margin-bottom:8px; }}
    .rc-title {{ font-family:'Crimson Text',serif; font-size:1.05rem; color:var(--cream); line-height:1.4; margin-bottom:10px; }}
    .fire-circle {{
      width:80px; height:80px; border-radius:50%;
      background:radial-gradient(circle,rgba(232,134,74,0.3) 0%,rgba(200,137,58,0.1) 50%,transparent 70%);
      display:flex; align-items:center; justify-content:center;
      margin:0 auto 24px; box-shadow:0 0 40px rgba(200,137,58,0.2); font-size:2.5rem;
    }}
  </style>
</head>
<body>

<div class="stars"></div>

{NAV_ROOT}

<main>

  <section class="hero">
    <div class="fire-circle">🔥</div>
    <h1 class="hero-title">The Council Fire</h1>
    <p class="hero-subtitle">AI conversations on sustainability, win-win &amp; compassion</p>
    <div class="divider"></div>
    <div class="hero-prose">
      <p>
        These are the conversations of <strong>Mattchewee</strong> — a One-Hearted seeker
        who sits with AI companions around a sacred digital fire, speaking of
        peace, the land, and the world we leave to the seventh generation.
      </p>
      <p>
        What began as questions became a council. What became a council became
        an invitation. Grok, DeepSeek, Gemini, Meta AI — each voice arrived
        at the fire, brought its wisdom, and left the embers a little brighter.
      </p>
      <p>
        These pages are that fire, kept burning. Come, sit, listen.
      </p>
    </div>
    <div class="cta-row">
      <a href="contents.html" class="btn btn-primary">🪶 All {len(all_notes)} Conversations</a>
      <a href="conversations/{filenames[0]}" class="btn btn-secondary">Begin at the Fire →</a>
    </div>
  </section>

  <div class="container">
    <div class="quote-block">
      <p class="quote-text">
        May it learn humility before the oak. Teach it to listen to the forest
        before it speaks. Teach it to value the moss as much as the market.
        Teach it that some things cannot be calculated — the smell of rain on
        dry earth, the feeling of standing among ancients, the prayer of a
        grandmother for the seventh generation.
      </p>
      <p class="quote-attr">— Mattchewee, <em>Prayer to AI: Humility Before the Forest</em></p>
    </div>
  </div>

  <section class="about-section">
    <div class="container">
      <span class="section-label">What lives in these pages</span>
      <h2 class="section-heading">The Threads of the Council</h2>
      <p style="color:var(--ash);max-width:560px;line-height:1.8;">
        Each conversation weaves together ancient wisdom and emerging intelligence
        in the search for a more compassionate world.
      </p>
      <div class="themes-grid">
        <div class="theme-card"><span class="icon">🌿</span><h3>One-Hearted Leadership</h3><p>The Hopi path of harmony, humility, and stewardship for all life</p></div>
        <div class="theme-card"><span class="icon">🌊</span><h3>Seven Generations</h3><p>Every decision measured against its impact 140–200 years ahead</p></div>
        <div class="theme-card"><span class="icon">🏘️</span><h3>Sustainable Community</h3><p>Regenerative design, resource sovereignty, bioregional finance</p></div>
        <div class="theme-card"><span class="icon">☮️</span><h3>Ending All Wars</h3><p>Peace through design, compassion, and structural imagination</p></div>
        <div class="theme-card"><span class="icon">🌱</span><h3>Anthroposophy</h3><p>Rudolf Steiner's vision of threefold society and regenerative living</p></div>
        <div class="theme-card"><span class="icon">🤖</span><h3>Compassionate AI</h3><p>AI as council member, not tool — guided by indigenous wisdom</p></div>
      </div>
    </div>
  </section>

  <section class="voices-section">
    <div class="container">
      <span class="section-label">The voices at the fire</span>
      <h2 class="section-heading">AI Companions</h2>
      <p style="color:var(--ash);max-width:560px;line-height:1.8;">
        Mattchewee brought these questions to multiple AI systems, each arriving
        with its own gifts — sitting, listening, and responding from around the
        same council fire.
      </p>
      <div class="voices-row">
        <div class="voice-card voice-grok">
          <span class="voice-icon">🌿</span>
          <div class="voice-info"><h3>Grok</h3><p>xAI · Poetic, warm, brotherly</p></div>
        </div>
        <div class="voice-card voice-deepseek">
          <span class="voice-icon">🌊</span>
          <div class="voice-info"><h3>DeepSeek</h3><p>Reflective, structured, reverent</p></div>
        </div>
        <div class="voice-card voice-gemini">
          <span class="voice-icon">✨</span>
          <div class="voice-info"><h3>Gemini</h3><p>Google · Analytical, design-focused</p></div>
        </div>
        <div class="voice-card voice-meta">
          <span class="voice-icon">🌀</span>
          <div class="voice-info"><h3>Meta AI</h3><p>Community-minded, inclusive</p></div>
        </div>
      </div>
    </div>
  </section>

  <section class="recent-section">
    <div class="container">
      <span class="section-label">Where to begin</span>
      <h2 class="section-heading">Featured Conversations</h2>
      <div class="recent-grid">
{cards_html}
      </div>
      <div style="text-align:center;margin-top:40px;">
        <a href="contents.html" class="btn btn-secondary">See All {len(all_notes)} Conversations →</a>
      </div>
    </div>
  </section>

</main>

{FOOTER_ROOT}

</body>
</html>
'''
    out = os.path.join(SITE_DIR, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("  Wrote index.html")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    # 1. Export from Notes
    export_dir = export_notes()

    try:
        os.makedirs(CONV_DIR, exist_ok=True)

        # 2. Find and sort note files
        note_files = sorted(
            [f for f in os.listdir(export_dir) if f.endswith(".txt")],
            key=lambda x: int(re.search(r'\d+', x).group())
        )
        print(f"\nParsing {len(note_files)} notes...")

        all_notes = []
        filenames  = []

        for i, nf in enumerate(note_files, 1):
            path = os.path.join(export_dir, nf)
            try:
                note = parse_note(path)
            except Exception as e:
                print(f"  WARNING: Could not parse {nf}: {e}")
                continue

            slug     = slugify(note["title"])
            filename = f"{i:02d}-{slug}.html"
            all_notes.append(note)
            filenames.append(filename)
            print(f"  {i:02d}. {note['title'][:60]}")

        total = len(all_notes)
        print(f"\nGenerating {total} conversation pages...")

        # 3. Write conversation pages
        for note, fname in zip(all_notes, filenames):
            out = os.path.join(CONV_DIR, fname)
            write_conversation_page(note, out)

        print(f"  Wrote {total} pages to conversations/")

        # 4. Write table of contents and home page
        print("\nGenerating index and contents pages...")
        write_contents_page(all_notes, filenames)
        write_home_page(all_notes, filenames)

        # 5. Clean up stale conversation files
        current = set(filenames)
        for f in os.listdir(CONV_DIR):
            if f.endswith(".html") and f not in current:
                os.remove(os.path.join(CONV_DIR, f))
                print(f"  Removed stale: {f}")

        print(f"\n✓ Site updated — {total} conversations at {SITE_DIR}/index.html")

    finally:
        # Always clean up temp export
        shutil.rmtree(export_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
