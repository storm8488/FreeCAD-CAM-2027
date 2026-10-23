# Setup sheet — 01 Palpage du coin

- CAM2027 0.1.3 on FreeCAD 1.1.4
- Machine: LUNYEE 4040 Nova (controller: grbl)
- Post processor: grbl --no-show-editor --precision=3
- Work coordinate systems: G54
- Stock: 200.00 x 150.00 x 18.00 mm, X 0.00..200.00, Y 0.00..150.00, Z -18.00..0.00

## Tools

| T | Assembly | Tool | Type | D (mm) | Flutes | Stickout (mm) | Holder | Change |
|---|---|---|---|---|---|---|---|---|
| 99 | T99 Touch probe | Touch probe | Flat end mill | 2.000 | 1 | 40.0 | - | manual |

## Operations

| # | Operation | Strategy | T | Preset | Spindle (rpm) | Feed (mm/min) | Plunge (mm/min) |
|---|---|---|---|---|---|---|---|
| 1 | Probe the origin (corner) | probe | 99 | Probing | 0 | 100 | 100 |

## Estimated machining time

- Total: 0 min 03 s (feed and rapid moves with acceleration 500 mm/s², rapids at 3000 mm/min; tool changes not counted)
- Without acceleration (length / feed): 0 min 02 s
- Assumed (machine profile to fill in): acceleration 500 mm/s², rapid feed 3000 mm/min

| Operation | Time |
|---|---|
| Probe the origin (corner) | 0 min 03 s |

## G-code analysis

- Lines: 31, units: mm, axes: X Y Z
- Codes: G0 G10 G17 G21 G38.2 G54 G90 G91 M2 M5
- X: 0.000 .. 10.000
- Y: 0.000 .. 0.000
- Max feed: F100, spindle: , tool changes (M6): 0, pauses (M0): 0

## Checks

- [UNVERIFIABLE] X travel unknown: envelope 0.00..10.00 mm not checked
- [UNVERIFIABLE] Y travel unknown: envelope 0.00..0.00 mm not checked
- [UNVERIFIABLE] max feed unknown: F100 not checked
- [UNVERIFIABLE] collisions not checked for these toolpaths: run Simulate > Material and collision check

Machine data still to fill in: travel_x_mm, travel_y_mm, travel_z_mm, max_feed_xy_mm_min, max_feed_z_mm_min, acceleration_mm_s2, spindle_min_rpm, spindle_max_rpm, collet, feed_mode_rotary
