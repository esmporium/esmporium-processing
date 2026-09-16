"""
Expressing, compiling and solving the data requirements of analyses

This is a prototype which is expected to move into esmporium.
To keep that move mechanical, this package imports only from esmporium,
pydantic and the standard library, never from the rest of esmporium-processing.

Constraints are a pluggable protocol
([Constraint][esmporium_processing.requirements.constraints.Constraint])
and must stay that way, here and in esmporium.
"""

from esmporium_processing.requirements.catalog import (
    Catalog,
    ClashingFacetError,
    DatasetRecord,
    InMemoryCatalog,
    MetadataUnavailableError,
    UnsupportedFacetError,
    matches,
)
from esmporium_processing.requirements.compile import SearchPlan, to_search_plan
from esmporium_processing.requirements.constraints import (
    BRANCH_TIME_IN_PARENT,
    TIME_RANGE,
    Constraint,
    Covers,
    Degraded,
    Fail,
    GroupView,
    Lineage,
    Outcome,
    Pass,
    SameTimeRange,
)
from esmporium_processing.requirements.relations import (
    STRICT_MATCH,
    Ancestors,
    Aux,
    Sibling,
)
from esmporium_processing.requirements.solve import (
    Explanation,
    NodeResult,
    Resolved,
    ResolvedGroup,
    SolveResult,
    Unresolved,
    UnresolvedGroup,
    solve,
)
from esmporium_processing.requirements.tree import (
    AllOf,
    AnyOf,
    ConflictingFacetsError,
    DuplicateRoleError,
    Leaf,
    Namespace,
    OptionalNode,
    Requirement,
    all_of,
    any_of,
    namespace,
    optional,
)

__all__ = [
    "BRANCH_TIME_IN_PARENT",
    "STRICT_MATCH",
    "TIME_RANGE",
    "AllOf",
    "Ancestors",
    "AnyOf",
    "Aux",
    "Catalog",
    "ClashingFacetError",
    "ConflictingFacetsError",
    "Constraint",
    "Covers",
    "DatasetRecord",
    "Degraded",
    "DuplicateRoleError",
    "Explanation",
    "Fail",
    "GroupView",
    "InMemoryCatalog",
    "Leaf",
    "Lineage",
    "MetadataUnavailableError",
    "Namespace",
    "NodeResult",
    "OptionalNode",
    "Outcome",
    "Pass",
    "Requirement",
    "Resolved",
    "ResolvedGroup",
    "SameTimeRange",
    "SearchPlan",
    "Sibling",
    "SolveResult",
    "Unresolved",
    "UnresolvedGroup",
    "UnsupportedFacetError",
    "all_of",
    "any_of",
    "matches",
    "namespace",
    "optional",
    "solve",
    "to_search_plan",
]
