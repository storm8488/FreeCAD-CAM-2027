# SPDX-License-Identifier: LGPL-2.1-or-later
"""Spécification déclarative des paramètres d'opération exposés dans l'éditeur.

Chaque propriété FreeCAD listée dans ``STRATEGIES[kind]["params"]`` a ici un
libellé, un groupe d'onglet et une aide courte (chaînes anglaises, traduites
via ``tr()``). Le type, les valeurs admises d'une énumération et la valeur
courante sont lus sur l'objet FreeCAD lui-même (``operations.param_kind`` /
``read_params``), ce qui évite de dupliquer les définitions de FreeCAD.

Groupes (onglets de l'éditeur) : ``heights`` (hauteurs et profondeurs),
``passes`` (passes, engagement, surépaisseur), ``strategy`` (propre à la
stratégie), ``thread`` (filetage), ``entry`` (entrées, sorties, attaches).
"""

GROUPS = (
    ("heights", "Heights & depths"),
    ("passes", "Passes"),
    ("strategy", "Strategy"),
    ("thread", "Thread"),
    ("entry", "Entry, exit & tabs"),
)

#: nom de propriété FreeCAD -> (libellé, groupe, aide)
PARAM_SPECS = {
    # hauteurs et profondeurs
    "ClearanceHeight": ("Clearance height", "heights", "Z for rapid moves between cuts, above every obstacle."),
    "SafeHeight": ("Safe height", "heights", "Z reached at rapid before plunging at feed."),
    "StartDepth": ("Start depth (Z)", "heights", "Top of the material to cut, usually the stock top."),
    "FinalDepth": ("Final depth (Z)", "heights", "Bottom of the cut."),
    "FinishDepth": ("Finish pass depth", "heights", "Thickness left for a final full-depth pass (0 = none)."),
    "StepDown": ("Step down", "heights", "Axial depth of cut per pass."),
    "RetractHeight": ("Retract height", "heights", "Z the drill retracts to between pecks."),
    # passes et engagement
    "StepOver": ("Step over (%)", "passes", "Radial engagement as a percentage of the tool diameter."),
    "ExtraOffset": ("Extra offset", "passes", "Material left on the walls (pocket) or added outside (facing)."),
    "OffsetExtra": ("Extra offset", "passes", "Material left on the profile walls (positive = oversize)."),
    "StockToLeave": ("Stock to leave", "passes", "Material left for a finishing operation."),
    "Passes": ("Number of passes", "passes", "Radial passes used to reach the full thread depth."),
    "UseComp": ("Cutter compensation", "passes", "Offset the path by the tool radius (G41/G42 not emitted)."),
    "KeepToolDown": ("Keep tool down", "passes", "Avoid retracts between adjacent pocket passes."),
    "MinTravel": ("Minimise travel", "passes", "Reorder passes to shorten rapid moves."),
    "FinishingProfile": ("Finishing profile", "passes", "Add a final profile pass along the walls."),
    "Tolerance": ("Tolerance", "passes", "Geometric tolerance of the computation (smaller = slower)."),
    "Discretize": ("Discretisation", "passes", "Segment length used to sample curves."),
    "Colinear": ("Colinear filter", "passes", "Angle (deg) under which consecutive segments are merged."),
    "LiftDistance": ("Lift distance", "passes", "Z lift between adaptive links."),
    "KeepToolDownRatio": ("Keep tool down ratio", "passes", "Max link length (x tool diameter) kept at depth."),
    # stratégie
    "Side": ("Side", "strategy", "Which side of the geometry the tool runs on."),
    "Direction": ("Direction", "strategy", "Milling direction (climb / conventional, CW / CCW)."),
    "processHoles": ("Process holes", "strategy", "Also profile the inner contours (holes)."),
    "processPerimeter": ("Process perimeter", "strategy", "Profile the outer contour."),
    "processCircles": ("Process circles", "strategy", "Also profile circular holes."),
    "EnableRotation": ("Enable rotation", "strategy", "Rotational axis use (4th axis), off for XYZ jobs."),
    "CutMode": ("Cut mode", "strategy", "Climb or conventional milling."),
    "ZigZagAngle": ("Zigzag angle", "strategy", "Angle of the zigzag passes (deg)."),
    "OffsetPattern": ("Pattern", "strategy", "Offset, zigzag, spiral... pass pattern."),
    "ClearingPattern": ("Pattern", "strategy", "Offset, zigzag, spiral... pass pattern."),  # nom FreeCAD 1.1
    "StartAt": ("Start at", "strategy", "Start the pocket at the centre or at the edge."),
    "UseOutline": ("Use outline", "strategy", "Use only the outline of the selected faces."),
    "HelixAngle": ("Helix angle", "strategy", "Ramp angle of the helical entry (deg)."),
    "HelixDiameterLimit": ("Helix diameter limit", "strategy", "Maximum helix diameter (0 = automatic)."),
    "HelixConeAngle": ("Helix cone angle", "strategy", "Cone angle of the helical entry (deg)."),
    "OperationType": ("Operation type", "strategy", "Clearing or profiling."),
    "ForceInsideOut": ("Force inside-out", "strategy", "Always clear from the inside towards the walls."),
    "UseHelixArcs": ("Helix as arcs", "strategy", "Emit the helix as G2/G3 arcs instead of lines."),
    "PeckEnabled": ("Peck drilling", "strategy", "Retract between pecks (G83)."),
    "PeckDepth": ("Peck depth", "strategy", "Depth of each peck."),
    "DwellEnabled": ("Dwell at bottom", "strategy", "Pause at the bottom of the hole (G82)."),
    "DwellTime": ("Dwell time", "strategy", "Pause duration (s)."),
    "RetractMode": ("Retract mode", "strategy", "Retract to the retract height (G99) or the clearance height (G98)."),
    "BoundaryShape": ("Boundary", "strategy", "Area to face: bounding box, face region, perimeter or stock."),
    "ExcludeRaisedAreas": ("Exclude raised areas", "strategy", "Do not face islands higher than the face."),
    "ClearEdges": ("Clear edges", "strategy", "Let the tool centre pass just beyond the face edges."),
    "StartVertex": ("Start vertex", "strategy", "Index of the vertex where the engraving starts."),
    "StartSide": ("Start side", "strategy", "Start the helix inside or outside."),
    "StartRadius": ("Start radius", "strategy", "Radius of the first helix pass."),
    "CustomPoint1": ("Start point (custom)", "strategy", "First end of the slot when no geometry is selected (X, Y, Z)."),
    "CustomPoint2": ("End point (custom)", "strategy", "Second end of the slot when no geometry is selected (X, Y, Z)."),
    "Reference1": ("Start reference", "strategy", "Which point of the first selected feature starts the slot."),
    "Reference2": ("End reference", "strategy", "Which point of the second selected feature ends the slot."),
    "ExtendRadius": ("Extend radius", "strategy", "Extra radius added around the slot ends."),
    "ExtendPathStart": ("Extend start", "strategy", "Extend the slot at its start."),
    "ExtendPathEnd": ("Extend end", "strategy", "Extend the slot at its end."),
    "LayerMode": ("Layer mode", "strategy", "Single pass or multiple depth layers."),
    "PathOrientation": ("Path orientation", "strategy", "Orientation of the slot path."),
    "ReverseDirection": ("Reverse direction", "strategy", "Swap the start and end of the slot."),
    "Width": ("Chamfer width", "strategy", "Width of the chamfer measured on the top face."),
    "ExtraDepth": ("Extra depth", "strategy", "Extra plunge below the chamfer depth (avoids rubbing the tip)."),
    "EntryPoint": ("Entry point", "strategy", "Index of the segment where the chamfer starts."),
    # 3D (OpenCamLib)
    "CutPattern": ("Cut pattern", "strategy", "Shape of the passes: line, zigzag, offset, spiral or circular (slot: line or zigzag)."),
    "CutPatternAngle": ("Pattern angle (deg)", "strategy", "Angle of the passes in the XY plane (deg)."),
    "SampleInterval": ("Sample interval", "passes", "Distance between surface samples along a pass (smaller = more precise, slower)."),
    "BoundBox": ("Boundary", "strategy", "Machine the model bounding box or the whole stock."),
    "BoundaryAdjustment": ("Boundary adjustment", "strategy", "Grow (positive) or shrink (negative) the machined area."),
    "DepthOffset": ("Depth offset", "passes", "Material left above the surface (positive) for a later finishing pass."),
    "OptimizeLinearPaths": ("Optimise straight paths", "passes", "Merge collinear moves to shorten the G-code."),
    "LinearDeflection": ("Linear deflection", "passes", "Mesh tolerance used to sample the model (smaller = more precise)."),
    "AngularDeflection": ("Angular deflection", "passes", "Angular mesh tolerance used to sample the model."),
    "Algorithm": ("Algorithm", "strategy", "OCL Dropcutter (reference) or FreeCAD experimental."),
    "ClearLastLayer": ("Clear last layer", "strategy", "Clear the flat area left at the final depth."),
    "ScallopHeight": ("Maximum scallop height", "passes", "Height of the ridge left between two passes; the step along the surface is derived from it and the tool radius."),
    "SteepShallow": ("Steep and shallow", "strategy", "Constant-Z passes on slopes above the threshold angle, constant scallop below, in one operation."),
    "ThresholdAngle": ("Threshold angle (deg)", "strategy", "Slope separating steep areas (constant Z) from shallow areas (constant scallop)."),
    # filetage
    "ThreadOrientation": ("Thread orientation", "thread", "Right-hand or left-hand thread."),
    "ThreadType": ("Thread type", "thread", "Standard table (metric / imperial, internal / external) or custom."),
    "ThreadName": ("Thread name", "thread", "Designation in the standard table, e.g. M8 x 1.25."),
    "ThreadFit": ("Thread fit (%)", "thread", "0 = tightest tolerance, 100 = loosest."),
    "MajorDiameter": ("Major diameter", "thread", "Outer diameter of the thread."),
    "MinorDiameter": ("Minor diameter", "thread", "Inner diameter of the thread."),
    "Pitch": ("Pitch", "thread", "Thread pitch (metric)."),
    "TPI": ("Threads per inch", "thread", "Imperial pitch (0 when metric)."),
    "LeadInOut": ("Lead-in / lead-out arcs", "thread", "Enter and leave the thread on an arc."),
    # reprise des angles (pencil)
    "ReferenceDiameter": ("Reference tool diameter", "strategy", "Ball of the previous finishing: corners it cannot reach are taken again (0 = 3 x this tool)."),
    "Threshold": ("Ignore corners leaving less than", "strategy", "Material left by the reference tool below which a corner is skipped."),
    "MaxSlope": ("Maximum slope (deg)", "strategy", "Corners on a steeper surface are skipped (90 = all)."),
}


def spec(name):
    """(libellé, groupe, aide) d'un paramètre ; un nom inconnu reçoit le groupe « strategy »."""
    return PARAM_SPECS.get(name, (name, "strategy", ""))


def unknown_params(strategies):
    """Noms listés par les stratégies mais absents de PARAM_SPECS (outil de contrôle / test)."""
    missing = set()
    for meta in strategies.values():
        for name in meta["params"]:
            if name not in PARAM_SPECS:
                missing.add(name)
    return sorted(missing)
