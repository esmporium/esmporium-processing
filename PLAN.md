- declarative way to say what you need and get it in a sensible form
- way to specify how to load
- loading
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
