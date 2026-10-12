# Fix SOF dispatch overload resolution

## Why
The receiver-type fallback can misidentify a business `fireEvent` overload as SOF dispatch when generated getters prevent exact method resolution. The reproduced call binds to an empty private overload, but the scan invents a listener edge.

## What Changes
- Check same-name candidate method declarations, including inheritance and variable arity, before accepting SOF dispatch after exact resolution fails.
- Share the check across explicit and implicit receivers; ambiguous business overloads retain a dispatch diagnostic and produce no listener edge.
- Preserve exact resolution, ordinary wrapper behavior and unambiguous inherited SOF dispatch.

## Impact
Only Java semantic dispatch analysis, its regression tests and the existing source-scan requirement change. No new dependencies, persistence or business-specific configuration.
