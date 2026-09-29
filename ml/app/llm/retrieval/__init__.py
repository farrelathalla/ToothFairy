"""Local, offline RAG stack for the advisory layer (PLAN §8.2).

Anthropic **Contextual Retrieval** + hybrid search + cross-encoder rerank:

    PDF → chunk → Haiku contextual blurb (cached)
        ├─ BGE-M3 dense embeddings ─┐
        └─ BM25 sparse index ───────┴─ RRF fuse → bge-reranker-v2-m3 → top-N

Everything heavy (torch, FlagEmbedding) is imported **inside functions**, never at module
import, so `import app.llm.retrieval` stays free for the backend's unit tests.
"""
