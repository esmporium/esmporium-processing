# Expressing analysis data requirements

Short design note for the prototype in `src/esmporium_processing/requirements/`.
Expect to throw this away. The code and the use cases in
`tests/unit/requirements/use_cases.py` are the source of truth.

Written: 2026-09-14.

## Where this is going

Requirements will move into esmporium.
esmporium then owns the database, requirement-driven searches, solving,
and storing requirements and their results.
esmporium-processing keeps only the analyses, which declare requirements.

To keep that move mechanical, `esmporium_processing.requirements` imports only
esmporium, pydantic and the standard library. A test enforces this.

**Constraints must remain a pluggable protocol, here and in esmporium.**
`Covers` is just one implementation. The solver never special-cases it.

## Three kinds of "or"

| Kind | Example | Expressed as |
|---|---|---|
| Alias | `abrupt-4xCO2` / `abrupt4xCO2`, `fLuc` / `fLUC` | Tuple facet values in `Query` |
| Fan-out | Any of the piClim experiments, each analysed separately | `group_by` includes the facet |
| Alternative | `sfcWind` or (`uas` and `vas`) | `any_of(...)`: first that can be satisfied wins |

Most "or"s in the use cases are fan-outs.

## The tree

A leaf carries everything about one dataset, because that is where the work happens:

- **`Leaf.of(query, role=, aux=, lineage=, constraints=)`** — one dataset per group. A bare string means `Query(variable=...)`. A facet with several values is an OR, exactly as in esmporium, so `variable=("fLuc", "fLUC")` takes either. The role says what the dataset is *for*, which is why pattern scaling's nine variables sit in one leaf called `field`, with the variable itself in the group key.
- **`all_of`, `any_of` (ordered) and `optional`.** An optional part must meet its own constraints, otherwise it is absent.
- **`namespace(name, child, constraints=)`** — prefixes roles, so the same role can appear twice (`abrupt4x.tas` and `abrupt2x.tas`), and holds checks which compare leaves.
- **`Requirement(tree, name=, where=, group_by=, prefer=, cardinality=, constraints=)`** — the root.

Every node has the same three ways to say something about the leaves below it, and each pushes down to the leaves:

| Helper | Sets | Contradiction |
|---|---|---|
| `.where(**facets)` | facets on each leaf's query | raises `ConflictingFacetsError` |
| `.with_lineage(relation)` | how each leaf finds its control | replaces |
| `.with_constraints(*checks)` | checks on each leaf, one leaf at a time | adds |

`Requirement.where` does the same thing for the whole tree, and raises the same
error when a leaf already sets a facet differently: **set each facet once.**

There is deliberately no node for "one experiment": that was four separable
things in a trench coat (shared facets, a lineage, scoped checks and a role
prefix), and each now has one home.

Resolved roles look like `tas`, `control.tas`, `chain.0.tas`, `nbp.sftlf`
and, inside a namespace, `abrupt4x.control.tas`.

## Relations

`group_by` applies to the datasets a leaf selects. Everything else hangs off one of those:

- **`Ancestors(until=..., role=...)`** walks parent links, which come from file headers (esmporium PR6). `until` is a query, so `("piControl", "esm-piControl")` works. `role` is **required**, names the dataset it stops at, and is what constraints refer to: write `role="control"` when walking back to piControl, `role="historical"` when that is where you stop.
- **`Sibling(query, match_on=..., role=...)`** matches facets instead. piClim-histall and piClim-control are both children of piControl, so ERF needs this.
- **`Aux(query, required=, match=, via=, also_for_lineage=)`** is auxiliary data, **named explicitly** by the user: sftlf for land variables, sftof for ocean ones, and areacella, areacello or areacellr. There is no built-in mapping.
  - `via="match"` (the default) compares facets level by level. The default is a **single strict level** (model, grid, experiment, variant), so fallbacks are opt-in: see `FX_FALLBACK` in the use cases.
  - `via="link"` follows dataset-to-dataset links. **This is where all of it should end up:** esmporium links at ingestion, once, so every analysis reads the same answer instead of redoing the matching. `match` stays as the fallback for whatever is not linked yet, and should be rare.
  - `also_for_lineage` (True by default) says whether the control needs the auxiliary data too.

Proposed esmporium work: create those links from each file's **`cell_measures`** attribute only, e.g. tas → areacella.
`cell_methods` names an area type, not a variable, so it isn't used.
Picking *which* areacella dataset to link is also strict by default, with fallbacks opt-in and recorded on the link.

## Constraints

A `Constraint` declares the metadata it needs and returns `Pass`, `Degraded(msg)` or `Fail(msg)`.

**Where a check goes decides what happens when it fails**, which is the point of
attaching them at three levels:

- **On a leaf** (most checks): it sees that dataset and its lineage. A failure
  fails that leaf, so an `optional` part around it is simply dropped.
- **On a namespace**: it sees everything inside. This is the home for checks
  which compare leaves.
- **On the requirement**: it sees the whole group.

Shipped checks:

- **`Covers(role, target, align="branch" | "calendar", pad_years=, ideal_pad_years=)`** — e.g. the control covers the dataset's span, mapped through branch times along the whole chain. `pad_years=None` makes it soft. `role` and `target` name datasets **as the lineage names them**, which is why a lineage's `role` is required: `Covers(role="control")` and `Ancestors(role="control")` are visibly the same thing. `"self"` is the anchor, `"chain.<i>"` an intermediate parent, `"end"` works without knowing the name.
- **`SameTimeRange(roles)`** — a cross-leaf check: a Gregory regression uses temperature and radiation together, so ECS puts this on its namespace. Identical periods pass, overlapping ones degrade (naming the overlap), disjoint ones fail.

**Serialisation:** constraints are stored with their import path, so they must be pydantic models to serialise.

## Solving

`solve(requirement, catalog)` is greedy, with no backtracking.

- **Groups** are the union of `group_by` values over every leaf's candidates.
- **Leaves** apply `prefer`, then resolve their lineage, auxiliary data and own checks. If several candidates remain, the group is `ambiguous`.
- **Ambiguous and undetermined results are never skipped**: `any_of` stops at them, and `optional` passes them on.
- **Output:** resolved, unsatisfied, ambiguous and undetermined groups, each with an explanation tree (`SolveResult.explain()`). Per node, `Resolved` and `Unresolved` carry the roles, lineages, choices and notes that are merged upwards.

`Catalog` is a protocol with `find`, `parent_of`, `linked` and `metadata`.
`InMemoryCatalog` stands in until esmporium has parent links and file information.

## Flow and storage

1. `to_search_plan(requirement)` returns queries for every leaf (including optional ones and every alternative), sibling queries and auxiliary queries. Leaves that differ only in variable are merged, which `merge_variables=False` turns off. It also returns `ancestry_until`.
2. esmporium searches (`QueryCollection`, PR3.7), then adds parent links (PR6).
3. `solve`.

A `QueryCollection` that is a plain union is enough.
"Requirement became satisfiable" is the difference between `solve` at t1 and at t2.
Storing requirements (their canonical JSON and hash) and solve snapshots only matters for that comparison.
Once requirements are in esmporium, those are ordinary esmporium tables.

## Global mean of piControl vs global mean of a scenario

For `PLAN-LOAD-CLAUDE.md`:

- **Types name the transformation:** `GlobalMean`.
- **Annotations name the role:** `Annotated[GlobalMean, From("abrupt4x.control.tas")]`.
- **A DAG node's identity** is (step, version, input dataset IDs, params). A shared piControl global mean is therefore computed once, with no extra types.

This is not prototyped yet.

## Examples

```python
TO_CONTROL = Ancestors(until=Q(experiment=("piControl", "esm-piControl")), role="control")
CONTROL_COVERS = Covers(role="control", target="self", ideal_pad_years=(20, 20))
RADIATION = all_of(atmos("rsdt"), atmos("rlut"), atmos("rsut"))

def abrupt(name, experiment):
    return namespace(
        name,
        all_of(atmos("tas"), RADIATION)
        .where(experiment=experiment)
        .with_lineage(TO_CONTROL)
        .with_constraints(CONTROL_COVERS),
        constraints=[SameTimeRange(roles=("tas", "rsdt", "rlut", "rsut"))],
    )

ECS = Requirement(
    all_of(
        abrupt("abrupt4x", ("abrupt-4xCO2", "abrupt4xCO2")),
        optional(abrupt("abrupt2x", "abrupt-2xCO2")),
        optional(abrupt("abrupt0p5x", "abrupt-0p5xCO2")),
    ),
    name="ecs",
    where=Q(reporting_interval="mon"),
)
```

Read that as: these variables, from this experiment, back to the control, which
must cover them; and across the four of them, the same period.

With only one simulation involved, no namespace is needed:

```python
TCR = Requirement(
    atmos("tas")
    .where(experiment="1pctCO2")
    .with_lineage(TO_CONTROL)
    .with_constraints(CONTROL_COVERS),
    name="tcr",
    where=Q(reporting_interval="mon"),
)
```

Carbon-cycle closure: land variables need sftlf, the 1pctCO2 simulation is
required, and every other experiment is its own optional namespace, so several
being available is not ambiguous:

```python
def land(v, role=None):
    return Leaf.of(Q(variable=v), role=role,
                   aux=[Aux(Q(variable="sftlf")), Aux(Q(variable="areacella"), required=False)])

needs = all_of(
    any_of(land("cLand"), all_of(land("cVeg"), land("cLitter"), land("cSoil"), land("cProduct"))),
    any_of(land("npp"), all_of(land("gpp"), land("ra"))),
    land("rh"),
    optional(land(("fLuc", "fLUC"), role="fLuc")),
    ...
)
CARBON_CLOSURE = Requirement(
    all_of(
        namespace("onepct", needs.where(experiment="1pctCO2")),
        *(optional(namespace(e, needs.where(experiment=e))) for e in OTHER_EXPERIMENTS),
    ),
    name="carbon-closure",
    where=Q(reporting_interval="mon"),
)
```

## Findings worth remembering

These come from the CMIP6 CMOR tables and the CVs (read WCRP-universe, not CMIP7-CVs, for parents).

- **Fractions:** land carbon variables and nbp are `area: mean where land`, so they need sftlf. fgco2, hfds and siconc are `mean where sea`, with areacello, so they need sftof. fCLandToOcean uses areacellr.
- **Radiation:** there is no `rndt`, so radiation is rsdt, rlut and rsut. `rtmt` is top of *model*.
- **Parents:**
  - esm-bell-\* → esm-piControl.
  - esm-1pct-brch-\* → 1pctCO2 or esm-1pctCO2.
  - esm-flat10 → esm-piControl; esm-flat10-zec and -cdr → esm-flat10, at the end of year 100.
  - piClim-control and piClim-histall → piControl.
- **Case:** CMIP7 CV IDs are lower-case. Check whether ESGF facet values are too.

## Queries and facets

`set_facets` flattens a query, including `other_terms`, because that is esmporium's
escape hatch for facets a query class does not name.
Naming the same facet twice raises `ClashingFacetError`.

**Project-specific facets are supported, and esmporium decides how.**
Answering a query which names CMIP5's `product` is `Catalog.find`'s business, and
nothing here needs to know how it is done. The one thing selection needs is that
grouping, `prefer` and auxiliary matching compare *records*, so a catalog must put
any facet it wants used that way into each record's `extra`. Requirements therefore
accept any facet name, and a facet no record knows fails when solving, naming the
facet and the dataset.

## Known limits of the prototype

- **Greedy solving:** a choice made for one leaf is never revisited to satisfy another.
- **Searching may be wider than needed:** auxiliary queries inherit nothing, so they find fx data for every model. If that proves too broad, narrow first and widen only when nothing is found, the way `ancestry_until` is handled.
- **Times are plain years:** `time_range` and `branch_time_in_parent` are floats, not calendars.
- **Wrapped errors:** errors raised in pydantic validators surface as `ValidationError`.
- **Trust when loading:** loading a serialised requirement imports constraint classes by name, so only load requirements you trust.
