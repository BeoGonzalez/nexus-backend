"""Publica los dashboards de observability/dashboards en Grafana (el repo es la fuente de verdad).

Uso:
    GRAFANA_URL=https://<stack>.grafana.net GRAFANA_SA_TOKEN=<token> python observability/publish_dashboards.py
    # o bien: python observability/publish_dashboards.py --env-file ../nexus-infrastructure/api.grafana.env

El token es de una service account con rol Editor (Administration > Users and access > Service accounts).
Idempotente: crea la carpeta si falta y sobrescribe cada dashboard por su uid.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

DASHBOARDS_DIR = Path(__file__).parent / "dashboards"
FOLDER_TITLE = "Nexus Digital Store"


class Grafana:
    def __init__(self, url: str, token: str) -> None:
        self.url, self.token = url.rstrip("/"), token

    def _call(self, method: str, path: str, body: dict | None = None):
        req = urllib.request.Request(
            self.url + path,
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                     "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - URL del propio stack de Grafana
            return json.load(resp)

    def get(self, path: str):
        return self._call("GET", path)

    def post(self, path: str, body: dict):
        return self._call("POST", path, body)


def folder_uid(api, title: str) -> str:
    """uid de la carpeta (la crea si no existe).

    Usa la búsqueda y no /api/folders: con permisos por carpeta, /api/folders puede ocultar carpetas en las que
    el service account sí publica, y cada ejecución crearía un duplicado.
    """
    query = urllib.parse.urlencode({"type": "dash-folder", "query": title, "limit": 100})
    for folder in api.get(f"/api/search?{query}"):
        if folder.get("title") == title:
            return folder["uid"]
    return api.post("/api/folders", {"title": title})["uid"]


def payload(dashboard: dict, folder: str) -> dict:
    clean = {k: v for k, v in dashboard.items() if k not in ("id", "version")}
    return {"dashboard": clean, "folderUid": folder, "overwrite": True,
            "message": "Publicado desde el repo nexus-backend (observability/dashboards)"}


def publish_all(api, directory: Path, title: str) -> list[str]:
    folder = folder_uid(api, title)
    published = []
    for path in sorted(directory.glob("*.json")):
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        result = api.post("/api/dashboards/db", payload(dashboard, folder))
        print(f"{dashboard['title']}: {result.get('status')} {result.get('url', '')}")
        published.append(dashboard["uid"])
    return published


def _load_env_file(path: str) -> None:
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--env-file", help="archivo con GRAFANA_URL y GRAFANA_SA_TOKEN (fuera de Git)")
    parser.add_argument("--folder", default=FOLDER_TITLE)
    args = parser.parse_args(argv)
    if args.env_file:
        _load_env_file(args.env_file)
    url, token = os.getenv("GRAFANA_URL", ""), os.getenv("GRAFANA_SA_TOKEN", "")
    if not url or not token:
        print("Faltan GRAFANA_URL y GRAFANA_SA_TOKEN", file=sys.stderr)
        return 1
    publish_all(Grafana(url, token), DASHBOARDS_DIR, args.folder)
    return 0


if __name__ == "__main__":
    sys.exit(main())
