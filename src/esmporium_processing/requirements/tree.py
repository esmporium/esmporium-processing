"""
The requirement tree

A requirement picks datasets into named roles,
e.g. `abrupt4x.tas` and `abrupt4x.control.tas`.

- [Leaf][esmporium_processing.requirements.tree.Leaf]: one dataset per group.
  It carries everything about that dataset: the query which identifies it,
  its auxiliary data, how to find its lineage, and the checks it must pass.
- [AllOf][esmporium_processing.requirements.tree.AllOf]: all children are needed
- [AnyOf][esmporium_processing.requirements.tree.AnyOf]: alternatives,
  the first one which can be satisfied wins
- [OptionalNode][esmporium_processing.requirements.tree.OptionalNode]:
  used if it can be satisfied (including its constraints), absent otherwise
- [Namespace][esmporium_processing.requirements.tree.Namespace]: prefixes the
  roles of everything inside it, so the same role can appear twice, and holds
  checks which compare leaves
- [Requirement][esmporium_processing.requirements.tree.Requirement]:
  the root, which also says how datasets are grouped

Every node has the same three ways to say something about the leaves below it:
`.where(**facets)`, `.with_lineage(...)` and `.with_constraints(...)`.
Each pushes down to the leaves, because that is where the work happens.

Two other kinds of 'or' are deliberately not nodes:
aliases are tuple facet values in a query,
fan-out is `group_by` on the requirement.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Iterator
from typing import Annotated, Any, Literal, TypeVar, Union, cast

from esmporium.query import Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from esmporium_processing.requirements.catalog import set_facets
from esmporium_processing.requirements.constraints import Constraint, Constraints
from esmporium_processing.requirements.relations import Ancestors, Aux, Sibling

NODE_MODEL_CONFIG = ConfigDict(frozen=True, extra="forbid")
"""Model config shared by nodes"""

RESERVED_ROLES: frozenset[str] = frozenset({"chain", "self"})
"""
Role names the machinery itself uses, which a leaf may not take

A lineage's own `role` is reserved too, but only for the leaf which declares it:
`"control"` is just a name someone chose, so it is free everywhere else.
"""

LineageRelation = Annotated[Union[Ancestors, Sibling], Field(discriminator="kind")]
"""
How a leaf's reference dataset is found

`discriminator="kind"` tells pydantic to pick the member of the union by reading
the literal `kind` field, rather than trying each in turn. That makes validation
errors specific, and is what lets a stored requirement load back into the right
relation class.
"""


class DuplicateRoleError(ValueError):
    """Raised when two parts of a requirement which can both be used share a role."""

    def __init__(self, roles: Iterable[str]) -> None:
        """
        Initialise the error

        Parameters
        ----------
        roles
            The duplicated roles
        """
        self.roles = tuple(sorted(roles))
        super().__init__(
            f"Roles {', '.join(map(repr, self.roles))} are used more than once. "
            "Give leaves distinct roles with `Leaf.of(..., role=...)`, "
            "or put them in different namespaces "
            "(roles may only repeat across the alternatives of an `any_of`)."
        )


class ConflictingFacetsError(ValueError):
    """Raised when a facet is set to different values for the same dataset."""

    def __init__(self, role: str, facets: Iterable[str], source: str) -> None:
        """
        Initialise the error

        Parameters
        ----------
        role
            Role of the leaf whose query is being added to

        facets
            Facets which are set differently

        source
            Where the other values come from, e.g. `"where"`
        """
        self.facets = tuple(sorted(facets))
        super().__init__(
            f"{source} sets {', '.join(self.facets)} differently to leaf {role!r}. "
            f"Set each facet once: on the leaf or in {source}, not both."
        )


Node = Annotated[
    Union["Leaf", "AllOf", "AnyOf", "OptionalNode", "Namespace"],
    Field(discriminator="kind"),
]
"""Any node of a requirement tree"""

NodeLike = Union["Leaf", "AllOf", "AnyOf", "OptionalNode", "Namespace", str]
"""A node, or a variable name as shorthand for a leaf"""

LeafUpdate = Callable[["Leaf"], "Leaf"]
"""An update applied to every leaf below a node"""

NodeT = TypeVar(
    "NodeT", bound=Union["Leaf", "AllOf", "AnyOf", "OptionalNode", "Namespace"]
)
"""Any node type, kept as itself by the helpers which update leaves"""


def _normalise(facets: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    # Validate through Query so values are normalised exactly as esmporium does
    return set_facets(Query(**facets))


def add_facets(
    query: Query, facets: dict[str, tuple[str, ...]], role: str, source: str
) -> Query:
    """
    Add facets to a leaf's query

    Parameters
    ----------
    query
        The leaf's query

    facets
        Facets to add

    role
        Role of the leaf, used in error messages

    source
        Where the facets come from, used in error messages

    Returns
    -------
    :
        `query` with `facets` added

    Raises
    ------
    ConflictingFacetsError
        `facets` and `query` set the same facet to different values
    """
    already = set_facets(query)
    conflicts = {k for k, v in facets.items() if k in already and already[k] != v}
    if conflicts:
        raise ConflictingFacetsError(role, conflicts, source)

    update = {k: v for k, v in facets.items() if k not in already}
    if not update:
        return query

    return query.model_copy(update=update)


class Leaf(BaseModel):
    """
    One dataset (per group) in a role, and everything about that dataset
    """

    model_config = NODE_MODEL_CONFIG

    kind: Literal["leaf"] = "leaf"

    query: Query
    """
    Query identifying the dataset

    A facet with several values is an OR, exactly as in esmporium:
    `Query(variable=("fLuc", "fLUC"))` matches either spelling, and
    `Query(variable=("tas", "pr"))` accepts whichever is available.
    Use `group_by` to turn such a list into one group per value instead.
    """

    role: str
    """
    Role the dataset is resolved into

    Say what the dataset is *for*, not which variable it happens to be:
    the variable is in the query (and, when fanning out, in the group key).
    """

    aux: tuple[Aux, ...] = ()
    """
    Auxiliary data for this dataset

    Also found for each dataset in its lineage,
    unless the auxiliary data says otherwise.
    """

    lineage: LineageRelation | None = None
    """
    How to find this dataset's reference dataset, e.g. its control

    Resolves `chain.<i>` roles for intermediate parents, and a role named by the
    relation (e.g. `control`), each holding this leaf's role beneath it.
    """

    constraints: Constraints = ()
    """
    Checks on this dataset and its lineage

    This is where most checks belong, because most checks are about one dataset:
    `Covers(role="control", target="self")` says this leaf's control must cover
    it. Checks which compare leaves go on a
    [Namespace][esmporium_processing.requirements.tree.Namespace]
    or on the [Requirement][esmporium_processing.requirements.tree.Requirement].
    """

    @classmethod
    def of(
        cls,
        query: Query | str,
        role: str | None = None,
        aux: Iterable[Aux] = (),
        lineage: Ancestors | Sibling | None = None,
        constraints: Iterable[Constraint] = (),
    ) -> Leaf:
        """
        Create a leaf

        Parameters
        ----------
        query
            Query identifying the dataset, or a variable name

        role
            Role name. If not given, the query's variable is used
            (it must then set exactly one variable).

        aux
            Auxiliary data for the dataset

        lineage
            How to find the dataset's reference dataset

        constraints
            Checks on the dataset and its lineage

        Returns
        -------
        :
            Leaf
        """
        if isinstance(query, str):
            query = Query(variable=(query,))

        if role is None:
            if len(query.variable) != 1:
                msg = (
                    "Give the leaf a `role` "
                    "unless its query sets exactly one variable, "
                    f"got variable={query.variable!r}"
                )
                raise ValueError(msg)

            role = query.variable[0]

        return cls(
            query=query,
            role=role,
            aux=tuple(aux),
            lineage=lineage,
            constraints=tuple(constraints),
        )

    @field_validator("role")
    @classmethod
    def _valid_role(cls, value: str) -> str:
        if not value or "." in value:
            msg = f"Roles must be non-empty and contain no '.', got {value!r}"
            raise ValueError(msg)

        if value in RESERVED_ROLES:
            msg = (
                f"Role {value!r} is reserved: "
                f"{', '.join(sorted(RESERVED_ROLES))} are used for lineages"
            )
            raise ValueError(msg)

        return value

    @model_validator(mode="after")
    def _distinct_roles(self) -> Leaf:
        names = [a.role_name for a in self.aux]
        duplicated = {n for n in names if names.count(n) > 1}
        if duplicated:
            raise DuplicateRoleError(f"{self.role}.{n}" for n in duplicated)

        if self.lineage is not None and self.lineage.role == self.role:
            msg = (
                f"Leaf role {self.role!r} is also this leaf's lineage role, "
                "which would be confusing. Rename one of them."
            )
            raise ValueError(msg)

        return self

    def where(self, **facets: Any) -> Leaf:
        """
        Add facets to this leaf's query

        Parameters
        ----------
        **facets
            Facet values

        Returns
        -------
        :
            Updated leaf

        Raises
        ------
        ConflictingFacetsError
            A facet is already set to a different value
        """
        return self.model_copy(
            update={
                "query": add_facets(self.query, _normalise(facets), self.role, "where")
            }
        )

    def with_lineage(self, lineage: Ancestors | Sibling) -> Leaf:
        """
        Set how this leaf's reference dataset is found

        Parameters
        ----------
        lineage
            The relation to use

        Returns
        -------
        :
            Updated leaf
        """
        return self.model_copy(update={"lineage": lineage})

    def with_constraints(self, *constraints: Constraint) -> Leaf:
        """
        Add checks on this leaf

        Parameters
        ----------
        *constraints
            Checks to add

        Returns
        -------
        :
            Updated leaf
        """
        return self.model_copy(
            update={"constraints": (*self.constraints, *constraints)}
        )


class AllOf(BaseModel):
    """
    All children are needed
    """

    model_config = NODE_MODEL_CONFIG

    kind: Literal["all_of"] = "all_of"

    children: tuple[Node, ...]

    @model_validator(mode="after")
    def _distinct_roles(self) -> AllOf:
        role_paths(self)
        return self

    def where(self, **facets: Any) -> AllOf:
        """
        Add facets to every leaf below this node

        Parameters
        ----------
        **facets
            Facet values

        Returns
        -------
        :
            Updated node
        """
        return apply_to_leaves(self, lambda leaf: leaf.where(**facets))

    def with_lineage(self, lineage: Ancestors | Sibling) -> AllOf:
        """
        Set how every leaf below this node finds its reference dataset

        Parameters
        ----------
        lineage
            The relation to use

        Returns
        -------
        :
            Updated node
        """
        return apply_to_leaves(self, lambda leaf: leaf.with_lineage(lineage))

    def with_constraints(self, *constraints: Constraint) -> AllOf:
        """
        Add checks to every leaf below this node, each checked on its own

        Parameters
        ----------
        *constraints
            Checks to add

        Returns
        -------
        :
            Updated node
        """
        return apply_to_leaves(self, lambda leaf: leaf.with_constraints(*constraints))


class AnyOf(BaseModel):
    """
    Alternatives, in order of preference: the first which can be satisfied wins
    """

    model_config = NODE_MODEL_CONFIG

    kind: Literal["any_of"] = "any_of"

    children: tuple[Node, ...] = Field(min_length=2)

    def where(self, **facets: Any) -> AnyOf:
        """
        Add facets to every leaf below this node

        Parameters
        ----------
        **facets
            Facet values

        Returns
        -------
        :
            Updated node
        """
        return apply_to_leaves(self, lambda leaf: leaf.where(**facets))

    def with_lineage(self, lineage: Ancestors | Sibling) -> AnyOf:
        """
        Set how every leaf below this node finds its reference dataset

        Parameters
        ----------
        lineage
            The relation to use

        Returns
        -------
        :
            Updated node
        """
        return apply_to_leaves(self, lambda leaf: leaf.with_lineage(lineage))

    def with_constraints(self, *constraints: Constraint) -> AnyOf:
        """
        Add checks to every leaf below this node, each checked on its own

        Parameters
        ----------
        *constraints
            Checks to add

        Returns
        -------
        :
            Updated node
        """
        return apply_to_leaves(self, lambda leaf: leaf.with_constraints(*constraints))


class OptionalNode(BaseModel):
    """
    Used if it can be satisfied, including its constraints, absent otherwise
    """

    model_config = NODE_MODEL_CONFIG

    kind: Literal["optional"] = "optional"

    child: Node

    def where(self, **facets: Any) -> OptionalNode:
        """
        Add facets to every leaf below this node

        Parameters
        ----------
        **facets
            Facet values

        Returns
        -------
        :
            Updated node
        """
        return apply_to_leaves(self, lambda leaf: leaf.where(**facets))

    def with_lineage(self, lineage: Ancestors | Sibling) -> OptionalNode:
        """
        Set how every leaf below this node finds its reference dataset

        Parameters
        ----------
        lineage
            The relation to use

        Returns
        -------
        :
            Updated node
        """
        return apply_to_leaves(self, lambda leaf: leaf.with_lineage(lineage))

    def with_constraints(self, *constraints: Constraint) -> OptionalNode:
        """
        Add checks to every leaf below this node, each checked on its own

        Parameters
        ----------
        *constraints
            Checks to add

        Returns
        -------
        :
            Updated node
        """
        return apply_to_leaves(self, lambda leaf: leaf.with_constraints(*constraints))


class Namespace(BaseModel):
    """
    Prefixes the roles of everything inside it

    Needed whenever the same role would otherwise appear twice, e.g. the `tas` of
    abrupt-4xCO2 and the `tas` of abrupt-2xCO2 in one requirement.
    Its `constraints` are the place for checks which compare leaves.
    """

    model_config = NODE_MODEL_CONFIG

    kind: Literal["namespace"] = "namespace"

    name: str
    """Prefix for the roles inside, e.g. `abrupt4x` giving `abrupt4x.tas`"""

    child: Node
    """What is inside"""

    constraints: Constraints = ()
    """
    Checks across everything inside this namespace

    Use these for checks which compare leaves. A check about a single dataset
    belongs on its [Leaf][esmporium_processing.requirements.tree.Leaf], so that
    an `optional` part which fails it is dropped rather than failing the group.
    """

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not value or "." in value:
            msg = f"Namespace names must be non-empty and contain no '.', got {value!r}"
            raise ValueError(msg)

        return value

    def where(self, **facets: Any) -> Namespace:
        """
        Add facets to every leaf below this node

        Parameters
        ----------
        **facets
            Facet values

        Returns
        -------
        :
            Updated node
        """
        return apply_to_leaves(self, lambda leaf: leaf.where(**facets))

    def with_lineage(self, lineage: Ancestors | Sibling) -> Namespace:
        """
        Set how every leaf below this node finds its reference dataset

        Parameters
        ----------
        lineage
            The relation to use

        Returns
        -------
        :
            Updated node
        """
        return apply_to_leaves(self, lambda leaf: leaf.with_lineage(lineage))

    def with_constraints(self, *constraints: Constraint) -> Namespace:
        """
        Add checks to every leaf below this node, each checked on its own

        This does not add checks which compare leaves: for those,
        pass `constraints` to
        [namespace][esmporium_processing.requirements.tree.namespace].

        Parameters
        ----------
        *constraints
            Checks to add

        Returns
        -------
        :
            Updated node
        """
        return apply_to_leaves(self, lambda leaf: leaf.with_constraints(*constraints))


class Requirement(BaseModel):
    """
    The root of a requirement: the tree plus how datasets are grouped
    """

    model_config = NODE_MODEL_CONFIG

    name: str
    """Name of the requirement, e.g. used to name its query collection"""

    tree: Node
    """The datasets needed"""

    where: Query = Field(default_factory=Query)
    """
    Facets added to every leaf's query

    A leaf which sets one of these facets differently is an error:
    set each facet once.
    Not applied to auxiliary queries, which would exclude fx data.
    """

    group_by: tuple[str, ...] = ("model", "variant_label")
    """
    Facets which define a group

    Include e.g. `experiment` or `variable` to fan out over their values.

    Project-specific facets (CMIP5's `product`, say) can be used,
    as long as the catalog puts them in each record's `extra`.
    They cannot be checked when the requirement is built,
    because what a catalog can answer is the catalog's business,
    so a facet no record knows fails when the requirement is solved.
    """

    prefer: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    """
    Facet -> values in order of preference, used to break ties between candidates

    Project-specific facets can be used, on the same terms as `group_by`.
    """

    cardinality: Literal["one", "all"] = "one"
    """
    How many datasets each leaf resolves to per group

    `"one"` treats several remaining candidates as ambiguous.
    """

    constraints: Constraints = ()
    """
    Checks across the whole group

    For a check about a single dataset, use the
    [Leaf][esmporium_processing.requirements.tree.Leaf]'s own constraints,
    so that an `optional` part which fails it is dropped rather than
    failing the group.
    """

    def __init__(self, tree: NodeLike | None = None, /, **data: Any) -> None:
        """
        Initialise

        Parameters
        ----------
        tree
            The tree, can also be passed by keyword

        **data
            Other fields
        """
        if tree is not None:
            data["tree"] = as_node(tree)

        super().__init__(**data)

    @model_validator(mode="after")
    def _check_tree(self) -> Requirement:
        role_paths(self.tree)
        # Fail here, rather than when the facets are actually used
        for _, leaf in walk_leaves(self.tree):
            effective_query(leaf, self.where)

        return self

    def canonical_json(self) -> str:
        """
        Get a canonical JSON representation

        Returns
        -------
        :
            JSON with sorted keys and no insignificant whitespace
        """
        return json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )

    def requirement_hash(self) -> str:
        """
        Get a hash which identifies this requirement

        Returns
        -------
        :
            SHA-256 of the canonical JSON
        """
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()


def effective_query(leaf: Leaf, where: Query | None) -> Query:
    """
    Get the query which identifies a leaf's datasets

    Parameters
    ----------
    leaf
        The leaf

    where
        Facets to add, from the requirement

    Returns
    -------
    :
        The combined query

    Raises
    ------
    ConflictingFacetsError
        `where` and the leaf set the same facet to different values
    """
    if where is None:
        return leaf.query

    return add_facets(leaf.query, set_facets(where), leaf.role, "where")


def apply_to_leaves(node: NodeT, update: LeafUpdate) -> NodeT:
    """
    Apply an update to every leaf below a node

    Parameters
    ----------
    node
        Node to update

    update
        What to do to each leaf

    Returns
    -------
    :
        Updated node, of the same kind as `node`
    """
    if isinstance(node, Leaf):
        return cast(NodeT, update(node))

    if isinstance(node, (AllOf, AnyOf)):
        children = tuple(apply_to_leaves(c, update) for c in node.children)
        return cast(NodeT, node.model_copy(update={"children": children}))

    if isinstance(node, (OptionalNode, Namespace)):
        child = apply_to_leaves(node.child, update)
        return cast(NodeT, node.model_copy(update={"child": child}))

    msg = f"Not a node: {node!r}"
    raise TypeError(msg)


def walk_leaves(node: Node, prefix: str = "") -> Iterator[tuple[str, Leaf]]:
    """
    Iterate over every leaf in a tree

    Parameters
    ----------
    node
        Node to walk

    prefix
        Role prefix the node sits under

    Yields
    ------
    :
        The prefix each leaf sits under, and the leaf
    """
    if isinstance(node, Leaf):
        yield prefix, node
    elif isinstance(node, (AllOf, AnyOf)):
        for child in node.children:
            yield from walk_leaves(child, prefix)
    elif isinstance(node, OptionalNode):
        yield from walk_leaves(node.child, prefix)
    else:
        yield from walk_leaves(node.child, f"{prefix}{node.name}.")


def role_paths(node: Node) -> frozenset[str]:
    """
    Get the role paths a node can resolve (`chain.<i>` roles excluded)

    Parameters
    ----------
    node
        Node to inspect

    Returns
    -------
    :
        Role paths

    Raises
    ------
    DuplicateRoleError
        Roles are duplicated in a way which could not be resolved
    """
    if isinstance(node, Leaf):
        paths = {node.role, *(f"{node.role}.{a.role_name}" for a in node.aux)}
        if node.lineage is not None:
            end = f"{node.lineage.role}.{node.role}"
            paths |= {end, *(f"{end}.{a.role_name}" for a in node.aux)}

        return frozenset(paths)

    if isinstance(node, AllOf):
        seen: set[str] = set()
        duplicated: set[str] = set()
        for child in node.children:
            child_roles = role_paths(child)
            duplicated |= seen & child_roles
            seen |= child_roles

        if duplicated:
            raise DuplicateRoleError(duplicated)

        return frozenset(seen)

    if isinstance(node, AnyOf):
        return frozenset().union(*(role_paths(c) for c in node.children))

    if isinstance(node, OptionalNode):
        return role_paths(node.child)

    return frozenset(f"{node.name}.{r}" for r in role_paths(node.child))


def as_node(value: NodeLike) -> Leaf | AllOf | AnyOf | OptionalNode | Namespace:
    """
    Turn a variable name into a leaf, leaving nodes alone

    Parameters
    ----------
    value
        Node, or a variable name

    Returns
    -------
    :
        Node
    """
    if isinstance(value, str):
        return Leaf.of(value)

    return value


def all_of(*nodes: NodeLike) -> AllOf:
    """
    Require all of the given nodes

    Parameters
    ----------
    *nodes
        Nodes (or variable names)

    Returns
    -------
    :
        Node
    """
    return AllOf(children=tuple(as_node(n) for n in nodes))


def any_of(*nodes: NodeLike) -> AnyOf:
    """
    Require the first of the given nodes which can be satisfied

    Parameters
    ----------
    *nodes
        Nodes (or variable names), in order of preference

    Returns
    -------
    :
        Node
    """
    return AnyOf(children=tuple(as_node(n) for n in nodes))


def optional(node: NodeLike) -> OptionalNode:
    """
    Use a node if it can be satisfied

    Parameters
    ----------
    node
        Node (or variable name)

    Returns
    -------
    :
        Node
    """
    return OptionalNode(child=as_node(node))


def namespace(
    name: str, node: NodeLike, constraints: Iterable[Constraint] = ()
) -> Namespace:
    """
    Put a node under a role prefix

    Parameters
    ----------
    name
        Prefix for the roles inside

    node
        Node (or variable name)

    constraints
        Checks across everything inside, i.e. checks which compare leaves

    Returns
    -------
    :
        Node
    """
    return Namespace(name=name, child=as_node(node), constraints=tuple(constraints))


for _model in (Leaf, AllOf, AnyOf, OptionalNode, Namespace, Requirement):
    _model.model_rebuild()
