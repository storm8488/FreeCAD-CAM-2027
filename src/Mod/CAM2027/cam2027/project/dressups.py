# SPDX-License-Identifier: LGPL-2.1-or-later
"""Habillages FreeCAD exposés comme options d'une opération : attaches, rampe, dogbones, entrées/sorties.

Un habillage est un objet FreeCAD qui prend le parcours de l'opération
(``Base``) et le transforme. Dans le job CAM2027 **il remplace l'opération
dans le groupe « Operations »** : FreeCAD postprocesse tous les objets actifs
du groupe, et laisser l'opération de base à côté de son habillage sortirait
le parcours deux fois. L'opération de base reste dans le document (dépendance
recalculée) ; ``base_operation()`` la retrouve depuis n'importe quel habillage.

Les noms d'objets contiennent « Dressup » : les utilitaires FreeCAD
(``Path.Dressup.Utils.baseOp`` / ``hasEntryMethod``) s'appuient sur ce mot.
"""

import importlib

import FreeCAD

#: clé -> module, libellé, paramètres (nom -> genre pour l'éditeur), limites
DRESSUPS = {
    "tags": {
        "module": "Path.Dressup.Tags",
        "label": "Holding tags",
        "suffix": "_DressupTags",
        "params": (("Width", "length"), ("Height", "length"), ("Angle", "angle"), ("Radius", "length")),
        "limits": "Profile paths only (closed contour); tags are spread evenly along the contour, "
                  "positions can be moved in the FreeCAD tag panel.",
    },
    "ramp": {
        "module": "Path.Dressup.Gui.RampEntry",
        "label": "Ramp entry",
        "suffix": "_DressupRamp",
        "params": (("Angle", "angle"), ("Method", "enum"), ("RampFeedRate", "enum"), ("UseStartDepth", "bool"),
                   ("DressupStartDepth", "length")),
        "limits": "Replaces vertical plunges by ramps along the path; not for drilling, helix or thread milling.",
    },
    "dogbone": {
        "module": "Path.Dressup.DogboneII",
        "label": "Dogbones (sharp inner corners)",
        "suffix": "_DressupDogbone",
        "params": (("Style", "enum"), ("Side", "enum"), ("Incision", "enum"), ("Custom", "length")),
        "limits": "Adds a bone at every inner corner so a round cutter clears a square corner (joinery); "
                  "contour paths and pockets with the Offset pattern (not zigzag, not adaptive), corners detected on "
                  "the computed path; "
                  "the bone goes past the walls by design (0.88 mm at a right angle with a 6 mm cutter).",
    },
    "leads": {
        "module": "Path.Dressup.Gui.LeadInOut",
        "label": "Lead-in and lead-out",
        "suffix": "_DressupLeads",
        "params": (("StyleIn", "enum"), ("RadiusIn", "length"), ("AngleIn", "angle"),
                   ("StyleOut", "enum"), ("RadiusOut", "length"), ("AngleOut", "angle")),
        "limits": "Arc (horizontal radius and sweep angle) or vertical arc entering and leaving the cut tangentially, "
                  "at every step-down; profile, slot and pocket paths. Vertical arcs and sweep angles other than 90° "
                  "need FreeCAD 1.1.",
    },
    "pattern": {
        "module": "cam2027.project.patterns",
        "label": "Pattern",
        "suffix": "_DressupPattern",
        "params": (("Kind", "enum"), ("Columns", "int"), ("Rows", "int"), ("StepX", "length"), ("StepY", "length"),
                   ("Count", "int"), ("Centre", "vector"), ("Angle", "angle")),
        "limits": "Copies of the computed toolpath on a grid or a circle (Machining > Pattern).",
    },
}

ORDER = ("dogbone", "ramp", "tags", "leads", "pattern")  # ordre d'empilement : du plus proche de l'opération au plus haut
ON_TOP = ("leads", "pattern")  # restent au-dessus des habillages ajoutés après eux (les autres s'empilent)
#: poches FreeCAD (3D et 2D) : motifs dont les demi-tours au bord reçoivent des os dans les parois quel que soit le
#: côté (2,75 à 5 mm sur la plaque des tests, 26 mm de haut sur un plateau à alvéoles)
DOGBONE_POCKETS = ("Path.Op.Pocket", "Path.Op.PocketShape")
DOGBONE_BAD_PATTERNS = ("ZigZag", "ZigZagOffset")


def dogbone_refused(strategy, pattern=None):
    """Dogbones refusés (FreeCAD plante les os dans les parois) pour la stratégie FreeCAD ``strategy`` (module de
    l'opération) et le motif de vidage ``pattern`` : adaptative toujours, poches en zigzag."""
    return strategy == "Path.Op.Adaptive" or (strategy in DOGBONE_POCKETS and pattern in DOGBONE_BAD_PATTERNS)


def dogbone_possible(base):
    """Un motif au moins de l'opération ``base`` accepte les dogbones (déduit de ``dogbone_refused``) : sinon
    l'éditeur ne propose pas la case, qui échouerait toujours."""
    strategy = type(getattr(base, "Proxy", None)).__module__
    prop = next((p for p in ("ClearingPattern", "OffsetPattern") if p in base.PropertiesList), None)
    choices = base.getEnumerationsOfProperty(prop) if prop else [None]
    return any(not dogbone_refused(strategy, p) for p in choices or [None])


def is_dressup(obj):
    return "Dressup" in obj.Name and hasattr(obj, "Base")


def base_operation(obj):
    """Opération sous-jacente (traverse la chaîne d'habillages)."""
    while is_dressup(obj) and obj.Base is not None:
        obj = obj.Base
    return obj


def dressup_chain(top):
    """Liste des habillages du plus haut au plus proche de l'opération."""
    chain = []
    obj = top
    while is_dressup(obj) and obj.Base is not None:
        chain.append(obj)
        obj = obj.Base
    return chain


def dressup_kind(obj):
    for key, meta in DRESSUPS.items():
        if obj.Name.endswith(meta["suffix"]) or meta["suffix"] in obj.Name:
            return key
    return None


def top_of(job, op):
    """Objet du groupe « Operations » qui représente ``op`` (l'opération ou son habillage le plus haut)."""
    for obj in job.Operations.Group:
        if obj.Name == op.Name or base_operation(obj).Name == op.Name:
            return obj
    return op


def add_dressup(job, op, kind, params=None, count=None):
    """Ajoute l'habillage ``kind`` au-dessus de ``op`` (ou de son habillage courant) et le met dans le groupe."""
    if kind not in DRESSUPS:
        raise ValueError("habillage inconnu : %r (disponibles : %s)" % (kind, ", ".join(DRESSUPS)))
    meta = DRESSUPS[kind]
    current = top_of(job, op)
    if any(dressup_kind(d) == kind for d in dressup_chain(current)):
        raise ValueError("l'opération %s a déjà un habillage %s" % (op.Label, kind))
    # ordre d'empilement fixe (ORDER) : les attaches et la rampe sous les entrées/sorties (contour fermé), le motif
    # au-dessus de tout ; un habillage ajouté après un habillage plus haut est inséré dessous
    upper = None
    while is_dressup(current) and dressup_kind(current) in ON_TOP and ORDER.index(dressup_kind(current)) > ORDER.index(kind):
        upper, current = current, current.Base
    doc = job.Document
    previous = FreeCAD.ActiveDocument
    FreeCAD.setActiveDocument(doc.Name)
    try:
        mod = importlib.import_module(meta["module"])
        name = base_operation(current).Name + meta["suffix"]
        if kind == "tags":
            # FreeCAD place les attaches sur le parcours de ce qu'elles enveloppent : un habillage ajouté juste
            # avant (même validation de l'éditeur) n'est pas encore calculé, parcours vide (IndexError)
            if is_dressup(current) and not current.Path.Commands:
                current.recompute()
            if not any(c.Name in ("G1", "G01", "G2", "G02", "G3", "G03") for c in current.Path.Commands):
                from ..i18n import UserError

                raise UserError("Holding tags need a computed contour toolpath: {op} has no cutting move", op=op.Label)
            obj = mod.Create(current, name=name)
            if obj is None:
                raise ValueError("FreeCAD refuse les attaches sur %s (contour fermé requis)" % op.Label)
            if count:
                obj.Proxy.generateTags(obj, int(count))
        elif kind == "dogbone":
            base = base_operation(current)
            strategy = type(getattr(base, "Proxy", None)).__module__
            pattern = getattr(base, "ClearingPattern", getattr(base, "OffsetPattern", None))
            if dogbone_refused(strategy, pattern):
                from ..i18n import UserError

                if strategy == "Path.Op.Adaptive":
                    raise UserError("Dogbones are not available on an adaptive toolpath ({op}): FreeCAD puts bones at the turns of the trochoids, into the walls", op=op.Label)
                raise UserError("Dogbones are not available on {op} with the {pattern} pattern: FreeCAD puts bones at the turns of the passes, into the walls; choose the Offset pattern", op=op.Label, pattern=pattern)
            obj = mod.Create(current, name)
            job.Proxy.addOperation(obj, current)
            if strategy in DOGBONE_POCKETS and getattr(base, "CutMode", None) in ("Climb", "Conventional"):
                # FreeCAD règle le côté pour un contour (Side / Direction) ; une poche n'en a pas : « Right » par
                # défaut, aucun os en opposition
                obj.Side = "Right" if base.CutMode == "Climb" else "Left"
        elif kind == "leads":
            from . import leads

            obj = leads.create(doc, job, current, name)
        elif kind == "pattern":
            from . import patterns

            obj = patterns.create(doc, job, current, name)
        else:
            obj = doc.addObject("Path::FeaturePython", name)
            dbo = mod.ObjectDressup(obj)
            obj.Base = current
            job.Proxy.addOperation(obj, current)
            dbo.setup(obj)
    finally:
        if previous is not None and previous.Name != doc.Name:
            try:
                FreeCAD.setActiveDocument(previous.Name)
            except Exception:
                pass
    obj.Label = "%s + %s" % (base_operation(current).Label, meta["label"].lower())
    # l'habillage remplace l'objet qu'il enveloppe dans le groupe
    job.Operations.Group = [o for o in job.Operations.Group if o.Name != current.Name]
    if upper is not None:  # inséré sous les entrées/sorties : elles l'enveloppent, elles restent dans le groupe
        job.Operations.Group = [o for o in job.Operations.Group if o.Name != obj.Name]
        upper.Base = obj
    if FreeCAD.GuiUp and obj.ViewObject is not None:
        try:
            if kind == "tags":
                import Path.Dressup.Gui.Tags as TagsGui

                obj.ViewObject.Proxy = TagsGui.PathDressupTagViewProvider(obj.ViewObject)
            elif kind == "pattern":
                pass  # fournisseur de vue posé à la création
            elif kind == "dogbone":
                import Path.Dressup.Gui.DogboneII as DogboneGui

                obj.ViewObject.Proxy = DogboneGui.ViewProviderDressup(obj.ViewObject)
            else:
                obj.ViewObject.Proxy = mod.ViewProviderDressup(obj.ViewObject)
            current.ViewObject.Visibility = False
            obj.ViewObject.Visibility = upper is None
        except Exception as exc:  # fournisseur de vue absent : l'habillage reste calculable
            FreeCAD.Console.PrintWarning("CAM2027: dressup view provider: %s\n" % exc)
    try:
        ignored = set_dressup_params(obj, params or {})
    except Exception:
        remove_dressup(job, obj)
        raise
    if kind == "tags" and params and any(k in params for k in ("Width", "Height", "Angle", "Radius")):
        obj.Proxy.generateTags(obj, int(count or max(len(obj.Positions), 1)))
    return obj, ignored


def remove_dressup(job, obj):
    """Retire l'habillage ``obj`` ; ce qu'il enveloppait reprend sa place dans le groupe."""
    base = obj.Base
    group = list(job.Operations.Group)
    if obj in group:
        i = group.index(obj)
        group[i] = base
    else:
        # habillage intermédiaire : rebrancher celui du dessus
        for upper in group:
            for d in dressup_chain(upper):
                if d.Base is not None and d.Base.Name == obj.Name:
                    d.Base = base
    job.Operations.Group = group
    if FreeCAD.GuiUp and base is not None and base.ViewObject is not None:
        base.ViewObject.Visibility = True
    job.Document.removeObject(obj.Name)
    return base


def set_dressup_params(obj, params):
    """Applique les paramètres exposés d'un habillage ; retourne les noms ignorés."""
    if dressup_kind(obj) == "leads":
        from . import leads

        ignored = leads.set_params(obj, params)
        _secure_leads(obj)
        return ignored
    if dressup_kind(obj) == "pattern":
        from . import patterns

        return patterns.set_params(obj, params)
    from .operations import set_params

    return set_params(obj, params)


def _secure_leads(obj):
    """Entrées/sorties loin de la pièce (point de départ déplacé sur 1.1) ou refus avec la position du contact."""
    from . import leads
    from ..i18n import UserError

    import PathScripts.PathUtils as PathUtils

    job = PathUtils.findParentJob(obj)
    shapes = [o.Shape for o in getattr(getattr(job, "Model", None), "Group", []) if getattr(o, "Shape", None)
              and not o.Shape.isNull() and o.Shape.Solids]
    hits = leads.secure(obj, shapes)
    if hits:
        x, y, z = hits[0]
        msg = "The lead-in or lead-out hits the part at X{x:.1f} Y{y:.1f} Z{z:.1f}: reduce the radius or use a vertical arc."
        raise UserError(msg, x=x, y=y, z=z)


def dressup_params(obj):
    """Valeurs courantes des paramètres exposés d'un habillage (plus ``Count`` pour les attaches)."""
    from .operations import read_params

    kind = dressup_kind(obj)
    if kind == "leads":
        from . import leads

        return leads.read_params(obj)
    if kind == "pattern":
        from . import patterns

        return patterns.read_params(obj)
    values = read_params(obj, [n for n, _k in DRESSUPS[kind]["params"]]) if kind else {}
    if kind == "tags":
        values["Count"] = len(obj.Positions)
    return values
