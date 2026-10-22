# SPDX-License-Identifier: LGPL-2.1-or-later
"""4e axe indexé (3+1) : la pièce tourne d'un angle A autour de X, l'usinage reste en 3 axes.

Principe :

- pour un angle d'index θ, une **copie tournée** du modèle (rotation de θ autour de l'axe A,
  droite parallèle à X passant par ``machine.rotary.center_offset_mm`` = (y, z)) est créée hors du
  modèle du job ; les opérations de cet index la référencent et sont calculées en 3 axes, la
  fraise venant toujours de +Z ;
- avant chaque groupe d'opérations au même angle, une opération « Custom » FreeCAD
  ``CAM2027Index…`` monte au plan de dégagement puis positionne l'axe : ``G0 Z… / G0 A…`` ;
  A ne bouge jamais pendant une coupe (contrôlé à l'export) ;
- signe : ``positive_direction = "right_hand"`` (A positif = règle de la main droite autour de +X,
  convention RS274) écrit A = θ ; ``"left_hand"`` écrit A = −θ.

Aucune donnée machine n'est inventée : le centre de l'axe A et son sens positif doivent être
renseignés dans le profil machine, sinon l'index est refusé.
"""

import FreeCAD

from ..i18n import Msg

INDEX_PREFIX = "CAM2027Index"
ANGLE_PROPERTY = "IndexAngle"
POSITIVE_DIRECTIONS = ("right_hand", "left_hand")


def check_machine(machine):
    """Lève ValueError si le profil ne permet pas l'indexation ; retourne (cy, cz, signe)."""
    rot = machine.rotary
    if not rot.present:
        raise ValueError("le profil machine n'a pas d'axe rotatif A (cocher « axe A présent »)")
    if rot.about != "X":
        raise ValueError("axe rotatif autour de %s : seul A autour de X est pris en charge" % rot.about)
    if rot.center_offset_mm is None:
        raise ValueError("centre de l'axe A inconnu : renseigner Y et Z du centre dans le profil machine")
    if rot.positive_direction not in POSITIVE_DIRECTIONS:
        raise ValueError("sens positif de l'axe A non renseigné dans le profil machine")
    cy, cz = (float(v) for v in rot.center_offset_mm)
    return cy, cz, (1.0 if rot.positive_direction == "right_hand" else -1.0)


def check_angle(machine, angle):
    rot = machine.rotary
    if rot.min_deg is not None and angle < rot.min_deg - 1e-9:
        raise ValueError("angle A %.3f inférieur au minimum %.3f" % (angle, rot.min_deg))
    if rot.max_deg is not None and angle > rot.max_deg + 1e-9:
        raise ValueError("angle A %.3f supérieur au maximum %.3f" % (angle, rot.max_deg))


def rotation_matrix(angle, cy, cz):
    """Rotation de ``angle`` degrés autour de la droite (y = cy, z = cz) parallèle à X.

    Cosinus et sinus arrondis aux valeurs exactes 0 / ±1 (multiples de 90°) : sinon une face
    tournée de 90° se retrouve à Z 10,000000000000004 et une profondeur finale « 10 » la manque.
    """
    import math

    def snap(v):
        for exact in (0.0, 1.0, -1.0, 0.5, -0.5):
            if abs(v - exact) < 1e-12:
                return exact
        return v

    rad = math.radians(float(angle))
    c, s = snap(math.cos(rad)), snap(math.sin(rad))
    return FreeCAD.Matrix(1, 0, 0, 0,
                          0, c, -s, cy - c * cy + s * cz,
                          0, s, c, cz - s * cy - c * cz,
                          0, 0, 0, 1)


def angle_tag(angle):
    return ("%g" % angle).replace("-", "m").replace(".", "p")


def source_of(clone):
    """Objet source d'un clone du job (ou l'objet lui-même)."""
    for attr in ("Objects", "Base"):
        inner = getattr(clone, attr, None)
        if isinstance(inner, list) and len(inner) == 1:
            inner = inner[0]
        if inner is not None and hasattr(inner, "Shape") and hasattr(inner, "Name"):
            return inner
    return clone


def rotated_model(job, machine, source, angle):
    """Copie de ``source`` tournée de ``angle`` autour de l'axe A (créée au besoin).

    La copie reste **hors du modèle du job** : les opérations « toute la pièce » (géométrie vide)
    continuent de ne voir que la pièce réelle ; seules les opérations indexées la référencent.
    Copie figée : réindexer si la pièce change.
    """
    cy, cz, _sign = check_machine(machine)
    doc = job.Document
    name = "%s_A%s" % (source.Name, angle_tag(angle))
    copy = doc.getObject(name)
    if copy is None:
        copy = doc.addObject("Part::Feature", name)
        copy.Label = "%s @A%g" % (source.Label, angle)
        shape = source.Shape.copy()
        shape.transformShape(rotation_matrix(angle, cy, cz))
        copy.Shape = shape
        if FreeCAD.GuiUp and copy.ViewObject is not None:
            copy.ViewObject.Visibility = False
    return copy


def index_base(project, kind, base, angle, tool_diameter):
    """Géométrie d'une opération indexée : sous-éléments reportés sur la copie tournée.

    Sans sous-élément : trous détectés sur la copie (perçage, hélice, filetage), faces en relief
    (ébauche 3D), sinon refus (« toute la pièce » n'a pas de sens pour une face indexée).
    """
    from . import operations as opsmod

    job = project.job
    if base is None:
        base = [(c, []) for c in job.Model.Group]
    out = []
    for obj, subs in base:
        source = source_of(obj)
        rotated = rotated_model(job, project.machine, source, angle)
        subs = list(subs)
        if not subs:
            if kind in opsmod.HOLE_STRATEGIES:
                from Path.Base import Drillable

                subs = [name for _o, name in Drillable.getDrillableTargets(
                    rotated, ToolDiameter=tool_diameter, vector=FreeCAD.Vector(0, 0, 1))]
            elif kind == "rough3d":
                subs = opsmod.raised_faces(rotated)
            else:
                raise ValueError("opération indexée A%g : sélectionner les faces ou arêtes à usiner" % angle)
        if subs:
            out.append((rotated, subs))
    if not out:
        raise ValueError("opération indexée A%g : aucune géométrie usinable à cet angle" % angle)
    return out


def source_of_rotated(doc, obj):
    """Objet source d'une copie tournée ``<source>_A<angle>`` (ou l'objet lui-même / la source d'un clone)."""
    name = obj.Name
    if "_A" in name:
        head = name.rsplit("_A", 1)[0]
        src = doc.getObject(head)
        if src is not None and getattr(src, "Shape", None) is not None:
            return src
    return source_of(obj)


def is_index_op(obj):
    return obj.Name.startswith(INDEX_PREFIX)


def stock_swept_radius(job, cy, cz):
    """Plus grande distance du brut à l'axe A (arêtes échantillonnées) : rayon balayé pendant une rotation."""
    import math

    shape = job.Stock.Shape if job.Stock is not None else None
    if shape is None or shape.isNull():
        return 0.0
    radius = 0.0
    for edge in shape.Edges:
        for p in edge.discretize(Number=24):
            radius = max(radius, math.hypot(p.y - cy, p.z - cz))
    return radius


def rotation_height(project, base):
    """Z sûr avant de tourner A : au-dessus du brut balayé (rayon maximal autour de l'axe + marge de dégagement du
    job) et au moins le dégagement de l'opération qui suit. Le dégagement seul ne suffit pas : il vaut 5 mm
    tant que FreeCAD ne l'a pas calculé (l'outil descendait alors dans le brut) et un barreau carré balaie sa
    demi-diagonale, au-delà de « dessus du brut + marge »."""
    cy, cz, _sign = check_machine(project.machine)
    job = project.job
    offset = 5.0
    sheet = getattr(job, "SetupSheet", None)
    if sheet is not None and hasattr(sheet, "ClearanceHeightOffset"):
        offset = float(sheet.ClearanceHeightOffset.getValueAs("mm"))
    clearance = float(base.ClearanceHeight.getValueAs("mm")) if hasattr(base, "ClearanceHeight") else 0.0
    return max(clearance, cz + stock_swept_radius(job, cy, cz) + offset)


def refresh(project):
    """Hauteurs des positionnements A recalculées (brut ou dégagements changés depuis leur création) ; retourne
    True si un positionnement a changé (le document doit être recalculé)."""
    from .dressups import base_operation

    if not project.has_job:
        return False
    ops = project.operations()
    sign = None
    changed = False
    for k, obj in enumerate(ops):
        if not is_index_op(obj):
            continue
        if sign is None:
            try:
                sign = check_machine(project.machine)[2]
            except ValueError:  # axe A retiré du profil depuis : l'export refuse les mots A, le calcul continue
                return False
        following = next((o for o in ops[k + 1:] if not is_index_op(o)), None)
        base = base_operation(following) if following is not None else obj
        gcode = ["G0 Z%.3f" % rotation_height(project, base), "G0 A%.4f" % (sign * getattr(obj, ANGLE_PROPERTY))]
        if list(obj.Gcode) != gcode:
            obj.Gcode = gcode
            changed = True
    return changed


def sync(project):
    """Recrée les positionnements A devant chaque groupe d'opérations au même angle.

    Sans aucune opération indexée, aucun mot A n'est produit (projet 3 axes pur). Sinon, chaque
    changement d'angle (en partant d'un état inconnu) reçoit ``G0 Z<dégagement>`` puis ``G0 A<θ>``,
    les opérations sans index étant usinées à A0.
    """
    import Path.Op.Custom as Custom

    job = project.job
    doc = project.doc
    reg = project.registry
    for obj in [o for o in doc.Objects if is_index_op(o)]:
        job.Operations.Group = [o for o in job.Operations.Group if o.Name != obj.Name]
        obj.Label = "CAM2027IndexRemoved"  # libère le libellé (suppression différée sur 1.1)
        doc.removeObject(obj.Name)
    ops = list(job.Operations.Group)

    def angle_of(obj):
        from .dressups import base_operation

        rec = reg.get(base_operation(obj).Name, {})
        return rec.get("index_deg")

    from .wrap import is_wrap_op

    if all(angle_of(o) is None for o in ops) and not any(is_wrap_op(o) for o in ops):
        return []
    _cy, _cz, sign = check_machine(project.machine)
    created = []
    current = None
    group = []
    previous = FreeCAD.ActiveDocument
    FreeCAD.setActiveDocument(doc.Name)
    try:
        for obj in ops:
            if is_wrap_op(obj):  # 4e axe continu : se positionne seul, laisse A à un angle quelconque
                group.append(obj)
                current = None
                continue
            angle = angle_of(obj) or 0.0
            if current is None or abs(angle - current) > 1e-9:
                from .dressups import base_operation

                base = base_operation(obj)
                clearance = rotation_height(project, base)
                idx = Custom.Create("%s_A%s" % (INDEX_PREFIX, angle_tag(angle)), parentJob=job)
                idx.Label = "Index A%g" % angle
                idx.addProperty("App::PropertyFloat", ANGLE_PROPERTY, "CAM2027", "Index angle A (deg)")
                setattr(idx, ANGLE_PROPERTY, float(angle))
                idx.Source = "Text"
                idx.Gcode = ["G0 Z%.3f" % clearance, "G0 A%.4f" % (sign * angle)]
                tc = getattr(base, "ToolController", None)
                if tc is not None:
                    idx.ToolController = tc  # même outil que l'opération suivante : pas de changement d'outil
                job.Operations.Group = [o for o in job.Operations.Group if o.Name != idx.Name]
                group.append(idx)
                created.append(idx)
                current = angle
            group.append(obj)
    finally:
        if previous is not None and previous.Name != doc.Name:
            FreeCAD.setActiveDocument(previous.Name)
    job.Operations.Group = group
    return created


def order_issues(project):
    """Contrôle de cohérence : chaque opération indexée suit un positionnement au bon angle."""
    from .dressups import base_operation

    issues = []
    if not project.has_job:
        return issues
    reg = project.registry
    current = None
    used = False
    from .wrap import is_wrap_op

    for obj in project.operations():
        if is_index_op(obj):
            current = getattr(obj, ANGLE_PROPERTY, None)
            continue
        if is_wrap_op(obj):
            current = None
            used = True
            continue
        angle = reg.get(base_operation(obj).Name, {}).get("index_deg")
        used = used or angle is not None
        if used and (current is None or abs((angle or 0.0) - current) > 1e-9):
            issues.append(("error", Msg("operation {op} expects A{a:g} but the axis is at {now}", op=obj.Label,
                                        a=angle or 0.0, now=Msg("an unknown angle") if current is None
                                        else "A%g" % current)))
    return issues
