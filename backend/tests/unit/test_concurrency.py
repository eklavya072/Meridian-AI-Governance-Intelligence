"""Admission control, backpressure and graceful shutdown.

The analysis worker runs in-process, so nothing bounded the number of
concurrent pipelines. Each one internally runs up to
ANALYSIS_MAX_CONCURRENCY dimension workers, so ten workspaces starting at
once meant eighty concurrent provider calls against a per-credential ceiling
of roughly ten a minute, on an 8GB host.
"""

import asyncio

import pytest

from src.concurrency import AnalysisSlots, CapacityFull, get_slots, reset_slots


@pytest.fixture(autouse=True)
def _clean():
    reset_slots()
    yield
    reset_slots()


class TestAdmission:
    def test_a_slot_can_be_taken_and_returned(self):
        slots = AnalysisSlots(limit=2)

        slots.acquire()

        assert slots.in_flight == 1
        slots.release()
        assert slots.in_flight == 0

    def test_capacity_is_refused_rather_than_queued(self):
        slots = AnalysisSlots(limit=1)
        slots.acquire()

        # Blocking here would hold the HTTP request open until it timed out
        # and tell the caller nothing.
        with pytest.raises(CapacityFull):
            slots.acquire()

    def test_the_refusal_reports_the_numbers(self):
        slots = AnalysisSlots(limit=2)
        slots.acquire()
        slots.acquire()

        with pytest.raises(CapacityFull) as exc:
            slots.acquire()

        assert exc.value.in_flight == 2
        assert exc.value.limit == 2
        assert "2 of 2" in str(exc.value)

    def test_releasing_frees_the_slot_for_the_next_caller(self):
        slots = AnalysisSlots(limit=1)
        slots.acquire()
        slots.release()

        slots.acquire()  # must not raise

    def test_release_never_goes_negative(self):
        slots = AnalysisSlots(limit=1)

        slots.release()
        slots.release()

        # A negative count would silently grant extra capacity forever.
        assert slots.in_flight == 0

    def test_available_reflects_what_is_left(self):
        slots = AnalysisSlots(limit=3)
        slots.acquire()

        assert slots.available == 2


class TestDraining:
    def test_draining_refuses_new_work(self):
        slots = AnalysisSlots(limit=4)

        slots.begin_drain()

        with pytest.raises(CapacityFull):
            slots.acquire()

    def test_draining_does_not_cancel_in_flight_work(self):
        slots = AnalysisSlots(limit=2)
        slots.acquire()

        slots.begin_drain()

        # In-flight runs finish; only new admissions stop.
        assert slots.in_flight == 1
        slots.release()

    def test_draining_is_idempotent(self):
        slots = AnalysisSlots(limit=1)
        slots.begin_drain()
        slots.begin_drain()

        assert slots.draining


class TestGracefulShutdown:
    async def test_an_idle_server_drains_immediately(self):
        slots = AnalysisSlots(limit=2)

        assert await slots.wait_for_idle(timeout=0.5) is True

    async def test_in_flight_work_is_waited_for(self):
        slots = AnalysisSlots(limit=2)
        slots.acquire()

        async def _finish():
            await asyncio.sleep(0.05)
            slots.release()

        task = asyncio.create_task(_finish())
        drained = await slots.wait_for_idle(timeout=2.0)
        await task

        assert drained is True

    async def test_work_that_outlasts_the_grace_period_is_abandoned_not_hung(self):
        slots = AnalysisSlots(limit=2)
        slots.acquire()

        drained = await slots.wait_for_idle(timeout=0.05)

        # Abandoning is a legitimate outcome — the startup sweep reclaims the
        # workspace. Hanging shutdown forever is not.
        assert drained is False
        slots.release()


class TestSnapshot:
    def test_the_snapshot_reports_everything_readiness_needs(self):
        slots = AnalysisSlots(limit=3)
        slots.acquire()

        snap = slots.snapshot()

        assert snap == {"in_flight": 1, "limit": 3, "available": 2, "draining": False}

    def test_the_snapshot_shows_draining(self):
        slots = AnalysisSlots(limit=1)
        slots.begin_drain()

        assert slots.snapshot()["draining"] is True


class TestGlobalSlots:
    def test_get_slots_returns_one_shared_instance(self):
        assert get_slots() is get_slots()

    def test_reset_clears_it(self):
        first = get_slots()
        reset_slots()

        assert get_slots() is not first


class TestConcurrentAdmission:
    def test_the_limit_holds_under_concurrent_callers(self):
        import threading

        slots = AnalysisSlots(limit=3)
        admitted = []
        refused = []

        def worker():
            try:
                slots.acquire()
                admitted.append(1)
            except CapacityFull:
                refused.append(1)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Without the lock, several callers can each read in_flight below the
        # limit and all be admitted — which is exactly the burst the bound
        # exists to prevent.
        assert len(admitted) == 3
        assert len(refused) == 17
