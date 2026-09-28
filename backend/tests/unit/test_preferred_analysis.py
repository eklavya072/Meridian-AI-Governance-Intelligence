"""Which run the page, the brief and chat use when none is named.

A run that lost dimensions to the provider is still saved, because on a first
run it is all there is. Taking the newest run regardless let a Japan run with
all eight dimensions failed replace a finished result everywhere at once.
"""

from types import SimpleNamespace

from main import _failed_dimensions, _is_provisional, _preferred_analysis


def _run(name, *gaps):
    return SimpleNamespace(id=name, governance_gaps=list(gaps))


OK = {"dimension": "Privacy"}
FAILED = {"dimension": "Safety", "analysis_error": "quota"}
UNCHECKED = {"dimension": "Fairness", "mechanism_adjudication": "unavailable"}


def test_a_newer_partial_run_does_not_displace_a_complete_one():
    newest_partial, older_complete = _run("new", OK, FAILED), _run("old", OK, OK)

    assert _preferred_analysis([newest_partial, older_complete]).id == "old"


def test_a_run_with_unadjudicated_mechanisms_is_provisional_not_complete():
    provisional, complete = _run("new", OK, UNCHECKED), _run("old", OK, OK)

    assert _is_provisional(provisional)
    assert _preferred_analysis([provisional, complete]).id == "old"


def test_the_newest_run_is_used_when_nothing_is_complete():
    assert _preferred_analysis([_run("new", FAILED), _run("old", FAILED)]).id == "new"


def test_failed_dimensions_are_named():
    assert _failed_dimensions(_run("r", OK, FAILED)) == ["Safety"]


def test_no_runs_means_nothing_to_prefer():
    assert _preferred_analysis([]) is None
