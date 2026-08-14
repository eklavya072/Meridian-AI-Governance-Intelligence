from __future__ import annotations

import logging
import os
import sys

import structlog


def setup_logging() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level, logging.INFO),
    )


def log_analysis_run(
    analysis_id: str,
    retrieval_count: int,
    frameworks_queried: list[str],
    similarity_scores: list[float],
    citation_results: list[dict],
    llm_latency: float,
    ragas_metrics: dict | None = None,
    total_processing_time: float = 0.0,
) -> None:
    logger = structlog.get_logger()
    logger.info(
        "analysis_run",
        analysis_id=analysis_id,
        retrieval_count=retrieval_count,
        frameworks_queried=frameworks_queried,
        avg_similarity_score=sum(similarity_scores) / len(similarity_scores)
        if similarity_scores
        else None,
        min_similarity_score=min(similarity_scores) if similarity_scores else None,
        max_similarity_score=max(similarity_scores) if similarity_scores else None,
        citations_total=len(citation_results),
        citations_passed=sum(1 for c in citation_results if c.get("verified", False)),
        citations_failed=sum(1 for c in citation_results if not c.get("verified", False)),
        llm_latency_seconds=llm_latency,
        ragas_metrics=ragas_metrics or {},
        total_processing_time_seconds=total_processing_time,
    )


def log_guardrail_event(
    query: str | None,
    reason: str,
    result: str,
) -> None:
    logger = structlog.get_logger()
    logger.info(
        "guardrail_event",
        query_preview=query[:100] if query else None,
        reason=reason,
        result=result,
    )


def log_upload_rejection(
    filename: str,
    error_type: str,
    error_message: str,
) -> None:
    logger = structlog.get_logger()
    logger.info(
        "upload_rejected",
        filename=filename,
        error_type=error_type,
        error_message=error_message,
    )
