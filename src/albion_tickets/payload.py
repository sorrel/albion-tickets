"""Reading the embedded data the club's pages carry.

The pages are rendered in the browser from a JavaScript data payload of the
form  a.slug="…";a.mediaType="Article";…;a.articleBody={…rich text…}.
We never execute it: we find our article's object and read its text nodes.
"""
import json
import re

_TOKEN = re.compile(r'nodeType:"([^"]+)"|value:"((?:[^"\\]|\\.)*)"')
_BLOCKS = re.compile(r"^(paragraph|heading-\d|list-item|table-row|hr|blockquote)$")


def unescape(js: str) -> str:
    try:
        return json.loads(f'"{js}"')
    except ValueError:
        return js.replace("\\n", "\n").replace('\\"', '"')


def object_at(s: str, start: int) -> str | None:
    """The {...} literal starting at s[start], bracket-matched, strings respected."""
    if start >= len(s) or s[start] != "{":
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
            if depth == 0:
                return s[start: i + 1]
    return None


def rich_text(obj: str) -> str:
    """Rich-text nodes → plain text, one line per block."""
    out: list[str] = []
    for m in _TOKEN.finditer(obj):
        if m.group(1) is not None:
            if _BLOCKS.match(m.group(1)):
                out.append("\n")
        else:
            out.append(unescape(m.group(2)))
    lines = (ln.strip() for ln in "".join(out).splitlines())
    return "\n".join(ln for ln in lines if ln)


def article_var(s: str, slug: str) -> tuple[str, int] | None:
    """The payload variable holding the article with this slug, and where it is."""
    m = re.search(r'(\w+)\.slug="' + re.escape(slug) + r'";\1\.mediaType="Article"', s)
    return (m.group(1), m.start()) if m else None


def field_after(s: str, var: str, name: str, start: int, limit: int = 200_000) -> str | None:
    m = re.compile(re.escape(var) + r"\." + name + r'="((?:[^"\\]|\\.)*)"').search(s, start, start + limit)
    return unescape(m.group(1)) if m else None
