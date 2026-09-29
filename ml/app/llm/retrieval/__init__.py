"""Local, offline RAG stack for the advisory layer.

**Contextual Retrieval** + hybrid search + cross-encoder rerank:

    PDF → chunk → contextual blurb from the cheap model (cached to disk)
        ├─ BGE-M3 dense embeddings ─┐
        └─ BM25 sparse index ───────┴─ RRF fuse → bge-reranker-v2-m3 → top-N

The embedder and reranker are open-weight models that run **locally**, so no patient-derived
query text leaves the machine during retrieval; only the final clinical prompt goes to the
model provider.

Everything heavy (torch, transformers) is imported **inside functions**, never at module
import, so `import app.llm.retrieval` stays free for the service's unit tests.
"""
