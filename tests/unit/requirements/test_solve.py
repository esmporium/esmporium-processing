"""
Tests of solving requirements against in-memory catalogs
"""

from __future__ import annotations

import pytest
from esmporium.query import Query as Q
from tests.unit.requirements.helpers import AtLeastNDatasets, record
from tests.unit.requirements.use_cases import (
    ECS,
    ERF_TIMESLICE,
    FX_FALLBACK,
    TCRE_1PCT,
    TO_CONTROL,
)

from esmporium_processing.requirements import (
    BRANCH_TIME_IN_PARENT,
    TIME_RANGE,
    Ancestors,
    Aux,
    Covers,
    InMemoryCatalog,
    Leaf,
    Requirement,
    UnsupportedFacetError,
    all_of,
    any_of,
    namespace,
    solve,
)

ONLY_GROUP = (("model", "ModelA"), ("variant_label", "r1i1p1f1"))


def ecs_catalog(
    *,
    variables: tuple[str, ...] = ("tas", "rsdt", "rlut", "rsut"),
    x2_control_end: float | None = None,
    x4_metadata: bool = True,
) -> InMemoryCatalog:
    """
    abrupt-4xCO2 plus piControl (and optionally abrupt-2xCO2) for ModelA
    """
    records = []
    parents = {}
    metadata: dict[str, dict[str, object]] = {}
    experiments = [("abrupt-4xCO2", 1000.0)]
    if x2_control_end is not None:
        experiments.append(("abrupt-2xCO2", x2_control_end))

    for experiment, control_end in experiments:
        for variable in variables:
            child = record(experiment=experiment, variable=variable)
            control = record(
                f"piControl-for-{experiment}.{variable}",
                experiment="piControl",
                variable=variable,
            )
            records.extend([child, control])
            parents[child.id] = control.id
            if experiment == "abrupt-2xCO2" or x4_metadata:
                metadata[child.id] = {
                    TIME_RANGE: (1850.0, 2000.0),
                    BRANCH_TIME_IN_PARENT: 100.0,
                }
                metadata[control.id] = {TIME_RANGE: (0.0, control_end)}

    records.append(record(experiment="abrupt-4xCO2", variable="areacella"))
    return InMemoryCatalog(
        records=tuple(records), parents=parents, metadata_by_id=metadata
    )


def test_all_satisfied():
    res = solve(ECS, ecs_catalog())

    assert list(res.resolved) == [ONLY_GROUP]
    group = res.resolved[ONLY_GROUP]
    assert group.one("abrupt4x.tas").id == "ModelA.abrupt-4xCO2.r1i1p1f1.tas.gn"
    assert group.one("abrupt4x.control.tas").id == "piControl-for-abrupt-4xCO2.tas"
    assert group.one("abrupt4x.tas.areacella").variable == "areacella"
    # Cell areas are optional and only exist for abrupt-4xCO2 itself
    assert "abrupt4x.control.tas.areacella" not in group.roles
    assert "optional abrupt2x absent" in group.notes
    assert "optional abrupt0p5x absent" in group.notes


def test_required_variable_missing():
    res = solve(ECS, ecs_catalog(variables=("tas", "rsdt", "rsut")))

    assert not res.resolved
    explanation = res.unsatisfied[ONLY_GROUP].explanation.render()
    assert "[unsatisfied] abrupt4x.rlut: no dataset matches" in explanation
    assert "variable=rlut" in explanation


def test_optional_run_with_too_short_control_is_absent():
    # The abrupt-2xCO2 control ends before the branch point plus simulation length
    res = solve(ECS, ecs_catalog(x2_control_end=200.0))

    group = res.resolved[ONLY_GROUP]
    assert "abrupt2x.tas" not in group.roles
    assert "optional abrupt2x absent" in group.notes
    assert "Covers: " in res.explain()


def test_optional_run_with_long_enough_control_is_used():
    res = solve(ECS, ecs_catalog(x2_control_end=1000.0))

    group = res.resolved[ONLY_GROUP]
    assert group.one("abrupt2x.control.rlut").experiment == "piControl"


def test_missing_metadata_is_undetermined_not_passed():
    res = solve(ECS, ecs_catalog(x4_metadata=False))

    assert not res.resolved
    assert ONLY_GROUP in res.undetermined
    assert "needs metadata which is not available" in res.explain()


def test_degraded_when_ideal_padding_not_met():
    # Needs [100, 250]; ideal padding 20 years either side needs [80, 270]
    catalog = ecs_catalog()
    metadata = {
        k: ({TIME_RANGE: (90.0, 1000.0)} if k.startswith("piControl") else v)
        for k, v in catalog.metadata_by_id.items()
    }
    catalog = InMemoryCatalog(
        records=catalog.records, parents=catalog.parents, metadata_by_id=metadata
    )

    group = solve(ECS, catalog).resolved[ONLY_GROUP]

    assert any("Covers degraded" in note for note in group.notes)


def test_alternative_chosen_in_order():
    requirement = Requirement(
        any_of("sfcWind", all_of("uas", "vas")),
        name="wind",
        group_by=("model",),
    )
    both = InMemoryCatalog(
        records=(
            record(variable="sfcWind"),
            record(variable="uas"),
            record(variable="vas"),
        )
    )
    components_only = InMemoryCatalog(
        records=(record(variable="uas"), record(variable="vas"))
    )

    first = solve(requirement, both).resolved[(("model", "ModelA"),)]
    second = solve(requirement, components_only).resolved[(("model", "ModelA"),)]

    assert first.choices == {"any_of(sfcWind | uas+vas)": 0}
    assert "sfcWind" in first.roles
    assert second.choices == {"any_of(sfcWind | uas+vas)": 1}
    assert set(second.roles) == {"uas", "vas"}
    assert "using alternative 2" in second.notes[0]


def test_alternative_applies_to_whole_lineage():
    requirement = Requirement(
        any_of("cLand", all_of("cVeg", "cSoil"))
        .where(experiment="1pctCO2")
        .with_lineage(TO_CONTROL),
        name="lineage-consistency",
    )
    records = [
        record(experiment="1pctCO2", variable=v) for v in ("cLand", "cVeg", "cSoil")
    ] + [record(experiment="piControl", variable=v) for v in ("cVeg", "cSoil")]
    parents = {
        f"ModelA.1pctCO2.r1i1p1f1.{v}.gn": f"ModelA.piControl.r1i1p1f1.{v}.gn"
        for v in ("cVeg", "cSoil")
    }
    catalog = InMemoryCatalog(records=tuple(records), parents=parents)

    group = solve(requirement, catalog).resolved[ONLY_GROUP]

    # cLand exists for 1pctCO2, but not for its control, so the components are used
    assert "cLand" not in group.roles
    assert group.one("control.cVeg").experiment == "piControl"


def test_bell_is_rooted_in_esm_picontrol():
    requirement = Requirement(
        Leaf.of("tas").where(experiment="esm-bell-1000PgC").with_lineage(TO_CONTROL),
        name="bell",
    )
    bell = record(experiment="esm-bell-1000PgC")
    control = record(experiment="esm-piControl")
    catalog = InMemoryCatalog(records=(bell, control), parents={bell.id: control.id})

    group = solve(requirement, catalog).resolved[ONLY_GROUP]

    assert group.one("control.tas") == control


def branch_chain_catalog(control_end: float) -> InMemoryCatalog:
    brch = record(experiment="esm-1pct-brch-1000PgC")
    onepct = record(experiment="1pctCO2")
    control = record(experiment="piControl", variant_label="r1i1p2f1")
    return InMemoryCatalog(
        records=(brch, onepct, control),
        parents={brch.id: onepct.id, onepct.id: control.id},
        metadata_by_id={
            # Branches from 1pctCO2 at year 70 of 1pctCO2's time axis
            brch.id: {TIME_RANGE: (0.0, 100.0), BRANCH_TIME_IN_PARENT: 70.0},
            # Branches from piControl at year 100 of piControl's time axis
            onepct.id: {TIME_RANGE: (0.0, 150.0), BRANCH_TIME_IN_PARENT: 100.0},
            control.id: {TIME_RANGE: (0.0, control_end)},
        },
    )


BRANCH_REQUIREMENT = Requirement(
    Leaf.of("tas")
    .where(experiment="esm-1pct-brch-1000PgC")
    .with_lineage(TO_CONTROL)
    .with_constraints(Covers(role="control", target="self")),
    name="zec",
)


def test_branch_chain_back_to_picontrol():
    # In piControl's time axis,
    # 1pctCO2 is [100, 250) and the branch simulation [170, 270)
    res = solve(BRANCH_REQUIREMENT, branch_chain_catalog(control_end=300.0))

    group = res.resolved[ONLY_GROUP]
    assert group.one("chain.0.tas").experiment == "1pctCO2"
    # Different variant to the child, still linked via the parent link
    assert group.one("control.tas").variant_label == "r1i1p2f1"


def test_branch_chain_control_must_cover_child_and_parents():
    res = solve(BRANCH_REQUIREMENT, branch_chain_catalog(control_end=260.0))

    assert not res.resolved
    assert "needed [100, 270)" in res.unsatisfied[ONLY_GROUP].explanation.render()


def test_erf_control_found_as_sibling():
    piclim_4xco2_rsdt = record(experiment="piClim-4xCO2", variable="rsdt")
    records = tuple(
        record(experiment=e, variable=v)
        for e in ("piClim-4xCO2", "piClim-aer", "piClim-control")
        for v in ("rsdt", "rlut", "rsut")
    )
    catalog = InMemoryCatalog(records=records)

    res = solve(ERF_TIMESLICE, catalog)

    # Fan-out: one group per experiment
    assert len(res.resolved) == 2
    assert {key[2] for key in res.resolved} == {
        ("experiment", "piClim-4xCO2"),
        ("experiment", "piClim-aer"),
    }
    group = next(
        g for g in res.resolved.values() if piclim_4xco2_rsdt in g.roles["rsdt"]
    )
    assert group.one("control.rsdt").experiment == "piClim-control"

    # No parent links recorded, so the same requirement via ancestors cannot resolve
    via_ancestors = Requirement(
        Leaf.of("rsdt")
        .where(experiment="piClim-4xCO2")
        .with_lineage(Ancestors(until=Q(experiment="piClim-control"), role="control")),
        name="erf-via-ancestors",
    )
    assert not solve(via_ancestors, catalog).resolved


def test_ambiguous_grids_and_prefer():
    requirement = Requirement(Leaf.of("tas"), name="tas")
    catalog = InMemoryCatalog(
        records=(record(grid_label="gn"), record(grid_label="gr"))
    )

    ambiguous = solve(requirement, catalog)
    preferred = solve(
        requirement.model_copy(update={"prefer": {"grid_label": ("gn", "gr")}}),
        catalog,
    )

    assert ONLY_GROUP in ambiguous.ambiguous
    # With no `prefer`, the message says how to resolve the ambiguity
    assert "2 candidates and no way to choose between them" in ambiguous.explain()
    assert "Set `prefer` on the requirement" in ambiguous.explain()
    assert preferred.resolved[ONLY_GROUP].one("tas").grid_label == "gn"


def test_ambiguous_despite_prefer_says_what_was_preferred():
    requirement = Requirement(
        Leaf.of("tas"),
        name="tas",
        prefer={"grid_label": ("gn", "gr")},
    )
    catalog = InMemoryCatalog(
        records=(
            record("gn-one", grid_label="gn"),
            record("gn-two", grid_label="gn", variable="tas", institution="InstB"),
        )
    )

    res = solve(requirement, catalog)

    assert (
        "which preferring grid_label in order gn, gr did not narrow to one"
        in res.explain()
    )


def test_ambiguity_is_not_skipped_by_any_of():
    requirement = Requirement(any_of("tas", "ts"), name="tas-or-ts")
    catalog = InMemoryCatalog(
        records=(
            record(grid_label="gn"),
            record(grid_label="gr"),
            record(variable="ts"),
        )
    )

    res = solve(requirement, catalog)

    assert ONLY_GROUP in res.ambiguous
    assert "later alternatives are not considered" in res.explain()


def fx_requirement(**aux_kwargs: object) -> Requirement:
    return Requirement(
        namespace(
            "abrupt4x",
            Leaf.of("tas", aux=[Aux(Q(variable="areacella"), **aux_kwargs)]).where(
                experiment="abrupt-4xCO2"
            ),
        ),
        name="fx",
    )


FX_CATALOG = InMemoryCatalog(
    records=(
        record(experiment="abrupt-4xCO2"),
        # CMIP5-style fx data: only for piControl, variant r0i0p0
        record(
            experiment="piControl",
            variant_label="r0i0p0",
            variable="areacella",
            reporting_interval="fx",
        ),
    )
)


def test_fx_not_matched_by_default():
    optional_res = solve(fx_requirement(required=False), FX_CATALOG)
    required_res = solve(fx_requirement(), FX_CATALOG)

    group = optional_res.resolved[ONLY_GROUP]
    assert "abrupt4x.tas.areacella" not in group.roles
    assert any(
        n.startswith("optional abrupt4x.tas.areacella absent") for n in group.notes
    )
    assert ONLY_GROUP in required_res.unsatisfied


def test_fx_matched_with_opt_in_fallback():
    group = solve(fx_requirement(match=FX_FALLBACK), FX_CATALOG).resolved[ONLY_GROUP]

    assert group.one("abrupt4x.tas.areacella").variant_label == "r0i0p0"
    assert (
        "abrupt4x.tas.areacella: matched at level 3 (model, grid_label)" in group.notes
    )


def test_fallback_still_requires_same_grid():
    catalog = InMemoryCatalog(
        records=(
            record(experiment="abrupt-4xCO2", grid_label="gn"),
            record(experiment="piControl", variable="areacella", grid_label="gr"),
        )
    )

    res = solve(fx_requirement(match=FX_FALLBACK), catalog)

    assert ONLY_GROUP in res.unsatisfied


def test_aux_via_link():
    tas = FX_CATALOG.records[0]
    areacella = FX_CATALOG.records[1]
    linked = InMemoryCatalog(
        records=FX_CATALOG.records, links={tas.id: (areacella.id,)}
    )

    via_link = solve(fx_requirement(via="link"), linked).resolved[ONLY_GROUP]
    no_link_required = solve(fx_requirement(via="link"), FX_CATALOG)
    no_link_optional = solve(fx_requirement(via="link", required=False), FX_CATALOG)

    assert via_link.one("abrupt4x.tas.areacella") == areacella
    assert ONLY_GROUP in no_link_required.unsatisfied
    assert "abrupt4x.tas.areacella" not in no_link_optional.resolved[ONLY_GROUP].roles


def test_fractions_are_not_linked():
    # esmporium only creates links from cell_measures (e.g. tas -> areacella),
    # so fractions must be matched by facets
    nbp = record(variable="nbp", processing_id="Lmon")
    areacella = record(variable="areacella", reporting_interval="fx")
    sftlf = record(variable="sftlf", reporting_interval="fx")
    catalog = InMemoryCatalog(
        records=(nbp, areacella, sftlf), links={nbp.id: (areacella.id,)}
    )

    def requirement(via: str) -> Requirement:
        return Requirement(
            Leaf.of("nbp", aux=[Aux(Q(variable="sftlf"), via=via)]), name="nbp"
        )

    assert ONLY_GROUP in solve(requirement("link"), catalog).unsatisfied
    assert (
        solve(requirement("match"), catalog).resolved[ONLY_GROUP].one("nbp.sftlf")
        == sftlf
    )


def carbon_catalog(*, with_sftof: bool) -> InMemoryCatalog:
    records = [
        record(experiment=e, variable=v)
        for e in ("1pctCO2", "piControl")
        for v in ("tas", "fgco2", "nbp")
    ]
    for experiment in ("1pctCO2", "piControl"):
        records.append(record(experiment=experiment, variable="sftlf"))
        if with_sftof:
            records.append(record(experiment=experiment, variable="sftof"))

    parents = {
        f"ModelA.1pctCO2.r1i1p1f1.{v}.gn": f"ModelA.piControl.r1i1p1f1.{v}.gn"
        for v in ("tas", "fgco2", "nbp")
    }
    metadata: dict[str, dict[str, object]] = {}
    for child, control in parents.items():
        metadata[child] = {TIME_RANGE: (0.0, 150.0), BRANCH_TIME_IN_PARENT: 0.0}
        metadata[control] = {TIME_RANGE: (0.0, 500.0)}

    return InMemoryCatalog(
        records=tuple(records), parents=parents, metadata_by_id=metadata
    )


def test_land_and_ocean_fractions():
    group = solve(TCRE_1PCT, carbon_catalog(with_sftof=True)).resolved[ONLY_GROUP]

    assert group.one("nbp.sftlf").variable == "sftlf"
    assert group.one("fgco2.sftof").variable == "sftof"
    assert group.one("control.fgco2.sftof").experiment == "piControl"
    assert "tas.sftlf" not in group.roles


def test_missing_required_sea_fraction():
    res = solve(TCRE_1PCT, carbon_catalog(with_sftof=False))

    assert ONLY_GROUP in res.unsatisfied
    assert "fgco2.sftof" in res.explain()


def test_user_defined_constraint():
    catalog = InMemoryCatalog(
        records=(record(variant_label="r1i1p1f1"), record(variant_label="r2i1p1f1"))
    )

    def requirement(n: int) -> Requirement:
        return Requirement(
            Leaf.of("tas"),
            name="ensemble",
            group_by=("model",),
            cardinality="all",
            constraints=[AtLeastNDatasets(role="tas", n=n)],
        )

    enough = solve(requirement(2), catalog)
    too_few = solve(requirement(3), catalog)

    assert len(enough.resolved[(("model", "ModelA"),)].roles["tas"]) == 2
    assert (
        "AtLeastNDatasets: tas holds 2 datasets, need at least 3" in too_few.explain()
    )


def test_explanation_is_readable():
    res = solve(ECS, ecs_catalog(variables=("tas", "rsdt", "rsut")))

    rendered = res.explain()

    assert rendered.splitlines()[0] == (
        "[unsatisfied] model=ModelA, variant_label=r1i1p1f1"
    )
    assert (
        "  [unsatisfied] all_of(abrupt4x & optional abrupt2x & optional abrupt0p5x)"
        in rendered
    )


def test_lineage_role_names_where_it_stopped():
    # Walking back to historical, not to a control
    requirement = Requirement(
        Leaf.of("tas")
        .where(experiment="ssp126")
        .with_lineage(Ancestors(until=Q(experiment="historical"), role="historical")),
        name="scenario-anomaly",
    )
    scenario = record(experiment="ssp126")
    historical = record(experiment="historical")
    catalog = InMemoryCatalog(
        records=(scenario, historical), parents={scenario.id: historical.id}
    )

    group = solve(requirement, catalog).resolved[ONLY_GROUP]

    assert group.one("historical.tas") == historical
    assert "control.tas" not in group.roles


def test_aux_only_for_the_anchor_dataset():
    requirement = Requirement(
        namespace(
            "abrupt4x",
            Leaf.of("tas", aux=[Aux(Q(variable="areacella"), also_for_lineage=False)])
            .where(experiment="abrupt-4xCO2")
            .with_lineage(TO_CONTROL),
        ),
        name="aux-scope",
    )
    child = record(experiment="abrupt-4xCO2")
    control = record(experiment="piControl")
    areacella = record(experiment="abrupt-4xCO2", variable="areacella")
    catalog = InMemoryCatalog(
        records=(child, control, areacella), parents={child.id: control.id}
    )

    group = solve(requirement, catalog).resolved[ONLY_GROUP]

    assert group.one("abrupt4x.tas.areacella") == areacella
    # The control has no areacella, but none was asked for either
    assert "abrupt4x.control.tas.areacella" not in group.roles


def test_project_specific_facets_come_from_the_catalog():
    # esmporium answers `find` for CMIP5's `product`;
    # selection can then group and prefer on it because the record carries it
    requirement = Requirement(
        Leaf.of(Q(variable="tas", other_terms={"product": "output1"})),
        name="cmip5",
        group_by=("model", "product"),
    )
    wanted = record("wanted", project="CMIP5", extra={"product": "output1"})
    other = record("other", project="CMIP5", extra={"product": "output2"})
    catalog = InMemoryCatalog(records=(wanted, other))

    res = solve(requirement, catalog)

    assert list(res.resolved) == [(("model", "ModelA"), ("product", "output1"))]
    assert res.resolved[(("model", "ModelA"), ("product", "output1"))].one("tas") == (
        wanted
    )


def test_facet_no_dataset_knows_is_an_error():
    requirement = Requirement(
        Leaf.of("tas"), name="oops", group_by=("model", "prodcut")
    )

    with pytest.raises(UnsupportedFacetError, match="prodcut"):
        solve(requirement, InMemoryCatalog(records=(record(),)))


def ecs_catalog_with_spans(
    spans: dict[str, tuple[float, float]], experiment: str = "abrupt-4xCO2", **kwargs
) -> InMemoryCatalog:
    """ECS data, with a time range per variable of one experiment"""
    catalog = ecs_catalog(**kwargs)
    metadata = {}
    for dataset_id, existing in catalog.metadata_by_id.items():
        parts = dataset_id.split(".")
        variable = parts[-2] if len(parts) > 1 else ""
        if experiment in dataset_id and variable in spans:
            metadata[dataset_id] = {**existing, TIME_RANGE: spans[variable]}
        else:
            metadata[dataset_id] = existing

    return InMemoryCatalog(
        records=catalog.records, parents=catalog.parents, metadata_by_id=metadata
    )


def test_cross_leaf_constraint_degrades_when_periods_differ():
    # A Gregory regression uses tas and radiation together,
    # so ECS asks for them over the same years
    res = solve(
        ECS, ecs_catalog_with_spans({"tas": (1850.0, 2000.0), "rsdt": (1850.0, 1950.0)})
    )

    group = res.resolved[ONLY_GROUP]
    assert any("SameTimeRange degraded" in note for note in group.notes)
    assert "only [1850, 1950) is covered by all of" in res.explain()


def test_cross_leaf_constraint_fails_when_periods_are_disjoint():
    res = solve(
        ECS,
        ecs_catalog_with_spans(
            {
                "tas": (1850.0, 1900.0),
                "rsdt": (1950.0, 2000.0),
                "rlut": (1950.0, 2000.0),
                "rsut": (1950.0, 2000.0),
            }
        ),
    )

    assert not res.resolved
    assert "no period is covered by all of" in (
        res.unsatisfied[ONLY_GROUP].explanation.render()
    )


def test_cross_leaf_constraint_is_scoped_to_its_namespace():
    # Only abrupt-2xCO2's periods disagree, so only that optional part is dropped
    res = solve(
        ECS,
        ecs_catalog_with_spans(
            {
                "tas": (1850.0, 1900.0),
                "rsdt": (1950.0, 2000.0),
                "rlut": (1950.0, 2000.0),
                "rsut": (1950.0, 2000.0),
            },
            experiment="abrupt-2xCO2",
            x2_control_end=1000.0,
        ),
    )

    group = res.resolved[ONLY_GROUP]
    assert group.one("abrupt4x.tas")
    assert "abrupt2x.tas" not in group.roles
    assert "optional abrupt2x absent" in group.notes
