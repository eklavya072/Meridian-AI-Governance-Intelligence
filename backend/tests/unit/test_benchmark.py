import pytest

from src.benchmark import BenchmarkConfig, BenchmarkRunner
from src.evaluation import RetrievalEvaluator
from src.models import RetrievalMetrics


class MockVectorstore:
    def __init__(self):
        pass


def test_benchmark_config_defaults():
    config = BenchmarkConfig(name="test")
    assert config.name == "test"
    assert config.max_candidates == 30
    assert config.top_k_after_rerank == 10


def test_benchmark_runner_init():
    vs = MockVectorstore()
    runner = BenchmarkRunner(vs)
    assert runner.evaluator is not None
    assert runner.get_runs() == []


def test_benchmark_runner_run_empty():
    vs = MockVectorstore()
    evaluator = RetrievalEvaluator(vs)
    runner = BenchmarkRunner(vs, evaluator)

    def mock_retrieval(dim, config):
        class MockResult:
            document_chunks = []
            framework_chunks = []
            retrieval_queries = []
            retrieval_latency = 0.0
            total_candidates = 0

        return MockResult()

    config = BenchmarkConfig(name="baseline")
    runs = runner.run_comparison(
        dimensions=["Test"],
        configs=[config],
        retrieval_fn=mock_retrieval,
    )
    assert len(runs) == 1
    assert runs[0].config.name == "baseline"


def test_benchmark_aggregate_metrics():
    vs = MockVectorstore()
    runner = BenchmarkRunner(vs)

    m1 = RetrievalMetrics(precision_at_5=0.8, recall_at_5=0.6)
    m2 = RetrievalMetrics(precision_at_5=0.6, recall_at_5=0.4)

    agg = runner._aggregate_metrics([m1, m2])
    assert agg.precision_at_5 == 0.7
    assert agg.recall_at_5 == 0.5


def test_benchmark_aggregate_empty():
    vs = MockVectorstore()
    runner = BenchmarkRunner(vs)
    agg = runner._aggregate_metrics([])
    assert agg.precision_at_5 == 0.0


def test_benchmark_comparison_logging():
    vs = MockVectorstore()
    runner = BenchmarkRunner(vs)

    m1 = RetrievalMetrics(precision_at_5=0.9)
    m2 = RetrievalMetrics(precision_at_5=0.7)

    run1 = type(
        "BenchmarkRun",
        (),
        {
            "config": BenchmarkConfig(name="reranker"),
            "aggregate": m1,
            "total_latency": 5.0,
        },
    )()
    run2 = type(
        "BenchmarkRun",
        (),
        {
            "config": BenchmarkConfig(name="baseline"),
            "aggregate": m2,
            "total_latency": 2.0,
        },
    )()

    runner._log_comparison([run1, run2])


def test_benchmark_last_run():
    vs = MockVectorstore()
    runner = BenchmarkRunner(vs)
    assert runner.get_last_run() is None

    def mock_retrieval(dim, config):
        class MockResult:
            document_chunks = []
            framework_chunks = []
            retrieval_queries = []
            retrieval_latency = 0.0
            total_candidates = 0

        return MockResult()

    config = BenchmarkConfig(name="test")
    runner.run_comparison(["A"], [config], mock_retrieval)
    assert runner.get_last_run() is not None
