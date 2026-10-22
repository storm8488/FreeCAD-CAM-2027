# SPDX-License-Identifier: LGPL-2.1-or-later
"""Comparer et modifier plusieurs opérations à la fois (tableau « paramètres × opérations »).

Les lignes sont les paramètres exposés (``STRATEGIES[kind]["params"]``) présents sur **toutes** les opérations
choisies ; une valeur modifiée est écrite sur chacune par ``Project.update_operation`` (registre compris), comme
depuis l'éditeur d'opération. Les opérations sans stratégie connue (positionnements A, gravure enroulée, angles
vifs...) ne sont pas proposées.
"""

from . import operations as opsmod
from . import paramspec

#: écart en dessous duquel deux valeurs numériques sont « identiques »
TOLERANCE = 1e-6


def editable_operations(project, ops=None):
    """Opérations de base modifiables (une par entrée du groupe Operations, habillages ramenés à leur base)."""
    reg = project.registry
    out = []
    for obj in (project.operations() if ops is None else ops):
        base = project.base_operation(obj)
        rec = reg.get(base.Name)
        if rec and rec.get("kind") in opsmod.STRATEGIES and base not in out:
            out.append(base)
    return out


def _same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) <= TOLERANCE
        except (TypeError, ValueError):
            return False
    return a == b


def compare(project, ops):
    """Lignes du tableau : ``[{"name", "label", "group", "kind", "choices", "values", "differs"}]``.

    ``values`` : une valeur par opération (même ordre que ``ops``). Ordre : celui des onglets de l'éditeur."""
    reg = project.registry
    names = None
    for op in ops:
        params = [p for p in opsmod.STRATEGIES[reg[op.Name]["kind"]]["params"] if p in op.PropertiesList]
        names = params if names is None else [p for p in names if p in params]
    rows = []
    order = {g: i for i, (g, _l) in enumerate(paramspec.GROUPS)}
    for name in names or []:
        kind, choices = opsmod.param_kind(ops[0], name)
        if kind in ("other", "vector"):
            continue
        values = [opsmod.read_params(op, [name]).get(name) for op in ops]
        if any(v is None for v in values):
            continue
        if kind == "enum":  # mêmes choix partout, sinon la ligne n'est pas commune
            if any(tuple(opsmod.param_kind(op, name)[1]) != tuple(choices) for op in ops[1:]):
                continue
        label, group, help_text = paramspec.spec(name)
        rows.append({"name": name, "label": label, "group": group, "help": help_text, "kind": kind,
                     "choices": tuple(choices), "values": values,
                     "differs": any(not _same(values[0], v) for v in values[1:])})
    rows.sort(key=lambda r: (order.get(r["group"], len(order)), names.index(r["name"])))
    return rows


def parse(kind, text, choices=()):
    """Valeur saisie (texte) convertie selon le genre du paramètre ; ValueError si invalide."""
    from .. import units

    text = str(text).strip()
    if kind == "bool":
        if text.lower() in ("1", "true", "yes", "oui", "vrai"):
            return True
        if text.lower() in ("0", "false", "no", "non", "faux"):
            return False
        raise ValueError(text)
    if kind == "enum":
        if text not in choices:
            raise ValueError(text)
        return text
    if kind == "length":
        return units.to_mm(text)
    if kind == "angle":
        return units.to_deg(text)
    if kind == "percent":
        value = units.to_float(text.replace("%", "").strip())
        if not 0 <= value <= 100:
            raise ValueError(text)
        return int(round(value))
    if kind == "float":
        return units.to_float(text)
    if kind == "int":
        return int(units.to_float(text))
    return text


def apply(project, ops, changes):
    """Écrit ``changes`` = ``{paramètre: valeur}`` sur chaque opération ; retourne ``{opération: [ignorés]}``."""
    ignored = {}
    for op in ops:
        rest = project.update_operation(op, dict(changes))
        if rest:
            ignored[op.Label] = rest
    return ignored
