# Setup sheet — 04 Percage

- CAM2027 0.1.3 on FreeCAD 1.1.4
- Machine: LUNYEE 4040 Nova (controller: grbl)
- Post processor: grbl --no-show-editor --precision=3
- Work coordinate systems: G54
- Stock: 200.00 x 150.00 x 18.00 mm, X 0.00..200.00, Y 0.00..150.00, Z -18.00..0.00

## Tools

| T | Assembly | Tool | Type | D (mm) | Flutes | Stickout (mm) | Holder | Change |
|---|---|---|---|---|---|---|---|---|
| 1 | T1 6 mm flat end mill 2F | 6 mm flat end mill 2F | Flat end mill | 6.000 | 2 | 35.0 | ER20 collet chuck (generic) | manual |

## Operations

| # | Operation | Strategy | T | Preset | Spindle (rpm) | Feed (mm/min) | Plunge (mm/min) |
|---|---|---|---|---|---|---|---|
| 1 | Percage 3 trous | drilling | 1 | Wood roughing | 18000 | 1800 | 600 |

## Estimated machining time

- Total: 0 min 04 s (feed and rapid moves with acceleration 500 mm/s², rapids at 3000 mm/min; tool changes not counted)
- Without acceleration (length / feed): 0 min 04 s
- Assumed (machine profile to fill in): acceleration 500 mm/s², rapid feed 3000 mm/min

| Operation | Time |
|---|---|
| Percage 3 trous | 0 min 04 s |

## G-code analysis

- Lines: 23, units: mm, axes: X Y Z
- Codes: G0 G1 G17 G21 G54 G90 M2 M3 M5
- X: 140.000 .. 180.000
- Y: 35.000 .. 35.000
- Z: -10.000 .. 5.000
- Max feed: F600, spindle: S18000, tool changes (M6): 0, pauses (M0): 0

## Checks

- [UNVERIFIABLE] X travel unknown: envelope 140.00..180.00 mm not checked
- [UNVERIFIABLE] Y travel unknown: envelope 35.00..35.00 mm not checked
- [UNVERIFIABLE] Z travel unknown: envelope -10.00..5.00 mm not checked
- [UNVERIFIABLE] max feed unknown: F600 not checked
- [UNVERIFIABLE] spindle range unknown: S18000..S18000 not checked
- [UNVERIFIABLE] collisions not checked for these toolpaths: run Simulate > Material and collision check

Machine data still to fill in: travel_x_mm, travel_y_mm, travel_z_mm, max_feed_xy_mm_min, max_feed_z_mm_min, acceleration_mm_s2, spindle_min_rpm, spindle_max_rpm, collet, feed_mode_rotary
