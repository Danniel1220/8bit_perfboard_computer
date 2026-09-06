# Blank-routing startup fix

Replace perfopt/coordinator.py in your existing v2 installation with the copy in this update. Stop the optimizer before replacing program files. No configuration or run files are included.

The startup now generates the physical junction plan before validation. All 12 physical-rule tests pass, including blank startup with connector escape lengths 1 and 2; a zero-candidate CLI startup/exit also passes.

With connector_escape_cells=2, the supplied starting placement has a separate collision: J_BUS stubs enter U_BUS. In config/alu.json, changing U_BUS initial x from 5 to 6 supplies the necessary clearance and passes physical validation. This placement change is not applied by the update. Use --fresh --blank-routing with a new run folder after changing geometry.
