# SPDX-License-Identifier: LGPL-2.1-or-later
"""Brut et montage.

Le brut réutilise ``Path.Main.Stock`` de FreeCAD (boîte autour du modèle avec
marges, boîte explicite, cylindre). Le montage, dans cette première tranche,
se limite au repère pièce (G54...) et à l'origine du brut. Les brides
(``Clamp``) sont des boîtes dans un groupe ``Fixture`` : elles sont visibles
en 3D mais **pas encore prises en compte** par le contrôle de collision.
"""

import FreeCAD
import Path.Main.Stock as PathStock

ORIGIN_CHOICES = ("stock_top_front_left", "stock_top_center", "stock_bottom_front_left", "model_origin")


def _guard_stock_recursion():
    """``StockFromBase.execute`` de FreeCAD : sur une boîte englobante invalide (clone sans forme), la hauteur
    calculée est négative, ``execute`` corrige ``ExtZneg``, ``onChanged`` rappelle ``execute``... jusqu'au
    débordement de pile (plantages du 2026-10-20). Un appel réentrant est ignoré : le brut reste sans forme
    et CAM2027 le signale au lieu de planter."""
    cls = PathStock.StockFromBase
    original = cls.execute
    if getattr(original, "cam2027_guarded", False):
        return

    def execute(self, obj):
        if getattr(self, "_cam2027_executing", False):
            return
        self._cam2027_executing = True
        try:
            original(self, obj)
        finally:
            self._cam2027_executing = False

    execute.cam2027_guarded = True
    cls.execute = execute


_guard_stock_recursion()


def _active(doc):
    previous = FreeCAD.ActiveDocument
    FreeCAD.setActiveDocument(doc.Name)
    return previous


def _restore(previous, doc):
    if previous is not None and previous.Name != doc.Name:
        try:
            FreeCAD.setActiveDocument(previous.Name)
        except Exception:
            pass


def set_stock(job, spec):
    """Remplace le brut du job selon ``spec`` :

    - ``{"kind": "box_margins", "xy": 2.0, "z_top": 0.0, "z_bottom": 0.0}``
    - ``{"kind": "box", "length": L, "width": W, "height": H, "origin": [x, y, z]}``
    - ``{"kind": "cylinder", "radius": R, "height": H, "origin": [x, y, z]}``
    """
    doc = job.Document
    previous = _active(doc)
    try:
        kind = spec.get("kind", "box_margins")
        old = job.Stock
        if kind == "box_margins":
            xy = float(spec.get("xy", 0.0))
            neg = FreeCAD.Vector(xy, xy, float(spec.get("z_bottom", 0.0)))
            pos = FreeCAD.Vector(xy, xy, float(spec.get("z_top", 0.0)))
            stock = PathStock.CreateFromBase(job, neg, pos)
        elif kind == "box":
            extent = FreeCAD.Vector(float(spec["length"]), float(spec["width"]), float(spec["height"]))
            origin = spec.get("origin")
            placement = FreeCAD.Placement(FreeCAD.Vector(*origin), FreeCAD.Rotation()) if origin else None
            stock = PathStock.CreateBox(job, extent, placement)
        elif kind == "cylinder_x":
            # brut rond pour le 4e axe : cylindre d'axe X, centré sur l'axe A (center = [y, z])
            cy, cz = spec.get("center", (0.0, 0.0))
            placement = FreeCAD.Placement(FreeCAD.Vector(float(spec.get("x_start", 0.0)), float(cy), float(cz)),
                                          FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), 90))  # Z du cylindre -> +X
            stock = PathStock.CreateCylinder(job, float(spec["radius"]), float(spec["length"]), placement)
        elif kind == "cylinder":
            origin = spec.get("origin")
            placement = FreeCAD.Placement(FreeCAD.Vector(*origin), FreeCAD.Rotation()) if origin else None
            stock = PathStock.CreateCylinder(job, float(spec["radius"]), float(spec["height"]), placement)
        else:
            raise ValueError("type de brut inconnu : %r" % (kind,))
        job.Stock = stock
        if old is not None and old.Name != stock.Name:
            old.Label = "StockRemoved"  # libère l'étiquette avant la suppression (différée sur 1.1)
            doc.removeObject(old.Name)
        stock.Label = "Stock"
        if stock.ViewObject:
            stock.ViewObject.Transparency = 80
        doc.recompute()
        return stock
    finally:
        _restore(previous, doc)


def stock_bounds(job):
    bb = job.Stock.Shape.BoundBox
    return {
        "xmin": bb.XMin, "xmax": bb.XMax,
        "ymin": bb.YMin, "ymax": bb.YMax,
        "zmin": bb.ZMin, "zmax": bb.ZMax,
        "length": bb.XLength, "width": bb.YLength, "height": bb.ZLength,
    }


def set_fixtures(job, fixtures):
    """Repères pièce utilisés par le job (``["G54"]``, ``["G54", "G55"]``...)."""
    allowed = ("G54", "G55", "G56", "G57", "G58", "G59", "G59.1", "G59.2", "G59.3")
    for f in fixtures:
        if f not in allowed:
            raise ValueError("repère inconnu : %r" % (f,))
    job.Fixtures = list(fixtures)
    return job.Fixtures


def add_clamp(job, name, length, width, height, origin):
    """Ajoute une bride parallélépipédique dans le groupe « Fixture » (visuel seulement)."""
    doc = job.Document
    group = None
    for obj in doc.Objects:
        if obj.Name == "CAM2027Fixture":
            group = obj
            break
    if group is None:
        group = doc.addObject("App::DocumentObjectGroup", "CAM2027Fixture")
        group.Label = "Fixture"
    clamp = doc.addObject("Part::Box", "Clamp")
    clamp.Label = name
    clamp.Length = float(length)
    clamp.Width = float(width)
    clamp.Height = float(height)
    clamp.Placement = FreeCAD.Placement(FreeCAD.Vector(*origin), FreeCAD.Rotation())
    group.addObject(clamp)
    if clamp.ViewObject:
        clamp.ViewObject.ShapeColor = (0.85, 0.35, 0.1)
    doc.recompute()
    return clamp


def clamps(doc):
    group = doc.getObject("CAM2027Fixture")
    return list(group.Group) if group is not None else []
