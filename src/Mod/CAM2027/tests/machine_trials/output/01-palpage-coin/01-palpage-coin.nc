(Exported by FreeCAD)
(Post Processor: grbl_post)
(Begin preamble)
G17 G90
G21
(Begin operation: Fixture)
(Path: Fixture)
G54
(Finish operation: Fixture)
(Begin operation: TC: probe)
(Path: TC: probe)
(TC: probe)
(Begin toolchange)
( M6 T99 )
(Finish operation: TC: probe)
(Begin operation: Probe the origin [corner])
(Path: Probe the origin [corner])
(Probe the origin corner])
(Begin Custom)
(CAM2027 probe origin: corner front-left)
M5
G21
G90
G54
G91
G38.2 Z-25.000 F100.000
G10 Z0.000 L20.0 P1.0
G0 Z2.000
G0 X-16.000
G0 Z-5.000
G38.2 X11.000 F100.000
G10 X-1.000 L20.0 P1.0
G0 X-5.000
G0 Z5.000
G90
G0 X10.000
G91
G0 Y-16.000
G0 Z-5.000
G38.2 Y11.000 F100.000
G10 Y-1.000 L20.0 P1.0
G0 Y-5.000
G0 Z5.000
G90
G0 X0.000 Y0.000
(End Custom)
(Finish operation: Probe the origin [corner])
(Begin postamble)
M5
G17 G90
M2
