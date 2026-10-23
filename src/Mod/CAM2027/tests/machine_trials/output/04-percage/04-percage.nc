(Exported by FreeCAD)
(Post Processor: grbl_post)
(Begin preamble)
G17 G90
G21
(Begin operation: Fixture)
(Path: Fixture)
G54
(Finish operation: Fixture)
(Begin operation: TC: Percage 3 trous)
(Path: TC: Percage 3 trous)
(TC: Percage 3 trous)
(Begin toolchange)
( M6 T1 )
M3 S18000
(Finish operation: TC: Percage 3 trous)
(Begin operation: Percage 3 trous)
(Path: Percage 3 trous)
(Percage 3 trous)
(Begin Drilling)
G90
G0 Z5.000
( G98 )
G0 X140.000 Y35.000
G0 Z3.000
(G81 X140.000 Y35.000 Z-10.000 F600.000 R3.000)
G0 X140.000 Y35.000
G1 Z-10.000 F600.00
G0 Z3.000
G0 X160.000 Y35.000
(G81 X160.000 Y35.000 Z-10.000 F600.000 R3.000)
G0 X160.000 Y35.000
G1 Z-10.000 F600.00
G0 Z3.000
G0 X180.000 Y35.000
(G81 X180.000 Y35.000 Z-10.000 F600.000 R3.000)
G0 X180.000 Y35.000
G1 Z-10.000 F600.00
G0 Z3.000
( G80 )
G0 Z5.000
(Finish operation: Percage 3 trous)
(Begin postamble)
M5
G17 G90
M2
