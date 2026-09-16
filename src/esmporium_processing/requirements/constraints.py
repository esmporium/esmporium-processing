"""
Constraints: pluggable checks on resolved datasets

**Constraints must remain a pluggable protocol**,
both here and once requirements move into esmporium.
[Constraint][esmporium_processing.requirements.constraints.Constraint]
is the extension point: anything implementing it can be passed to a
[Leaf][esmporium_processing.requirements.tree.Leaf], a
[Namespace][esmporium_processing.requirements.tree.Namespace] or a
[Requirement][esmporium_processing.requirements.tree.Requirement].
Where it is attached decides what a failure means: a leaf's check failing makes
that leaf unsatisfied, so an `optional` part around it is dropped, while a
requirement's check failing fails the whole group.
The solver never special-cases the constraints defined in this module,
they are simply implementations we happen to ship.

For requirements to be serialisable, constraints must also be pydantic models
that can be imported by their fully qualified name.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Protocol, TypeGuard, cast

from pydantic import BaseModel, ConfigDict, PlainSerializer, PlainValidator

from esmporium_processing.requirements.catalog import Catalog, DatasetRecord

TIME_RANGE = "time_range"
"""
Metadata key: `(start, end)` of a dataset, in fractional years of its own time axis

`end` is exclusive.
"""

BRANCH_TIME_IN_PARENT = "branch_time_in_parent"
"""
Metadata key: the time in the parent's time axis (fractional years)
at which a dataset branches, i.e. which corresponds to its own start
"""


@dataclass(frozen=True)
class Pass:
    """The constraint is met"""

    message: str = ""


@dataclass(frozen=True)
class Degraded:
    """The constraint is met, but not ideally. The group is kept, the message noted."""

    message: str


@dataclass(frozen=True)
class Fail:
    """The constraint is not met"""

    message: str


Outcome = Pass | Degraded | Fail
"""The outcome of evaluating a constraint"""


@dataclass(frozen=True)
class Lineage:
    """
    The datasets a leaf's lineage resolved to, and what they are called
    """

    members: tuple[DatasetRecord, ...]
    """`(anchor, *intermediate_parents, end)`"""

    end_role: str
    """
    Role the last member was resolved into

    This is the `role` of the
    [Ancestors][esmporium_processing.requirements.relations.Ancestors] or
    [Sibling][esmporium_processing.requirements.relations.Sibling] relation,
    e.g. `"control"`.
    """

    def index_of(self, role: str) -> int:
        """
        Get the position in the lineage a role refers to

        Parameters
        ----------
        role
            `"self"` for the anchor dataset, `"chain.<i>"` for an intermediate
            parent, or the lineage's `end_role` (`"end"` also works, for
            constraints written without knowing the name)

        Returns
        -------
        :
            Position in `members`

        Raises
        ------
        ValueError
            `role` is not part of this lineage
        """
        if role == "self":
            return 0

        if role in (self.end_role, "end"):
            return len(self.members) - 1

        head, _, index = role.partition(".")
        if head == "chain" and index.isdigit():
            position = int(index) + 1
            if position < len(self.members) - 1:
                return position

        msg = (
            f"{role!r} is not in this lineage: "
            f"use 'self', {self.end_role!r} (or 'end') "
            f"or 'chain.<i>' with i < {max(len(self.members) - 2, 0)}"
        )
        raise ValueError(msg)


@dataclass(frozen=True)
class GroupView:
    """
    What a constraint can see of the datasets resolved so far

    Role names given to and returned by this view are relative to `prefix`.
    """

    prefix: str
    """
    Prefix of the scope being checked

    For example, `"abrupt4x."` when checking a simulation named `abrupt4x`,
    or `""` when checking the whole group.
    """

    roles: Mapping[str, tuple[DatasetRecord, ...]]
    """Role path (relative to `prefix`) -> datasets"""

    lineages: Mapping[str, tuple[Lineage, ...]]
    """
    Leaf role (relative to `prefix`) -> lineage of each dataset in that role

    Leaves without a lineage relation are absent.
    """


class Constraint(Protocol):
    """
    A check on resolved datasets

    This protocol is the extension point for constraints and must stay pluggable.

    If metadata needed by the check has not been recorded,
    [Catalog.metadata][esmporium_processing.requirements.catalog.Catalog.metadata]

    Raises
    ------
    [MetadataUnavailableError][esmporium_processing.requirements.catalog.MetadataUnavailableError].
    Let it propagate: the solver turns it into an 'undetermined' outcome
    so that the check never silently passes.
    """

    def required_metadata(self) -> frozenset[str]:
        """
        Get the metadata keys this constraint reads

        Returns
        -------
        :
            Metadata keys e.g. `{"time_range"}`
        """
        ...

    def evaluate(self, view: GroupView, catalog: Catalog) -> Outcome:
        """
        Evaluate the constraint

        Parameters
        ----------
        view
            The resolved datasets in scope

        catalog
            Catalog, used to get metadata

        Returns
        -------
        :
            Outcome of the check
        """
        ...


class NotSerialisableConstraintError(TypeError):
    """Raised when a constraint cannot be serialised."""

    def __init__(self, constraint: object) -> None:
        """
        Initialise the error

        Parameters
        ----------
        constraint
            The constraint which cannot be serialised
        """
        super().__init__(
            f"{type(constraint).__qualname__} is not a pydantic model, "
            "so requirements using it cannot be serialised. "
            "Make constraints pydantic models to store requirements."
        )


class NotAConstraintError(TypeError):
    """Raised when something passed as a constraint does not implement the protocol."""

    def __init__(self, value: object) -> None:
        """
        Initialise the error

        Parameters
        ----------
        value
            The value which is not a constraint
        """
        super().__init__(
            f"{value!r} is not a constraint: "
            "it needs `required_metadata()` and `evaluate(view, catalog)` methods"
        )


def _is_constraint(value: object) -> TypeGuard[Constraint]:
    return callable(getattr(value, "required_metadata", None)) and callable(
        getattr(value, "evaluate", None)
    )


def _load_constraint(value: object) -> Constraint:
    if _is_constraint(value):
        return value

    if isinstance(value, dict) and "type" in value:
        serialised = cast(dict[str, Any], value)
        module_name, _, qualname = str(serialised["type"]).partition(":")
        target: Any = importlib.import_module(module_name)
        for attribute in qualname.split("."):
            target = getattr(target, attribute)

        loaded: object = target.model_validate(
            {k: v for k, v in serialised.items() if k != "type"}
        )
        if _is_constraint(loaded):
            return loaded

    raise NotAConstraintError(value)


def _validate_constraints(value: object) -> tuple[Constraint, ...]:
    if not isinstance(value, (list, tuple)):
        raise NotAConstraintError(value)

    return tuple(_load_constraint(v) for v in value)


def _serialise_constraints(value: tuple[Constraint, ...]) -> list[dict[str, Any]]:
    out = []
    for constraint in value:
        if not isinstance(constraint, BaseModel):
            raise NotSerialisableConstraintError(constraint)

        cls = type(constraint)
        out.append(
            {
                "type": f"{cls.__module__}:{cls.__qualname__}",
                **constraint.model_dump(mode="json"),
            }
        )

    return out


Constraints = Annotated[
    tuple[Constraint, ...],
    # Constraints are part of a requirement, and requirements are serialised so
    # that they can be stored and compared over time
    # (a stored requirement plus its hash is what makes two solve results
    # comparable, see PLAN-REQUIREMENTS.md).
    # Deserialising is what lets a stored requirement be solved again later,
    # which is why the import path is carried rather than only dumped.
    PlainValidator(_validate_constraints),
    PlainSerializer(_serialise_constraints),
]
"""
Field type for holding constraints on pydantic models

Serialised constraints carry their import path.
Loading a serialised requirement therefore imports the named module:
only load requirements you trust.
"""


def _as_year(value: object, what: str) -> float:
    if isinstance(value, (int, float)):
        return float(value)

    msg = f"{what} should be a number of years, got {value!r}"
    raise TypeError(msg)


def _as_time_range(catalog: Catalog, record: DatasetRecord) -> tuple[float, float]:
    raw = catalog.metadata(record, TIME_RANGE)
    what = f"{TIME_RANGE} of {record.id}"
    if not isinstance(raw, (tuple, list)) or len(raw) != 2:  # noqa: PLR2004
        msg = f"{what} should be (start, end), got {raw!r}"
        raise TypeError(msg)

    return _as_year(raw[0], what), _as_year(raw[1], what)


class Covers(BaseModel):
    """
    One dataset in a lineage must cover the span of another

    For example, `Covers("control", "self")` requires each dataset's control
    to cover the dataset's span.

    With `align="branch"`, `target`'s span (plus that of every dataset between
    `target` and `role` in the lineage) is mapped into `role`'s time axis
    using the recorded branch times.
    With `align="calendar"`, time ranges are compared directly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str
    """
    The covering dataset, named as the lineage names it

    Usually the `role` of the simulation's lineage, e.g. `"control"`.
    `"self"` is the anchor dataset, `"chain.<i>"` an intermediate parent,
    and `"end"` works wherever the lineage stops, for constraints written
    without knowing the lineage's role name.
    """

    target: str = "self"
    """The covered dataset, named the same way as `role`"""

    align: Literal["branch", "calendar"] = "branch"
    """How to align the time axes"""

    pad_years: tuple[float, float] | None = (0.0, 0.0)
    """
    Years `role` must additionally cover before and after the target span

    If `None`, coverage is not required, only checked against `ideal_pad_years`.
    """

    ideal_pad_years: tuple[float, float] | None = None
    """
    Years `role` should ideally cover before and after the target span

    If this is not met (but `pad_years` is), the outcome is degraded.
    """

    def required_metadata(self) -> frozenset[str]:
        """
        Get the metadata keys this constraint reads

        Returns
        -------
        :
            Metadata keys
        """
        if self.align == "branch":
            return frozenset({TIME_RANGE, BRANCH_TIME_IN_PARENT})

        return frozenset({TIME_RANGE})

    def _needed_span(self, lineage: Lineage, catalog: Catalog) -> tuple[float, float]:
        # Note: we'll have to make the time handling clearer when we break things out.
        # In particular to make it easy for users to see how to override
        # given branch time values (these often have bugs).
        # This is fine for now.
        members = lineage.members
        target_index = lineage.index_of(self.target)
        role_index = lineage.index_of(self.role)
        if self.align == "calendar":
            return _as_time_range(catalog, members[target_index])

        if target_index >= role_index:
            msg = (
                f"With align='branch', {self.role!r} must be an ancestor "
                f"of {self.target!r}"
            )
            raise ValueError(msg)

        starts: list[float] = []
        ends: list[float] = []
        for member_index in range(target_index, role_index):
            start, end = _as_time_range(catalog, members[member_index])
            # Map this member's span up the lineage into the role's time axis
            for step in range(member_index, role_index):
                step_start, _ = _as_time_range(catalog, members[step])
                branch = _as_year(
                    catalog.metadata(members[step], BRANCH_TIME_IN_PARENT),
                    f"{BRANCH_TIME_IN_PARENT} of {members[step].id}",
                )
                start, end = branch + (start - step_start), branch + (end - step_start)

            starts.append(start)
            ends.append(end)

        return min(starts), max(ends)

    def evaluate(self, view: GroupView, catalog: Catalog) -> Outcome:
        """
        Evaluate the constraint

        Parameters
        ----------
        view
            The resolved datasets in scope

        catalog
            Catalog, used to get metadata

        Returns
        -------
        :
            Outcome of the check
        """
        if not view.lineages:
            return Fail("Covers needs a lineage, but none was resolved")

        degraded: list[str] = []
        for leaf_role, lineages in sorted(view.lineages.items()):
            for lineage in lineages:
                need_start, need_end = self._needed_span(lineage, catalog)
                covering = lineage.members[lineage.index_of(self.role)]
                have_start, have_end = _as_time_range(catalog, covering)

                description = (
                    f"{view.prefix}{leaf_role}: {covering.id} covers "
                    f"[{have_start:g}, {have_end:g}), "
                    f"needed [{need_start:g}, {need_end:g})"
                )
                if self.pad_years is not None and not _covers(
                    have_start, have_end, need_start, need_end, self.pad_years
                ):
                    return Fail(f"{description} with padding {self.pad_years}")

                if self.ideal_pad_years is not None and not _covers(
                    have_start, have_end, need_start, need_end, self.ideal_pad_years
                ):
                    degraded.append(
                        f"{description}, ideal padding {self.ideal_pad_years} not met"
                    )

        if degraded:
            return Degraded("; ".join(degraded))

        return Pass()


def _covers(
    have_start: float,
    have_end: float,
    need_start: float,
    need_end: float,
    pad: tuple[float, float],
) -> bool:
    return have_start <= need_start - pad[0] and have_end >= need_end + pad[1]


class SameTimeRange(BaseModel):
    """
    Several roles must cover the same period

    A check which compares leaves, so it belongs on a namespace or on the
    requirement rather than on a leaf. For example, a Gregory regression uses
    temperature and radiation together, so it wants them over the same years.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    roles: tuple[str, ...]
    """Roles to compare, relative to the scope being checked"""

    def required_metadata(self) -> frozenset[str]:
        """
        Get the metadata keys this constraint reads

        Returns
        -------
        :
            Metadata keys
        """
        return frozenset({TIME_RANGE})

    def evaluate(self, view: GroupView, catalog: Catalog) -> Outcome:
        """
        Evaluate the constraint

        Roles which did not resolve are skipped, so an optional part which is
        absent does not make this fail.

        Parameters
        ----------
        view
            The resolved datasets in scope

        catalog
            Catalog, used to get metadata

        Returns
        -------
        :
            Outcome of the check
        """
        spans = [
            (f"{view.prefix}{role}", record.id, _as_time_range(catalog, record))
            for role in self.roles
            for record in view.roles.get(role, ())
        ]
        if len(spans) < 2:  # noqa: PLR2004 - nothing to compare
            return Pass()

        if len({span for _, _, span in spans}) == 1:
            return Pass()

        described = "; ".join(
            f"{role} ({dataset_id}) [{start:g}, {end:g})"
            for role, dataset_id, (start, end) in spans
        )
        overlap_start = max(start for _, _, (start, _) in spans)
        overlap_end = min(end for _, _, (_, end) in spans)
        if overlap_start >= overlap_end:
            return Fail(f"no period is covered by all of: {described}")

        return Degraded(
            f"periods differ, only [{overlap_start:g}, {overlap_end:g}) "
            f"is covered by all of: {described}"
        )
