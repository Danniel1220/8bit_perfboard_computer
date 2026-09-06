# v0.4 configuration notes

The enabled portfolio changes best ranking to manual-finish merit and uses dedicated scouts/slot routers. See README.md for the authoritative v0.4 settings and worker allocation; v3 explorer settings below apply only when portfolio mode is disabled. `placement_groups` must assign every IC exactly once. `portfolio.slots` is fixed for a run; search/merit/refresh tuning is allowed on resume. Existing physical geometry and logic schemas below remain unchanged.

# Configuration and extension guide

`config/alu.json` is the complete board description. There are no references to the original E: drive or earlier build scripts. Paths such as `assets/AND.svg` and `config/alu-seed-v2.json` resolve relative to the parent of the configuration directory. Keep another board in the same `config/` folder or use the same folder structure elsewhere.

This is a generic geometry/search engine with a supported family of logical primitives, not an arbitrary circuit simulator. A new package for an existing primitive needs JSON and artwork. A new kind of logic device also needs a primitive implementation/equivalence rule in `perfopt/logic.py`, with appropriate tests. The ALU exhaustive truth-table oracle is deliberately board-specific and selected by `validation.kind`.

## Top-level schema, version 1

| Field | Meaning |
|---|---|
| `schema_version` | Integer 1 |
| `name` | Dashboard/export title |
| `board` | `width`, `height` in hole cells; `pitch_mm`; `svg_pitch` in artwork units |
| `constants` | Constant net names and bit values; current power roles use `VCC` and `GND` |
| `packages` | Named package geometries, pin role mappings, and SVG artwork |
| `components` | Instances, physical pin-to-net assignments, initial placements, movement/permutation permissions |
| `groups` | Named functional groups with `members` and optional bounding-box `padding` |
| `symmetry_pairs` | Component `a`, component `b`, desired `[dx,dy]` offset |
| `flow_edges` | Group `from`, group `to`, direction `left/right/up/down` |
| `corridors` | `[x,y,width,height]` rectangle, allowed net glob patterns, organization penalty multiplier `weight` (0–1) |
| `keepouts` | Objects containing grid `rect: [x,y,width,height]` |
| `constraints` | Escape, crossing, cap, and connector rail rules |
| `weights` | Nonnegative aesthetic/routing cost coefficients |
| `search` | Budgets, plateau settings, retention, and mutation probabilities |
| `validation` | `kind: alu8` or `equivalence_only`; ALU flag instance IDs |
| `colors` | Net prefix to SVG color mapping |
| `seed` | Relative path to a JSON object containing `candidate` |

All hole coordinates and movements are integers. Origin is the board's upper-left hole cell, x rightward and y downward. The supplied board is **114 columns × 77 rows** at 2.54 mm pitch. Rectangles use an inclusive origin and exclusive upper bound. Pin holes lie at cell centers in the SVG. The SVG uses 7.2 artwork units per grid pitch; physical dimensions are specified in mm.

## Packages and components

IC package fields: `kind: ic`, `name`, `size: [width,height]`, `asset`, and `pins`. Pin keys are physical pin numbers as strings. Each pin declares a logical `role`, local `at: [x,y]`, and cardinal outward direction `out: [dx,dy]`. Local geometry describes the unrotated IC; the engine rotates body, pins, and escape directions together.

Example pin from the quad AND package:

```json
"1": {"role": "a0", "at": [0, 3], "out": [0, 1]}
```

Connector packages use `kind: connector` and `count` (2–8 for your JSTs). The engine creates a three-cell-wide connector body and an inward-facing escape. Existing JST6/JST8 artwork is included; other supported counts use generated vector artwork.

Each component declares:

```json
{
  "id": "U_EXAMPLE",
  "package": "AND",
  "function": "AND",
  "initial": {"x": 20, "y": 20, "rotation": 0},
  "pin_nets": {"1": "A0", "2": "B0", "3": "AND0"},
  "fixed": false,
  "rotations": [0, 90, 180, 270],
  "capacitor": true,
  "group": "logic",
  "equivalent_channels": [["a0", "b0", "q0"], ["a1", "b1", "q1"]],
  "commutative_pairs": [["a0", "b0"], ["a1", "b1"]]
}
```

The example is abbreviated: a real `pin_nets` must include **every physical pin**. Use `null` for an unused pin, never for an input that must be tied. Assign VCC/GND or another constant for fixed ties. Gates whose outputs are unused may have unused channels; an active logical channel must have its required input nets defined.

`fixed` locks placement. `rotations` lists allowed right-angle rotations. `capacitor: true` adds a cap attached directly to the right of a horizontal IC or below a vertical IC, rotated as necessary, and includes it in body collision checks. Only those two cap rules are supported in version 1.

Connectors additionally specify `edges`, `reorder_pins`, and an `initial.edge`. Their x/y position identifies the first pin. Left/right rails constrain x, top/bottom rails constrain y, using `constraints.connector_inset`. Along-edge movement is limited by board bounds and body collisions. Give `edges: ["left"]` to constrain a connector to the left side. Give multiple legal edges only if you want it to move between them during larger mutations. Connector sizes are fixed during search; change the configuration to introduce another connector.

`equivalent_channels` lists bundles of roles that move together. The optimizer swaps two whole bundles, retaining logical net names. A quad mux channel contains its A input, B input, and output. A mux's A/B inputs are not commutative. `commutative_pairs` explicitly allows interchangeable input pairs on AND/OR/XOR gates. Adder carry chains and weighted bit roles have no channel permutation permission. Configured permutations must preserve the canonical primitive netlist; unsafe definitions fail validation rather than silently rewiring the circuit.

## Logical primitive roles

Every IC includes physical roles `VCC` and `GND` assigned to those power nets.

| Primitive | Required signal role naming |
|---|---|
| AND / OR / XOR | `a0..a3`, `b0..b3`, `q0..q3` |
| MUX (quad 2:1) | `a0..a3`, `b0..b3`, `q0..q3`, `sel`, `en` (active low) |
| ADD (4-bit) | `a0..a3`, `b0..b3`, `q0..q3`, `ci`, `co` |
| BUF (8-bit transceiver) | `a0..a7`, `b0..b7`, `dir`, `oe` |
| CMP (74LS688) | `p0..p7`, `q0..q7`, `en`, `eq_n` |
| LUT (74LS151) | `d0..d7`, `s0..s2`, `en`, `y`, `w` |
| REG (74LS173) | `d0..d3`, `q0..q3`, `clk`, `clr`, `g1`, `g2`, `m`, `n` |
| SEL (74LS153) | `d00..d03`, `d10..d13`, `q0`, `q1`, `s0`, `s1`, `en0`, `en1` |

Net equality defines electrical connectivity; there is no separate duplicated connection list. The engine checks all nonconstant terminal nets, even if routing is incomplete. Canonical equivalence preserves the configured circuit under allowed physical permutations. `equivalence_only` protects that initial topology but does **not** establish that an arbitrary new circuit implements your intended function; add a functional oracle for that board.

## Supplied ALU behavior

OP1/OP0 select: 00 arithmetic, 01 XOR, 10 AND, 11 OR. SUB selects A+B or A+(B XOR FF)+1 in the arithmetic path. A and B arrive from top and bottom connectors. Bus/control/flag connectors remain on the left, with pin order flexible.

The discrete adder/gate/mux architecture is retained. Carry is the arithmetic carry-out (for subtraction, the usual no-borrow carry convention). N is selected result bit R7. The 74LS688 compares the selected result to zero, giving **ZERO_N**, low for zero.

Overflow uses one 74LS151: selector bits S0=A7, S1=BX7, S2=SUM7, with D3/D4 high and all other D inputs low. BX7 is the existing subtraction-conditioned B bit. Thus V is valid for both ADD and SUB without another SUB-conditioning IC. C/V still reflect the arithmetic path during logic operations.

The 74LS173 captures C, ZERO_N, N, V together on a rising CLK when FLAGS_LOAD_N is low. CLEAR high asynchronously resets all stored bits to zero. Because ZERO_N is stored without inversion, clear also makes stored ZERO_N low. The 74LS153 presents a single FLAG: FS1/FS0=00 C, 01 ZERO_N, 10 N, 11 V. Nothing suppresses flag loading for a logic operation.

## Hard geometry rules (v2)

`ic_escape_cells` defaults to 1 for this ALU. Cells 1..N belong exclusively to that pin's net; cells 1..N-1 must be straight/unbranched, and turns/branches may begin at N. `active_escape_cells` is retained solely for legacy configurations without the new key.

`connector_escape_cells` defaults to 1 and counts exposed cells beyond the housing, all protected and unbranched. One additional cell after this region is the earliest turn/branch location. The housing margin itself is also straight. Connector clearance includes unused and constant pins. Unused IC pins reserve no exit; underside IC ties retain first-cell no-turn protection.

`physical_junctions: true` enables physical T/+ templates. One arm owns the central termination hole. Each other arm ends one cell short, in a distinct adjacent hole, and an explicit underneath link joins it to the center. Landing holes cannot be crossed by unrelated wires, overlap a component/pin, occupy a forbidden straight escape, or be claimed by another junction. Non-owner arms must approach straight; a mandatory stub edge cannot become an underneath edge. A T has three owner choices; a + has four when rotated choices are included. Only combinations with compatible hole occupancy are accepted.

Candidate `junctions` records contain `net`, `center`, `owner`, `ends`, and `underneath` links. Every coordinate is a node ID (`row * width + column`). The validator recomputes the deterministic plan and rejects a stale/mismatched saved plan. The logical graph's cut edges are exactly restored by the recorded underneath links. SVG thick paths are the maximal remaining top-wire chains, with thin dashed underside links in a separate group.

All existing grid, bounds, body/cap overlap, insulated orthogonal crossing, and electrical-equivalence rules remain in force. Configured keepouts block placement and routing. Version 2 starts from blank wiring; legacy bests are not compatible with these rules.

## Search and scoring settings

`candidate_seconds` bounds routing work, not whole-process startup/export time. `max_astar_nodes` bounds each A* search (checked in batches of 512 expansions); `max_route_attempts` bounds candidate repair. Workers keep room for negotiated rip-up after initial strict attempts. The path search uses unit length, bend/crossing penalties, compact grid indices, precomputed neighbors, foreign-net axis masks, and historical conflict costs.

`mutation_weights` supports `route`, `move`, `rotate`, `connector_move`, `connector_order`, `gate_channels`, `mux_channels`, `input_swap`, `group_move`. Values need not sum to one. Omit a mutation or give zero to disable it; at least one must have positive weight. Plateau levels enlarge moves from radius 1 to 3, 8, then 14 cells, alter probabilities, and enable occasional elite restarts.

`plateau_seconds` and `plateau_candidates` use time/count since each worker's local best improvement. `worker_state_seconds` and `adopt_seconds` control durable state frequency and adoption of another worker's global best. `summary_seconds` defaults to 600. `checkpoint_retention` defaults to 40. State keeps a bounded congestion history; it is a heuristic, not an exhaustive record of every contested cell.

The weighted organization terms are measured from current group centers/bounds and net membership. `corridors.weight` reduces foreign-group/internal-escape penalties for matching nets inside its rectangle: 0 means exempt, 1 means no discount. Corridors are aesthetic preferences, not hard empty lanes. `symmetry_pairs` penalize displacement from the configured offset and differing orientations; this is alignment guidance rather than a hard mirror constraint. Increasing a weight increases its importance in best-candidate ranking; the A* inner loop remains a simpler geometric/congestion router.

Topology compatibility hashes include board, packages, pin assignments, constraints, groups, and validation definition. Search settings, aesthetic weights, colors, and the seed path are excluded so they can be changed on resume. Copy a board configuration and use a fresh run when making structural changes.

## Candidate/checkpoint representation

A candidate has `placements`, `pin_nets`, and `routes`. Route records contain `net`, `kind: pin|wire`, and `points`: unit-adjacent integer node IDs `row * board_width + column`. Pin routes must exactly match regenerated stubs. A seed wraps it as `{"candidate": ...}`. A durable resume checkpoint wraps its payload with schema version and SHA-256 and additionally records metrics/search/RNG information. Never hand-edit a resume checkpoint without regenerating its checksum and revalidating its candidate.

Use `config/example-connector-board.json` with a separate run to see a small fully connected non-ALU example. Its two named nets join two movable two-pin edge connectors; the test suite also validates it independently. It illustrates geometry/config reuse without claiming generic exhaustive electronics simulation.

## V3 exploration and bundle settings

See README.md for defaults and exact tuning commands. `signal_bundles` contains objects with `name` and `nets`: each net must be known, nonconstant, and appear in at most one bundle. Bundle membership never authorizes logical bit permutation. `weights.bundle_separation` strongly penalizes unpaired parallel lane edges; `search.bundle_route_penalty` guides A* toward existing peer lanes. Explorer worker settings are persisted in worker checkpoint progress as described in the operating guide.
