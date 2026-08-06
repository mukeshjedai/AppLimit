from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from applimit.wiki_store import AzureWikiStore

_TREE_VERSION = 1
_MAX_FOLDER_DEPTH = 12
_MAX_NAME_LEN = 120


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _empty_tree() -> dict[str, Any]:
    return {"version": _TREE_VERSION, "folders": [], "links": []}


def _normalize_name(name: str) -> str:
    n = (name or "").strip()
    if not n:
        raise ValueError("Name is required.")
    if len(n) > _MAX_NAME_LEN:
        raise ValueError(f"Name must be at most {_MAX_NAME_LEN} characters.")
    return n


def _normalize_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        raise ValueError("URL is required.")
    if u.startswith("/"):
        return u
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must start with /, http://, or https://.")
    return u


def _folder_depth(folders: list[dict[str, Any]], folder_id: str) -> int:
    by_id = {f["id"]: f for f in folders}
    depth = 0
    cur = folder_id
    seen: set[str] = set()
    while cur:
        if cur in seen:
            raise ValueError("Folder hierarchy is circular.")
        seen.add(cur)
        folder = by_id.get(cur)
        if not folder:
            break
        depth += 1
        cur = folder.get("parent_id") or ""
    return depth


class WikiFolderStore:
    """Persist wiki folder tree (folders + links) alongside page storage."""

    def __init__(self, backend: str) -> None:
        self._backend = backend
        if backend == "azure":
            self._azure = AzureWikiStore()
        else:
            base = os.environ.get("APPLIMIT_LOCAL_WIKI_DIR", "").strip()
            self._local_dir = Path(base) if base else Path.cwd() / "wiki-data"

    def _local_tree_path(self) -> Path:
        d = self._local_dir / "folders"
        d.mkdir(parents=True, exist_ok=True)
        return d / "tree.json"

    def _azure_blob_name(self) -> str:
        return "folders/tree.json"

    def load(self) -> dict[str, Any]:
        if self._backend == "azure":
            cc = self._azure._container_client()
            bc = cc.get_blob_client(self._azure_blob_name())
            try:
                raw = bc.download_blob().readall()
                data = json.loads(raw.decode("utf-8"))
            except Exception:
                return _empty_tree()
        else:
            p = self._local_tree_path()
            if not p.is_file():
                return _empty_tree()
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return _empty_tree()
        if not isinstance(data, dict):
            return _empty_tree()
        data.setdefault("version", _TREE_VERSION)
        data.setdefault("folders", [])
        data.setdefault("links", [])
        if not isinstance(data["folders"], list):
            data["folders"] = []
        if not isinstance(data["links"], list):
            data["links"] = []
        return data

    def save(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        if self._backend == "azure":
            cc = self._azure._container_client()
            bc = cc.get_blob_client(self._azure_blob_name())
            bc.upload_blob(payload, overwrite=True, content_type="application/json")
        else:
            self._local_tree_path().write_bytes(payload)

    def _find_folder(self, data: dict[str, Any], folder_id: str) -> dict[str, Any] | None:
        for f in data["folders"]:
            if f.get("id") == folder_id:
                return f
        return None

    def create_folder(self, name: str, parent_id: str | None = None) -> dict[str, Any]:
        data = self.load()
        title = _normalize_name(name)
        pid = (parent_id or "").strip() or None
        if pid and not self._find_folder(data, pid):
            raise ValueError("Parent folder not found.")
        if pid and _folder_depth(data["folders"], pid) >= _MAX_FOLDER_DEPTH:
            raise ValueError(f"Maximum folder depth is {_MAX_FOLDER_DEPTH}.")
        folder = {
            "id": uuid.uuid4().hex[:12],
            "name": title,
            "parent_id": pid,
            "created_at": _now_iso(),
        }
        data["folders"].append(folder)
        self.save(data)
        return folder

    def create_link(
        self,
        folder_id: str,
        title: str,
        url: str,
        wiki_page_id: str | None = None,
    ) -> dict[str, Any]:
        data = self.load()
        fid = folder_id.strip()
        if not self._find_folder(data, fid):
            raise ValueError("Folder not found.")
        link = {
            "id": uuid.uuid4().hex[:12],
            "folder_id": fid,
            "title": _normalize_name(title),
            "url": _normalize_url(url),
            "wiki_page_id": (wiki_page_id or "").strip() or None,
            "created_at": _now_iso(),
        }
        data["links"].append(link)
        self.save(data)
        return link

    def delete_folder(self, folder_id: str) -> None:
        data = self.load()
        fid = folder_id.strip()
        if not self._find_folder(data, fid):
            raise ValueError("Folder not found.")
        to_remove = {fid}
        changed = True
        while changed:
            changed = False
            for f in data["folders"]:
                if f.get("parent_id") in to_remove and f.get("id") not in to_remove:
                    to_remove.add(f["id"])
                    changed = True
        data["folders"] = [f for f in data["folders"] if f.get("id") not in to_remove]
        data["links"] = [l for l in data["links"] if l.get("folder_id") not in to_remove]
        self.save(data)

    def delete_link(self, link_id: str) -> None:
        data = self.load()
        lid = link_id.strip()
        before = len(data["links"])
        data["links"] = [l for l in data["links"] if l.get("id") != lid]
        if len(data["links"]) == before:
            raise ValueError("Link not found.")
        self.save(data)

    def build_tree(self) -> list[dict[str, Any]]:
        data = self.load()
        folders = data["folders"]
        links = data["links"]
        by_parent: dict[str | None, list[dict[str, Any]]] = {}
        for f in folders:
            parent = f.get("parent_id") or None
            by_parent.setdefault(parent, []).append(f)
        for group in by_parent.values():
            group.sort(key=lambda x: (x.get("name") or "").lower())

        links_by_folder: dict[str, list[dict[str, Any]]] = {}
        for link in links:
            fid = link.get("folder_id")
            if fid:
                links_by_folder.setdefault(fid, []).append(link)
        for group in links_by_folder.values():
            group.sort(key=lambda x: (x.get("title") or "").lower())

        def nest(parent_id: str | None) -> list[dict[str, Any]]:
            nodes = []
            for folder in by_parent.get(parent_id, []):
                fid = folder["id"]
                nodes.append(
                    {
                        **folder,
                        "children": nest(fid),
                        "links": links_by_folder.get(fid, []),
                    }
                )
            return nodes

        return nest(None)

    def list_flat(self) -> list[dict[str, str]]:
        """Flat list of folders with path labels for dropdowns (e.g. Physics / Calculus)."""

        def walk(nodes: list[dict[str, Any]], prefix: str = "") -> list[dict[str, str]]:
            out: list[dict[str, str]] = []
            for node in nodes:
                name = node.get("name") or "Folder"
                label = name if not prefix else f"{prefix} / {name}"
                out.append({"id": node["id"], "label": label})
                out.extend(walk(node.get("children") or [], label))
            return out

        return walk(self.build_tree())


def get_wiki_folder_store(allow_local: bool = True) -> tuple[WikiFolderStore, str]:
    try:
        AzureWikiStore()
        return WikiFolderStore("azure"), "azure"
    except Exception:
        if allow_local:
            return WikiFolderStore("local"), "local"
        raise
