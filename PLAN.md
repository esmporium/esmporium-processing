## Round 1

- declarative way to say what you need and get it in a sensible form
- way to specify how to load
    - don't do this
- pass database engine and datasets to the user based on some declaration
    - declaration should ideally match searches too
    - user can specify load function etc. in their own function
        - we offer pre-built that support our use cases,
          but users can also define their own
    - declaration e.g.

```py
Inputs(
    tas: Annotated[
        xr.DataArray,  # xr.Dataset
        DatasetSpec(
            variable="tas",
            frequency="mon",
            experiment="abrupt-4xCO2" OR "abrupt4xco2",
            parent_until="piControl",
            auxilliary_file="areacella" OR CMIP5_specific_name OR None,
        ),
    ],
    rsdt: Annotated[
        xr.DataArray,  # xr.Dataset
        DatasetSpec(
            variable="rsdt",
            frequency="mon",
            experiment="abrupt-4xCO2" OR "abrupt4xco2",
            parent_until="piControl",
            auxilliary_file="areacella" OR CMIP5_specific_name OR None,
        ),
    ],
    rlut: Annotated[
        xr.DataArray,  # xr.Dataset
        DatasetSpec(
            variable="rlut",
            frequency="mon",
            experiment="abrupt-4xCO2" OR "abrupt4xco2",
            parent_until="piControl",
            auxilliary_file="areacella" OR CMIP5_specific_name OR None,
        ),
    ],
    rsut: Annotated[
        xr.DataArray,  # xr.Dataset
        DatasetSpec(
            variable="rsut",
            frequency="mon",
            experiment="abrupt-4xCO2" OR "abrupt4xco2",
            parent_until="piControl",
            auxilliary_file="areacella" OR CMIP5_specific_name OR None,
        ),
    ],
    group_by=["model", "ensemble_member"]  # would have to figure out what to do with multiple grid matches, maybe define order of preference?
    # filter idea here too i.e. I only want to run this on these groups?
    # Not so useful for ECS (unless you only wanted to run e.g. for some models or first variant or something),
    # but could be useful for stitching if you only want to stitch some variables, not all.
)
```
        - names happen to match variables in this case, doesn't always have to be like this
            - e.g. could be different experiments for stitching workflows and you group by variable instead
        - abrupt-4xCO2 or abrupt4xco2 i.e. either spelling (values are not ours i.e. have to be changed at load time)
        - parent required back until piControl
            - no parent finding injection here - has to be done at ingestion time i.e. during search or between search and this function
        - auxilliary_file is optional
            - no auxilliary file finding injection here - has to be done at ingestion time i.e. during search or between search and this function
        - one of multiple experiments because the target experiment can vary by CMIP phase i.e. project
        - define how to group so we can figure out how to determine whether groups are complete or not and raise appropriately on multiple matches
- loading
    - user chosen, this would just be some of our defaults
    - get_data_access(ds: Dataset, engine: DatabaseEngine, other_context?) -> DAO:  # DAO is a data access option protocol
    - load(DAO, other_context?) -> LT:  # LT is loaded type
        - default would be something like
            1. load_to_netcdf4(DAO, other_context?) -> tuple[netcdf4.Dataset, ...]:
            1. apply_netcdf4_fixes(nc_ds: tuple[netcdf4.Dataset, ...], ds: Dataset, other_context?) -> tuple[netcdf4.Dataset, ...]:
            1. xr.open_mfdataset(nc_ds: tuple[netcdf4.Dataset], **kwargs) -> xr.Dataset:
            1. apply_xarray_fixes(xr_ds: xr.Dataset, ds: Dataset, other_context?) -> xr.Dataset:
    - see right hand side here too: https://excalidraw.com/#json=KIzhvEqCD1D0zkd8w-3vr,HZy2XexoWvG2UzK8Iw8lew
- use
    - tracking of jobs etc.
        - each task can define its own state: important for flexible caching logic (default is probably, have I seen this dataset combination before, but need flexibility for cases we don't anticipate)
        - see https://github.com/esmporium/esmporium/blob/jobs-plan/LOAD-CLAUDE-INVESTIGAION.md
    - ability to compose jobs
        - ideally also the ability to define which bits are steps i.e. expensive to recompute because of how important this is: https://github.com/esmporium/esmporium/blob/jobs-plan/LOAD-CLAUDE-INVESTIGAION.md#why-this-matters-so-much


## Round 2

Want to be able to declare desired bundles of data.


Option a:

```py
Inputs(
    tas: Annotated[
        xr.DataArray,  # xr.Dataset
        DatasetSpec(
            variable="tas",
            frequency="mon",
            experiment="abrupt-4xCO2" OR "abrupt4xco2",
            parent_until="piControl" OR "pi-Control",
            auxilliary_file="areacella" OR CMIP5_specific_name OR None,
            # Default is optional=False, but need a way for the user to say this input is optional.
            # Maybe having a type hint of type | None is the best way.
            # This is basically an implicit AND,
            # with optional=False meaning not required.
            # I'm not sure how best to represent OR across groups of variable options.
            # optional=False,
        ),
    ],
    rsdt: Annotated[
        xr.DataArray,  # xr.Dataset
        DatasetSpec(
            variable="rsdt",
            frequency="mon",
            experiment="abrupt-4xCO2" OR "abrupt4xco2",
            parent_until="piControl",
            auxilliary_file="areacella" OR CMIP5_specific_name OR None,
        ),
    ],
    rlut: Annotated[
        xr.DataArray,  # xr.Dataset
        DatasetSpec(
            variable="rlut",
            frequency="mon",
            experiment="abrupt-4xCO2" OR "abrupt4xco2",
            parent_until="piControl",
            auxilliary_file="areacella" OR CMIP5_specific_name OR None,
        ),
    ],
    rsut: Annotated[
        xr.DataArray,  # xr.Dataset
        DatasetSpec(
            variable="rsut",
            frequency="mon",
            experiment="abrupt-4xCO2" OR "abrupt4xco2",
            parent_until="piControl",
            auxilliary_file="areacella" OR CMIP5_specific_name OR None,
        ),
    ],
    group_by=["model", "ensemble_member"]  # would have to figure out what to do with multiple grid matches, maybe define order of preference?
    # filter idea here too i.e. I only want to run this on these groups?
    # Not so useful for ECS (unless you only wanted to run e.g. for some models or first variant or something),
    # but could be useful for stitching if you only want to stitch some variables, not all.
)
```


```py
# maybe decorator, I don't know
def gregory_calculation(
    tas: TypeHint,
    rsdt: TypeHint,
) -> ReturnType:
    tas_xr = load(tas)
    rsdt_xr = load(rsdt)
    # We'll have a bunch of default loaders
    # e.g. load_xarray_dataarray(ds: Dataset, fixes, ...)


    get_global_mean(tas.parent)
```

```py
Inputs(
    experiment: Annotated[
        xr.DataArray,  # xr.Dataset
        DatasetSpec(
            parent_until="historical" OR "esm-hist",
            auxilliary_file="areacella" OR CMIP5_specific_name OR None,
        ),
    ],
    group_by=["model", "ensemble_member", "variable"]  # would have to figure out what to do with multiple grid matches, maybe define order of preference?
    # filter idea here too i.e. I only want to run this on these groups?
    # Not so useful for ECS (unless you only wanted to run e.g. for some models or first variant or something),
    # but could be useful for stitching if you only want to stitch some variables, not all.
)
```

## Use cases

### TCR calculation

Need tas monthly for 1pctCO2 and piControl. piControl has to span at least the same length as 1pctCO2 (ideally longer). Cell areas are desirable but optional.

### ECS calculation

Need tas, rsdt, rlut and rsut for abrupt-4xCO2 and piControl. piControl has to span at least the same length as abrupt-4xCO2 (ideally longer). Cell areas are desirable but optional.

### TCRE calculation

#### flat10

Need tas monthly for esm-flat10 and piControl. piControl has to span at least the same length as esm-flat10 (ideally longer). Cell areas are desirable but optional.

#### 1pctCO2

Need tas and fgco2 and nbp monthly for 1pctCO2 and piControl. piControl has to span at least the same length as 1pctCO2 (ideally longer). Cell areas are desirable but optional.

[Method: use fgco2 and nbp and assumed change in atmospheric CO2 to get inferred fossil carbon flux, then use that plus tas to get TCRE]

### ZEC

#### flat10

Need tas monthly for esm-flat10-zec and piControl. piControl has to span at least the same length as esm-flat10-zec (ideally longer). Cell areas are desirable but optional.

#### 1pctCO2

NA in CMIP7 I think (no cessation experiments, no bell experiments ?)

Need tas and fgco2 and nbp monthly for 1pctCO2 branch experiments and piControl. piControl has to span at least the same length as 1pctCO2 (ideally longer). Cell areas are desirable but optional.

[Method: use fgco2 and nbp and assumed change in atmospheric CO2 to get inferred fossil carbon flux, then use that plus tas to get TCRE]

#### Bell experiments

Need tas monthly for 1pctCO2 branch experiments and piControl. piControl has to span at least the same length as the bell experiment (ideally longer). Cell areas are desirable but optional.

[Method note: you have to have the piControl. Without it, you can misdiagnose ZEC (assume it is flat when actually it wouldn't be flat if you accounted for model drift)]

### Other calibration stuff

tas monthly for esm-flat10-cdr and piControl. piControl has to span at least same length as esm-flat10-cdr (ideally longer). Cell areas are desirable but optional.

### ERF calculation

Either of the two below can work

#### transient

Experiment: piClim-control plus any of piClim-histall, piClim-histaer. Variables: rsut, rlut, rsdt (or rndt or whatever it is that is the pre-calculated difference of these)

Ideally piClim-control extends as long as the other experiments. If it doesn't, have to somehow extend.

[Method: subtract rndt from e.g. piClim-histall from same from piClim-control and get ERF (logic is that rndt = ERF + lambda * T, run two experiments with same T (prescribed), assume that ERF is zero in piClim-control so then taking the difference between the two experiments leaves delta rndt = ERF)]

#### time slice

Experiment: piClim-control plus any of piClim-4xCO2, piClim-aer, piClim-anthro, piClim-CH4, piClim-N2O, piClim-NOx, piClim-ODS, piClim-SO2. Variables: rsut, rlut, rsdt (or rndt or whatever it is that is the pre-calculated difference of these)

[Method: subtract rndt from e.g. piClim-4xCO2 from same from piClim-control and get ERF (logic is that rndt = ERF + lambda * T, run two experiments with same T (prescribed), assume that ERF is zero in piClim-control so then taking the difference between the two experiments leaves delta rndt = ERF).
Time slice experiments so you only get the ERF for the particular period in time at which the forcing was taken, not a transient ERF like the above]

### tas scenario calculation including anomalies

Need tas monthly for scenarios plus historical plus piControl. piControl ideally spans same length as historical plus scenarios. Cell areas are desirable but optional.

### GCMagicc

Daily or monthly

Variables (ideally all, @malte is there a minimum set/combination of sets?): clt, evspsbl, hurs, huss, mrso, pr, psl, rlut, rsds, rsdt, rsut, rtmt, sfcWind, tas, tasmax, tasmin, ts, uas, va

Experiments (any): historical, esm-hist, scenarios, abrupt-*, 1pctCO2, piControl (@malte others?)

### carbon cycle closure checking/carbon cycle calibration

@Gang I guess carbon pools and fluxes? Are there multiple options for combinations of variables e.g. "I need to {A, B, C} or {A, D, E}, but I don't need all of {A, B, C, D, E}"?

Cell areas desirable but optional? Surface land fractions required?

Experiments (any): historical, esm-hist, scenarios, abrupt-*, 1pctCO2, piControl (@Gang others?)

### Energy balance

Need rsdt, rlut, rsut, hfds and ocean surface fraction. Cell areas desirable but optional.

Experiments, any of: piControl, historical, scenarios, abrupt-*, 1pctCO2, ...

### pattern scaling

Same as tas scenario calculation?

### pattern effect

Need tas monthly for historical
