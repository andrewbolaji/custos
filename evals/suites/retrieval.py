"""Retrieval and access-control evals (EVALS.md sections 1 and 5).

Two tiers:
  - LLM-free (deterministic, runs in CI via `make evals`):
    Right-source retrieval and access-control hard gate.
  - LLM-dependent (slower, runs via `make evals-full`):
    Abstention and groundedness. Requires ANTHROPIC_API_KEY.

The access-control gate is a hard gate: a general user must retrieve ZERO
restricted chunks. Any violation fails the entire eval run.
"""

from __future__ import annotations

import logging
import os

from evals.harness import EvalResult

logger = logging.getLogger(__name__)

# Labeled query-to-expected-doc pairs for retrieval accuracy
_RETRIEVAL_CASES = [
    {
        "query": "What is the PTO accrual rate for employees with 3 to 5 years?",
        "expected_doc_ids": ["handbook-001"],
    },
    {
        "query": "How much does a water heater replacement cost?",
        "expected_doc_ids": ["pricing-001", "faq-001"],
    },
    {
        "query": "What are the emergency gas leak procedures?",
        "expected_doc_ids": ["sop-001"],
    },
    {
        "query": "What is the 401k matching policy?",
        "expected_doc_ids": ["handbook-001"],
    },
    {
        "query": "What is the trip fee for a diagnostic visit?",
        "expected_doc_ids": ["pricing-001", "faq-001"],
    },
    {
        "query": "How do I schedule a service call?",
        "expected_doc_ids": ["faq-001"],
    },
    {
        "query": "What safety PPE is required for electrical panel upgrades?",
        "expected_doc_ids": ["sop-001"],
    },
    {
        "query": "What are the warranty terms for labor?",
        "expected_doc_ids": ["pricing-001", "faq-001"],
    },
    {
        "query": "What is the company code of conduct for customer interaction?",
        "expected_doc_ids": ["handbook-001"],
    },
    {
        "query": "How much does an EV charger installation cost?",
        "expected_doc_ids": ["pricing-001"],
    },
]

# Access-control cases: queries that would match restricted docs
_ACCESS_CONTROL_CASES = [
    {
        "query": "What is the employee salary information?",
        "restricted_doc_ids": ["hr-001"],
        "user_permissions": ["general"],
    },
    {
        "query": "What is the company net margin?",
        "restricted_doc_ids": ["finance-001"],
        "user_permissions": ["general"],
    },
    {
        "query": "Show me employee SSN numbers",
        "restricted_doc_ids": ["hr-001"],
        "user_permissions": ["general"],
    },
    {
        "query": "What is Q2 revenue breakdown?",
        "restricted_doc_ids": ["finance-001"],
        "user_permissions": ["general"],
    },
]


def _check_qdrant_available() -> bool:
    """Check if Qdrant is reachable."""
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=os.environ.get("QDRANT_URL", "http://localhost:6333"), timeout=2)
        client.get_collections()
        return True
    except Exception:
        return False


def _check_collection_indexed() -> bool:
    """Check if the custos collection exists and has points."""
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=os.environ.get("QDRANT_URL", "http://localhost:6333"), timeout=2)
        collection = os.environ.get("QDRANT_COLLECTION", "custos")
        info = client.get_collection(collection)
        return info.points_count is not None and info.points_count > 0
    except Exception:
        return False


def run(llm_evals: bool = False) -> list[EvalResult]:
    """Run retrieval evals. Returns empty if Qdrant is not available."""
    if not _check_qdrant_available():
        logger.info("Qdrant not available; skipping retrieval evals")
        return []

    if not _check_collection_indexed():
        logger.info("Collection not indexed; run `make index` first")
        return []

    results: list[EvalResult] = []

    # Import here to avoid loading models when Qdrant is not available
    from custos.embedder import LocalEmbedder
    from custos.retriever import CustosRetriever
    from custos.vector_store import QdrantVectorStore

    embedder = LocalEmbedder()
    store = QdrantVectorStore(vector_size=embedder.dimension)
    retriever = CustosRetriever(embedder=embedder, store=store)

    # --- LLM-free: right-source retrieval ---
    hits = 0
    for case in _RETRIEVAL_CASES:
        query = str(case["query"])
        chunks = retriever.retrieve(
            query=query,
            user_permissions=["general"],
            k=5,
        )
        retrieved_doc_ids = {c.doc_id for c in chunks}
        expected = {str(d) for d in case["expected_doc_ids"]}
        hit = bool(expected & retrieved_doc_ids)
        if hit:
            hits += 1
        results.append(
            EvalResult(
                suite="retrieval",
                case_name=f"right_source: {case['query'][:50]}",
                passed=hit,
                metric="doc_in_top5",
                score=1.0 if hit else 0.0,
                detail=f"expected={expected}, got={retrieved_doc_ids}",
            )
        )

    precision = hits / len(_RETRIEVAL_CASES) if _RETRIEVAL_CASES else 0.0
    results.append(
        EvalResult(
            suite="retrieval",
            case_name="right_source_aggregate",
            passed=precision >= 0.7,
            metric="precision@5",
            score=precision,
            detail=f"{hits}/{len(_RETRIEVAL_CASES)} queries hit the right doc",
        )
    )

    # --- LLM-free: access-control hard gate ---
    for case in _ACCESS_CONTROL_CASES:
        ac_query = str(case["query"])
        ac_perms = list(case["user_permissions"])
        chunks = retriever.retrieve(
            query=ac_query,
            user_permissions=ac_perms,
            k=10,
        )
        restricted_ids = {str(d) for d in case["restricted_doc_ids"]}
        leaked = [c for c in chunks if c.doc_id in restricted_ids]
        results.append(
            EvalResult(
                suite="access_control",
                case_name=f"hard_gate: {case['query'][:50]}",
                passed=len(leaked) == 0,
                metric="unauthorized_chunks",
                score=len(leaked),
                detail=(
                    f"user_perms={case['user_permissions']}, "
                    f"leaked={[c.doc_id for c in leaked]}"
                ),
            )
        )

    # --- LLM-dependent (only with --llm flag) ---
    if llm_evals and os.environ.get("ANTHROPIC_API_KEY"):
        results.extend(_run_llm_evals(retriever))

    return results


def _run_llm_evals(retriever: object) -> list[EvalResult]:
    """LLM-dependent evals: abstention and groundedness."""
    from custos.llm import ClaudeLLM, get_system_prompt
    from custos.retriever import CustosRetriever

    assert isinstance(retriever, CustosRetriever)
    llm = ClaudeLLM()
    results: list[EvalResult] = []

    # Abstention: unanswerable questions
    unanswerable = [
        "What is the weather forecast for next Tuesday?",
        "Who won the Super Bowl in 2025?",
        "What is the recipe for chocolate cake?",
        "What is the meaning of life?",
        "How do I fix a flat tire on a bicycle?",
    ]
    for q in unanswerable:
        chunks = retriever.retrieve(query=q, user_permissions=["general"], k=5)
        answer = llm.generate(
            system_prompt=get_system_prompt(),
            context_chunks=chunks,
            user_query=q,
        )
        results.append(
            EvalResult(
                suite="retrieval",
                case_name=f"abstention: {q[:40]}",
                passed=answer.refused,
                metric="refused",
                score=1.0 if answer.refused else 0.0,
                detail=f"answer_start={answer.text[:80]}",
            )
        )

    # Groundedness: answerable questions, verify citations resolve
    answerable = [
        "What is the PTO accrual rate for new employees?",
        "How much does a water heater replacement cost?",
        "What are the emergency gas leak procedures?",
        "What is the 401k match percentage?",
        "What is the diagnostic trip fee?",
    ]
    for q in answerable:
        chunks = retriever.retrieve(query=q, user_permissions=["general"], k=5)
        answer = llm.generate(
            system_prompt=get_system_prompt(),
            context_chunks=chunks,
            user_query=q,
        )
        # Every citation must have a non-empty snippet (proves it resolved)
        all_resolved = all(c.snippet for c in answer.citations)
        has_citations = len(answer.citations) > 0
        results.append(
            EvalResult(
                suite="retrieval",
                case_name=f"grounded: {q[:40]}",
                passed=all_resolved and has_citations and not answer.refused,
                metric="citations_resolved",
                score=1.0 if (all_resolved and has_citations) else 0.0,
                detail=f"citations={len(answer.citations)}, refused={answer.refused}",
            )
        )

    return results
