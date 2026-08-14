from __future__ import annotations

import os
import time
import uuid
import structlog
from typing import Any, Callable

from src.evaluation import RetrievalEvaluator, evaluate_retrieval
from src.models import BenchmarkConfig, BenchmarkRun, RetrievalMetrics

logger = structlog.get_logger()

ENABLE_RETRIEVAL_BENCHMARK = os.getenv("ENABLE_RETRIEVAL_BENCHMARK", "false").lower() == "true"
CONFIDENCE_MODE = os.getenv("CONFIDENCE_MODE", "calibrated")
MAX_RETRIEVAL_CANDIDATES = int(os.getenv("MAX_RETRIEVAL_CANDIDATES", "30"))


class BenchmarkRunner:
    def __init__(self, vectorstore, evaluator: RetrievalEvaluator | None = None):
        self.vectorstore = vectorstore
        self.evaluator = evaluator or RetrievalEvaluator(vectorstore)
        self._runs: list[BenchmarkRun] = []

    def run_comparison(
        self,
        dimensions: list[str],
        configs: list[BenchmarkConfig],
        retrieval_fn: Callable,
        relevant_ids_map: dict[str, set[str]] | None = None,
    ) -> list[BenchmarkRun]:
        runs: list[BenchmarkRun] = []

        for config in configs:
            run = self._run_single_config(
                config=config,
                dimensions=dimensions,
                retrieval_fn=retrieval_fn,
                relevant_ids_map=relevant_ids_map,
            )
            runs.append(run)

        self._runs.extend(runs)
        self._log_comparison(runs)
        return runs

    def _run_single_config(
        self,
        config: BenchmarkConfig,
        dimensions: list[str],
        retrieval_fn: Callable,
        relevant_ids_map: dict[str, set[str]] | None = None,
    ) -> BenchmarkRun:
        run_id = str(uuid.uuid4())[:8]
        t0 = time.time()

        per_dimension: dict[str, RetrievalMetrics] = {}
        all_false_positives = 0
        all_false_negatives = 0
        all_total_retrieved = 0
        all_total_relevant = 0

        for dim in dimensions:
            result = retrieval_fn(dim, config)
            chunk_ids = [c.get("chunk_id", "") for c in result.document_chunks + result.framework_chunks]
            relevant = (relevant_ids_map or {}).get(dim, set(chunk_ids[:3]))

            metrics = evaluate_retrieval(
                retrieved_chunk_ids=chunk_ids,
                relevant_chunk_ids=relevant,
                total_retrieved=len(chunk_ids),
                duplicate_count=len(chunk_ids) - len(set(chunk_ids)),
                diversity_count=len({c.get("source_framework", "") for c in result.document_chunks + result.framework_chunks}),
                similarity_scores=[
                    c.get("reranker_score") or c.get("rrf_score") or c.get("similarity_score") or 0.0
                    for c in result.document_chunks + result.framework_chunks
                ],
            )
            per_dimension[dim] = metrics

        agg = self._aggregate_metrics(list(per_dimension.values()))
        total_time = time.time() - t0

        run = BenchmarkRun(
            run_id=run_id,
            config=config,
            per_dimension=per_dimension,
            aggregate=agg,
            total_latency=round(total_time, 3),
        )

        logger.info(
            "benchmark_run_complete",
            run_id=run_id,
            config=config.name,
            dimensions=len(dimensions),
            latency=round(total_time, 3),
            precision=agg.precision_at_5,
            recall=agg.recall_at_5,
        )

        return run

    def _aggregate_metrics(self, metrics_list: list[RetrievalMetrics]) -> RetrievalMetrics:
        if not metrics_list:
            return RetrievalMetrics()

        agg = RetrievalMetrics()
        fields = [
            "precision_at_1", "precision_at_3", "precision_at_5", "precision_at_10",
            "recall_at_3", "recall_at_5", "recall_at_10",
            "mrr", "ndcg_at_5", "ndcg_at_10",
            "coverage_recall", "evidence_diversity", "duplicate_rate",
            "avg_retrieval_similarity", "framework_retrieval_accuracy",
            "policy_retrieval_accuracy", "false_positive_rate", "false_negative_rate",
        ]
        for field in fields:
            vals = [getattr(m, field) for m in metrics_list]
            valid = [v for v in vals if v is not None]
            if valid:
                setattr(agg, field, round(sum(valid) / len(valid), 4))

        return agg

    def _log_comparison(self, runs: list[BenchmarkRun]):
        if len(runs) < 2:
            return
        logger.info("benchmark_comparison", num_configs=len(runs))
        for run in runs:
            logger.info(
                "config_result",
                config=run.config.name,
                p5=run.aggregate.precision_at_5,
                r5=run.aggregate.recall_at_5,
                mrr=run.aggregate.mrr,
                latency=run.total_latency,
            )

    def get_runs(self) -> list[BenchmarkRun]:
        return self._runs

    def get_last_run(self) -> BenchmarkRun | None:
        return self._runs[-1] if self._runs else None
