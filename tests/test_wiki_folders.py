from __future__ import annotations

import pytest

from applimit.wiki_folders import WikiFolderStore


@pytest.fixture
def folder_store(tmp_path, monkeypatch):
    monkeypatch.setenv("APPLIMIT_LOCAL_WIKI_DIR", str(tmp_path))
    return WikiFolderStore("local")


def test_create_folder_and_subfolder(folder_store):
    root = folder_store.create_folder("Physics")
    sub = folder_store.create_folder("Calculus", root["id"])
    tree = folder_store.build_tree()
    assert len(tree) == 1
    assert tree[0]["name"] == "Physics"
    assert len(tree[0]["children"]) == 1
    assert tree[0]["children"][0]["name"] == "Calculus"
    assert sub["parent_id"] == root["id"]


def test_add_link_to_folder(folder_store):
    folder = folder_store.create_folder("Notes")
    link = folder_store.create_link(folder["id"], "Gradient", "/wiki/abc123", "abc123")
    tree = folder_store.build_tree()
    assert len(tree[0]["links"]) == 1
    assert tree[0]["links"][0]["title"] == "Gradient"
    assert link["url"] == "/wiki/abc123"


def test_list_flat_shows_paths(folder_store):
    root = folder_store.create_folder("Physics")
    folder_store.create_folder("Calculus", root["id"])
    flat = folder_store.list_flat()
    assert flat[0]["label"] == "Physics"
    assert flat[1]["label"] == "Physics / Calculus"


def test_delete_folder_removes_children_and_links(folder_store):
    root = folder_store.create_folder("Root")
    sub = folder_store.create_folder("Child", root["id"])
    folder_store.create_link(sub["id"], "Link", "https://example.com")
    folder_store.delete_folder(root["id"])
    assert folder_store.build_tree() == []


def test_rejects_invalid_url(folder_store):
    folder = folder_store.create_folder("X")
    with pytest.raises(ValueError, match="URL"):
        folder_store.create_link(folder["id"], "Bad", "ftp://x.com")
