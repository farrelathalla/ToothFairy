"""LLM + RAG advisory layer.

    graph.run(case) -> {diagnosis_md, recommendation_md, sanity_md}

Two clinical agents (diagnosis, recommendation), each grounded in its own slice of a local
hybrid-retrieval corpus, plus a deterministic consistency check. The whole layer is gated
behind `LLM_ENABLED` + an API key: with either missing every agent returns a deterministic
stub, so the test suite and the offline demo never touch the network.
"""
