"""
The use cases from PLAN.md, written as requirements

Shared aliases and helpers live here rather than in the library,
at least until we see which of them are worth shipping.
Experiment lists are illustrative, not exhaustive.
"""

from __future__ import annotations

from esmporium.query import Query as Q

from esmporium_processing.requirements import (
    Ancestors,
    Aux,
    Covers,
    Leaf,
    Requirement,
    SameTimeRange,
    Sibling,
    all_of,
    any_of,
    namespace,
    optional,
)

# Aliases and experiment families
# -------------------------------
CONTROL = ("piControl", "esm-piControl")
SCENARIOS = (
    # CMIP6
    "ssp119",
    "ssp126",
    "ssp245",
    "ssp370",
    "ssp434",
    "ssp460",
    "ssp534-over",
    "ssp585",
    # CMIP7
    "scen7-h",
    "scen7-hl",
    "scen7-m",
    "scen7-ml",
    "scen7-l",
    "scen7-ln",
    "scen7-vl",
    "esm-scen7-h",
    "esm-scen7-hl",
    "esm-scen7-m",
    "esm-scen7-ml",
    "esm-scen7-l",
    "esm-scen7-ln",
    "esm-scen7-vl",
)
ABRUPT = ("abrupt-4xCO2", "abrupt4xCO2", "abrupt-2xCO2", "abrupt-0p5xCO2")
ONE_PCT_FAMILY = (
    "1pctCO2-bgc",
    "1pctCO2-rad",
    "1pctCO2Ndep",
    "1pctCO2Ndep-bgc",
    "1pctCO2-cdr",
    "esm-1pctCO2",
)
ZEC_1PCT_BRANCH = (
    "esm-1pct-brch-750PgC",
    "esm-1pct-brch-1000PgC",
    "esm-1pct-brch-2000PgC",
)
ZEC_BELL = ("esm-bell-750PgC", "esm-bell-1000PgC", "esm-bell-2000PgC")
FLAT10 = ("esm-flat10", "esm-flat10-zec", "esm-flat10-cdr")
PICLIM_TRANSIENT = ("piClim-histall", "piClim-histaer")
PICLIM_TIMESLICE = (
    "piClim-4xCO2",
    "piClim-aer",
    "piClim-anthro",
    "piClim-CH4",
    "piClim-N2O",
    "piClim-NOx",
    "piClim-ODS",
    "piClim-SO2",
)

# Relations and constraints
# -------------------------
TO_CONTROL = Ancestors(until=Q(experiment=CONTROL), role="control")
CONTROL_COVERS = Covers(role="control", target="self", ideal_pad_years=(20.0, 20.0))
# 'ideally spans', but there are workarounds, so not required
CONTROL_IDEALLY_COVERS = Covers(
    role="control", target="self", pad_years=None, ideal_pad_years=(0.0, 0.0)
)

FX_FALLBACK = (
    ("model", "grid_label", "experiment", "variant_label"),
    ("model", "grid_label", "variant_label"),
    ("model", "grid_label"),
)
"""An opt-in fallback for finding fx data from other experiments/variants"""


# Leaf helpers: the auxiliary variables are always named explicitly
# -----------------------------------------------------------------
def _leaf(variable: str | tuple[str, ...], aux: list[Aux], role: str | None) -> Leaf:
    names = (variable,) if isinstance(variable, str) else variable
    return Leaf.of(Q(variable=names), role=role or names[0], aux=aux)


def atmos(variable: str | tuple[str, ...], role: str | None = None) -> Leaf:
    """Atmosphere variable, cell areas optional"""
    return _leaf(variable, [Aux(Q(variable="areacella"), required=False)], role)


def land(variable: str | tuple[str, ...], role: str | None = None) -> Leaf:
    """Land variable ('area: mean where land'): land fraction required"""
    return _leaf(
        variable,
        [Aux(Q(variable="sftlf")), Aux(Q(variable="areacella"), required=False)],
        role,
    )


def ocean(variable: str | tuple[str, ...], role: str | None = None) -> Leaf:
    """Ocean variable ('area: mean where sea'): sea fraction required"""
    return _leaf(
        variable,
        [Aux(Q(variable="sftof")), Aux(Q(variable="areacello"), required=False)],
        role,
    )


RADIATION = all_of(atmos("rsdt"), atmos("rlut"), atmos("rsut"))
CARBON_FLUXES = all_of(ocean("fgco2"), land("nbp"))

FAN_OUT_OVER_EXPERIMENT = ("model", "variant_label", "experiment")


# Use cases
# ---------
# Every leaf says what it needs (`where`), where its control comes from
# (`with_lineage`) and what it must satisfy (`with_constraints`).
# A `namespace` is only needed when the same role appears twice.
TCR = Requirement(
    atmos("tas")
    .where(experiment="1pctCO2")
    .with_lineage(TO_CONTROL)
    .with_constraints(CONTROL_COVERS),
    name="tcr",
    where=Q(reporting_interval="mon"),
)


def abrupt(name: str, experiment: str | tuple[str, ...]) -> object:
    """
    Data for Gregory-style ECS calculations

    The namespace keeps abrupt-4xCO2's roles apart from abrupt-2xCO2's,
    and carries the one check which compares leaves rather than describing
    a single dataset: a Gregory regression uses temperature and radiation
    together, so they should cover the same years.
    """
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

TCRE_FLAT10 = Requirement(
    atmos("tas")
    .where(experiment="esm-flat10")
    .with_lineage(TO_CONTROL)
    .with_constraints(CONTROL_COVERS),
    name="tcre-flat10",
    where=Q(reporting_interval="mon"),
)

TCRE_1PCT = Requirement(
    all_of(atmos("tas"), CARBON_FLUXES)
    .where(experiment="1pctCO2")
    .with_lineage(TO_CONTROL)
    .with_constraints(CONTROL_COVERS),
    name="tcre-1pct",
    where=Q(reporting_interval="mon"),
)

ZEC_FLAT10 = Requirement(
    atmos("tas")
    .where(experiment="esm-flat10-zec")
    .with_lineage(TO_CONTROL)
    .with_constraints(CONTROL_COVERS),
    name="zec-flat10",
    where=Q(reporting_interval="mon"),
)


def zec_with_optional_carbon(experiments: tuple[str, ...]) -> object:
    """tas (plus optional carbon fluxes) back to the control, fanned out"""
    return (
        all_of(atmos("tas"), optional(CARBON_FLUXES))
        .where(experiment=experiments)
        .with_lineage(TO_CONTROL)
        .with_constraints(CONTROL_COVERS)
    )


ZEC_1PCT = Requirement(
    zec_with_optional_carbon(ZEC_1PCT_BRANCH),
    name="zec-1pct",
    where=Q(reporting_interval="mon"),
    group_by=FAN_OUT_OVER_EXPERIMENT,
)

ZEC_BELL_REQ = Requirement(
    zec_with_optional_carbon(ZEC_BELL),
    name="zec-bell",
    where=Q(reporting_interval="mon"),
    group_by=FAN_OUT_OVER_EXPERIMENT,
)

FLAT10_CDR = Requirement(
    zec_with_optional_carbon(("esm-flat10-cdr",)),
    name="flat10-cdr",
    where=Q(reporting_interval="mon"),
)


def erf(experiments: tuple[str, ...]) -> object:
    """
    ERF: radiation for piClim experiments and piClim-control

    piClim-control is a sibling (both are children of piControl),
    and its 30 years are used as they are, so there is no coverage constraint.
    """
    return RADIATION.where(experiment=experiments).with_lineage(
        Sibling(Q(experiment="piClim-control"), role="control")
    )


ERF_TRANSIENT = Requirement(
    erf(PICLIM_TRANSIENT),
    name="erf-transient",
    where=Q(reporting_interval="mon"),
    group_by=FAN_OUT_OVER_EXPERIMENT,
)

ERF_TIMESLICE = Requirement(
    erf(PICLIM_TIMESLICE),
    name="erf-timeslice",
    where=Q(reporting_interval="mon"),
    group_by=FAN_OUT_OVER_EXPERIMENT,
)

TAS_SCENARIO_ANOMALIES = Requirement(
    atmos("tas")
    .where(experiment=SCENARIOS)
    .with_lineage(TO_CONTROL)
    .with_constraints(CONTROL_IDEALLY_COVERS),
    name="tas-scenario-anomalies",
    where=Q(reporting_interval="mon"),
    group_by=FAN_OUT_OVER_EXPERIMENT,
)

_GCMAGICC_VARIABLES = all_of(
    "hurs",
    "huss",
    "pr",
    "psl",
    "rsds",
    any_of(all_of("rlut", "rsdt", "rsut"), "rtmt"),
    any_of("sfcWind", all_of("uas", "vas")),
    "tas",
    "tasmax",
    "tasmin",
    "ts",
    optional("clt"),
    optional("evspsbl"),
    optional("mrso"),
)
_GCMAGICC_EXPERIMENTS = (
    "historical",
    "esm-hist",
    *SCENARIOS,
    *ABRUPT,
    "1pctCO2",
    "piControl",
)
# 'Daily or monthly': prefer daily, fall back to monthly,
# with the same frequency for every variable.
GCMAGICC = Requirement(
    any_of(
        _GCMAGICC_VARIABLES.where(reporting_interval="day"),
        _GCMAGICC_VARIABLES.where(reporting_interval="mon"),
    ).where(experiment=_GCMAGICC_EXPERIMENTS),
    name="gcmagicc",
    group_by=FAN_OUT_OVER_EXPERIMENT,
)

ENERGY_BALANCE = Requirement(
    all_of(RADIATION, ocean("hfds")).where(
        experiment=(
            "piControl",
            "historical",
            *SCENARIOS,
            *ABRUPT,
            "1pctCO2",
            *FLAT10,
        )
    ),
    name="energy-balance",
    where=Q(reporting_interval="mon"),
    group_by=FAN_OUT_OVER_EXPERIMENT,
)

PATTERN_EFFECT = Requirement(
    Leaf.of(Q(variable="tas", experiment="historical", reporting_interval="mon")),
    name="pattern-effect",
)

PATTERN_SCALING = Requirement(
    Leaf.of(
        # One leaf with several variables is an OR: any one of them can fill the
        # role. `group_by` below includes `variable`, so this fans out into one
        # group per variable rather than picking a single variable.
        Q(
            variable=(
                "tas",
                "tasmax",
                "tasmin",
                "huss",
                "pr",
                "sfcWind",
                "ps",
                "rsds",
                "rlds",
            )
        ),
        # The role says what the dataset is *for*, not which variable it is:
        # `field` is the field being pattern scaled, `control.field` the same
        # field in the control. Which variable it is sits in the group key.
        role="field",
        aux=[
            Aux(Q(variable="areacella"), required=False),
            Aux(Q(variable="sftlf"), required=False),
        ],
    )
    .where(experiment=SCENARIOS)
    .with_lineage(TO_CONTROL),
    name="pattern-scaling",
    where=Q(reporting_interval="mon"),
    group_by=("model", "variant_label", "experiment", "variable"),
)

_OPTIONAL_CARBON_FLUXES = (
    optional(land("fAnthDisturb")),
    optional(land("fProductDecomp")),
    optional(land("fFireNat")),
    optional(
        Leaf.of(
            "fCLandToOcean",
            aux=[
                Aux(Q(variable="sftlf")),
                Aux(Q(variable="areacellr"), required=False),
            ],
        )
    ),
    optional(land("fFire")),
    # CMIP6 spells it fLuc, so both spellings are accepted (an alias)
    # and the role says which name the results use.
    optional(land(("fLuc", "fLUC"), role="fLuc")),
)
_CARBON_CLOSURE_EXPERIMENTS = (
    *ONE_PCT_FAMILY,
    *ZEC_1PCT_BRANCH,
    *ZEC_BELL,
    *FLAT10,
    "piControl",
    "historical",
    *SCENARIOS,
)


def carbon_closure(name: str, pools: object) -> Requirement:
    """Carbon cycle closure: 1pctCO2 required, other experiments optional"""
    needs = all_of(
        pools,  # type: ignore[arg-type]
        any_of(land("npp"), all_of(land("gpp"), land("ra"))),
        land("rh"),
        *_OPTIONAL_CARBON_FLUXES,
    )
    return Requirement(
        all_of(
            namespace("onepct", needs.where(experiment="1pctCO2")),
            # One optional namespace per experiment, so that several available
            # experiments are not ambiguous
            *(
                optional(namespace(e, needs.where(experiment=e)))
                for e in _CARBON_CLOSURE_EXPERIMENTS
            ),
        ),
        name=name,
        where=Q(reporting_interval="mon"),
    )


CARBON_CLOSURE = carbon_closure(
    "carbon-closure",
    any_of(
        land("cLand"),
        all_of(land("cVeg"), land("cLitter"), land("cSoil"), land("cProduct")),
    ),
)

CARBON_CALIBRATION = carbon_closure(
    "carbon-calibration",
    all_of(
        optional(land("cLand")),
        land("cVeg"),
        land("cLitter"),
        land("cSoil"),
        land("cProduct"),
    ),
)

ETCCDI = Requirement(
    all_of("tasmax", "tasmin", "pr")
    .where(experiment=SCENARIOS)
    .with_lineage(TO_CONTROL),
    name="etccdi",
    where=Q(reporting_interval="day"),
    group_by=FAN_OUT_OVER_EXPERIMENT,
)

AMOC = Requirement(
    any_of("msftmz", "msftyz").where(experiment=SCENARIOS).with_lineage(TO_CONTROL),
    name="amoc",
    where=Q(reporting_interval="mon"),
    group_by=FAN_OUT_OVER_EXPERIMENT,
)

SEA_ICE = Requirement(
    Leaf.of(
        "siconc",
        # 'Need ocean cell areas too'; sftof formally required ('mean where sea')
        aux=[Aux(Q(variable="sftof")), Aux(Q(variable="areacello"))],
    )
    .where(experiment=SCENARIOS)
    .with_lineage(TO_CONTROL),
    name="sea-ice",
    where=Q(reporting_interval="mon"),
    group_by=FAN_OUT_OVER_EXPERIMENT,
)

USE_CASES: dict[str, Requirement] = {
    "01-tcr": TCR,
    "02-ecs": ECS,
    "03-tcre-flat10": TCRE_FLAT10,
    "04-tcre-1pct": TCRE_1PCT,
    "05-zec-flat10": ZEC_FLAT10,
    "06-zec-1pct": ZEC_1PCT,
    "07-zec-bell": ZEC_BELL_REQ,
    "08-flat10-cdr": FLAT10_CDR,
    "09-erf-transient": ERF_TRANSIENT,
    "10-erf-timeslice": ERF_TIMESLICE,
    "11-tas-scenario-anomalies": TAS_SCENARIO_ANOMALIES,
    "12-gcmagicc": GCMAGICC,
    "13-energy-balance": ENERGY_BALANCE,
    "14-pattern-effect": PATTERN_EFFECT,
    "15-pattern-scaling": PATTERN_SCALING,
    "16-carbon-closure": CARBON_CLOSURE,
    "16a-carbon-calibration": CARBON_CALIBRATION,
    "17-etccdi": ETCCDI,
    "18-amoc": AMOC,
    "19-sea-ice": SEA_ICE,
}
