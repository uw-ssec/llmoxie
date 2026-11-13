"""Turns a concept's Markdown into HTML for the knowledge page.

The text was written by members' tools, so it is not trusted: HTML in it is shown as text, images are
not loaded, and a link is kept only if it goes to another concept of the same bundle or to an http(s)
or mailto address. The page inserts the result as it is, so this is where the text is made safe; the
content security policy, which allows no inline script, is the second line if this ever fails.
"""

import posixpath
from urllib.parse import quote

from markdown_it import MarkdownIt

_md = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"]).disable("image")


def _link(href: str, folder: str, concept_ids: set[str]) -> dict | None:
    """The attributes a link keeps, or None for one that leads nowhere the reader should go."""
    if href.lower().startswith(("http://", "https://", "mailto:")):
        return {"href": href, "rel": "noopener noreferrer"}
    path = href.split("#")[0]
    if ":" in path or not path.endswith(".md"):
        return None
    target = posixpath.normpath(posixpath.join(folder, path))[:-3]
    return {"href": f"?concept={quote(target, safe='/')}#concept"} if target in concept_ids else None


def render(text: str, concept_id: str = "", concept_ids: set[str] | None = None) -> str:
    """`concept_id` is the concept the text belongs to; its links to other concepts open them on this page."""
    folder = posixpath.dirname(concept_id)
    tokens = _md.parse(text)
    for token in tokens:
        for child in token.children or []:
            if child.type == "link_open":
                child.attrs = _link(str(child.attrs.get("href", "")), folder, concept_ids or set()) or {}
    return _md.renderer.render(tokens, _md.options, {})
