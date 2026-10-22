# SPDX-License-Identifier: LGPL-2.1-or-later
"""Usinage recto-verso (face A, puis la pièce retournée en face B), comme le « Double Sided » d'Aspire.

Principe :

- la face B est un **second job FreeCAD** du même document : sa pièce est une copie de la pièce de la face A
  tournée de 180° autour d'une droite parallèle à X (ou à Y) passant par le centre du brut. Le brut, boîte
  symétrique par rapport à cette droite, occupe donc la même place sur les deux faces : le repère G54 est le
  même (même coin du brut) ;
- le lien ``Job`` du projet désigne la face courante : bascule A / B = changement de ce lien. Tout ce qui
  travaille sur « le job du projet » (ajout et édition d'opérations, recalcul, aperçu, export) s'applique
  donc à la face affichée ;
- repérage : « même coin » (le brut est remis contre les mêmes butées, dimensions exactes) ou **goujons** :
  deux trous percés depuis la face A, à travers le brut et dans le martyr, **sur l'axe de retournement**
  (un point de l'axe reste à sa place quand la pièce tourne autour de lui) : la pièce retournée se repose
  sur les mêmes goujons ;
- contrôle matière enchaîné : la carte de hauteur de la face A, retournée, sert de brut à la face B
  (colonne de matière ``[zmin, hA]`` → ``[zmin + zmax − hA, zmax]`` après retournement).

La copie retournée est figée (comme les copies indexées du 4e axe) : ``resync`` la refait si la pièce change.
"""

import json

import FreeCAD

from ..i18n import Msg, UserError

PROPERTY = "TwoSided"
AXES = ("X", "Y")
FLIP_SUFFIX = "_FlipB"
REG_PREFIX = "CAM2027Registration"
REG_KIND = "registration"
REG_LABEL = "Registration holes (dowels)"


# -- état ------------------------------------------------------------------------------------------------


def config(project):
    raw = getattr(project.info, PROPERTY, "")
    return json.loads(raw) if raw else None


def _save(project, cfg):
    if PROPERTY not in project.info.PropertiesList:
        project.info.addProperty("App::PropertyString", PROPERTY, "CAM2027", "Two-sided machining (JSON)")
        project.info.setEditorMode(PROPERTY, 1)
    setattr(project.info, PROPERTY, json.dumps(cfg))


def is_two_sided(project):
    return config(project) is not None


def jobs(project):
    """``{"A": job, "B": job}`` (vide hors recto-verso)."""
    cfg = config(project)
    if not cfg:
        return {}
    return {side: project.doc.getObject(cfg[side]) for side in ("A", "B")}


def current_side(project):
    cfg = config(project)
    if not cfg:
        return None
    return "B" if project.info.Job is not None and project.info.Job.Name == cfg["B"] else "A"


def all_operations(project):
    """Opérations des deux faces (A puis B) ; celles du job courant hors recto-verso."""
    if not is_two_sided(project):
        return project.operations()
    return [o for side in ("A", "B") for o in jobs(project)[side].Operations.Group]


# -- géométrie -------------------------------------------------------------------------------------------


def flip_matrix(axis, center):
    """Rotation de 180° autour de la droite parallèle à ``axis`` passant par ``center`` = (cx, cy, cz)."""
    cx, cy, cz = center
    if axis == "X":  # (x, y, z) -> (x, 2cy - y, 2cz - z)
        return FreeCAD.Matrix(1, 0, 0, 0, 0, -1, 0, 2 * cy, 0, 0, -1, 2 * cz, 0, 0, 0, 1)
    if axis == "Y":  # (x, y, z) -> (2cx - x, y, 2cz - z)
        return FreeCAD.Matrix(-1, 0, 0, 2 * cx, 0, 1, 0, 0, 0, 0, -1, 2 * cz, 0, 0, 0, 1)
    raise ValueError("flip axis must be X or Y")


def flip_point(axis, center, p):
    x, y, z = p
    cx, cy, cz = center
    return (x, 2 * cy - y, 2 * cz - z) if axis == "X" else (2 * cx - x, y, 2 * cz - z)


def flip_grid(axis, array):
    """Colonnes de la carte de hauteur après retournement (grille symétrique par rapport au centre du brut)."""
    return array[:, ::-1].copy() if axis == "X" else array[::-1, :].copy()


def _flipped_copy(doc, source, axis, center):
    name = source.Name + FLIP_SUFFIX
    copy = doc.getObject(name)
    if copy is None:
        copy = doc.addObject("Part::Feature", name)
    copy.Label = "%s (side B)" % source.Label
    shape = source.Shape.copy()
    shape.transformShape(flip_matrix(axis, center))
    copy.Shape = shape
    if FreeCAD.GuiUp and copy.ViewObject is not None:
        copy.ViewObject.Visibility = False
    return copy


def _sources(job):
    from .indexing import source_of

    return [source_of(c) for c in job.Model.Group]


# -- mise en place ---------------------------------------------------------------------------------------


def enable(project, axis="X"):
    """Crée la face B (job de la pièce retournée autour de ``axis``) ; la face A reste la face courante.

    Le brut de la face A doit être une boîte : il est repris tel quel (mêmes cotes) pour la face B."""
    if axis not in AXES:
        raise UserError("flip axis must be X or Y")
    if is_two_sided(project):
        raise UserError("the project is already two-sided")
    job_a = project.job
    if getattr(job_a.Stock, "Radius", None) is not None:
        raise UserError("two-sided machining needs box stock (round stock is for the 4th axis)")
    sb = project.stock_bounds()
    center = ((sb["xmin"] + sb["xmax"]) / 2.0, (sb["ymin"] + sb["ymax"]) / 2.0, (sb["zmin"] + sb["zmax"]) / 2.0)
    flipped = [_flipped_copy(project.doc, s, axis, center) for s in _sources(job_a)]
    project.doc.recompute()
    project.info.Job = None  # create_job refuse un projet qui a déjà un job
    try:
        job_b = project.create_job(flipped, stock={"kind": "box", "length": sb["length"], "width": sb["width"],
                                                   "height": sb["height"],
                                                   "origin": [sb["xmin"], sb["ymin"], sb["zmin"]]},
                                   fixtures=list(job_a.Fixtures), post_processor=job_a.PostProcessor,
                                   post_args=job_a.PostProcessorArgs)
    finally:
        project.info.Job = job_a
    job_b.Label = "Job (side B)"
    if FreeCAD.GuiUp:
        _show(job_b, False)
    _save(project, {"axis": axis, "center": list(center), "A": job_a.Name, "B": job_b.Name,
                    "registration": {"kind": "corner"}})
    project.doc.recompute()
    return job_b


def set_side(project, side):
    """Rend ``side`` ("A" ou "B") courant : opérations ajoutées, recalcul, export portent sur cette face."""
    if side not in ("A", "B"):
        raise ValueError("side must be A or B")
    js = jobs(project)
    if not js:
        raise UserError("the project is not two-sided")
    project.info.Job = js[side]
    if FreeCAD.GuiUp:
        _show(js[side], True)
        _show(js["B" if side == "A" else "A"], False)
    return js[side]


def _show(job, visible):
    objs = list(job.Model.Group) + list(job.Operations.Group)
    if job.Stock is not None:
        objs.append(job.Stock)
    for o in objs:
        vo = getattr(o, "ViewObject", None)
        if vo is not None:
            vo.Visibility = visible


def resync(project):
    """Refait les copies retournées de la face B après une modification de la pièce de la face A."""
    cfg = config(project)
    js = jobs(project)
    for s in _sources(js["A"]):
        _flipped_copy(project.doc, s, cfg["axis"], cfg["center"])
    project.doc.recompute()


def disable_check(project):
    """Messages si la face B ne correspond plus à la face A (brut modifié depuis)."""
    cfg = config(project)
    if not cfg:
        return []
    js = jobs(project)
    a, b = js["A"].Stock.Shape.BoundBox, js["B"].Stock.Shape.BoundBox
    issues = []
    if max(abs(a.XMin - b.XMin), abs(a.XMax - b.XMax), abs(a.YMin - b.YMin), abs(a.YMax - b.YMax),
           abs(a.ZMin - b.ZMin), abs(a.ZMax - b.ZMax)) > 1e-6:
        issues.append(("error", Msg("two-sided: the stock of side B differs from the stock of side A")))
    return issues


# -- repérage par goujons --------------------------------------------------------------------------------


def default_dowel_positions(project, diameter, clearance=3.0):
    """Deux positions sur l'axe de retournement, dans la marge du brut, de part et d'autre de la pièce."""
    cfg = config(project)
    js = jobs(project)
    sb = js["A"].Stock.Shape.BoundBox
    pb = None
    for s in _sources(js["A"]):
        pb = s.Shape.BoundBox if pb is None else pb.united(s.Shape.BoundBox)
    r = diameter / 2.0
    cx, cy, _cz = cfg["center"]
    if cfg["axis"] == "X":
        lo, hi, plo, phi = sb.XMin, sb.XMax, pb.XMin, pb.XMax
    else:
        lo, hi, plo, phi = sb.YMin, sb.YMax, pb.YMin, pb.YMax
    if plo - lo < diameter + 2 * clearance or hi - phi < diameter + 2 * clearance:
        raise UserError("not enough stock margin along the flip axis for {d:g} mm dowels: {n:g} mm needed on each side of the part",
                        d=diameter, n=diameter + 2 * clearance)
    a, b = (lo + plo) / 2.0, (phi + hi) / 2.0
    del r
    return [(a, cy), (b, cy)] if cfg["axis"] == "X" else [(cx, a), (cx, b)]


def add_dowel_holes(project, assembly_id, preset_id, positions=None, depth_below=5.0, peck=3.0, name=None):
    """Trous de goujons percés depuis la face A, à travers le brut et ``depth_below`` mm dans le martyr.

    Les positions doivent être sur l'axe de retournement et hors de la pièce (refus sinon). Opération
    « Custom » (plongées avec débourrage, sans cycle G81 : GRBL n'a pas de cycles de perçage), placée en
    tête de la face A. Retourne l'opération."""
    import Part
    import Path.Op.Custom as Custom
    from ..tools import bridge

    cfg = config(project)
    if not cfg:
        raise UserError("the project is not two-sided")
    js = jobs(project)
    job_a = js["A"]
    asm, tool, _holder = project.library.resolve_assembly(assembly_id)
    preset = tool.preset(preset_id)
    values = preset.resolve(tool)
    d = float(tool.geometry.diameter)
    positions = [tuple(p) for p in (positions or default_dowel_positions(project, d))]
    if len(positions) < 2:
        raise UserError("two dowel holes are needed")
    cx, cy, _cz = cfg["center"]
    sb = job_a.Stock.Shape.BoundBox
    parts = [s.Shape for s in _sources(job_a)]
    for (x, y) in positions:
        off = abs(y - cy) if cfg["axis"] == "X" else abs(x - cx)
        if off > 1e-6:
            raise UserError("dowel hole at X {x:.2f} Y {y:.2f} is not on the flip axis: it would move when the part is flipped",
                            x=x, y=y)
        if not (sb.XMin + d / 2 <= x <= sb.XMax - d / 2 and sb.YMin + d / 2 <= y <= sb.YMax - d / 2):
            raise UserError("dowel hole at X {x:.2f} Y {y:.2f} is outside the stock", x=x, y=y)
        cyl = Part.makeCylinder(d / 2.0 + 0.5, sb.ZLength + 2, FreeCAD.Vector(x, y, sb.ZMin - 1))
        for p in parts:
            if p.common(cyl).Volume > 1e-6:
                raise UserError("dowel hole at X {x:.2f} Y {y:.2f} cuts into the part", x=x, y=y)
    top, bottom = sb.ZMax, sb.ZMin - float(depth_below)
    clearance = top + 5.0
    plunge = values["plunge_feed_mm_min"] / 60.0
    lines = []
    for (x, y) in positions:
        lines += ["G0 Z%.4f" % clearance, "G0 X%.4f Y%.4f" % (x, y), "G0 Z%.4f" % (top + 1.0)]
        z = top
        while z > bottom + 1e-9:
            z = max(bottom, z - float(peck))
            lines.append("G1 Z%.4f F%.6f" % (z, plunge))
            if z > bottom + 1e-9:  # débourrage : remontée hors du trou puis retour 0,5 mm au-dessus du fond
                lines += ["G0 Z%.4f" % (top + 1.0), "G0 Z%.4f" % (z + 0.5)]
        lines.append("G0 Z%.4f" % clearance)
    label = name or Msg(REG_LABEL)
    previous_job = project.info.Job
    project.info.Job = job_a
    previous = FreeCAD.ActiveDocument
    FreeCAD.setActiveDocument(project.doc.Name)
    try:
        toolbit, warnings = bridge.create_toolbit(project.doc, tool, label="%s (T%d)" % (tool.name, asm.output.tool_number))
        tc, _ = bridge.create_tool_controller(project.doc, asm, tool, values, toolbit=toolbit, label="TC: %s" % label)
        job_a.Proxy.addToolController(tc)
        op = Custom.Create(REG_PREFIX, parentJob=job_a)
        op.Label = str(label)
        op.ToolController = tc
        op.Source = "Text"
        op.Gcode = lines
        job_a.Operations.Group = [op] + [o for o in job_a.Operations.Group if o.Name != op.Name]
        reg = project.registry
        reg[op.Name] = {"kind": REG_KIND, "label": str(label), "order": -1, "assembly_id": asm.id, "tool_id": tool.id,
                        "holder_id": asm.holder_id, "preset_id": preset.id, "values": values,
                        "tool_controller": tc.Name, "toolbit": toolbit.Name,
                        "params": {"positions": [list(p) for p in positions], "depth_below": float(depth_below),
                                   "peck": float(peck)},
                        "ignored_params": [], "warnings": list(warnings), "index_deg": None}
        project._save_registry(reg)
        cfg["registration"] = {"kind": "dowels", "diameter": d, "positions": [list(p) for p in positions],
                               "depth_below": float(depth_below), "operation": op.Name}
        _save(project, cfg)
        project.doc.recompute()
    finally:
        project.info.Job = previous_job
        if previous is not None and previous.Name != project.doc.Name:
            FreeCAD.setActiveDocument(previous.Name)
    return op


# -- contrôle matière enchaîné ---------------------------------------------------------------------------


def material_check(project, resolution=None, tolerance=0.02):
    """Face A sur le brut, puis face B sur la carte de la face A retournée. Retourne le rapport de la face
    courante complété par ``two_sided`` : rapport de chaque face, volume total, épaisseur finale."""
    from . import sim

    np = sim._np()
    cfg = config(project)
    js = jobs(project)
    current = project.info.Job
    reports = {}
    try:
        project.info.Job = js["A"]
        rep_a = project.material_check(resolution, tolerance, start_zmap=False)
        zmap_a, heights_a = project.last_zmap, project.last_heights
        reports["A"] = rep_a
        project.info.Job = js["B"]
        zmap_b = sim.ZMap.from_bounds(project.stock_bounds(), zmap_a.res)
        flipped = flip_grid(cfg["axis"], zmap_a.top)
        zmin, zmax = js["B"].Stock.Shape.BoundBox.ZMin, js["B"].Stock.Shape.BoundBox.ZMax
        through = flipped <= zmin + 1e-6  # face A usinée jusqu'en bas : plus rien dans la colonne
        bottom_b = np.where(through, np.inf, zmin + zmax - flipped)
        zmap_b.top = np.where(through, zmin, zmax).astype(float)
        zmap_b.initial = zmap_b.top.copy()
        rep_b = project.material_check(resolution, tolerance, start_zmap=zmap_b)
        reports["B"] = rep_b
        heights_b = project.last_heights
    finally:
        project.info.Job = current
    # volume de la face B : seulement la matière réellement présente (au-dessus du fond laissé par la face A)
    gone = np.clip(zmap_b.initial - np.maximum(zmap_b.top, np.where(np.isfinite(bottom_b), bottom_b, zmap_b.top)), 0, None)
    vol_b = float(gone.sum() * zmap_b.res ** 2)
    final_top_a = zmap_a.top
    final_bottom_a = flip_grid(cfg["axis"], np.where(np.isfinite(bottom_b), zmin + zmax - zmap_b.top, np.nan))
    combined = dict(reports[current_side(project)])
    combined["gouge_max"] = max(rep_a["gouge_max"], rep_b["gouge_max"])
    combined["two_sided"] = {
        "axis": cfg["axis"], "A": rep_a, "B": rep_b,
        "removed_volume": rep_a["removed_volume"] + vol_b, "removed_volume_B": vol_b,
        "registration": cfg.get("registration"),
    }
    project.last_two_sided = {"zmap_A": zmap_a, "zmap_B": zmap_b, "top_A": final_top_a, "bottom_A": final_bottom_a,
                              "heights_A": heights_a, "heights_B": heights_b}
    # contrôle stocké : empreinte des deux faces (``_paths_fingerprint`` les parcourt toutes les deux)
    if combined["gouge_max"] > tolerance:
        worst = rep_a if rep_a["gouge_max"] >= rep_b["gouge_max"] else rep_b
        combined["gouge_at"] = worst["gouge_at"]
    combined["collisions"] = _merge_collisions(rep_a["collisions"], rep_b["collisions"])
    project._store_check(combined)
    return combined


def _merge_collisions(a, b):
    order = {"collision": 2, "not_checked": 1, "ok": 0}
    out = {"events": list(a["events"]) + list(b["events"])}
    for key in ("flute_length", "holder", "clamps", "rapids"):
        out[key] = a[key] if order[a[key]] >= order[b[key]] else b[key]
    for key in ("no_holder", "clamps_defined", "not_run"):
        out[key] = list(a[key]) + [x for x in b[key] if x not in a[key]]
    return out


def final_part_maps(project, shapes_a=None):
    """Après ``material_check`` : (dessus, dessous) de la matière restante et de la pièce, en repère A
    (NaN / -inf hors matière). Sert à comparer la carte finale à la pièce."""
    from . import sim

    np = sim._np()
    data = project.last_two_sided
    zmap_a = data["zmap_A"]
    cfg = config(project)
    js = jobs(project)
    shapes_a = shapes_a or [o.Shape for o in js["A"].Model.Group]
    part_top = sim.model_heights(zmap_a, shapes_a)
    shapes_b = [o.Shape for o in js["B"].Model.Group]
    sb = js["A"].Stock.Shape.BoundBox
    top_b = sim.model_heights(data["zmap_B"], shapes_b)
    part_bottom = np.where(np.isfinite(top_b), sb.ZMin + sb.ZMax - top_b, np.nan)
    part_bottom = flip_grid(cfg["axis"], part_bottom)
    return data["top_A"], data["bottom_A"], part_top, part_bottom


# -- export ----------------------------------------------------------------------------------------------


def export(project, path, **kwargs):
    """Un fichier G-code par face (``<nom>-A.nc``, ``<nom>-B.nc``) et une fiche par face, complétée par la
    section « Recto-verso » (retournement, repérage, ordre). Retourne ``{"A": résultat, "B": résultat}``."""
    import os

    base, ext = os.path.splitext(path)
    current = project.info.Job
    out = {}
    try:
        for side in ("A", "B"):
            set_side(project, side)
            out[side] = project.export_gcode("%s-%s%s" % (base, side, ext or ".nc"), **kwargs)
            if out[side].get("sheet"):
                with open(out[side]["sheet"], "a", encoding="utf-8") as fp:
                    fp.write("\n" + setup_text(project, side) + "\n")
                out[side]["sheet_text"] += "\n" + setup_text(project, side) + "\n"
    finally:
        project.info.Job = current
        if FreeCAD.GuiUp:
            set_side(project, "B" if current.Name == config(project)["B"] else "A")
    return out


def setup_text(project, side):
    """Section « Two-sided » de la fiche (Markdown, anglais comme le reste de la fiche)."""
    cfg = config(project)
    js = jobs(project)
    sb = js["A"].Stock.Shape.BoundBox
    lines = ["## Two-sided machining - side %s" % side, ""]
    lines.append("- Flip axis: %s (the stock turns 180 deg about the line %s through the stock centre X %.2f Y %.2f)"
                 % (cfg["axis"], cfg["axis"], cfg["center"][0], cfg["center"][1]))
    lines.append("- Stock on both sides: X %.2f..%.2f, Y %.2f..%.2f, Z %.2f..%.2f (same work offset %s)"
                 % (sb.XMin, sb.XMax, sb.YMin, sb.YMax, sb.ZMin, sb.ZMax, " ".join(js["A"].Fixtures)))
    reg = cfg.get("registration") or {"kind": "corner"}
    if reg["kind"] == "dowels":
        pos = ", ".join("X %.2f Y %.2f" % tuple(p) for p in reg["positions"])
        lines.append("- Registration: %d dowel pins D %.2f mm at %s, drilled from side A through the stock and %.1f mm into the spoilboard"
                     % (len(reg["positions"]), reg["diameter"], pos, reg["depth_below"]))
        if side == "B":
            lines.append("- Before side B: put the dowel pins in the spoilboard holes, flip the stock about %s and push it onto the pins; do not change X Y of the work offset" % cfg["axis"])
    else:
        lines.append("- Registration: same corner (the stock goes back against the same stops; its dimensions must be exact)")
        if side == "B":
            lines.append("- Before side B: flip the stock about %s, put it against the same stops, set the work offset at the same stock corner as for side A" % cfg["axis"])
    if side == "B":
        lines.append("- Z: probe the top of the flipped stock again if its thickness is not exactly %.2f mm" % sb.ZLength)
    ops = [o.Label for o in js[side].Operations.Group]
    lines.append("- Operations of side %s: %s" % (side, ", ".join(ops) if ops else "-"))
    return "\n".join(lines)


def exporter(project):
    """Fonction d'export ``(chemin, post, arguments)`` : celle du projet, ou les deux faces en recto-verso
    (résultat fusionné : fichiers, fiches, contrôles et G-code des deux faces)."""
    if not is_two_sided(project):
        return project.export_gcode

    def run(path, post_processor=None, post_args=None):
        res = export(project, path, post_processor=post_processor, post_args=post_args)
        a, b = res["A"], res["B"]
        return {"files": a["files"] + b["files"], "sheet": "%s, %s" % (a["sheet"], b["sheet"]),
                "sheet_text": a["sheet_text"] + "\n\n" + b["sheet_text"], "analysis": b["analysis"],
                "issues": a["issues"] + b["issues"], "gcode": a["gcode"] + "\n" + b["gcode"], "sides": res}
    return run
