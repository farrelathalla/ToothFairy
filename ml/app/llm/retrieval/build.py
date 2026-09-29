"""One-shot index build.

    cd backend
    LLM_ENABLED=1 python -m app.llm.retrieval.build            # all 23 docs
    LLM_ENABLED=1 python -m app.llm.retrieval.build 1 2 3      # only these doc ids

Needs `OPENAI_API_KEY` + `LLM_ENABLED=1` for the contextual blurbs (cached to disk, so a
re-run is nearly free) and the BAAI/bge-m3 weights for the dense vectors. Without the key the
build still works — it just indexes bare chunks and warns.
"""
from __future__ import annotations

import logging
import sys

from ...config import settings
from . import index


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    doc_ids = argv or None
    print(f"building index -> {settings.rag_index_dir}")
    meta = index.build(doc_ids)
    print(
        f"done: {meta['n_chunks']} chunks from {meta['n_docs']} docs, "
        f"dim={meta['dim']} ({meta['embed_model']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
