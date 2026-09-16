"""
Solving requirements: selecting datasets into roles, group by group

The solver is greedy and does not backtrack:

1. groups are the union of `group_by` values over every leaf's candidates
1. per group, the tree is evaluated
    - leaves apply `prefer`; several remaining candidates are ambiguous
      (unless `cardinality="all"`)
    - `any_of` takes the first child which can be satisfied
    - `optional` gives its child or nothing
    - lineages and auxiliary data are resolved for each chosen dataset
    - a leaf's checks run once it resolves, a namespace's once everything
      inside it resolves, and the requirement's once the group resolves

Ambiguous and undetermined outcomes are never skipped over:
an `any_of` stops at them rather than trying the next alternative,
and an `optional` passes them on rather than treating them as absent.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from esmporium.query import Query

from esmporium_processing.requirements.catalog import (
    Catalog,
    DatasetRecord,
    MetadataUnavailableError,
    matches,
    set_facets,
)
from esmporium_processing.requirements.compile import sibling_query
from esmporium_processing.requirements.constraints import (
    Constraint,
    Degraded,
    Fail,
    GroupView,
    Lineage,
)
from esmporium_processing.requirements.relations import Ancestors, Aux, Sibling
from esmporium_processing.requirements.tree import (
    AllOf,
    AnyOf,
    Leaf,
    Namespace,
    Node,
    OptionalNode,
    Requirement,
    effective_query,
    walk_leaves,
)

NotOkStatus = Literal["unsatisfied", "ambiguous", "undetermined"]
"""Ways in which (part of) a requirement can fail to resolve"""

ExplanationStatus = Literal[
    "satisfied", "degraded", "absent", "unsatisfied", "ambiguous", "undetermined"
]
"""Statuses shown in explanations"""

GroupKey = tuple[tuple[str, str | None], ...]
"""`(facet, value)` pairs identifying a group"""

_STATUS_PRIORITY: dict[NotOkStatus, int] = {
    "unsatisfied": 0,
    "ambiguous": 1,
    "undetermined": 2,
}


@dataclass(frozen=True)
class Explanation:
    """
    Why (part of) a requirement did or did not resolve
    """

    subject: str
    """What this explanation is about, e.g. a role path"""

    status: ExplanationStatus
    """Outcome"""

    message: str = ""
    """Details"""

    children: tuple[Explanation, ...] = ()
    """Explanations of the parts"""

    def render(self, indent: int = 0) -> str:
        """
        Render as indented text

        Parameters
        ----------
        indent
            Indentation level to start at

        Returns
        -------
        :
            Rendered explanation
        """
        line = f"{'  ' * indent}[{self.status}] {self.subject}"
        if self.message:
            line = f"{line}: {self.message}"

        return "\n".join([line, *(child.render(indent + 1) for child in self.children)])


@dataclass(frozen=True)
class ResolvedGroup:
    """
    A group for which the requirement is satisfied
    """

    key: GroupKey
    """Values of the `group_by` facets"""

    roles: Mapping[str, tuple[DatasetRecord, ...]]
    """Role path -> datasets"""

    choices: Mapping[str, int]
    """`any_of` label -> index of the alternative used"""

    notes: tuple[str, ...]
    """Absent optional parts, degraded checks, fallback matches"""

    explanation: Explanation
    """How the group was resolved"""

    def one(self, role: str) -> DatasetRecord:
        """
        Get the single dataset in a role

        Parameters
        ----------
        role
            Role path

        Returns
        -------
        :
            The dataset

        Raises
        ------
        KeyError
            The role was not resolved

        ValueError
            The role holds more than one dataset
        """
        records = self.roles[role]
        if len(records) != 1:
            msg = f"{role!r} holds {len(records)} datasets"
            raise ValueError(msg)

        return records[0]


@dataclass(frozen=True)
class UnresolvedGroup:
    """
    A group for which the requirement is not satisfied
    """

    key: GroupKey
    """Values of the `group_by` facets"""

    status: NotOkStatus
    """Why the group did not resolve"""

    explanation: Explanation
    """Details"""


@dataclass(frozen=True)
class SolveResult:
    """
    The result of solving a requirement
    """

    resolved: dict[GroupKey, ResolvedGroup] = field(default_factory=dict)
    unsatisfied: dict[GroupKey, UnresolvedGroup] = field(default_factory=dict)
    ambiguous: dict[GroupKey, UnresolvedGroup] = field(default_factory=dict)
    undetermined: dict[GroupKey, UnresolvedGroup] = field(default_factory=dict)

    def explain(self) -> str:
        """
        Explain every group

        Returns
        -------
        :
            Rendered explanations, one block per group
        """
        groups: list[ResolvedGroup | UnresolvedGroup] = [
            *self.resolved.values(),
            *self.unsatisfied.values(),
            *self.ambiguous.values(),
            *self.undetermined.values(),
        ]
        return "\n\n".join(
            g.explanation.render()
            for g in sorted(groups, key=lambda g: _sortable(g.key))
        )


@dataclass(frozen=True)
class Resolved:
    """
    What one node of the tree resolved to, within one group

    Nodes are resolved bottom-up and merged, so the whole group's
    [ResolvedGroup][esmporium_processing.requirements.solve.ResolvedGroup]
    is the `Resolved` of the requirement's root node.
    """

    roles: dict[str, tuple[DatasetRecord, ...]]
    """Role path -> datasets, including lineage and auxiliary roles"""

    lineages: dict[str, tuple[Lineage, ...]]
    """
    Leaf role path -> lineage of each dataset in that role

    Constraints such as
    [Covers][esmporium_processing.requirements.constraints.Covers] read these.
    """

    choices: dict[str, int]
    """`any_of` label -> index of the alternative which was used"""

    notes: tuple[str, ...]
    """Absent optional parts, degraded checks and fallback matches"""

    explanation: Explanation
    """How this node resolved"""


@dataclass(frozen=True)
class Unresolved:
    """
    Why one node of the tree did not resolve, within one group

    `optional` turns an `"unsatisfied"` child into an absent part,
    but passes `"ambiguous"` and `"undetermined"` on,
    so that a question we cannot answer is never silently treated as a 'no'.
    """

    status: NotOkStatus
    """Why the node did not resolve"""

    explanation: Explanation
    """Details"""


NodeResult = Resolved | Unresolved
"""The result of evaluating one node of the tree, within one group"""


@dataclass(frozen=True)
class _Context:
    """What stays the same while one group is evaluated"""

    requirement: Requirement
    catalog: Catalog
    group: dict[str, str | None]


def _sortable(key: GroupKey) -> tuple[str, ...]:
    return tuple("" if v is None else v for _, v in key)


def describe_query(query: Query) -> str:
    """
    Describe a query briefly

    Parameters
    ----------
    query
        Query to describe

    Returns
    -------
    :
        e.g. `experiment=abrupt-4xCO2|abrupt4xCO2, variable=tas`
    """
    return ", ".join(f"{k}={'|'.join(v)}" for k, v in set_facets(query).items())


def _merge(results: list[Resolved], explanation: Explanation) -> Resolved:
    roles: dict[str, tuple[DatasetRecord, ...]] = {}
    lineages: dict[str, tuple[Lineage, ...]] = {}
    choices: dict[str, int] = {}
    notes: list[str] = []
    for result in results:
        for role, records in result.roles.items():
            roles[role] = roles.get(role, ()) + records

        for role, role_lineages in result.lineages.items():
            lineages[role] = lineages.get(role, ()) + role_lineages

        choices.update(result.choices)
        notes.extend(result.notes)

    return Resolved(roles, lineages, choices, tuple(notes), explanation)


def _worst(results: list[Unresolved]) -> NotOkStatus:
    return min((r.status for r in results), key=_STATUS_PRIORITY.__getitem__)


def _choose(
    candidates: list[DatasetRecord],
    ctx: _Context,
    subject: str,
    cardinality: Literal["one", "all"],
) -> tuple[DatasetRecord, ...] | Unresolved:
    for facet, order in ctx.requirement.prefer.items():
        ranks = [
            order.index(value) if (value := c.facet(facet)) in order else len(order)
            for c in candidates
        ]
        best = min(ranks)
        candidates = [c for c, rank in zip(candidates, ranks) if rank == best]

    if cardinality == "one" and len(candidates) > 1:
        ids = ", ".join(c.id for c in candidates)
        if ctx.requirement.prefer:
            preferences = "; ".join(
                f"{facet} in order {', '.join(order)}"
                for facet, order in ctx.requirement.prefer.items()
            )
            message = (
                f"{len(candidates)} candidates left, "
                f"which preferring {preferences} did not narrow to one: {ids}"
            )
        else:
            message = (
                f"{len(candidates)} candidates and no way to choose between them: "
                f"{ids}. Set `prefer` on the requirement "
                "(e.g. `prefer={'grid_label': ('gn', 'gr')}`), "
                "narrow the query, or use `cardinality='all'`."
            )

        return Unresolved("ambiguous", Explanation(subject, "ambiguous", message))

    return tuple(candidates)


def _lineage(
    record: DatasetRecord, query: Query, leaf: Leaf, ctx: _Context, subject: str
) -> tuple[DatasetRecord, ...] | Unresolved:
    if leaf.lineage is None:
        return (record,)

    if isinstance(leaf.lineage, Sibling):
        return _sibling_lineage(record, query, leaf.lineage, ctx, subject)

    return _ancestor_lineage(record, leaf.lineage, ctx, subject)


def _sibling_lineage(
    record: DatasetRecord,
    query: Query,
    sibling: Sibling,
    ctx: _Context,
    subject: str,
) -> tuple[DatasetRecord, ...] | Unresolved:
    candidates = [
        c
        for c in ctx.catalog.find(sibling_query(query, sibling))
        if all(c.facet(f) == record.facet(f) for f in sibling.match_on)
    ]
    if not candidates:
        return Unresolved(
            "unsatisfied",
            Explanation(
                subject,
                "unsatisfied",
                f"no sibling matching {describe_query(sibling.query)} "
                f"with the same {', '.join(sibling.match_on)} as {record.id}",
            ),
        )

    chosen = _choose(candidates, ctx, subject, "one")
    if isinstance(chosen, Unresolved):
        return chosen

    return (record, *chosen)


def _ancestor_lineage(
    record: DatasetRecord, ancestors: Ancestors, ctx: _Context, subject: str
) -> tuple[DatasetRecord, ...] | Unresolved:
    chain: list[DatasetRecord] = []
    current = record
    for _ in range(ancestors.max_depth):
        parent = ctx.catalog.parent_of(current)
        if parent is None:
            return Unresolved(
                "unsatisfied",
                Explanation(
                    subject,
                    "unsatisfied",
                    f"no parent recorded for {current.id}, before reaching "
                    f"{describe_query(ancestors.until)}",
                ),
            )

        if matches(ancestors.until, parent):
            return (record, *chain, parent)

        chain.append(parent)
        current = parent

    return Unresolved(
        "unsatisfied",
        Explanation(
            subject,
            "unsatisfied",
            f"did not reach {describe_query(ancestors.until)} "
            f"within {ancestors.max_depth} parents of {record.id}",
        ),
    )


def _aux(
    aux: Aux, record: DatasetRecord, ctx: _Context, subject: str
) -> tuple[tuple[DatasetRecord, ...], str | None] | Unresolved:
    """Resolve auxiliary data, returning the datasets and an optional note"""
    if aux.via == "link":
        candidates = [c for c in ctx.catalog.linked(record) if matches(aux.query, c)]
        if not candidates:
            return Unresolved(
                "unsatisfied",
                Explanation(
                    subject,
                    "unsatisfied",
                    f"no dataset linked to {record.id} "
                    f"matches {describe_query(aux.query)}",
                ),
            )
        note = None
    else:
        available = ctx.catalog.find(aux.query)
        candidates = []
        for level_index, level in enumerate(aux.match):
            candidates = [
                c
                for c in available
                if all(c.facet(f) == record.facet(f) for f in level)
            ]
            if candidates:
                break

        if not candidates:
            tried = "; ".join(", ".join(level) for level in aux.match)
            return Unresolved(
                "unsatisfied",
                Explanation(
                    subject,
                    "unsatisfied",
                    f"no {describe_query(aux.query)} with the same facets as "
                    f"{record.id} (match levels tried: {tried})",
                ),
            )

        note = (
            f"{subject}: matched at level {level_index + 1} ({', '.join(level)})"
            if level_index > 0
            else None
        )

    chosen = _choose(candidates, ctx, subject, "one")
    if isinstance(chosen, Unresolved):
        return chosen

    return chosen, note


def _eval_leaf(leaf: Leaf, ctx: _Context, prefix: str) -> NodeResult:
    path = f"{prefix}{leaf.role}"
    query = effective_query(leaf, ctx.requirement.where)
    candidates = [
        c
        for c in ctx.catalog.find(query)
        if all(c.facet(f) == v for f, v in ctx.group.items())
    ]
    if not candidates:
        return Unresolved(
            "unsatisfied",
            Explanation(
                path, "unsatisfied", f"no dataset matches {describe_query(query)}"
            ),
        )

    chosen = _choose(candidates, ctx, path, ctx.requirement.cardinality)
    if isinstance(chosen, Unresolved):
        return chosen

    roles: dict[str, tuple[DatasetRecord, ...]] = {}
    lineages: list[Lineage] = []
    notes: list[str] = []
    children: list[Explanation] = []
    for record in chosen:
        lineage = _lineage(record, query, leaf, ctx, path)
        if isinstance(lineage, Unresolved):
            return lineage

        members = [(path, record)]
        if leaf.lineage is not None and len(lineage) > 1:
            end_role = leaf.lineage.role
            lineages.append(Lineage(members=lineage, end_role=end_role))
            members.extend(
                (f"{prefix}chain.{i}.{leaf.role}", parent)
                for i, parent in enumerate(lineage[1:-1])
            )
            members.append((f"{prefix}{end_role}.{leaf.role}", lineage[-1]))

        for member_path, member in members:
            roles[member_path] = (*roles.get(member_path, ()), member)
            if member_path != path:
                children.append(Explanation(member_path, "satisfied", member.id))

            for aux in leaf.aux:
                if member_path != path and not aux.also_for_lineage:
                    continue

                aux_path = f"{member_path}.{aux.role_name}"
                resolved = _aux(aux, member, ctx, aux_path)
                if isinstance(resolved, Unresolved):
                    if aux.required or resolved.status != "unsatisfied":
                        return Unresolved(
                            resolved.status,
                            Explanation(
                                path,
                                resolved.status,
                                "required auxiliary data not resolved",
                                (*children, resolved.explanation),
                            ),
                        )

                    notes.append(
                        f"optional {aux_path} absent: {resolved.explanation.message}"
                    )
                    children.append(
                        Explanation(aux_path, "absent", resolved.explanation.message)
                    )
                    continue

                aux_records, note = resolved
                roles[aux_path] = roles.get(aux_path, ()) + aux_records
                children.append(
                    Explanation(
                        aux_path,
                        "satisfied",
                        ", ".join(r.id for r in aux_records),
                    )
                )
                if note is not None:
                    notes.append(note)

    leaf_result = Resolved(
        roles,
        {path: tuple(lineages)} if lineages else {},
        {},
        tuple(notes),
        Explanation(
            path, "satisfied", ", ".join(r.id for r in chosen), tuple(children)
        ),
    )
    # A leaf's own checks see only this leaf and its lineage,
    # so an `optional` part which fails them is dropped rather than
    # failing everything around it
    return _evaluate_constraints(leaf.constraints, leaf_result, prefix, ctx, path)


def _label(node: Node) -> str:
    if isinstance(node, Namespace):
        return node.name

    if isinstance(node, Leaf):
        return node.role

    if isinstance(node, AllOf):
        return "+".join(_label(c) for c in node.children)

    if isinstance(node, AnyOf):
        return f"({' | '.join(_label(c) for c in node.children)})"

    return f"optional {_label(node.child)}"


def _eval_any_of(node: AnyOf, ctx: _Context, prefix: str) -> NodeResult:
    label = f"{prefix}any_of({' | '.join(_label(c) for c in node.children)})"
    tried: list[Explanation] = []
    for index, child in enumerate(node.children):
        result = _eval(child, ctx, prefix)
        if isinstance(result, Resolved):
            notes = result.notes
            if index > 0:
                notes = (
                    f"{label}: using alternative {index + 1} "
                    f"({_label(child)}), earlier alternatives unsatisfied",
                    *notes,
                )

            return Resolved(
                result.roles,
                result.lineages,
                {**result.choices, label: index},
                notes,
                Explanation(
                    label,
                    "satisfied",
                    f"alternative {index + 1}",
                    (*tried, result.explanation),
                ),
            )

        tried.append(result.explanation)
        if result.status != "unsatisfied":
            return Unresolved(
                result.status,
                Explanation(
                    label,
                    result.status,
                    f"alternative {index + 1} is {result.status}, "
                    "so later alternatives are not considered",
                    tuple(tried),
                ),
            )

    return Unresolved(
        "unsatisfied",
        Explanation(label, "unsatisfied", "no alternative satisfied", tuple(tried)),
    )


def _evaluate_constraints(
    constraints: tuple[Constraint, ...],
    result: Resolved,
    prefix: str,
    ctx: _Context,
    subject: str,
) -> NodeResult:
    view = GroupView(
        prefix=prefix,
        roles={
            k.removeprefix(prefix): v
            for k, v in result.roles.items()
            if k.startswith(prefix)
        },
        lineages={
            k.removeprefix(prefix): v
            for k, v in result.lineages.items()
            if k.startswith(prefix)
        },
    )
    notes = list(result.notes)
    children = [result.explanation]
    for constraint in constraints:
        name = type(constraint).__name__
        try:
            outcome = constraint.evaluate(view, ctx.catalog)
        except MetadataUnavailableError as exc:
            return Unresolved(
                "undetermined",
                Explanation(
                    subject,
                    "undetermined",
                    f"{name} needs metadata which is not available: {exc}",
                    tuple(children),
                ),
            )

        if isinstance(outcome, Fail):
            return Unresolved(
                "unsatisfied",
                Explanation(
                    subject,
                    "unsatisfied",
                    f"{name}: {outcome.message}",
                    tuple(children),
                ),
            )

        if isinstance(outcome, Degraded):
            notes.append(f"{subject}: {name} degraded: {outcome.message}")
            children.append(Explanation(name, "degraded", outcome.message))

    return Resolved(
        result.roles,
        result.lineages,
        result.choices,
        tuple(notes),
        Explanation(subject, "satisfied", children=tuple(children)),
    )


def _eval_all_of(node: AllOf, ctx: _Context, prefix: str) -> NodeResult:
    results = [_eval(child, ctx, prefix) for child in node.children]
    failures = [r for r in results if isinstance(r, Unresolved)]
    explanations = tuple(r.explanation for r in results)
    label = f"all_of({' & '.join(_label(c) for c in node.children)})"
    if failures:
        status = _worst(failures)
        return Unresolved(status, Explanation(label, status, children=explanations))

    oks = [r for r in results if isinstance(r, Resolved)]
    return _merge(oks, Explanation(label, "satisfied", children=explanations))


def _eval_optional(node: OptionalNode, ctx: _Context, prefix: str) -> NodeResult:
    result = _eval(node.child, ctx, prefix)
    if isinstance(result, Unresolved) and result.status == "unsatisfied":
        label = _label(node)
        return Resolved(
            {},
            {},
            {},
            (f"{label} absent",),
            Explanation(label, "absent", children=(result.explanation,)),
        )

    return result


def _eval_namespace(node: Namespace, ctx: _Context, prefix: str) -> NodeResult:
    inner = f"{prefix}{node.name}."
    result = _eval(node.child, ctx, inner)
    if isinstance(result, Unresolved):
        return Unresolved(
            result.status,
            Explanation(
                f"{prefix}{node.name}",
                result.status,
                children=(result.explanation,),
            ),
        )

    # A namespace's checks see everything inside it, so this is where
    # checks which compare leaves belong
    return _evaluate_constraints(
        node.constraints, result, inner, ctx, f"{prefix}{node.name}"
    )


def _eval(node: Node, ctx: _Context, prefix: str) -> NodeResult:
    if isinstance(node, Leaf):
        return _eval_leaf(node, ctx, prefix)

    if isinstance(node, AllOf):
        return _eval_all_of(node, ctx, prefix)

    if isinstance(node, AnyOf):
        return _eval_any_of(node, ctx, prefix)

    if isinstance(node, OptionalNode):
        return _eval_optional(node, ctx, prefix)

    return _eval_namespace(node, ctx, prefix)


def _group_values(
    requirement: Requirement, catalog: Catalog
) -> list[tuple[str | None, ...]]:
    values: set[tuple[str | None, ...]] = set()
    for _, leaf in walk_leaves(requirement.tree):
        query = effective_query(leaf, requirement.where)
        values.update(
            tuple(record.facet(f) for f in requirement.group_by)
            for record in catalog.find(query)
        )

    # Sorted so that the groups, and therefore the explanations,
    # come out in the same order every time
    return sorted(values, key=lambda v: tuple("" if x is None else x for x in v))


def solve(requirement: Requirement, catalog: Catalog) -> SolveResult:
    """
    Select datasets for a requirement, group by group

    Parameters
    ----------
    requirement
        Requirement to solve

    catalog
        Available datasets

    Returns
    -------
    :
        Resolved and unresolved groups, each with an explanation
    """
    result = SolveResult()
    for values in _group_values(requirement, catalog):
        group = dict(zip(requirement.group_by, values))
        key: GroupKey = tuple(group.items())
        subject = ", ".join(f"{k}={v}" for k, v in key) or "(all datasets)"
        ctx = _Context(requirement=requirement, catalog=catalog, group=group)

        evaluated = _eval(requirement.tree, ctx, "")
        if isinstance(evaluated, Resolved):
            evaluated = _evaluate_constraints(
                requirement.constraints, evaluated, "", ctx, subject
            )
        else:
            evaluated = Unresolved(
                evaluated.status,
                Explanation(
                    subject, evaluated.status, children=(evaluated.explanation,)
                ),
            )

        if isinstance(evaluated, Resolved):
            result.resolved[key] = ResolvedGroup(
                key=key,
                roles=evaluated.roles,
                choices=evaluated.choices,
                notes=evaluated.notes,
                explanation=evaluated.explanation,
            )
        else:
            getattr(result, evaluated.status)[key] = UnresolvedGroup(
                key=key, status=evaluated.status, explanation=evaluated.explanation
            )

    return result
