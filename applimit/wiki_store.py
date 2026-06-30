from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _normalize_section_key(section_key: str) -> str:
    s = str(section_key or "").strip()
    if not s or len(s) > 128:
        raise ValueError("invalid section_key")
    return s


def _coerce_read_counts_blob(data: Any) -> dict[str, int]:
    if isinstance(data, dict) and "counts" in data:
        data = data.get("counts")
    if not isinstance(data, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in data.items():
        ks = str(k).strip()
        if not ks or len(ks) > 128:
            continue
        try:
            iv = int(v)
        except (TypeError, ValueError):
            continue
        if iv < 0:
            iv = 0
        out[ks] = iv
    return out


def _blob_service_client():
    """Azure Blob client: connection string if set, else account URL + DefaultAzureCredential."""
    try:
        from azure.storage.blob import BlobServiceClient
    except Exception as e:
        raise RuntimeError(
            "Azure SDK missing. Install azure-identity and azure-storage-blob."
        ) from e

    conn = (
        os.environ.get("APPLIMIT_AZURE_STORAGE_CONNECTION_STRING")
        or os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        or ""
    ).strip()
    if conn:
        return BlobServiceClient.from_connection_string(conn)

    account = (
        os.environ.get("APPLIMIT_AZURE_STORAGE_ACCOUNT")
        or os.environ.get("AZURE_STORAGE_ACCOUNT")
        or ""
    ).strip()
    if not account:
        raise RuntimeError(
            "Set APPLIMIT_AZURE_STORAGE_CONNECTION_STRING (or AZURE_STORAGE_CONNECTION_STRING), "
            "or APPLIMIT_AZURE_STORAGE_ACCOUNT with Azure credentials "
            "(DefaultAzureCredential: managed identity on Azure, az login / env locally)."
        )

    account_url = f"https://{account}.blob.core.windows.net"
    try:
        from azure.identity import DefaultAzureCredential

        cred = DefaultAzureCredential()
    except Exception as e:
        raise RuntimeError(
            "Could not create Azure credentials. Install azure-identity and sign in (e.g. az login), "
            "or use APPLIMIT_AZURE_STORAGE_CONNECTION_STRING."
        ) from e
    return BlobServiceClient(account_url=account_url, credential=cred)


class AzureWikiStore:
    def __init__(self) -> None:
        self._service = _blob_service_client()
        container = os.environ.get("APPLIMIT_AZURE_WIKI_CONTAINER", "applimit-wiki").strip()
        self._container = container or "applimit-wiki"

    def _container_client(self):
        cc = self._service.get_container_client(self._container)
        try:
            cc.create_container()
        except Exception:
            pass
        return cc

    def save_page(self, page: dict[str, Any]) -> dict[str, Any]:
        page_id = str(page.get("id") or uuid.uuid4().hex[:14])
        page["id"] = page_id
        page.setdefault("created_at", _now_iso())

        blob_name = f"pages/{page_id}.json"
        payload = json.dumps(page, ensure_ascii=False).encode("utf-8")
        cc = self._container_client()
        bc = cc.get_blob_client(blob_name)
        bc.upload_blob(payload, overwrite=True, content_type="application/json")
        return page

    def get_page(self, page_id: str) -> dict[str, Any] | None:
        cc = self._container_client()
        blob_name = f"pages/{page_id}.json"
        bc = cc.get_blob_client(blob_name)
        try:
            raw = bc.download_blob().readall()
        except Exception:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    def search(self, query: str = "", limit: int = 25) -> list[dict[str, Any]]:
        cc = self._container_client()
        q = (query or "").strip().lower()
        out: list[dict[str, Any]] = []
        for blob in cc.list_blobs(name_starts_with="pages/"):
            bc = cc.get_blob_client(blob.name)
            try:
                raw = bc.download_blob().readall()
                page = json.loads(raw.decode("utf-8"))
            except Exception:
                continue
            hay = " ".join(
                [
                    str(page.get("title", "")),
                    str(page.get("video_id", "")),
                    str(page.get("body_raw", "")),
                    " ".join(page.get("terminologies", []) or []),
                    " ".join(page.get("important_points", []) or []),
                ]
            ).lower()
            if q and q not in hay:
                continue
            summ = (page.get("important_points") or [""])[0]
            if not summ and page.get("page_type") == "manual":
                br = str(page.get("body_raw", "")).strip()
                summ = (br[:160] + "…") if len(br) > 160 else br
            out.append(
                {
                    "id": page.get("id"),
                    "title": page.get("title") or f"Wiki {page.get('id', '')}",
                    "video_id": page.get("video_id", ""),
                    "page_type": page.get("page_type", ""),
                    "created_at": page.get("created_at", ""),
                    "summary": summ,
                }
            )
            if len(out) >= limit:
                break
        out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return out[:limit]

    def _read_progress_blob_name(self, page_id: str) -> str:
        return f"read-progress/{page_id}.json"

    def get_section_read_counts(self, page_id: str) -> dict[str, int]:
        cc = self._container_client()
        bc = cc.get_blob_client(self._read_progress_blob_name(page_id))
        try:
            raw = bc.download_blob().readall()
        except Exception:
            return {}
        try:
            return _coerce_read_counts_blob(json.loads(raw.decode("utf-8")))
        except Exception:
            return {}

    def increment_section_read_count(self, page_id: str, section_key: str) -> int:
        sk = _normalize_section_key(section_key)
        counts = dict(self.get_section_read_counts(page_id))
        counts[sk] = counts.get(sk, 0) + 1
        n = counts[sk]
        payload = json.dumps({"counts": counts}, ensure_ascii=False).encode("utf-8")
        cc = self._container_client()
        bc = cc.get_blob_client(self._read_progress_blob_name(page_id))
        bc.upload_blob(payload, overwrite=True, content_type="application/json")
        return n


class LocalWikiStore:
    def __init__(self) -> None:
        base = os.environ.get("APPLIMIT_LOCAL_WIKI_DIR", "").strip()
        if base:
            self._dir = Path(base)
        else:
            self._dir = Path.cwd() / "wiki-data"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, page_id: str) -> Path:
        return self._dir / f"{page_id}.json"

    def _read_progress_path(self, page_id: str) -> Path:
        d = self._dir / "read-progress"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{page_id}.json"

    def get_section_read_counts(self, page_id: str) -> dict[str, int]:
        p = self._read_progress_path(page_id)
        if not p.is_file():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return _coerce_read_counts_blob(data)

    def increment_section_read_count(self, page_id: str, section_key: str) -> int:
        sk = _normalize_section_key(section_key)
        counts = dict(self.get_section_read_counts(page_id))
        counts[sk] = counts.get(sk, 0) + 1
        n = counts[sk]
        p = self._read_progress_path(page_id)
        p.write_text(json.dumps({"counts": counts}, ensure_ascii=False), encoding="utf-8")
        return n

    def save_page(self, page: dict[str, Any]) -> dict[str, Any]:
        page_id = str(page.get("id") or uuid.uuid4().hex[:14])
        page["id"] = page_id
        page.setdefault("created_at", _now_iso())
        p = self._path(page_id)
        p.write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
        return page

    def get_page(self, page_id: str) -> dict[str, Any] | None:
        p = self._path(page_id)
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def search(self, query: str = "", limit: int = 25) -> list[dict[str, Any]]:
        q = (query or "").strip().lower()
        out: list[dict[str, Any]] = []
        for p in sorted(self._dir.glob("*.json"), reverse=True):
            try:
                page = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            hay = " ".join(
                [
                    str(page.get("title", "")),
                    str(page.get("video_id", "")),
                    str(page.get("body_raw", "")),
                    " ".join(page.get("terminologies", []) or []),
                    " ".join(page.get("important_points", []) or []),
                ]
            ).lower()
            if q and q not in hay:
                continue
            summ = (page.get("important_points") or [""])[0]
            if not summ and page.get("page_type") == "manual":
                br = str(page.get("body_raw", "")).strip()
                summ = (br[:160] + "…") if len(br) > 160 else br
            out.append(
                {
                    "id": page.get("id"),
                    "title": page.get("title") or f"Wiki {page.get('id', '')}",
                    "video_id": page.get("video_id", ""),
                    "page_type": page.get("page_type", ""),
                    "created_at": page.get("created_at", ""),
                    "summary": summ,
                }
            )
            if len(out) >= limit:
                break
        out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return out[:limit]
