"""Publicación de los dashboards del repo en Grafana: una carpeta, idempotente, el repo es la fuente de verdad."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "observability" / "publish_dashboards.py"
spec = importlib.util.spec_from_file_location("publish_dashboards", SCRIPT)
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)


class FakeGrafana:
    def __init__(self, folders):
        self.folders, self.posts = list(folders), []

    def get(self, path):
        # La búsqueda ve carpetas que /api/folders oculta (permisos por carpeta del service account).
        assert path.startswith("/api/search?type=dash-folder"), path
        return [{"uid": f["uid"], "title": f["title"], "type": "dash-folder"} for f in self.folders]

    def post(self, path, body):
        self.posts.append((path, body))
        if path == "/api/folders":
            folder = {"uid": "nuevo", "title": body["title"]}
            self.folders.append(folder)
            return folder
        return {"status": "success", "url": f"/d/{body['dashboard']['uid']}"}


def test_reuses_the_folder_when_it_already_exists():
    api = FakeGrafana([{"uid": "x1", "title": "Otra"}, {"uid": "nds", "title": "Nexus Digital Store"}])
    assert publish.folder_uid(api, "Nexus Digital Store") == "nds"
    assert api.posts == []


def test_creates_the_folder_when_missing():
    api = FakeGrafana([])
    assert publish.folder_uid(api, "Nexus Digital Store") == "nuevo"
    assert api.posts == [("/api/folders", {"title": "Nexus Digital Store"})]


def test_payload_overwrites_by_uid_into_the_folder_without_the_numeric_id():
    body = publish.payload({"id": 42, "uid": "nexus-backend", "title": "t", "version": 7}, "nds")
    assert body["folderUid"] == "nds" and body["overwrite"] is True
    assert "id" not in body["dashboard"] and "version" not in body["dashboard"]
    assert body["dashboard"]["uid"] == "nexus-backend"
    assert "repo" in body["message"]


def test_publishes_every_dashboard_of_the_repo():
    api = FakeGrafana([{"uid": "nds", "title": "Nexus Digital Store"}])
    published = publish.publish_all(api, publish.DASHBOARDS_DIR, "Nexus Digital Store")
    uids = sorted(b["dashboard"]["uid"] for p, b in api.posts if p == "/api/dashboards/db")
    assert uids == ["nexus-ai-model", "nexus-backend", "nexus-frontend", "nexus-overview"] == sorted(published)


def test_folder_lookup_uses_search_so_a_rerun_never_duplicates_the_folder():
    api = FakeGrafana([])
    first = publish.folder_uid(api, "Nexus Digital Store")
    second = publish.folder_uid(api, "Nexus Digital Store")
    assert first == second
    assert [p for p, _ in api.posts].count("/api/folders") == 1
