# SPDX-License-Identifier: LGPL-2.1-or-later
"""Identifiants stables.

Chaque outil, porte-outil, assemblage, préréglage, machine et opération reçoit
un identifiant UUID4 textuel à sa création. Les identifiants ne changent jamais,
même lors d'un renommage, d'une duplication (la copie reçoit un nouvel
identifiant) ou d'un import. Les références entre objets utilisent toujours
l'identifiant, jamais le nom.
"""

import re
import uuid

_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def new_id():
    return str(uuid.uuid4())


def is_id(value):
    return isinstance(value, str) and bool(_ID_RE.match(value))
