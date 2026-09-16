"""
Tests of compiling requirements into search plans
"""

from __future__ import annotations

from esmporium.query import Query as Q
from tests.unit.requirements.use_cases import (
    _GCMAGICC_EXPERIMENTS,
    CARBON_CLOSURE,
    CONTROL,
    ECS,
    ERF_TRANSIENT,
    GCMAGICC,
    PICLIM_TRANSIENT,
)

from esmporium_processing.requirements import to_search_plan
from esmporium_processing.requirements.compile import merge_on_variable


def test_ecs():
    plan = to_search_plan(ECS)

    variables = ("tas", "rsdt", "rlut", "rsut")
    assert plan.queries == (
        Q(
            experiment=("abrupt-4xCO2", "abrupt4xCO2"),
            variable=variables,
            reporting_interval="mon",
        ),
        # Auxiliary queries inherit nothing, so fx data can be found
        Q(variable="areacella"),
        # Optional simulations are searched for too
        Q(experiment="abrupt-2xCO2", variable=variables, reporting_interval="mon"),
        Q(experiment="abrupt-0p5xCO2", variable=variables, reporting_interval="mon"),
    )
    assert plan.ancestry_until == (Q(experiment=CONTROL),)


def test_gcmagicc_includes_every_alternative_and_optional():
    plan = to_search_plan(GCMAGICC)

    experiments = _GCMAGICC_EXPERIMENTS
    variables = (
        "hurs",
        "huss",
        "pr",
        "psl",
        "rsds",
        "rlut",
        "rsdt",
        "rsut",
        "rtmt",
        "sfcWind",
        "uas",
        "vas",
        "tas",
        "tasmax",
        "tasmin",
        "ts",
        "clt",
        "evspsbl",
        "mrso",
    )
    assert plan.queries == tuple(
        Q(experiment=experiments, variable=variables, reporting_interval=frequency)
        for frequency in ("day", "mon")
    )
    assert plan.ancestry_until == ()


def test_erf_includes_sibling_query():
    plan = to_search_plan(ERF_TRANSIENT)

    variables = ("rsdt", "rlut", "rsut")
    assert plan.queries == (
        Q(experiment=PICLIM_TRANSIENT, variable=variables, reporting_interval="mon"),
        Q(experiment="piClim-control", variable=variables, reporting_interval="mon"),
        Q(variable="areacella"),
    )


def test_carbon_closure():
    plan = to_search_plan(CARBON_CLOSURE)

    onepct = plan.queries[0]
    assert onepct.experiment == ("1pctCO2",)
    assert {"cLand", "cVeg", "npp", "gpp", "ra", "rh", "fLuc", "fLUC"} <= set(
        onepct.variable
    )
    aux = next(q for q in plan.queries if "sftlf" in q.variable)
    assert set(aux.variable) == {"sftlf", "areacella", "areacellr"}
    # 1pctCO2, 39 optional experiments and the auxiliary query
    assert len(plan.queries) == 41


def test_merge_on_variable():
    merged = merge_on_variable(
        (
            Q(experiment="a", variable="tas"),
            Q(experiment="b", variable="tas"),
            Q(experiment="a", variable=("pr", "tas")),
            Q(experiment="b"),
        )
    )

    assert merged == (
        Q(experiment="a", variable=("tas", "pr")),
        # A query without variables matches every variable
        Q(experiment="b"),
    )


def test_merging_variables_can_be_turned_off():
    unmerged = to_search_plan(ECS, merge_variables=False)

    variables = [q.variable for q in unmerged.queries]
    assert ("tas",) in variables
    assert ("rsdt",) in variables
    # One query per leaf, plus one auxiliary query per leaf
    assert len(unmerged.queries) == 24
