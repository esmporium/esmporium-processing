"""
Compiling requirements into what to search for

Search always has to fetch every alternative and every optional dataset,
because what is available is only known after searching.
The boolean structure of a requirement therefore never changes what is searched for,
only what is selected afterwards (see
[solve][esmporium_processing.requirements.solve.solve]).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from esmporium.query import Query

from esmporium_processing.requirements.catalog import set_facets
from esmporium_processing.requirements.relations import Ancestors, Sibling
from esmporium_processing.requirements.tree import (
    Requirement,
    effective_query,
    walk_leaves,
)


@dataclass(frozen=True)
class SearchPlan:
    """
    What to search for to be able to solve a requirement
    """

    queries: tuple[Query, ...]
    """
    Queries to search, i.e. what esmporium's `QueryCollection` will wrap

    Includes queries for optional datasets, every alternative,
    siblings and auxiliary data.
    """

    ancestry_until: tuple[Query, ...]
    """
    For datasets found by the search, follow parent links back until these

    Parent links (and any follow-up searches needed to find parents)
    are esmporium's job (esmporium PR6).
    """


def _key_without_variable(query: Query) -> str:
    facets: dict[str, Any] = {
        k: list(v) for k, v in set_facets(query).items() if k != "variable"
    }
    facets["other_terms"] = {k: list(v) for k, v in query.other_terms.items()}
    return json.dumps(facets, sort_keys=True)


def merge_on_variable(queries: tuple[Query, ...]) -> tuple[Query, ...]:
    """
    Merge queries which differ only in their variables

    The merged query can match more than the union of the originals
    when other facets also have several values
    (e.g. `variable=("tas", "pr")` with `reporting_interval=("day", "mon")`).
    For searching that overreach is harmless (we just get extra results),
    which is why this is only used when compiling searches.

    Parameters
    ----------
    queries
        Queries to merge

    Returns
    -------
    :
        Merged queries, in order of first appearance
    """
    merged: dict[str, Query] = {}
    for query in queries:
        key = _key_without_variable(query)
        if key not in merged:
            merged[key] = query
            continue

        existing = merged[key]
        if not existing.variable or not query.variable:
            # One of them does not restrict variable, so it matches everything
            variables: tuple[str, ...] = ()
        else:
            variables = tuple(dict.fromkeys((*existing.variable, *query.variable)))

        merged[key] = existing.model_copy(update={"variable": variables})

    return tuple(merged.values())


def to_search_plan(
    requirement: Requirement, merge_variables: bool = True
) -> SearchPlan:
    """
    Compile a requirement into a search plan

    Parameters
    ----------
    requirement
        Requirement to compile

    merge_variables
        Whether to merge queries which differ only in their variables.

        This trades a few big searches for many small ones
        (ECS goes from twelve queries to four),
        at the cost of matching more than was asked for
        when another facet also has several values.
        Turn it off if you would rather search exactly what was declared.

    Returns
    -------
    :
        Search plan
    """
    queries: list[Query] = []
    until: list[Query] = []
    for _, leaf in walk_leaves(requirement.tree):
        query = effective_query(leaf, requirement.where)
        queries.append(query)

        if isinstance(leaf.lineage, Sibling):
            queries.append(sibling_query(query, leaf.lineage))

        if isinstance(leaf.lineage, Ancestors) and leaf.lineage.until not in until:
            until.append(leaf.lineage.until)

        # Auxiliary queries are used as given: they inherit nothing,
        # so that fx data from any experiment can be found.
        # Note: this is smart.
        # It might give us too many results, so we might have to
        # treat this a bit more like until and only widen the search
        # if the initial narrow search fails, let's see.
        queries.extend(aux.query for aux in leaf.aux)

    return SearchPlan(
        queries=merge_on_variable(tuple(queries))
        if merge_variables
        else tuple(queries),
        ancestry_until=tuple(until),
    )


def sibling_query(query: Query, sibling: Sibling) -> Query:
    """
    Get the query for a sibling of the datasets identified by a query

    Parameters
    ----------
    query
        Query identifying the datasets

    sibling
        Sibling relation

    Returns
    -------
    :
        `query`, with the facets set by `sibling.query` replaced
    """
    return query.model_copy(update=set_facets(sibling.query))
