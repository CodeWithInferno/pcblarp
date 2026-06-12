"""Minimal KiCad s-expression parser / writer.

KiCad files are nested s-expressions of three atom kinds: bare symbols
(`kicad_sch`, `at`, layer names like `F.Cu`), quoted strings, and numbers.
We preserve the original text of bare atoms and numbers (`Sym`) so that
parsed trees round-trip byte-stably enough for KiCad to accept, and keep
quoted strings as plain Python `str`.
"""

from __future__ import annotations

from typing import Iterator, Union

Node = Union["Sym", str, list]


class Sym:
    """A bare (unquoted) atom, numeric or not, preserving its source text."""

    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = str(text)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Sym):
            return self.text == other.text
        if isinstance(other, str):
            return self.text == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.text)

    def __repr__(self) -> str:
        return f"Sym({self.text!r})"

    def __float__(self) -> float:
        return float(self.text)


def parse(text: str) -> list:
    """Parse one top-level s-expression into a nested list tree."""
    tokens = _tokenize(text)
    try:
        first = next(tokens)
    except StopIteration:
        raise ValueError("empty s-expression input") from None
    if first != "(":
        raise ValueError(f"expected '(' at start, got {first!r}")
    tree = _parse_list(tokens)
    return tree


def _tokenize(text: str) -> Iterator[str]:
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
        elif ch in "()":
            yield ch
            i += 1
        elif ch == '"':
            j = i + 1
            buf = []
            while j < n:
                c = text[j]
                if c == "\\" and j + 1 < n:
                    buf.append(text[j : j + 2])
                    j += 2
                elif c == '"':
                    break
                else:
                    buf.append(c)
                    j += 1
            else:
                raise ValueError("unterminated quoted string")
            yield '"' + "".join(buf) + '"'
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n()"':
                j += 1
            yield text[i:j]
            i = j


def _parse_list(tokens: Iterator[str]) -> list:
    out: list = []
    for tok in tokens:
        if tok == "(":
            out.append(_parse_list(tokens))
        elif tok == ")":
            return out
        elif tok.startswith('"'):
            out.append(_unescape(tok[1:-1]))
        else:
            out.append(Sym(tok))
    raise ValueError("unbalanced s-expression: missing ')'")


def _unescape(raw: str) -> str:
    return (
        raw.replace("\\\\", "\x00")
        .replace('\\"', '"')
        .replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace("\x00", "\\")
    )


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )


def dumps(tree: list, indent: int = 0) -> str:
    """Serialize a tree back to KiCad-style s-expression text."""
    pad = "\t" * indent
    # Render leaf-only lists inline, nested lists across lines (KiCad style).
    if not any(isinstance(item, list) for item in tree):
        return pad + "(" + " ".join(_atom(a) for a in tree) + ")"
    parts = [pad + "("]
    head: list[str] = []
    i = 0
    while i < len(tree) and not isinstance(tree[i], list):
        head.append(_atom(tree[i]))
        i += 1
    parts[0] += " ".join(head)
    for item in tree[i:]:
        if isinstance(item, list):
            parts.append(dumps(item, indent + 1))
        else:  # stray atom after lists; keep on its own line
            parts.append("\t" * (indent + 1) + _atom(item))
    parts.append(pad + ")")
    return "\n".join(parts)


def _atom(atom: Node) -> str:
    if isinstance(atom, Sym):
        return atom.text
    if isinstance(atom, str):
        return '"' + _escape(atom) + '"'
    raise TypeError(f"unexpected atom type: {type(atom)!r}")


# ---------------------------------------------------------------------------
# Tree queries
# ---------------------------------------------------------------------------

def tag(node: Node) -> str | None:
    """The leading symbol of a list node, e.g. 'pin' for (pin ...)."""
    if isinstance(node, list) and node and isinstance(node[0], Sym):
        return node[0].text
    return None


def children(node: list, name: str) -> list[list]:
    """All child lists whose tag is `name`."""
    return [c for c in node if isinstance(c, list) and tag(c) == name]


def child(node: list, name: str) -> list | None:
    """First child list whose tag is `name`, or None."""
    for c in node:
        if isinstance(c, list) and tag(c) == name:
            return c
    return None


def atoms(node: list) -> list:
    """Non-list members of a node, excluding the leading tag symbol."""
    rest = node[1:] if tag(node) is not None else node
    return [a for a in rest if not isinstance(a, list)]


def first_atom(node: list | None) -> Node | None:
    if not node:
        return None
    got = atoms(node)
    return got[0] if got else None


def number(node: list | None, index: int = 0, default: float = 0.0) -> float:
    """Nth numeric atom of a node, e.g. number(child(pad, 'at'), 1) -> y."""
    if not node:
        return default
    got = atoms(node)
    if index >= len(got):
        return default
    try:
        return float(got[index])  # Sym defines __float__; str raises
    except (TypeError, ValueError):
        return default


def text_of(node: list | None, index: int = 0, default: str = "") -> str:
    """Nth atom of a node as text (works for Sym and quoted strings)."""
    if not node:
        return default
    got = atoms(node)
    if index >= len(got):
        return default
    atom = got[index]
    return atom.text if isinstance(atom, Sym) else str(atom)
