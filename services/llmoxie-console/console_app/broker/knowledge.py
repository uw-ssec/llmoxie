"""Reading an organization's knowledge from the hub, for its leads to look at in the console.

The broker has a Keycloak client of its own for this, console-knowledge, whose token the hub lets read
every organization's bundle and write none of them (the hub's OAuth settings, role knowledge-reader). Which
organization a person may look at is decided before this is called, as for every broker operation.

A bundle is a set of Markdown files. A concept is one file: a header of `key: value` lines, then text.
A link from one concept's text to another concept's file is an edge of the knowledge graph.
"""

import os
import posixpath
import re

import httpx

from . import keycloak

_CLIENT_ID = os.environ["KNOWLEDGE_READER_CLIENT_ID"]
_CLIENT_SECRET = os.environ["KNOWLEDGE_READER_CLIENT_SECRET"]
_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)(?::\s*(.*))?")


class HubError(Exception):
    def __init__(self, operation: str, status: int):
        super().__init__(f"knowledge hub {operation} failed with HTTP {status}")
        self.operation, self.status = operation, status


def _files(slug: str) -> dict[str, dict]:
    """Every file of the organization's bundle: path -> {content, version}. Empty if nothing was written yet."""
    with httpx.Client(timeout=30) as http:
        token = http.post(keycloak.TOKEN_URL, data={"grant_type": "client_credentials", "client_id": _CLIENT_ID,
                                                    "client_secret": _CLIENT_SECRET})
        if token.status_code != 200:
            raise HubError("sign-in", token.status_code)
        response = http.get(f"{keycloak.HUB_URL}/v1/snapshot", params={"bundle": keycloak.bundle(slug)},
                            headers={"Authorization": f"Bearer {token.json()['access_token']}"})
    if response.status_code == 404:
        return {}
    if response.status_code != 200:
        raise HubError("snapshot", response.status_code)
    return response.json().get("files", {})


def _is_concept(path: str) -> bool:
    """The hub's own rule: a Markdown file that is not an index, a log, AGENTS.md or under a dot folder."""
    parts = path.split("/")
    name = parts[-1]
    return (name.endswith(".md") and name not in ("index.md", "log.md") and path.lower() != "agents.md"
            and not any(part.startswith(".") or part == "node_modules" for part in parts))


def _scalar(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    return text


def _split_header(content: str) -> tuple[dict, str]:
    """The header's fields and the text after it. Reads the plain shapes the hub writes; anything else is kept as text."""
    if not content.startswith("---"):
        return {}, content
    head, found, body = content[3:].partition("\n---")
    if not found:
        return {}, content
    fields: dict = {}
    key = None
    for line in head.splitlines():
        item = re.match(r"\s+-\s+(.*)$", line)
        if item and key:                                   # a list written one item per line
            if not isinstance(fields.get(key), list):
                fields[key] = []
            fields[key].append(_scalar(item.group(1)))
            continue
        pair = re.match(r"([A-Za-z_][\w.-]*):\s*(.*)$", line)
        if not pair:
            continue
        key, value = pair.group(1), pair.group(2).strip()
        if value.startswith("[") and value.endswith("]"):
            fields[key] = [_scalar(v) for v in value[1:-1].split(",") if v.strip()]
        elif value.startswith("{") and value.endswith("}"):
            fields[key] = {k: _scalar(v) for k, v in re.findall(r"([\w.-]+):\s*(\"[^\"]*\"|'[^']*'|[^,}]*)", value[1:-1])}
        else:
            fields[key] = _scalar(value)
    return fields, body.split("\n", 1)[1] if "\n" in body else ""


def bundle_view(slug: str) -> dict:
    """The organization's concepts, the links between them, and the bundle's own change log."""
    files = _files(slug)
    concepts: dict[str, dict] = {}
    for path, file in sorted(files.items()):
        if not _is_concept(path):
            continue
        fields, body = _split_header(file.get("content", ""))
        generated = fields.get("generated") if isinstance(fields.get("generated"), dict) else {}
        tags = fields.get("tags")
        concept_id = path[:-3]
        concepts[concept_id] = {
            "id": concept_id, "type": str(fields.get("type") or "concept"),
            "title": str(fields.get("title") or concept_id), "description": str(fields.get("description") or ""),
            "status": str(fields.get("status") or ""), "tags": tags if isinstance(tags, list) else ([tags] if tags else []),
            "written_at": generated.get("at", ""), "version": file.get("version"), "body": body.strip("\n"),
        }
    edges: dict[tuple[str, str], str] = {}
    for concept_id, concept in concepts.items():
        folder = posixpath.dirname(concept_id)
        for _text, href, note in _LINK.findall(concept["body"]):
            href = href.split("#")[0]
            if "://" in href or not href.endswith(".md"):
                continue
            target = posixpath.normpath(posixpath.join(folder, href))[:-3]
            if target in concepts and target != concept_id:
                key = (concept_id, target)
                edges[key] = edges.get(key) or note.strip()
    return {
        "concepts": list(concepts.values()),
        "edges": [{"source": s, "target": t, "note": note} for (s, t), note in edges.items()],
        "log": files.get("log.md", {}).get("content", ""),
    }
