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
