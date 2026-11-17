"""
Minimal line-preserving TOML key editor.

Only what a launcher needs: read or replace one scalar value by its full
dotted path ("input.bindings.port1"), or insert it where TOML allows. Every
other line - comments, ordering, arrays, other tables - stays byte for byte.
Values are written as TOML basic strings or integers.

Handles keys written under a [table] header and dotted keys inside a parent
table (e.g. "bindings.port1 = ..." under [input]). Arrays of tables ([[x]])
are skipped, never edited.
"""

import json
import re

_TABLE_RE = re.compile(r"^\s*\[\s*([^\[\]]+?)\s*\]\s*(#.*)?$")
_ARRAY_TABLE_RE = re.compile(r"^\s*\[\[")
_KEY_RE = re.compile(r"""^\s*((?:[A-Za-z0-9_-]+|"[^"]*"|'[^']*')(?:\s*\.\s*(?:[A-Za-z0-9_-]+|"[^"]*"|'[^']*'))*)\s*=\s*(.*)$""")


def _norm(path):
    parts = re.findall(r"""[A-Za-z0-9_-]+|"[^"]*"|'[^']*'""", path)
    return ".".join(p[1:-1] if p[:1] in "\"'" else p for p in parts)


def _scan(lines):
    """Yield (index, kind, full_path, raw_value) for headers and keys."""
    table = ""
    for i, line in enumerate(lines):
        if _ARRAY_TABLE_RE.match(line):
            table = None                      # inside [[...]]: never matched
            yield i, "header", None, None
            continue
        m = _TABLE_RE.match(line)
        if m:
            table = _norm(m.group(1))
            yield i, "header", table, None
            continue
        m = _KEY_RE.match(line)
        if m and table is not None:
            key = _norm(m.group(1))
            yield i, "key", f"{table}.{key}" if table else key, m.group(2)


def _strip_comment(raw):
    raw = raw.strip()
    if raw[:1] in "\"'":
        quote = raw[0]
        end = raw.find(quote, 1)
        return raw[:end + 1] if end > 0 else raw
    return raw.split("#", 1)[0].strip()


def get(lines, path, default=None):
    """The value at `path` as a Python str/int, or `default`."""
    for _, kind, full, raw in _scan(lines):
        if kind == "key" and full == path:
            value = _strip_comment(raw)
            if value[:1] in "\"'":
                return value[1:-1]
            try:
                return int(value, 0)
            except ValueError:
                return value
    return default


def all_values(lines):
    """{full path: raw value} of every plain key (for searching)."""
    return {full: raw for _, kind, full, raw in _scan(lines) if kind == "key"}


def literal(value):
    return str(value) if isinstance(value, int) else json.dumps(str(value))


def set(lines, path, value):
    """Replace `path` in place, or insert it into the deepest existing table."""
    set_raw(lines, path, literal(value))


def set_raw(lines, path, text):
    """Like set(), with `text` written verbatim (e.g. "true")."""
    entries = list(_scan(lines))
    for i, kind, full, _ in entries:
        if kind == "key" and full == path:
            key_part = lines[i].split("=", 1)[0]
            lines[i] = f"{key_part.rstrip()} = {text}"
            return

    parts = path.split(".")
    headers = [(i, full) for i, kind, full, _ in entries if kind == "header"]
    for cut in range(len(parts) - 1, 0, -1):
        table = ".".join(parts[:cut])
        for n, (i, full) in enumerate(headers):
            if full == table:
                end = headers[n + 1][0] if n + 1 < len(headers) else len(lines)
                while end > i + 1 and not lines[end - 1].strip():
                    end -= 1
                lines.insert(end, f"{'.'.join(parts[cut:])} = {text}")
                return

    # No table to put it in: new [table] at the end
    if lines and lines[-1].strip():
        lines.append("")
    lines.append(f"[{'.'.join(parts[:-1])}]")
    lines.append(f"{parts[-1]} = {text}")
