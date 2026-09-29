"""Key-term emphasis in the executive brief."""

from src.brief_emphasis import emphasize, emphasize_brief, split_marks


def test_counts_and_verdicts_are_marked_first():
    text = (
        "The document imposes 3 binding requirement(s) here and is Partially Covered, "
        "with enforcement powers named for two of them."
    )
    out = emphasize(text)
    assert "**3 binding requirement(s)**" in out
    assert "**Partially Covered**" in out


def test_a_paragraph_marks_a_few_terms_not_every_one():
    text = (
        "Transparency, Accountability, Privacy, Safety and Fairness are assessed; "
        "Safety carries 2 binding duties and Fairness none, so oversight is thin."
    )
    marked = emphasize(text).count("**") // 2
    assert 1 <= marked <= 2
    # Never more than two terms of one kind, so a list is not marked item by item.
    assert (
        emphasize(text).count("**Transparency**")
        + emphasize(text).count("**Accountability**")
        + emphasize(text).count("**Privacy**")
        <= 2
    )


def test_half_a_hyphenated_word_is_never_marked():
    assert "**discrimination**" not in emphasize("It aligns with non-discrimination standards.")


def test_text_already_marked_is_left_alone():
    assert emphasize("Already **marked** here.") == "Already **marked** here."


def test_split_marks_returns_fragments_in_order():
    assert split_marks("a **b** c") == [("a ", False), ("b", True), (" c", False)]


def test_the_stored_brief_is_not_changed_and_quotes_are_not_marked():
    brief = {
        "sections": {
            "executive_summary": "Accountability is the strongest dimension.",
            "areas_of_strength": [],
            "areas_requiring_attention": [],
            "priority_recommendations": [],
            "dimension_assessment": [
                {
                    "basis": "The document imposes 2 binding requirement(s) here.",
                    "key_provision": {"quote": "The Commissioner shall audit.", "source": "x"},
                }
            ],
        }
    }
    out = emphasize_brief(brief)
    assert "**" not in brief["sections"]["executive_summary"]
    assert "**Accountability**" in out["sections"]["executive_summary"]
    row = out["sections"]["dimension_assessment"][0]
    assert "**2 binding requirement(s)**" in row["basis"]
    assert row["key_provision"]["quote"] == "The Commissioner shall audit."
