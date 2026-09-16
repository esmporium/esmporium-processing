"""
Tests of catalog matching and of constraint edge cases
"""

from __future__ import annotations

import pytest
from esmporium.query import Query as Q
from pydantic import ValidationError
from tests.unit.requirements.helpers import record

from esmporium_processing.requirements import (
    BRANCH_TIME_IN_PARENT,
    TIME_RANGE,
    Aux,
    ClashingFacetError,
    Covers,
    GroupView,
    InMemoryCatalog,
    Lineage,
    MetadataUnavailableError,
    UnsupportedFacetError,
    matches,
)
from esmporium_processing.requirements.catalog import set_facets


def test_matches():
    tas = record(experiment="historical", variable="tas")

    assert matches(Q(variable=("pr", "tas")), tas)
    assert not matches(Q(variable="tas", experiment="ssp126"), tas)
    assert matches(Q(), tas)


@pytest.mark.parametrize(
    "query",
    [Q(realm="atmos"), Q(other_terms={"product": "output1"})],
    ids=["unrecorded-facet", "other-terms"],
)
def test_matching_unrecorded_facets_raises(query):
    # Rather than silently matching everything
    with pytest.raises(UnsupportedFacetError, match="Cannot select datasets on"):
        matches(query, record())


def test_catalog_rejects_duplicate_ids():
    with pytest.raises(ValueError, match="must be unique"):
        InMemoryCatalog(records=(record("a"), record("a")))


def test_catalog_rejects_unknown_references():
    with pytest.raises(ValueError, match=r"unknown datasets: \['b'\]"):
        InMemoryCatalog(records=(record("a"),), parents={"a": "b"})


def test_missing_metadata():
    catalog = InMemoryCatalog(records=(record("a"),))

    with pytest.raises(MetadataUnavailableError, match="No 'time_range' recorded"):
        catalog.metadata(record("a"), TIME_RANGE)


def lineage_view(*members, end_role="control"):
    return GroupView(
        prefix="",
        roles={},
        lineages={"tas": (Lineage(members=tuple(members), end_role=end_role),)},
    )


def test_covers_needs_a_lineage():
    outcome = Covers(role="control").evaluate(
        GroupView(prefix="", roles={}, lineages={}), InMemoryCatalog(records=())
    )

    assert outcome.message == "Covers needs a lineage, but none was resolved"


def test_covers_branch_needs_ancestor():
    child, control = record("child"), record("control")
    catalog = InMemoryCatalog(
        records=(child, control),
        metadata_by_id={
            "child": {TIME_RANGE: (0, 10), BRANCH_TIME_IN_PARENT: 0},
            "control": {TIME_RANGE: (0, 10)},
        },
    )

    with pytest.raises(ValueError, match="must be an ancestor"):
        Covers(role="self", target="control").evaluate(
            lineage_view(child, control), catalog
        )

    with pytest.raises(ValueError, match=r"'chain\.0' is not in this lineage"):
        Covers(role="chain.0").evaluate(lineage_view(child, control), catalog)

    with pytest.raises(ValueError, match="use 'self', 'historical'"):
        Covers(role="control").evaluate(
            lineage_view(child, control, end_role="historical"), catalog
        )


def test_covers_calendar():
    child, control = record("child"), record("control")
    catalog = InMemoryCatalog(
        records=(child, control),
        metadata_by_id={
            "child": {TIME_RANGE: (1850, 2015)},
            "control": {TIME_RANGE: (1850, 1880)},
        },
    )

    outcome = Covers(role="control", align="calendar").evaluate(
        lineage_view(child, control), catalog
    )

    assert outcome.message.startswith(
        "tas: control covers [1850, 1880), needed [1850, 2015)"
    )


def test_covers_rejects_malformed_metadata():
    child, control = record("child"), record("control")
    catalog = InMemoryCatalog(
        records=(child, control),
        metadata_by_id={
            "child": {TIME_RANGE: "1850-2015"},
            "control": {TIME_RANGE: (1850, 1880)},
        },
    )

    with pytest.raises(TypeError, match=r"should be \(start, end\)"):
        Covers(role="control", align="calendar").evaluate(
            lineage_view(child, control), catalog
        )


def test_aux_needs_at_least_one_match_level():
    with pytest.raises(ValidationError, match="At least one match level"):
        Aux(Q(variable="areacella"), match=())


def test_other_terms_are_facets_too():
    # `other_terms` is esmporium's escape hatch for facets a query class
    # does not name, so selection has to see them
    assert set_facets(Q(variable="tas", other_terms={"product": "output1"})) == {
        "variable": ("tas",),
        "product": ("output1",),
    }

    # ...but datasets do not record project-specific facets (yet)
    with pytest.raises(UnsupportedFacetError, match="product"):
        matches(Q(other_terms={"product": "output1"}), record())


def test_facet_set_twice():
    with pytest.raises(ClashingFacetError, match="variable set both as a query field"):
        set_facets(Q(variable="tas", other_terms={"variable": "pr"}))


def test_end_and_the_lineage_role_name_mean_the_same_thing():
    child, control = record("child"), record("control")
    catalog = InMemoryCatalog(
        records=(child, control),
        metadata_by_id={
            "child": {TIME_RANGE: (0, 10)},
            "control": {TIME_RANGE: (0, 10)},
        },
    )
    view = lineage_view(child, control)

    assert Covers(role="end", align="calendar").evaluate(view, catalog) == Covers(
        role="control", align="calendar"
    ).evaluate(view, catalog)
