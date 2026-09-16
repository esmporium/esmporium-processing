"""
Relations: how datasets other than the anchor datasets are found

`group_by` only applies to anchor datasets.
Parents, siblings and auxiliary data (cell areas, surface fractions)
hang off a chosen dataset through one of the relations defined here.
"""

from __future__ import annotations

from typing import Any, Literal

from esmporium.query import Query
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

RELATION_MODEL_CONFIG = ConfigDict(frozen=True, extra="forbid")
"""Model config shared by relations"""

MatchLevels = tuple[tuple[str, ...], ...]
"""
Ordered levels of facets on which auxiliary data must equal the data it belongs to
"""

STRICT_MATCH: MatchLevels = (("model", "grid_label", "experiment", "variant_label"),)
"""
The default auxiliary-data matching: a single, strict level

There is deliberately no fallback by default.
If you want to accept e.g. an areacella from a different experiment,
pass your own levels to [Aux][esmporium_processing.requirements.relations.Aux].
"""


class Ancestors(BaseModel):
    """
    Follow parent links back until a dataset matching `until` is found

    Resolves, for each anchor dataset,
    `chain.<i>` roles for intermediate parents (closest parent first)
    and a role named by `role` for the dataset matching `until`.
    Parent links are data read from file headers (esmporium PR6),
    so this relies on the catalog recording them.
    """

    model_config = RELATION_MODEL_CONFIG

    kind: Literal["ancestors"] = "ancestors"

    until: Query
    """Where to stop, e.g. `Query(experiment=("piControl", "esm-piControl"))`"""

    role: str
    """
    Role the dataset matching `until` is resolved into

    Required, with no default, so that constraints which name this role
    (e.g. `Covers(role="control", ...)`) can be read against the lineage
    which creates it. Use `"control"` when walking back to piControl,
    `"historical"` when that is where you stop, and so on.
    """

    max_depth: int = 10
    """Maximum number of parent links to follow before giving up"""


class Sibling(BaseModel):
    """
    Find the reference dataset by matching facets, rather than by parent links

    Needed where the reference simulation is not an ancestor
    (e.g. piClim-histall and piClim-control are both children of piControl)
    and useful where parent metadata is broken.

    Resolves a role named by `role` for each anchor dataset.
    """

    model_config = RELATION_MODEL_CONFIG

    kind: Literal["sibling"] = "sibling"

    query: Query
    """
    Facets which differ for the sibling, e.g. `Query(experiment="piClim-control")`

    These override the anchor dataset's query, everything else is kept.
    """

    match_on: tuple[str, ...] = ("model", "variant_label")
    """
    Facets on which the sibling must equal the anchor dataset

    Project-specific facets are allowed, as long as the catalog puts them in
    each record's `extra`. They are only checked when datasets are compared,
    because nothing here knows what a given catalog can answer.
    """

    role: str
    """
    Role the sibling is resolved into

    Required, with no default, for the same reason as
    [Ancestors.role][esmporium_processing.requirements.relations.Ancestors.role].
    """

    def __init__(self, query: Query | None = None, /, **data: Any) -> None:
        """
        Initialise

        Parameters
        ----------
        query
            Query, can also be passed by keyword

        **data
            Other fields
        """
        if query is not None:
            data["query"] = query

        super().__init__(**data)


class Aux(BaseModel):
    """
    Auxiliary data (e.g. cell areas, surface fractions) for a dataset

    The user names the auxiliary variable explicitly,
    e.g. `Aux(Query(variable="sftlf"))` for land variables.
    There is no built-in mapping from 'surface fraction' or 'cell area'
    to specific variables.

    Auxiliary queries do not inherit any facets from the requirement
    (e.g. `reporting_interval="mon"` would exclude fx data).
    """

    model_config = RELATION_MODEL_CONFIG

    query: Query
    """Query identifying the auxiliary data"""

    role: str = ""
    """
    Role name for the auxiliary data

    If empty, the query's variable is used (it must then set exactly one variable).
    """

    required: bool = True
    """Whether the data it is attached to is useless without this auxiliary data"""

    match: MatchLevels = STRICT_MATCH
    """
    Ordered levels of facets on which the auxiliary data must equal the data

    Used when `via="match"`.
    The first level with any candidates wins.
    The default is a single, strict level: fallbacks are opt-in.
    Project-specific facets are allowed here too, see
    [Sibling.match_on][esmporium_processing.requirements.relations.Sibling.match_on].
    """

    also_for_lineage: bool = True
    """
    Whether this auxiliary data is also needed for each dataset in the lineage

    For example, cell areas are needed for a simulation's control too,
    so that a global mean can be taken of both.
    Set to `False` for auxiliary data only the anchor dataset needs.
    """

    via: Literal["match", "link"] = "match"
    """
    How to find the auxiliary data

    - `"link"`: follow dataset links recorded by esmporium, keeping those which
      match `query`. **This is where we want to end up for everything.**
      Linking is done once, at ingestion, so every analysis which needs e.g. a
      surface fraction reads the same answer instead of redoing the matching.
    - `"match"`: find datasets matching `query` and compare facets using `match`.
      The fallback for data esmporium has not linked. It should be rare, and the
      default will become `"link"` once esmporium links at ingestion time.
    """

    def __init__(self, query: Query | None = None, /, **data: Any) -> None:
        """
        Initialise

        Parameters
        ----------
        query
            Query, can also be passed by keyword

        **data
            Other fields
        """
        if query is not None:
            data["query"] = query

        super().__init__(**data)

    @field_validator("match")
    @classmethod
    def _known_match_facets(cls, value: MatchLevels) -> MatchLevels:
        if not value:
            msg = "At least one match level is required"
            raise ValueError(msg)

        return value

    @model_validator(mode="after")
    def _role_resolvable(self) -> Aux:
        if not self.role and len(self.query.variable) != 1:
            msg = (
                "Aux needs an explicit `role` "
                "unless its query sets exactly one variable, "
                f"got variable={self.query.variable!r}"
            )
            raise ValueError(msg)

        return self

    @property
    def role_name(self) -> str:
        """
        The role this auxiliary data is resolved into
        """
        return self.role or self.query.variable[0]
