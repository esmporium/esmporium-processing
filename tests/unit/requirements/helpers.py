"""
Helpers for building catalogs in tests
"""

from __future__ import annotations

from esmporium.query import Query
from pydantic import BaseModel, ConfigDict

from esmporium_processing.requirements import (
    BRANCH_TIME_IN_PARENT,
    TIME_RANGE,
    Ancestors,
    Catalog,
    DatasetRecord,
    Fail,
    GroupView,
    InMemoryCatalog,
    Outcome,
    Pass,
    Requirement,
    Sibling,
)
from esmporium_processing.requirements.catalog import set_facets
from esmporium_processing.requirements.compile import sibling_query
from esmporium_processing.requirements.tree import effective_query, walk_leaves

DEFAULT_FACETS: dict[str, str | None] = {
    "project": "CMIP6",
    "model": "ModelA",
    "institution": "InstA",
    "experiment": "historical",
    "variant_label": "r1i1p1f1",
    "variable": "tas",
    "reporting_interval": "mon",
    "grid_label": "gn",
    "processing_id": "Amon",
}


def record(dataset_id: str | None = None, **facets: str | None) -> DatasetRecord:
    """
    Create a dataset record, filling unspecified facets with defaults

    The ID defaults to the experiment, variable, variant and grid.
    """
    values = {**DEFAULT_FACETS, **facets}
    if dataset_id is None:
        dataset_id = ".".join(
            str(values[f])
            for f in ("model", "experiment", "variant_label", "variable", "grid_label")
        )

    return DatasetRecord(id=dataset_id, **values)  # type: ignore[arg-type]


def _first_values(query: Query) -> dict[str, str]:
    return {k: v[0] for k, v in set_facets(query).items()}


def satisfying_catalog(requirement: Requirement) -> InMemoryCatalog:
    """
    Build a catalog in which every leaf of a requirement is available for one group

    Each leaf's dataset uses the first value of every facet its query sets.
    Lineages resolve directly to the control, with metadata that satisfies
    coverage checks. Auxiliary data matches strictly and is also linked.
    """
    records: dict[str, DatasetRecord] = {}
    parents: dict[str, str] = {}
    links: dict[str, tuple[str, ...]] = {}
    metadata: dict[str, dict[str, object]] = {}

    def add(**facets: str | None) -> DatasetRecord:
        new = record(**facets)
        records.setdefault(new.id, new)
        return records[new.id]

    for _, leaf in walk_leaves(requirement.tree):
        query = effective_query(leaf, requirement.where)
        data = add(**_first_values(query))
        metadata.setdefault(
            data.id, {TIME_RANGE: (0.0, 150.0), BRANCH_TIME_IN_PARENT: 100.0}
        )
        members = [data]

        if isinstance(leaf.lineage, Ancestors):
            control = add(**{**_facets_of(data), **_first_values(leaf.lineage.until)})
            metadata[control.id] = {TIME_RANGE: (0.0, 1000.0)}
            parents[data.id] = control.id
            members.append(control)

        if isinstance(leaf.lineage, Sibling):
            sibling = add(
                **{
                    **_facets_of(data),
                    **_first_values(sibling_query(query, leaf.lineage)),
                }
            )
            metadata[sibling.id] = {TIME_RANGE: (0.0, 30.0)}
            members.append(sibling)

        for member in members:
            for aux in leaf.aux:
                aux_record = add(
                    **{
                        **_facets_of(member),
                        "reporting_interval": "fx",
                        "processing_id": "fx",
                        **_first_values(aux.query),
                    }
                )
                links[member.id] = (*links.get(member.id, ()), aux_record.id)

    return InMemoryCatalog(
        records=tuple(records.values()),
        parents=parents,
        links={k: tuple(dict.fromkeys(v)) for k, v in links.items()},
        metadata_by_id=metadata,
    )


def _facets_of(dataset: DatasetRecord) -> dict[str, str | None]:
    return {f: dataset.facet(f) for f in DEFAULT_FACETS}


class AtLeastNDatasets(BaseModel):
    """
    A user-defined constraint: a role must hold at least `n` datasets

    Defined outside the requirements package to show that constraints are pluggable.
    """

    model_config = ConfigDict(frozen=True)

    role: str
    n: int

    def required_metadata(self) -> frozenset[str]:
        return frozenset()

    def evaluate(self, view: GroupView, catalog: Catalog) -> Outcome:
        found = len(view.roles.get(self.role, ()))
        if found < self.n:
            return Fail(f"{self.role} holds {found} datasets, need at least {self.n}")

        return Pass()
