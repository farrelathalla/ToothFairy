"""Evaluation harness for the RAG + diagnosis agent (PLAN §8.4).

    cd backend
    python -m evals.run_evals              # writes ../EVAL_REPORT.md

Retrieval metrics need no API key. Generation metrics need `ANTHROPIC_API_KEY`,
`LLM_ENABLED=1`, `RAG_ENABLED=1` and a built index.
"""
