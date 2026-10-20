# SPDX-License-Identifier: LGPL-2.1-or-later
"""Traduction de l'atelier.

Les chaînes sources sont en anglais dans le code ; les catalogues JSON de
``cam2027/i18n/<langue>.json`` fournissent les traductions. La langue suit le
réglage « Général > Langue » de FreeCAD (``fr`` si FreeCAD est en français),
avec remplacement possible par la variable d'environnement ``CAM2027_LANG``.

Un catalogue JSON a été préféré aux fichiers Qt ``.qm`` parce que la
distribution Windows de FreeCAD n'embarque pas ``lrelease``. Les clés restent
les chaînes anglaises, ce qui permet une conversion ultérieure vers ``.ts``.
"""

import json
import os

import FreeCAD

_CATALOG_DIR = os.path.join(os.path.dirname(__file__), "i18n")
_catalog = None
_language = None

_FREECAD_LANGUAGE_CODES = {
    "French": "fr",
    "Français": "fr",
    "fr": "fr",
    "fr-FR": "fr",
}


def _detect_language():
    forced = os.environ.get("CAM2027_LANG")
    if forced:
        return forced.lower()[:2]
    try:
        grp = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/General")
        lang = grp.GetString("Language", "")
    except Exception:
        lang = ""
    if lang:
        return _FREECAD_LANGUAGE_CODES.get(lang, "en")
    # préférence absente : FreeCAD suit la locale du système
    code = ""
    try:
        from PySide import QtCore

        code = QtCore.QLocale.system().name()
    except Exception:
        try:
            import locale

            code = locale.getlocale()[0] or ""
        except Exception:
            code = ""
    return "fr" if code.lower().startswith("fr") else "en"


def language():
    global _language
    if _language is None:
        _language = _detect_language()
    return _language


def set_language(code):
    """Force une langue (tests, préférence de l'atelier)."""
    global _language, _catalog
    _language = code
    _catalog = None


def _load_catalog():
    global _catalog
    if _catalog is not None:
        return _catalog
    _catalog = {}
    path = os.path.join(_CATALOG_DIR, "%s.json" % language())
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        _catalog = {k: v for k, v in data.items() if not k.startswith("_")}
    return _catalog


def tr(text, **kwargs):
    """Traduit ``text`` puis applique ``str.format`` avec ``kwargs``."""
    translated = _load_catalog().get(text, text)
    if kwargs:
        try:
            return translated.format(**kwargs)
        except (KeyError, IndexError):
            return translated
    return translated


def missing_translations(code="fr"):
    """Liste les chaînes utilisées par le code et absentes du catalogue (outil de contrôle)."""
    import re

    used = set()
    root = os.path.dirname(__file__)
    pattern = re.compile(r"\btr\(\s*([\"'])((?:\\.|(?!\1).)*)\1")
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(".py"):
                with open(os.path.join(dirpath, name), "r", encoding="utf-8") as fp:
                    for m in pattern.finditer(fp.read()):
                        # échappements Python résolus sans abîmer les caractères non ASCII (°)
                        used.add(m.group(2).encode("latin-1", "backslashreplace").decode("unicode_escape"))
    path = os.path.join(_CATALOG_DIR, "%s.json" % code)
    with open(path, "r", encoding="utf-8") as fp:
        have = set(k for k in json.load(fp) if not k.startswith("_"))
    return sorted(used - have)
