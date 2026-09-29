"""Evaluation harness for the RAG stack and the clinical agents.

    cd ml
    python -m evals.run_evals              # writes ../docs/EVAL_REPORT.md

Retrieval metrics need no API key. Generation metrics need `OPENAI_API_KEY`,
`LLM_ENABLED=1`, `RAG_ENABLED=1` and a built index.
"""
