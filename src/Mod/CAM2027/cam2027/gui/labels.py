# SPDX-License-Identifier: LGPL-2.1-or-later
"""Libellés communs des listes d'outils et de préréglages."""

from ..i18n import tr


def asm_label(a):
    """« T1 - fraise… » ; sans doubler le numéro quand le nom de l'assemblage commence déjà par « T1 »."""
    prefix = "T%d" % a.output.tool_number
    name = a.name[len(prefix):].lstrip(" -") if a.name.startswith(prefix + " ") else a.name
    return "%s - %s" % (prefix, name)


def preset_label(p):
    return "%s (%s, %s)" % (p.name, tr(p.usage), tr(p.material) if p.material else "-")
