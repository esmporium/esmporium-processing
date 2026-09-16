"""
What the solver needs to know about the datasets available

This is a stand-in for what esmporium's database will offer.
The in-memory implementation exists so that the rest of the requirements
machinery can be built and tested before esmporium records parent links
(esmporium PR6) and file information (esmporium PR7).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from esmporium.db.schema import DATASET_FACET_COLUMNS
from esmporium.query import Query

NON_FACET_QUERY_FIELDS: frozenset[str] = frozenset({"other_terms", "source_query"})
"""
Fields of `Query` which are not themselves facets

`other_terms` does hold facet values, so it is flattened in
[set_facets][esmporium_processing.requirements.catalog.set_facets]
rather than ignored.
"""


class ClashingFacetError(ValueError):
    """Raised when a query names a facet both as a field and in `other_terms`."""

    def __init__(self, facets: Iterable[str]) -> None:
        """
        Initialise the error

        Parameters
        ----------
        facets
            The facets named twice
        """
        self.facets = tuple(sorted(facets))
        super().__init__(
            f"{', '.join(self.facets)} set both as a query field "
            "and in `other_terms`. Set each facet once, "
            "so which value applies is unambiguous."
        )


class UnsupportedFacetError(ValueError):
    """Raised when a dataset does not know a facet it was asked about."""

    def __init__(self, facets: Iterable[str], dataset_id: str | None = None) -> None:
        """
        Initialise the error

        Parameters
        ----------
        facets
            The facets the dataset does not know

        dataset_id
            ID of the dataset which was asked, if there was one
        """
        self.facets = tuple(sorted(facets))
        self.dataset_id = dataset_id
        asked = f" (asked of {dataset_id})" if dataset_id is not None else ""
        recorded = ", ".join(DATASET_FACET_COLUMNS)
        super().__init__(
            f"Cannot select datasets on {', '.join(self.facets)}{asked}: "
            f"every dataset records {recorded}. "
            "Project-specific facets (CMIP5's `product`, say) are fine, "
            "but the catalog has to put them in each record's `extra`."
        )


class MetadataUnavailableError(LookupError):
    """
    Raised when metadata about a dataset has not been recorded (yet)

    The solver turns this into an 'undetermined' outcome,
    so a check which needs metadata we do not have never silently passes.
    """

    def __init__(self, dataset_id: str, key: str) -> None:
        """
        Initialise the error

        Parameters
        ----------
        dataset_id
            ID of the dataset whose metadata was requested

        key
            The metadata which was requested
        """
        self.dataset_id = dataset_id
        self.key = key
        super().__init__(f"No {key!r} recorded for dataset {dataset_id!r}")


@dataclass(frozen=True)
class DatasetRecord:
    """
    A dataset, as far as selection is concerned

    The facets mirror `Dataset`.
    """

    id: str
    """Unique identifier of the dataset"""

    project: str
    model: str
    institution: str
    experiment: str
    variant_label: str
    variable: str
    reporting_interval: str
    grid_label: str | None
    processing_id: str

    extra: Mapping[str, str | None] = field(default_factory=dict)
    """
    Facets beyond the ones every dataset records

    How a catalog answers a query which names a project-specific facet
    (CMIP5's `product`, say) is its own business.
    What selection needs is this: anything it should be able to group by,
    prefer on, or match auxiliary data on has to appear here,
    because those comparisons happen on the record rather than in the query.
    """

    def facet(self, name: str) -> str | None:
        """
        Get the value of a facet

        Parameters
        ----------
        name
            Facet to get

        Returns
        -------
        :
            The facet's value

        Raises
        ------
        UnsupportedFacetError
            Neither this dataset's facets nor its `extra` include `name`
        """
        if name in DATASET_FACET_COLUMNS:
            value: str | None = getattr(self, name)
            return value

        if name in self.extra:
            return self.extra[name]

        raise UnsupportedFacetError([name], self.id)


def set_facets(query: Query) -> dict[str, tuple[str, ...]]:
    """
    Get the facets a query actually sets, flattened

    `other_terms` is esmporium's escape hatch for facets a query class does not
    name, so its entries are facets too and are included here.

    Parameters
    ----------
    query
        Query to inspect

    Returns
    -------
    :
        Facet name -> values, for every facet with at least one value

    Raises
    ------
    ClashingFacetError
        A facet is set both as a field of `query` and in its `other_terms`
    """
    declared = {
        name: getattr(query, name)
        for name in type(query).model_fields
        if name not in NON_FACET_QUERY_FIELDS and getattr(query, name)
    }
    other = {name: values for name, values in query.other_terms.items() if values}

    clashes = set(declared) & set(other)
    if clashes:
        raise ClashingFacetError(clashes)

    return {**declared, **other}


def matches(query: Query, record: DatasetRecord) -> bool:
    """
    Determine whether a dataset matches a query

    A dataset matches if, for every facet the query sets,
    the dataset's value is one of the query's values.

    Parameters
    ----------
    query
        Query to match against

    record
        Dataset to check

    Returns
    -------
    :
        `True` if `record` matches `query`

    Raises
    ------
    UnsupportedFacetError
        `query` sets a facet `record` does not know, i.e. one which is neither
        a dataset facet nor in the record's `extra`

    ClashingFacetError
        A facet is set both as a field of `query` and in its `other_terms`
    """
    return all(
        record.facet(name) in values for name, values in set_facets(query).items()
    )


class Catalog(Protocol):
    """
    The datasets available to the solver, and what is known about them
    """

    def find(self, query: Query) -> tuple[DatasetRecord, ...]:
        """
        Find all datasets which match a query

        How project-specific query information is answered is up to the catalog:
        esmporium knows about CMIP5's `product` and friends, this package does not.
        Facets the catalog wants selection to use afterwards
        (grouping, `prefer`, auxiliary matching) belong in each record's `extra`.

        Parameters
        ----------
        query
            Query to match

        Returns
        -------
        :
            Matching datasets, in a stable order
        """
        ...

    def parent_of(self, record: DatasetRecord) -> DatasetRecord | None:
        """
        Get the parent of a dataset

        Parameters
        ----------
        record
            Dataset whose parent to get

        Returns
        -------
        :
            The parent dataset, or `None` if no parent is recorded
        """
        ...

    def linked(self, record: DatasetRecord) -> tuple[DatasetRecord, ...]:
        """
        Get the datasets a dataset links to

        In esmporium, these links will be created from each file's
        `cell_measures` attribute, e.g. a link from tas to areacella.

        Parameters
        ----------
        record
            Dataset whose links to get

        Returns
        -------
        :
            Linked datasets (empty if none are recorded)
        """
        ...

    def metadata(self, record: DatasetRecord, key: str) -> object:
        """
        Get metadata about a dataset

        Parameters
        ----------
        record
            Dataset whose metadata to get

        key
            Metadata to get e.g. `"time_range"`

        Returns
        -------
        :
            The metadata

        Raises
        ------
        MetadataUnavailableError
            The metadata has not been recorded for `record`
        """
        ...


@dataclass(frozen=True)
class InMemoryCatalog:
    """
    A catalog held entirely in memory

    Intended for tests and prototyping.
    """

    records: tuple[DatasetRecord, ...]
    """Available datasets"""

    parents: Mapping[str, str] = field(default_factory=dict)
    """Dataset ID -> ID of its parent dataset"""

    links: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """Dataset ID -> IDs of the datasets it links to"""

    metadata_by_id: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    """Dataset ID -> metadata key -> value"""

    def __post_init__(self) -> None:
        """
        Check that IDs are unique and that every reference points at a dataset

        Raises
        ------
        ValueError
            IDs are duplicated or a reference points at an unknown dataset
        """
        ids = [record.id for record in self.records]
        if len(ids) != len(set(ids)):
            msg = "Dataset IDs must be unique"
            raise ValueError(msg)

        known = set(ids)
        referenced = (
            set(self.parents)
            | set(self.parents.values())
            | set(self.links)
            | {linked for targets in self.links.values() for linked in targets}
            | set(self.metadata_by_id)
        )
        unknown = referenced - known
        if unknown:
            msg = f"References to unknown datasets: {sorted(unknown)}"
            raise ValueError(msg)

    def _by_id(self, dataset_id: str) -> DatasetRecord:
        return next(record for record in self.records if record.id == dataset_id)

    def find(self, query: Query) -> tuple[DatasetRecord, ...]:
        """
        Find all datasets which match a query

        Parameters
        ----------
        query
            Query to match

        Returns
        -------
        :
            Matching datasets, in the order they were given to the catalog
        """
        return tuple(record for record in self.records if matches(query, record))

    def parent_of(self, record: DatasetRecord) -> DatasetRecord | None:
        """
        Get the parent of a dataset

        Parameters
        ----------
        record
            Dataset whose parent to get

        Returns
        -------
        :
            The parent dataset, or `None` if no parent is recorded
        """
        parent_id = self.parents.get(record.id)
        if parent_id is None:
            return None

        return self._by_id(parent_id)

    def linked(self, record: DatasetRecord) -> tuple[DatasetRecord, ...]:
        """
        Get the datasets a dataset links to

        Parameters
        ----------
        record
            Dataset whose links to get

        Returns
        -------
        :
            Linked datasets (empty if none are recorded)
        """
        return tuple(self._by_id(i) for i in self.links.get(record.id, ()))

    def metadata(self, record: DatasetRecord, key: str) -> object:
        """
        Get metadata about a dataset

        Parameters
        ----------
        record
            Dataset whose metadata to get

        key
            Metadata to get

        Returns
        -------
        :
            The metadata

        Raises
        ------
        MetadataUnavailableError
            The metadata has not been recorded for `record`
        """
        try:
            return self.metadata_by_id[record.id][key]
        except KeyError:
            raise MetadataUnavailableError(record.id, key) from None
