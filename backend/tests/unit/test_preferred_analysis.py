"""Which run the page, the brief and chat use when none is named.

A run that lost dimensions to the provider is still saved, because on a first
run it is all there is. Taking the newest run regardless let a Japan run with
all eight dimensions failed replace a finished result everywhere at once.
"""

from types import SimpleNamespace

from main import _failed_dimensions, _is_provisional, _preferred_analysis


def _run(name, *gaps, documents=()):
    return SimpleNamespace(
        id=name,
        governance_gaps=list(gaps),
        ragas_metrics={"evaluated_documents": list(documents)},
        document_name=None,
    )


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


def test_a_newer_run_over_fewer_documents_does_not_displace_the_full_set():
    # Japan keeps a run over its guidelines alone next to the run over the
    # guidelines and both statutes. Re-scoring the guidelines alone must not
    # turn the country's page into a one-document assessment.
    guidelines_only = _run("new", OK, documents=["AI Guidelines for Business.pdf"])
    full_set = _run(
        "old", OK, documents=["AI Guidelines for Business.pdf", "APPI 2003.pdf", "AI Act.pdf"]
    )

    assert _preferred_analysis([guidelines_only, full_set]).id == "old"


def test_the_newest_wins_among_runs_over_the_same_documents():
    newer, older = _run("new", OK, documents=["a.pdf"]), _run("old", OK, documents=["a.pdf"])

    assert _preferred_analysis([newer, older]).id == "new"
