"""Reindexa el catálogo en Pinecone (envoltorio local de `python -m ai_agent_service.cli.reindex_catalog`).

Uso (desde la raíz del monorepo):
    .venv/Scripts/python.exe services/ai-agent-service/scripts/reindex_catalog.py \
        --catalog-url https://<sitio>.execute-api.us-east-1.amazonaws.com/api/v1/catalog [--dry-run]

En EKS lo ejecuta el pipeline dentro del pod del ai-agent después de cada despliegue.
"""

import sys

from ai_agent_service.cli.reindex_catalog import main

if __name__ == "__main__":
    sys.exit(main())
