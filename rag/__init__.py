"""RAG layer config + ingestion (Section 5.3).

Indexes a small SEO knowledge base (Google Search Central / web.dev style guidance
summaries bundled under rag/knowledge_base/) into a local Chroma collection. Falls
back to simple keyword retrieval when chromadb is not installed.
"""
from __future__ import annotations

import os
from pathlib import Path

KB_DIR = Path(__file__).resolve().parent / "knowledge_base"
PERSIST_DIR = Path(os.getenv("CHROMA_PERSIST_DIR", str(Path(__file__).resolve().parent.parent / "chroma_db")))
COLLECTION_NAME = "seo_kb"


def ingest_knowledge_base(force: bool = False) -> int:
    """Load .md files from knowledge_base/ into Chroma. Returns number of docs indexed."""
    docs = []
    for path in sorted(KB_DIR.glob("*.md")):
        docs.append({"id": path.stem, "text": path.read_text(encoding="utf-8"), "source": path.name})
    if not docs:
        return 0

    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(PERSIST_DIR))
        existing = [c.name for c in client.list_collections()]
        if COLLECTION_NAME in existing and not force:
            return len(docs)
        if COLLECTION_NAME in existing and force:
            client.delete_collection(COLLECTION_NAME)
        col = client.get_or_create_collection(COLLECTION_NAME)
        col.upsert(
            ids=[d["id"] for d in docs],
            documents=[d["text"] for d in docs],
            metadatas=[{"source": d["source"]} for d in docs],
        )
        return len(docs)
    except Exception:
        # Persist a simple JSON fallback index
        import json
        PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        (PERSIST_DIR / "fallback_kb.json").write_text(
            json.dumps(docs, indent=2), encoding="utf-8"
        )
        return len(docs)


def retrieve(query: str, k: int = 3) -> list[str]:
    """Return up to k relevant guidance snippets for the query."""
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(PERSIST_DIR))
        col = client.get_or_create_collection(COLLECTION_NAME)
        if col.count() == 0:
            ingest_knowledge_base()
        res = col.query(query_texts=[query], n_results=k)
        return list(res.get("documents", [[]])[0])
    except Exception:
        return _keyword_fallback(query, k)


def _keyword_fallback(query: str, k: int) -> list[str]:
    import json
    fallback = PERSIST_DIR / "fallback_kb.json"
    docs = []
    if fallback.exists():
        docs = json.loads(fallback.read_text(encoding="utf-8"))
    else:
        for path in KB_DIR.glob("*.md"):
            docs.append({"text": path.read_text(encoding="utf-8"), "source": path.name})
    q = query.lower().split()
    scored = []
    for d in docs:
        text = d.get("text", "")
        score = sum(1 for w in q if w in text.lower())
        scored.append((score, text[:1200]))
    scored.sort(reverse=True)
    return [t for s, t in scored[:k] if s > 0] or [t for _, t in scored[:k]]
