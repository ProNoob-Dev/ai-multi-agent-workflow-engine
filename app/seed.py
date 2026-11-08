"""Seed the store and the policy vector store from data/seed/.

Idempotent: running it twice does not duplicate anything (policies are
re-indexed from scratch; invoices/vendors are static files read on demand).
"""

import json
import re
from pathlib import Path

from .store import get_store
from .vectorstore import get_vector_store

SEED_DIR = Path(__file__).resolve().parent.parent / "data" / "seed"


def seed_policies() -> int:
    """Index the policy documents (split by ## section) for RAG.
    Idempotent: if the store already has documents, skip re-indexing."""
    store = get_vector_store()
    if store.count() > 0:
        return store.count()
    count = 0
    for path in sorted((SEED_DIR / "policies").glob("*.md")):
        text = path.read_text()
        # Drop the H1 document title line, then split on ## sections.
        text = re.sub(r"^# .+\n", "", text, count=1)
        title = path.stem.replace("-", " ").title()
        sections = re.split(r"\n##\s+", text)
        for section in sections:
            section = section.strip()
            if not section:
                continue
            lines = section.split("\n", 1)
            heading = lines[0].strip()
            body = lines[1].strip() if len(lines) > 1 else section
            doc_id = f"{path.stem}#{heading.lower().replace(' ', '-')}"
            # Index heading + body so section titles are searchable.
            store.add(
                doc_id,
                f"{heading}. {body}",
                {"title": title, "section": heading, "source": path.name},
            )
            count += 1
    return count


def seed_all() -> dict:
    """Seed everything. Returns counts."""
    policy_chunks = seed_policies()
    vendors = json.loads((SEED_DIR / "vendors.json").read_text())
    invoices = json.loads((SEED_DIR / "invoices.json").read_text())
    store = get_store()
    store.put("meta", "seeded", {"vendors": len(vendors), "invoices": len(invoices)})
    return {
        "vendors": len(vendors),
        "invoices": len(invoices),
        "policy_chunks": policy_chunks,
    }


if __name__ == "__main__":
    print(seed_all())
