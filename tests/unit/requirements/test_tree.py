"""
Tests of building, validating and serialising requirement trees
"""

from __future__ import annotations

import re

import pytest
from esmporium.query import Query as Q
from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticSerializationError
from tests.unit.requirements.helpers import AtLeastNDatasets
from tests.unit.requirements.use_cases import CARBON_CLOSURE, ECS

from esmporium_processing.requirements import (
    STRICT_MATCH,
    Ancestors,
    Aux,
    ConflictingFacetsError,
    Covers,
    Leaf,
    Requirement,
    SameTimeRange,
    Sibling,
    all_of,
    any_of,
    namespace,
    optional,
)
from esmporium_processing.requirements.constraints import NotAConstraintError
from esmporium_processing.requirements.tree import role_paths


def test_leaf_shorthand():
    assert Leaf.of("tas") == Leaf.of(Q(variable="tas"), role="tas")
    assert all_of("tas", "pr").children == (Leaf.of("tas"), Leaf.of("pr"))


def test_leaf_needs_role_for_several_variables():
    with pytest.raises(ValueError, match="Give the leaf a `role`"):
        Leaf.of(Q(variable=("fLuc", "fLUC")))

    assert Leaf.of(Q(variable=("fLuc", "fLUC")), role="fLuc").role == "fLuc"


def test_duplicate_roles_in_all_of():
    with pytest.raises(ValidationError, match="Roles 'tas' are used more than once"):
        all_of("tas", all_of("pr", "tas"))


def test_duplicate_roles_allowed_across_alternatives():
    node = any_of(
        Leaf.of(Q(variable="tas", grid_label="gn"), role="tas"),
        Leaf.of(Q(variable="tas", grid_label="gr"), role="tas"),
    )

    assert role_paths(node) == {"tas"}


def test_duplicate_aux_roles():
    with pytest.raises(ValidationError, match=re.escape("'tas.areacella'")):
        Leaf.of(
            "tas",
            aux=[Aux(Q(variable="areacella")), Aux(Q(variable="areacella"))],
        )


def test_where_adds_facets_to_every_leaf():
    node = all_of("tas", "pr").where(experiment="1pctCO2", reporting_interval="mon")

    assert node.children[0].query == Q(
        variable="tas", experiment="1pctCO2", reporting_interval="mon"
    )
    assert node.children[1].query == Q(
        variable="pr", experiment="1pctCO2", reporting_interval="mon"
    )


def test_where_contradicting_a_leaf_is_an_error():
    node = all_of("tas", Leaf.of(Q(variable="pr", reporting_interval="day")))

    with pytest.raises(ConflictingFacetsError, match="where sets reporting_interval"):
        node.where(reporting_interval="mon")

    # Setting the same value again is fine
    assert node.where(reporting_interval="day").children[
        1
    ].query.reporting_interval == (("day",))


def test_requirement_where_contradicting_a_leaf_is_an_error():
    with pytest.raises(ValidationError, match="where sets reporting_interval"):
        Requirement(
            Leaf.of(Q(variable="pr", reporting_interval="day")),
            name="clash",
            where=Q(reporting_interval="mon"),
        )


def test_with_lineage_and_with_constraints_reach_every_leaf():
    lineage = Ancestors(until=Q(experiment="piControl"), role="control")
    node = (
        all_of("tas", "pr")
        .with_lineage(lineage)
        .with_constraints(Covers(role="control"))
    )

    for leaf in node.children:
        assert leaf.lineage == lineage
        assert leaf.constraints == (Covers(role="control"),)


def test_leaf_role_cannot_be_its_own_lineage_role():
    with pytest.raises(ValidationError, match="is also this leaf's lineage role"):
        Leaf.of(
            Q(variable="tas"),
            role="control",
            lineage=Ancestors(until=Q(experiment="piControl"), role="control"),
        )


def test_role_names_are_free_unless_a_lineage_uses_them():
    # Nothing here is walking back to a control, so the name is free
    leaf = Leaf.of(Q(variable="tas"), role="control")

    assert leaf.role == "control"

    # ...and a lineage stopping somewhere else does not reserve it either
    with_historical = Leaf.of(
        Q(variable="tas"),
        role="control",
        lineage=Ancestors(until=Q(experiment="historical"), role="historical"),
    )

    assert with_historical.role == "control"


def test_machinery_role_names_are_always_reserved():
    with pytest.raises(ValidationError, match=r"'chain' is reserved"):
        Leaf.of(Q(variable="tas"), role="chain")


def test_namespaces_prefix_roles_and_can_nest():
    node = namespace("outer", namespace("inner", all_of("tas", "pr")))

    assert role_paths(node) == {"outer.inner.tas", "outer.inner.pr"}


def test_project_specific_facets_are_allowed_when_building():
    # Whether a facet can be answered is the catalog's business,
    # so it is not checked here, only when the requirement is solved
    requirement = Requirement(
        Leaf.of("tas"),
        name="cmip5",
        group_by=("model", "product"),
        prefer={"product": ("output1", "output2")},
    )

    assert requirement.group_by == ("model", "product")


def test_role_paths():
    assert role_paths(ECS.tree) == {
        f"{block}.{role}"
        for block in ("abrupt4x", "abrupt2x", "abrupt0p5x")
        for variable in ("tas", "rsdt", "rlut", "rsut")
        # Each leaf, its cell areas, and the same again for its control
        for role in (
            variable,
            f"{variable}.areacella",
            f"control.{variable}",
            f"control.{variable}.areacella",
        )
    }


def test_aux_defaults_to_strict_match():
    aux = Aux(Q(variable="areacella"))

    assert aux.match == STRICT_MATCH
    assert len(aux.match) == 1
    assert aux.via == "match"
    assert aux.role_name == "areacella"


def test_aux_needs_role_for_several_variables():
    with pytest.raises(ValidationError, match="Aux needs an explicit `role`"):
        Aux(Q(variable=("sftlf", "sftof")))


def test_aux_match_accepts_project_specific_facets():
    aux = Aux(Q(variable="areacella"), match=(("model", "product"),))

    assert aux.match == (("model", "product"),)


@pytest.mark.parametrize("requirement", [ECS, CARBON_CLOSURE])
def test_round_trip_and_hash(requirement):
    serialised = requirement.model_dump_json()
    loaded = Requirement.model_validate_json(serialised)

    assert loaded == requirement
    assert loaded.canonical_json() == requirement.canonical_json()
    assert loaded.requirement_hash() == requirement.requirement_hash()


def test_hash_changes_with_content():
    other = ECS.model_copy(update={"group_by": ("model",)})

    assert other.requirement_hash() != ECS.requirement_hash()


def test_round_trip_user_defined_constraint():
    requirement = Requirement(
        Leaf.of("tas"),
        name="ensemble",
        constraints=[
            AtLeastNDatasets(role="tas", n=3),
            Covers(role="control", align="calendar"),
        ],
    )

    loaded = Requirement.model_validate_json(requirement.model_dump_json())

    assert loaded.constraints == requirement.constraints
    assert isinstance(loaded.constraints[0], AtLeastNDatasets)


class NotPydantic:
    def required_metadata(self) -> frozenset[str]:
        return frozenset()

    def evaluate(self, view, catalog):
        raise NotImplementedError


def test_constraint_which_is_not_a_pydantic_model():
    # Usable...
    requirement = Requirement(Leaf.of("tas"), name="x", constraints=[NotPydantic()])

    # ...but not serialisable
    with pytest.raises(PydanticSerializationError, match="is not a pydantic model"):
        requirement.model_dump_json()


def test_not_a_constraint():
    class Nope(BaseModel):
        n: int

    with pytest.raises(NotAConstraintError):
        Requirement(Leaf.of("tas"), name="x", constraints=[Nope(n=1)])


def test_lineage_kinds_round_trip():
    requirement = Requirement(
        all_of(
            namespace(
                "sib",
                Leaf.of("rsdt").with_lineage(
                    Sibling(Q(experiment="piClim-control"), role="control")
                ),
            ),
            optional(
                namespace(
                    "anc",
                    Leaf.of("tas").with_lineage(
                        Ancestors(until=Q(experiment="piControl"), role="control")
                    ),
                )
            ),
        ),
        name="lineages",
    )

    assert Requirement.model_validate_json(requirement.model_dump_json()) == requirement


def test_namespace_carries_cross_leaf_constraints():
    node = namespace(
        "abrupt4x", all_of("tas", "rsdt"), constraints=[SameTimeRange(roles=("tas",))]
    )

    assert node.constraints == (SameTimeRange(roles=("tas",)),)
    # ...while with_constraints is about each leaf on its own
    assert node.with_constraints(Covers(role="control")).child.children[0].constraints
