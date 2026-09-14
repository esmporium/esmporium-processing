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

## Prompt

We are going to build a package for processing earth system model output.
We are going to build this around the data handling provided by the esmporium package (github here: https://github.com/esmporium/esmporium, the repo is cloned locally at `../esmporium`).
This is going to be a relatively large effort.

For right now, the task is to figure out a way to express requirements for different pieces of analysis.
I want to find a way to express requirements and somehow combine them in a way which is relatively easy to use/understand as a user.
If you look in `../esmporium/PLAN.md`, this is very closely linked to the implementation we want to do in PR3.7.
We want this expression to build around esmporium's existing idea of `Query` I think, but we will need to add lots of other components.

We need to support quite a number of use cases.
Here are some which I have already thought about.

### Use case 1: calculating TCR

Here we need tas monthly for the 1pctCO2 and piControl experiments. piControl has to span at least the same length as 1pctCO2, ideally it runs a given number of years longer at either end.
Cell areas that link to all tas datasets are desirable, but ultimately optional.

### Use case 2: calculating ECS

Here we need tas and rsdt and rlut and rsut monthly for the abrupt-4xCO2 and piControl experiments.
piControl has to span at least the same length as abrupt-4xCO2, ideally it runs a given number of years longer at either end.
Cell areas that link to all datasets are desirable, but ultimately optional.

The same data for the abrupt-2xCO2 and abrupt-0p5xCO2 experiments is also desirable, but optional.
The data is only useful if it meets the same constraints as for abrupt-4xCO2.
The data for abrupt-4xCO2 is required, only for abrupt-2xCO2 and abrupt-0p5xCO2 is it optional.

### Use case 3: calculating TCRE with flat10

Here we need tas monthly for the esm-flat10 and piControl experiments.
piControl has to span at least the same length as esm-flat10, ideally it runs a given number of years longer at either end.
Cell areas that link to all tas datasets are desirable, but ultimately optional.

### Use case 4: calculating TCRE with 1pctCO2

Here we need tas, fgco2 and nbp monthly for the 1pctCO2 and piControl experiments.
piControl has to span at least the same length as 1pctCO2, ideally it runs a given number of years longer at either end.
Cell areas that link to all datasets are desirable, but ultimately optional.
I think surface land (for nbp) and ocean (for fgco2) fractions are required to calculate global total fluxes for these two variables, so please make these also required (unless you can find evidence that these surface fractions are not required to perform the global flux calculations).

[Method note, don't worry about this right now @Claude: use fgco2 and nbp and assumed change in atmospheric CO2 to get inferred fossil carbon flux, then use that plus tas to get TCRE]

### Use case 5: ZEC with flat10

Here we need tas monthly for the esm-flat10-zec (and its parents back to piControl, if there are any) and piControl experiments.
piControl has to span at least the same length as esm-flat10, ideally it runs a given number of years longer at either end.
Cell areas that link to all tas datasets are desirable, but ultimately optional.

### Use case 6: calculating ZEC with 1pctCO2

Here we need tas monthly for the 1pctCO2 branch experiments plus their parents back to piControl (I can't remember their exact names) and piControl experiments.
piControl has to span at least the same length as 1pctCO2 branch plus its parents, ideally it runs a given number of years longer at either end.
Cell areas that link to all datasets are desirable, but ultimately optional.

Optionally, we would also like to get fgco2 and nbp monthly for the 1pctCO2 branch experiments plus their parents back to piControl (I can't remember their exact names) and piControl experiments.
I think surface land (for nbp) and ocean (for fgco2) fractions are required to calculate global total fluxes for these two variables, so please make these also required (unless you can find evidence that these surface fractions are not required to perform the global flux calculations).

[Method note, don't worry about this right now @Claude: use fgco2 and nbp and assumed change in atmospheric CO2 to get inferred fossil carbon flux and double check total carbon into the system at the branch time]

### Use case 7: calculating ZEC with bell

Here we need tas monthly for the zec bell experiments and piControl experiments.
piControl has to span at least the same length as 1pctCO2 branch plus its parents, ideally it runs a given number of years longer at either end.
Cell areas that link to all datasets are desirable, but ultimately optional.

Optionally, we would also like to get fgco2 and nbp monthly for the bell experiments and piControl experiments.
I think surface land (for nbp) and ocean (for fgco2) fractions are required to calculate global total fluxes for these two variables, so please make these also required (unless you can find evidence that these surface fractions are not required to perform the global flux calculations).

[Method note, don't worry about this right now @Claude: use fgco2 and nbp and assumed change in atmospheric CO2 to get inferred fossil carbon flux and double check total carbon into the system over the experiment]

### Use case 8: esm-flat10-cdr

Here we need tas monthly for esm-flat10-cdr (and its parents back to piControl) and piControl experiments.
piControl has to span at least the same length as esm-flat10-cdr (and its parents), ideally it runs a given number of years longer at either end.
Cell areas that link to all datasets are desirable, but ultimately optional.

Optionally, we would also like to get fgco2 and nbp monthly for the bell experiments and piControl experiments.
I think surface land (for nbp) and ocean (for fgco2) fractions are required to calculate global total fluxes for these two variables, so please make these also required (unless you can find evidence that these surface fractions are not required to perform the global flux calculations).

[Method note, don't worry about this right now @Claude: use fgco2 and nbp and assumed change in atmospheric CO2 to get inferred fossil carbon flux and double check total carbon into the system over the experiment]

### Use case 9: ERFs from transient experiments

Here we need piClim-control plus piClim-histall or piClim-histaer for rsut, rlut and rsdt or rndt (which is the pre-calculated difference between these, we can actually use rndt for ECS calculations too).
piClim-control has to span at least the same length as piClim-histall or piClim-histaer to be usable.
Cell areas that link to all datasets are desirable, but ultimately optional.

[Method note, don't worry about this right now @Claude: subtract rndt from e.g. piClim-histall from rndt from piClim-control. This difference is ERF (logic is that rndt = ERF + lambda * T, run two experiments with same T (prescribed), assume that ERF is zero in piClim-control so then taking the difference between the two experiments leaves delta rndt = ERF)]

### Use case 10: ERFs from time slice experiments

Here we need piClim-control plus piClim-4xCO2 or piClim-aer or piClim-anthro or piClim-CH4 or piClim-N2O or piClim-NOx or piClim-ODS or piClim-SO2
for rsut, rlut and rsdt or rndt (which is the pre-calculated difference between these, we can actually use rndt for ECS calculations too).
piClim-control has to span at least the same length as piClim-histall or piClim-histaer to be usable.
Cell areas that link to all datasets are desirable, but ultimately optional.

[Method note, don't worry about this right now @Claude: subtract rndt from e.g. piClim-4xCO2 from same from piClim-control and get ERF (logic is that rndt = ERF + lambda * T, run two experiments with same T (prescribed), assume that ERF is zero in piClim-control so then taking the difference between the two experiments leaves delta rndt = ERF). Time slice experiments so you only get the ERF for the particular period in time at which the forcing was taken, not a transient ERF like the above]

### Use case 11: tas scenario calculation including anomalies

Here we need tas monthly for scenarios plus their parents back to piControl.
piControl ideally spans at least the same length as the scenarios plus their parents (but there are ways to work around this if it is not the case).
Cell areas that link to all datasets are desirable, but ultimately optional.

### Use case 12: GCMagicc

Here we need daily or monthly data for the following variables: hurs, huss, pr, psl, rsds, ((rlut and rsdt and rsut) or rtmt), sfcWind or (uas and vas), tas, tasmax, tasmin, ts
These variables are optional: clt, evspsbl, mrso

We need these for any of the following experiments: historical, esm-hist, scenarios, abrupt-*, 1pctCO2, piControl

### Use case 13: energy balance

Here we need rsdt, rlut, rsut or rndt, and hfds.
Cell areas that link to all datasets are desirable, but ultimately optional.
Surface ocean fractions are required to calculate global fluxes from hfds I believe (correct me if I'm wrong).
We want these for any of the following experiments: piControl, historical, scenarios, abrupt-*, 1pctCO2, esm-flat10*

### Use case 14: pattern effect

Need tas monthly for historical

### Use case 15: pattern scaling

Need scenarios plus its parents back to piControl.
Need any of the following variables at monthly time sampling: tas, tasmax, tasmin, huss, pr, sfcWind, ps, rsds, rlds, pr
Cell areas that link to all datasets are desirable, but ultimately optional.
Land surface fractions that link to all datasets are desirable, but ultimately optional.

### Use case 16: carbon cycle closure

Need monthly for (cLand or (cVeg and cLitter and cSoil and cProduct)) and (npp or (gpp and ra)) and rh and optional(fAnthDisturb) and optional(fProductDecomp) and optional(fFireNat) and optional(fCLandToOcean) and optional (fFire) and optional(fLUC).
We want these for the whole 1pctCO2 family, including 1pctCO2, 1pctCO2-bgc, 1pctCO2-rad, and 1pctCO2-Ndep, plus the ZEC and esm-flat10 families too, plus piControl, historical and scenarios. The 1pctCO2 experiment is required, all other experiments are desirable but optional.
Cell areas that link to all datasets are desirable, but ultimately optional.
Land surface fractions that link to all datasets are required I believe (unless you can prove otherwise).

### Use case 16a: carbon cycle calibration

Same as above, but also requiring cVeg, cLitter, cSoil and cProduct.

### Use case 17: expert team on climate change detection and indices (ETCCDI)

Need daily tasmax, tasmin and pr for scenarios and parents back to piControl.
Full list is here if you want to dig this out more closely: https://cds.climate.copernicus.eu/datasets/sis-extreme-indices-cmip6?tab=overview

### Use case 18: AMOC/SMOC calculations

Monthly msftmz or msftyz for scenarios plus parents back to piControl

### Use case 19: sea-ice concentrations

Monthly siconc for scenarios plus parents back to piControl.
Need ocean cell areas too.
I'm not sure if ocean cell fractions are required or optional.

### Implementation

In terms of how to implement this, I am not sure exactly.
That's really what I want your help with.
How can we design a way to express these requirements, and translate them into esmporium search queries and other uses, in a way that is relatively easy to understand and support.
I am quite tempted by the idea of making some object(s), on which we can impose custom logic so it is relatively easy to compose queries using syntax like
`my_query = CustomType(experiment="scen7-m", parent_until="piControl") & CustomType2(variable="rsdt") & CustomType2(varaible="rsut") | CustomType2(variable="rndt") &Optional CustomType2(variable="hfds")`
That's obviously not real syntax, but hopefully you get the idea.
Maybe we'll need to use functions rather than this purely `&` `|` based logic, that would also be fine.

The REF (https://github.com/Climate-REF/climate-ref) has the idea of 'constraints' (https://github.com/Climate-REF/climate-ref/blob/main/packages/climate-ref-core/src/climate_ref_core/constraints.py),
but these seem to always apply with AND logic, whereas we need OR and the idea of OPTIONAL too.

I was thinking that it would be nice if an analysis function could decorate its inputs,
and this could then be used to derive a set of queries/constraints/whatever name we choose.
Something like

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

Notes:

- names happen to match variables in this case, doesn't always have to be like this
    - e.g. could be different experiments for stitching workflows and you group by variable instead
- abrupt-4xCO2 or abrupt4xco2 i.e. either spelling (values are not ours i.e. have to be changed at load time)
- parent required back until piControl
    - no parent finding injection here - has to be done at ingestion time i.e. during search or between search and this function
- auxilliary_file is optional
    - no auxilliary file finding injection here - has to be done at ingestion time i.e. during search or between search and this function
- one of multiple experiments because the target experiment can vary by CMIP phase i.e. project
- define how to group so we can figure out how to determine whether groups are complete or not and raise appropriately on multiple matches

I am not sure if this is a great way to implement this though.

I have already thought about this a bit, see `PLAN-LOAD-CLAUDE.md`.
That plan covers a lot more than just defining these requirements.
However I think it already has a hole: how would you express, "I need the global-mean from piControl", as compared to just, "I need a global-mean"? Having a type for global-mean from piControl separate to global-mean from scenarios etc. seems like it would lead to a lot of types very quickly.
