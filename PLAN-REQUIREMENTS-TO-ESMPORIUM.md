# Moving requirements into esmporium

How the prototype in `src/esmporium_processing/requirements/` becomes
`src/esmporium/requirements/`, in reviewable pieces.

Written: 2026-09-16.

## Claude note:

We are in the developement phase and over the course of this plan we will be making changes
and updates to the database and schema. You do not need to worry at all about breaking the 
API or database caused by migrations, because there are no users of this package. You have 
full freedom because the plans to build up the package into a working prototype will require 
breaking the current database logic. Please keep this in mind for all future prompts. 

## Context

`PLAN-REQUIREMENTS.md` says where this is going: **requirements move into esmporium**, which
then owns the database, requirement-driven searches, solving, and storing requirements and
their results. esmporium-processing keeps only the analyses, which declare requirements. The
prototype was written to make that move mechanical — it imports only esmporium, pydantic and
the standard library, and a test enforces it.

What is left is the sizing problem: 3 305 src lines, 1 802 test lines and 20 use cases, to be
landed in 100–1000 line PRs.

Two obvious orderings both have a real cost. Starting from the high-level interface — the one
we actually care about — and building complexity outwards churns every PR and re-teaches the
mental model each time. Starting from the lowest-level pieces churns almost nothing, but
leaves each piece unmotivated: it is hard to see why `Aux.match` is a tuple of tuples, or why
a lineage's `role` is required, without the high-level context.

## The ordering: a walking skeleton, then thicken

Three small PRs build a thin end-to-end slice — entries and matching, `Leaf`/`all_of`/
`Requirement`, then `solve` — so that a requirement can actually be solved by **R3**, roughly
1 300 lines in. From there every PR adds exactly one concept.

Three things make the rest cheap:

- **The node types are purely additive.** After R2 the `Node` union has two members. Each
  later node type is one more entry in that union plus one more branch in four small dispatch
  functions (`apply_to_leaves`, `walk_leaves`, `role_paths`, `_eval`). Nothing already written
  is reshaped.
- **The design note lands first (R0),** so every low-level PR can be read against a stated
  target. This is the direct answer to "it is hard to see why the low-level pieces are how
  they are".
- **The use cases grow PR by PR.** `use_cases.py` starts at R3 with one case and each later PR
  adds the cases it unlocks, so every PR ends with "and these real use cases now build and
  solve". Every low-level PR gets a high-level anchor without anyone having to invent one.

Numbered `R0`–`R12` rather than continuing esmporium's `PR1…PR9`, because **nothing here
depends on esmporium's PR4–PR9**; this can run in parallel with them. Only the follow-up
database-backed catalogue is gated on PR6 (parent links) and PR7 (file information).

| PR | Concept added | src | tests | Use cases unlocked |
|---|---|---|---|---|
| R0 | The design note, as docs including ascii or other plain text diagram(s) | ~300 | — | — |
| R1 | Entries, facets and matching | ~310 | ~160 | — |
| R2 | `Leaf`, `all_of`, `Requirement`, `.where()` | ~565 | ~200 | — |
| R3 | **`solve` — end to end works here** | ~450 | ~475 | 14 |
| R4 | `to_search_plan` | ~150 | ~135 | — 
| R5 | `Ancestors` lineage | ~325 | ~260 | 15, 17 |
| R6 | The `Constraint` protocol (no shipped checks) | ~425 | ~230 | — |
| R7 | `Covers` | ~190 | ~280 | 01, 03, 04, 05, 11 |
| R8 | `any_of`, `optional` | ~235 | ~300 | 06, 07, 08, 12, 18 |
| R9 | `namespace`, `SameTimeRange` | ~215 | ~270 | 02, 16, 16a |
| R10 | `Sibling` | ~110 | ~170 | 09, 10 |
| R11 | `Aux` | ~280 | ~400 | 13, 19 |
| R12 | `to_search_plan` |
| R13 | Retire the prototype | — | — | — |

Totals: ~3 255 src lines against the prototype's 3 305 — a useful check that the slices cover
the whole thing.

## Decisions taken up front

| Decision | Choice |
|---|---|
| Read-side dataset type | `CatalogueEntry`, kept separate from `DatasetFacets` and pinned by a drift test |
| Database-backed catalogue | Out of scope; protocol plus `InMemoryCatalogue` only |
| Use cases | Grown PR by PR inside esmporium's tests |
| Spelling | British English: `Catalogue`, `CatalogueEntry`, `InMemoryCatalogue`, `catalogue.py` |

Need to database-backed catalogue at some point, but requires doing some esmporium work yet so isn't part of this translation step.

### Why `CatalogueEntry` and not `DatasetFacets`

`DatasetFacets` (`esmporium/search/result_parsing.py`) already mirrors `Dataset`'s facet
columns, so it is the obvious candidate. It is the wrong one, because it is the **write-side**
DTO: parsers produce it and `save_dataset` turns it into a row. It has no surrogate `id`
because the row does not exist yet, and it is `extra="forbid"` precisely so that a parser
which invents a facet fails loudly.

The solver needs the **read-side** projection of a row that does exist: a stable `id` — every
parent link, aux link, metadata lookup and error message keys off it — and a deliberately
*open* `extra`, which is the documented home for project-specific facets used by `group_by`,
`prefer` and auxiliary matching. Merging the two gives one class whose `id` is `None` half the
time and whose `extra` must be forbidden on one path and open on the other.
(Let's think about whether we call this `extra` or something else and how we handle it exactly.)

Inheriting is wrong for a smaller reason: `DatasetFacets` is `DATASET_FACET_COLUMNS` *plus*
`id_project_specific`, whereas `CatalogueEntry.facet()` answers only for
`DATASET_FACET_COLUMNS` + `extra`. A subclass would carry a required `id_project_specific`
field that `.facet("id_project_specific")` then refuses to answer for.

esmporium already has a convention for this exact shape of problem — two classes mirroring the
same facets, kept separate and pinned by a single assertion whose docstring says the
hand-written list is deliberate, because "changing our Dataset model is a big deal"
(`tests/unit/test_schema.py`, `test_dataset_facets_mirror_dataset_columns`). R1 follows it.

The name is `CatalogueEntry` rather than `DatasetRecord` or `DatasetCandidate` because, of its
33 use sites, only three are candidate-shaped (`_choose`'s parameter and `_eval_leaf`'s local).
The rest hold datasets already decided on — `ResolvedGroup.roles`, `Lineage.members`,
`GroupView.roles`, the parent from `parent_of`, the auxiliary data from `linked`, the subject
of `metadata(...)` — plus `InMemoryCatalogue.records`, which is simply the catalogue's
contents, with no requirement in sight. Naming it for the layer that owns it reads correctly
everywhere.

## Deliberate deviations from the prototype

Each is small, and each exists because the incremental order exposes something an all-at-once
prototype could ignore. Listed so that anyone diffing against the prototype is not surprised.

1. **`Catalog` → `Catalogue`, `DatasetRecord` → `CatalogueEntry`, `catalog.py` →
   `catalogue.py`.** Spelling and naming, as above.
2. **`Lineage` moves from `constraints.py` to `relations.py`.** It is the resolved form of
   `Ancestors`/`Sibling`, and solving needs it at R4, before any constraint exists. A lone
   dataclass in a module called `constraints.py` before there is a constraint would be odd.
   `constraints.py` imports it from there.
3. **`sibling_query` moves from `compile.py` to `relations.py`.** `solve` needs it at R9;
   `compile.py` does not exist until R11. `compile.py` imports it from there.
4. **The import-boundary test inverts.** The prototype asserts that
   `esmporium_processing.requirements` imports only esmporium, pydantic and the standard
   library. In esmporium the mirror-image assertion is the useful one: `esmporium.requirements`
   may import `esmporium.query` and `DATASET_FACET_COLUMNS` from `esmporium.db.schema`, and
   nothing else from `esmporium.search` or `esmporium.db`. Port the AST walk from
   `tests/unit/requirements/test_use_cases.py` with the allow-list flipped.
   Unclear why we need this, maybe remove (at least chek).
5. **The `atmos`/`land`/`ocean` test helpers start auxiliary-free** and gain their `Aux` lists
   at R10. Six lines change in one helper module; the twenty use cases themselves never change.

## The PRs

### R0 — The design note, as docs

No code. Port `PLAN-REQUIREMENTS.md` into esmporium as
`docs/further-background/data-requirements.md`, and list it in `docs/NAVIGATION.md` under
*Further background*, beside *Dependency pinning and testing*. Add a `## Requirements (R0–R12)`
section to esmporium's `PLAN.md` holding the table above.

This is what makes the bottom-up half of the ordering tolerable. It lands the mental model —
the three kinds of "or", the three levels a check can be attached at and what each means when
it fails, what a role path looks like — before any of the pieces arrive, so every later PR can
be reviewed against a stated target.

Keep *Three kinds of "or"*, *The tree*, *Relations*, *Constraints*, *Solving*, *Flow and
storage*, *Queries and facets* and *Findings worth remembering*. Drop the prototype-specific
*Where this is going* and *Known limits*, folding the latter into this document's
*Out of scope* below.

### R1 — Entries, facets and matching

New package `src/esmporium/requirements/`, with `catalogue.py` and `__init__.py`.

- `CatalogueEntry`: `id`, the nine `DATASET_FACET_COLUMNS`, `extra`, and `.facet(name)`.
- `set_facets(query)`, which flattens a `Query` including `other_terms`; `ClashingFacetError`.
- `matches(query, entry)`; `UnsupportedFacetError`.
- `Catalogue` protocol with `find` only. `InMemoryCatalogue` with `records` and `find`, plus
  the `__post_init__` uniqueness check.

Tests: port `test_matches`, `test_matching_unrecorded_facets_raises`,
`test_other_terms_are_facets_too`, `test_facet_set_twice`, `test_catalog_rejects_duplicate_ids`
and the `record()` helper. Add `test_catalogue_entry_mirrors_dataset_columns` directly below
the existing `test_dataset_facets_mirror_dataset_columns` in `tests/unit/test_schema.py`.

### R2 — `Leaf`, `all_of`, `Requirement`, `.where()`

`tree.py`: `Leaf` (query, role, `Leaf.of`, role validator), `AllOf`, `all_of`, `as_node`,
`Requirement` (name, tree, where, group_by, prefer, cardinality), `canonical_json`,
`requirement_hash`, `add_facets`, `_normalise`, `effective_query`, `.where()`,
`apply_to_leaves`, `walk_leaves`, `role_paths`, `DuplicateRoleError`, `ConflictingFacetsError`.

The `Node` union is declared here with two members. Say in the PR description that every later
node type is an additive entry in that union plus a branch in four dispatch functions — that
property is what the whole ordering rests on.

Tests: `test_leaf_shorthand`, `test_leaf_needs_role_for_several_variables`,
`test_duplicate_roles_in_all_of`, `test_where_adds_facets_to_every_leaf`,
`test_where_contradicting_a_leaf_is_an_error`,
`test_requirement_where_contradicting_a_leaf_is_an_error`, `test_role_paths`,
`test_project_specific_facets_are_allowed_when_building`, `test_hash_changes_with_content`,
and a tree round-trip.

### R3 — `solve`: the skeleton closes

`solve.py`: `Explanation`, `Resolved`/`Unresolved`/`NodeResult`, `ResolvedGroup`/
`UnresolvedGroup`/`SolveResult`, `_Context`, `_group_values`, `_eval_leaf` (no lineage,
auxiliary data or constraints), `_eval_all_of`, `_choose` (i.e. `prefer` and `cardinality`),
`_merge`, `_worst`, `_label`, `describe_query`, `solve`.

`solve(PATTERN_EFFECT, catalogue)` works. So do grouping and fan-out — `group_by` including
`variable` or `experiment` — which is the least obvious third of the design and is now
demonstrable rather than described.

Introduce `tests/unit/requirements/use_cases.py`, seeded with `14-pattern-effect`, the
auxiliary-free `atmos`/`land`/`ocean` helpers, the alias tuples (`CONTROL`, `SCENARIOS`,
`ABRUPT`, …), and `test_use_cases.py::test_use_case` parametrised over the `USE_CASES` dict —
round-trip, hash, and solve against `satisfying_catalogue`. Port `satisfying_catalogue` in its
`find`-only form; it grows a branch per PR alongside the feature it serves.
[We'll think about all these helpers. Lots of them either obscure what is actually going on,
or are things we can just put in the package so there'll be some thinking here.]

Tests: `test_all_satisfied`, `test_required_variable_missing`, `test_ambiguous_grids_and_prefer`,
`test_ambiguous_despite_prefer_says_what_was_preferred`, `test_explanation_is_readable`,
`test_project_specific_facets_come_from_the_catalogue`, `test_facet_no_dataset_knows_is_an_error`.

If this runs long, move the `use_cases.py` seed to R4; the skeleton itself is ~450 src and
~250 test lines.

### R4 — `search` takes a `requirement`

Here is the first step to combining search and requirement logic. Update `search` to take a requirement, instead of a `QueryProtocol`. This will allow us to start performing live ESGF searches for simple use cases on CMIP7 data, to track what is currently available, what will be available in future (what was not satisfied becomes satisfied on another search). This will also mean we need to add a catalogue that is backed by our database, so we can test this live, rather than than only using the InMemoryCatalogue (we will keep the InMemoryCatalogue for testing, likely forever). We may need to update the catalogue protocol class too to make this work. If we need to make such a change, that is ok.

This PR will alter catalogue and search test logic. 


### R5 — `Ancestors` lineage

- `relations.py` (new): `RELATION_MODEL_CONFIG`, `Ancestors`, and `Lineage` with `index_of`
  (deviation 2).
- `catalogue.py`: `Catalogue.parent_of`, `InMemoryCatalogue.parents`, reference checking in
  `__post_init__`.
- `tree.py`: `LineageRelation` (one member for now), `Leaf.lineage`, `.with_lineage()`,
  `RESERVED_ROLES`, the leaf-role-versus-lineage-role validator, lineage entries in
  `role_paths`.
- `solve.py`: `_lineage`, `_ancestor_lineage`, `Resolved.lineages`, lineage role paths in
  `_eval_leaf`.

Role paths gain their second level here: `control.tas`, `chain.0.tas`.

Tests: `test_branch_chain_back_to_picontrol`, `test_bell_is_rooted_in_esm_picontrol`,
`test_lineage_role_names_where_it_stopped`, `test_catalog_rejects_unknown_references`,
`test_leaf_role_cannot_be_its_own_lineage_role`,
`test_role_names_are_free_unless_a_lineage_uses_them`,
`test_machinery_role_names_are_always_reserved`, no parent recorded, `max_depth` exhausted.

Use cases: `15-pattern-scaling`, `17-etccdi` — both have a lineage and no constraints.

### R6 — The `Constraint` protocol, with nothing shipped

- `constraints.py` (new): `Pass`/`Degraded`/`Fail`/`Outcome`, `GroupView`, the `Constraint`
  protocol, `NotAConstraintError`, `NotSerialisableConstraintError`, `_load_constraint`,
  `_serialise_constraints`, and the `Constraints` annotated field type.
- `catalogue.py`: `MetadataUnavailableError`, `Catalogue.metadata`,
  `InMemoryCatalogue.metadata_by_id`.
- `tree.py`: `Leaf.constraints`, `.with_constraints()`, `Requirement.constraints`.
- `solve.py`: `_evaluate_constraints`, the `undetermined` status.

**Ship no constraint implementation in this PR.** The design note's central claim — constraints
are a pluggable protocol and the solver never special-cases `Covers` — is *provable* here,
because `Covers` does not exist yet and the only constraint under test is the user-defined
`AtLeastNDatasets`. This is the strongest single argument for doing any of this bottom-up, and
the PR description should say so.

Tests: `test_user_defined_constraint`, `test_missing_metadata`,
`test_missing_metadata_is_undetermined_not_passed`, `test_not_a_constraint`,
`test_constraint_which_is_not_a_pydantic_model`, `test_round_trip_user_defined_constraint`,
`test_with_lineage_and_with_constraints_reach_every_leaf`.

### R7 — `Covers`

`constraints.py`: `TIME_RANGE`, `BRANCH_TIME_IN_PARENT`, `_as_year`, `_as_time_range`,
`Covers`, `_covers`. Carry the prototype's in-code note that branch-time handling needs to
become clearer, and easy for users to override, since recorded branch times often have bugs.

Tests: `test_covers_calendar`, `test_covers_branch_needs_ancestor`, `test_covers_needs_a_lineage`,
`test_covers_rejects_malformed_metadata`, `test_degraded_when_ideal_padding_not_met`,
`test_branch_chain_control_must_cover_child_and_parents`,
`test_end_and_the_lineage_role_name_mean_the_same_thing`.

Use cases: `01-tcr`, `03-tcre-flat10`, `04-tcre-1pct`, `05-zec-flat10`,
`11-tas-scenario-anomalies`, plus `TO_CONTROL`, `CONTROL_COVERS` and `CONTROL_IDEALLY_COVERS`.

### R8 — `any_of`, `optional`

- `tree.py`: `AnyOf` (`min_length=2`), `OptionalNode`, `any_of`, `optional`, and the new
  branches in `apply_to_leaves`, `walk_leaves` and `role_paths`.
- `solve.py`: `_eval_any_of`, `_eval_optional`, `choices`, `notes`.

Two things become visible here and belong in the PR description. First, the third kind of "or"
— alias, fan-out, alternative — is complete. Second, **ambiguous and undetermined results are
never skipped**: `any_of` stops at them rather than trying the next alternative, and `optional`
passes them on rather than treating them as absent, so a question we cannot answer is never
silently read as "no".

Tests: `test_alternative_chosen_in_order`, `test_alternative_applies_to_whole_lineage`,
`test_ambiguity_is_not_skipped_by_any_of`, `test_optional_run_with_too_short_control_is_absent`,
`test_optional_run_with_long_enough_control_is_used`,
`test_duplicate_roles_allowed_across_alternatives`.

Use cases: `06-zec-1pct`, `07-zec-bell`, `08-flat10-cdr`, `12-gcmagicc`, `18-amoc`.

### R9 — `namespace` and cross-leaf checks

- `tree.py`: `Namespace`, `namespace()`, the name validator, role prefixing.
- `solve.py`: `_eval_namespace` and the namespace-scoped `GroupView`.
- `constraints.py`: `SameTimeRange`.

The third attachment level lands, completing the design note's table of where a check goes and
what its failure costs. Worth restating that there is deliberately no "one experiment" node:
that was four separable things in a trench coat — shared facets, a lineage, scoped checks and a
role prefix — and each now has one home.

Tests: `test_namespaces_prefix_roles_and_can_nest`,
`test_namespace_carries_cross_leaf_constraints`,
`test_cross_leaf_constraint_degrades_when_periods_differ`,
`test_cross_leaf_constraint_fails_when_periods_are_disjoint`,
`test_cross_leaf_constraint_is_scoped_to_its_namespace`, and `test_round_trip_and_hash`
parametrised over `ECS` and `CARBON_CLOSURE` — the first requirements rich enough to be worth
round-tripping whole.

Use cases: `02-ecs`, `16-carbon-closure`, `16a-carbon-calibration`.

### R10 — `Sibling`

`relations.py`: `Sibling`, `sibling_query` (deviation 3). `tree.py`: `LineageRelation` becomes
a real discriminated union on `kind`. `solve.py`: `_sibling_lineage`.

Tests: `test_erf_control_found_as_sibling`, `test_lineage_kinds_round_trip`.

Use cases: `09-erf-transient`, `10-erf-timeslice`.

### R11 — `Aux`

- `relations.py`: `MatchLevels`, `STRICT_MATCH`, `Aux` (`role_name`, `required`, `match`,
  `via`, `also_for_lineage`) and its validators.
- `catalogue.py`: `Catalogue.linked`, `InMemoryCatalogue.links`.
- `tree.py`: `Leaf.aux`, auxiliary role paths, duplicate-auxiliary-role detection.
- `solve.py`: `_aux`, and auxiliary resolution in `_eval_leaf` including `also_for_lineage`,
  required-versus-optional, and the fallback-level note.

Switch the `atmos`/`land`/`ocean` helpers on to their real `Aux` lists (deviation 5); the
twenty use cases are untouched. Record in the PR description that `via="link"` is where all of
this should end up — esmporium links once at ingestion from each file's `cell_measures`
attribute, so every analysis reads the same answer instead of redoing the matching — and that
`via="match"` is the fallback for whatever is not linked yet.

Tests: `test_fx_not_matched_by_default`, `test_fx_matched_with_opt_in_fallback`,
`test_fallback_still_requires_same_grid`, `test_aux_via_link`, `test_fractions_are_not_linked`,
`test_land_and_ocean_fractions`, `test_missing_required_sea_fraction`,
`test_aux_only_for_the_anchor_dataset`, `test_aux_defaults_to_strict_match`,
`test_aux_needs_role_for_several_variables`, `test_aux_match_accepts_project_specific_facets`,
`test_duplicate_aux_roles`, `test_aux_needs_at_least_one_match_level`.

Use cases: `13-energy-balance`, `19-sea-ice`. All twenty now build and solve.

If this runs long, split at the `via` boundary: R10a is `via="match"` with match levels and
required-versus-optional; R10b adds `via="link"` and `also_for_lineage`.

### R12 - `to_search_plan`
`compile.py`: `SearchPlan`, `to_search_plan`, `merge_on_variable`, `_key_without_variable`,
importing `sibling_query` from `relations`. Add the `to_search_plan` assertion to
`test_use_case`, so all twenty are checked to compile as well as solve.

Tests: `test_ecs`, `test_gcmagicc_includes_every_alternative_and_optional`,
`test_erf_includes_sibling_query`, `test_carbon_closure`, `test_merge_on_variable`,
`test_merging_variables_can_be_turned_off`.

This is also where the flow gets documented end to end: `to_search_plan` → esmporium searches
(`QueryCollection`, PR3.7) → parent links (PR6) → `solve`.
[As soon as this and downloading lands, I would like to spin up and start doing tracking and downloading for scenario tas
(but only following parents back up to historical, not piControl):
I'm going to need it for a paper and it's a nice simple use case.]

### R13 — Retire the prototype

In esmporium-processing: delete `src/esmporium_processing/requirements/` and
`tests/unit/requirements/`, bump the esmporium dependency, and import `esmporium.requirements`
wherever analyses need it. `PLAN-REQUIREMENTS.md` can go, since its content now lives in
esmporium's docs.

## Per-PR conventions

- One changelog fragment per PR, `changelog/<issue>.feature.md`, in the existing style: a
  sentence naming the new objects with `[...][]` cross-references.
- `esmporium/requirements/__init__.py` grows its `__all__` each PR, matching
  `esmporium/query/__init__.py`'s style.
- API docs are auto-generated from `docs/api/`, so new modules need no manual page.
- `make checks` and `make test` pass on every PR. Everything here is a unit test, under
  `tests/unit/requirements/`.
- Numpydoc docstrings on everything public, at the prototype's density — the line estimates
  above assume the prototype's docstrings come across intact.
- Each PR's `USE_CASES` dict is strictly larger than the previous PR's, and `test_use_case`
  round-trips, hashes and solves every entry.

## Out of scope, named as follow-ups

- **A database-backed `Catalogue`.** `find` could be answered today, but `parent_of` needs
  esmporium PR6 and `metadata` needs PR7. The protocol plus `InMemoryCatalogue` is the
  deliverable here; the DB-backed implementation is a later PR gated on those.
- **Storing requirements and solve snapshots.** `canonical_json` and `requirement_hash` (R2)
  are the primitives; the tables are ordinary esmporium tables once requirements live there.
  "Requirement became satisfiable" is the difference between `solve` at t1 and at t2.
- **Linking from `cell_measures`** at ingestion, which is what makes `Aux(via="link")` the
  default rather than the fallback.
- **Backtracking.** Solving stays greedy: a choice made for one leaf is never revisited to
  satisfy another. [TODO: clarify what this means]
- **Narrowing auxiliary searches.** Auxiliary queries inherit nothing, so they find fx data for
  every model. If that proves too broad, narrow first and widen only when nothing is found, the
  way `ancestry_until` is handled. [I'm not convinced the logic of this is right, let's see when we get to auxiliary]
- **Calendars.** `time_range` and `branch_time_in_parent` stay plain fractional years. [Fine and probably simplest]
- **Trust when loading.** Loading a serialised requirement imports constraint classes by name,
  so only load requirements you trust. Worth a docstring note, not a mechanism, for now.
  [We might be able to do something a bit safer with a specific loading function in the DB, let's see]
- **The `From(...)` / `GlobalMean` annotation layer** from `PLAN-LOAD-CLAUDE.md`, which is
  esmporium-processing's side of the boundary.
