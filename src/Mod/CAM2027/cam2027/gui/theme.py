# SPDX-License-Identifier: LGPL-2.1-or-later
"""Couche de thème unique de l'atelier (direction artistique « Atelier »).

Source des valeurs : ``Resources/theme/tokens.json`` (copie de
``docs/design/02_DESIGN_TOKENS.json``). Les widgets n'utilisent que des noms
sémantiques (``color("muted")``, ``status_color("error")``…), jamais une couleur
isolée. La feuille de style produite est **limitée aux widgets CAM2027** : elle
est posée sur nos panneaux et dialogues (``apply(widget)``), jamais sur
l'application entière, pour ne pas modifier les autres parties de FreeCAD.

Thème : préférence ``BaseApp/Preferences/CAM2027/Theme`` = ``system`` (défaut),
``dark`` ou ``light`` ; ``system`` suit la luminosité de la palette Qt courante
(donc le thème FreeCAD actif). Les dimensions sont en pixels logiques : Qt gère
la mise à l'échelle DPI, aucune multiplication manuelle.
"""

import json
import os

from ..i18n import UserError

_RES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "Resources")
TOKENS_PATH = os.path.join(_RES, "theme", "tokens.json")
ICON_DIR = os.path.join(_RES, "icons", "atelier")
THEMES = ("system", "dark", "light")

_tokens = None


def tokens():
    global _tokens
    if _tokens is None:
        with open(TOKENS_PATH, "r", encoding="utf-8") as fp:
            _tokens = json.load(fp)
    return _tokens


# -- choix du thème ----------------------------------------------------------------


def preference():
    try:
        import FreeCAD

        value = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/CAM2027").GetString("Theme", "system")
    except Exception:
        value = "system"
    return value if value in THEMES else "system"


def set_preference(value):
    if value not in THEMES:
        raise UserError("unknown theme: {value}", value=repr(value))
    import FreeCAD

    FreeCAD.ParamGet("User parameter:BaseApp/Preferences/CAM2027").SetString("Theme", value)


def _system_is_dark():
    try:
        from .qt import QtGui, QtWidgets

        app = QtWidgets.QApplication.instance()
        if app is None:
            return True
        return app.palette().color(QtGui.QPalette.Window).lightness() < 128
    except Exception:
        return True


def resolve(name=None):
    """Thème effectif (``dark`` ou ``light``) pour une préférence donnée."""
    name = name or preference()
    if name == "system":
        return "dark" if _system_is_dark() else "light"
    return name


def chrome():
    """Thème de la fenêtre FreeCAD (barres d'outils, menus) d'après sa couleur de fond réelle : le thème des panneaux
    CAM2027 peut être clair dans une fenêtre restée sombre, et des icônes claires y seraient invisibles."""
    try:
        import FreeCADGui
        from .qt import QtGui

        window = FreeCADGui.getMainWindow().palette().color(QtGui.QPalette.Window)
        return "dark" if window.lightness() < 128 else "light"
    except Exception:
        return resolve()


def color(role, theme=None):
    """Couleur sémantique (``background``, ``surface``, ``muted``, ``primary``, ``success``…)."""
    return tokens()["themes"][resolve(theme)][role]


#: niveau de contrôle d'export / état -> rôle sémantique
_STATUS_ROLES = {
    "error": "danger", "danger": "danger", "failed": "danger",
    "warning": "warning", "unverifiable": "warning", "stale": "warning",
    "info": "info", "ok": "success", "success": "success", "done": "success",
    "todo": "muted", "muted": "muted",
}


def status_color(level, theme=None):
    return color(_STATUS_ROLES.get(level, "muted"), theme)


# -- icônes ------------------------------------------------------------------------


def icon_path(name, theme=None):
    """Chemin du SVG ``name`` (sans extension) adapté au thème (traits clairs sur sombre)."""
    path = os.path.join(ICON_DIR, resolve(theme), name + ".svg")
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    return path


_icons = {}  # (nom, thème effectif) -> QIcon : le panneau Projet en demande trois par opération à chaque rafraîchissement


def icon(name, theme=None):
    from .qt import QtGui

    key = (name, resolve(theme))
    if key not in _icons:
        _icons[key] = QtGui.QIcon(icon_path(name, key[1]))
    return _icons[key]


# -- feuille de style ----------------------------------------------------------------


def stylesheet(theme=None, density="comfortable"):
    """QSS du périmètre CAM2027 : s'applique au widget racine qui la reçoit et à ses enfants."""
    t = tokens()
    c = t["themes"][resolve(theme)]
    r = t["radius"]
    ctrl = t["density"][density]["control"]
    font = t["typography"]
    sp = t["spacing"]
    families = ", ".join('"%s"' % f if " " in f else f for f in font["familyUI"])
    mono = ", ".join('"%s"' % f if " " in f else f for f in font["familyMono"])
    return """
QWidget {{ background-color: {surface}; color: {text}; font-family: {families}; font-size: {body}px; }}
QLabel {{ background: transparent; }}
QLabel[role="muted"] {{ color: {muted}; font-size: {caption}px; }}
QLabel[role="section"] {{ font-size: {section}px; font-weight: 600; }}
QLabel[role="warning"] {{ color: {warning}; }}
QGroupBox {{ border: 1px solid {divider}; border-radius: {rpanel}px; margin-top: {xl}px; padding: {md}px {sm}px {sm}px {sm}px; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: {sm}px; top: {xs}px; padding: 0 {xs}px; color: {text}; background-color: {surface}; font-weight: 600; }}
QPushButton, QToolButton {{ background-color: {raised}; color: {text}; border: 1px solid {border};
    border-radius: {rinput}px; min-height: {ctrl_inner}px; padding: 0 {md}px; }}
QPushButton:hover, QToolButton:hover {{ background-color: {selected}; }}
QPushButton:pressed, QToolButton:pressed {{ background-color: {selected}; color: {selectedText}; border-color: {focus}; }}
QPushButton:focus, QToolButton:focus {{ border: 2px solid {focus}; }}
QPushButton:disabled, QToolButton:disabled {{ background-color: {surface}; color: {disabledText}; border-color: {divider}; }}
QPushButton[role="primary"] {{ background-color: {primary}; color: {onPrimary}; border: 1px solid {primary}; font-weight: 600; }}
QPushButton[role="primary"]:hover {{ background-color: {primaryHover}; }}
QPushButton[role="primary"]:focus {{ border: 2px solid {focus}; }}
QPushButton[role="danger"] {{ color: {danger}; border-color: {danger}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background-color: {background}; color: {text}; border: 1px solid {border}; border-radius: {rinput}px;
    min-height: {ctrl_inner}px; padding: 0 {xs}px; selection-background-color: {selected}; selection-color: {selectedText}; }}
QPlainTextEdit, QTextEdit {{ font-family: {mono}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 2px solid {focus}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {disabledText}; border-color: {divider}; }}
QComboBox QAbstractItemView {{ background-color: {raised}; color: {text}; selection-background-color: {selected};
    selection-color: {selectedText}; }}
QCheckBox {{ background: transparent; spacing: {sm}px; }}
QTabWidget::pane {{ border: 1px solid {divider}; border-radius: {rpanel}px; top: -1px; }}
QTabBar::tab {{ background: {surface}; color: {muted}; padding: {xs}px {md}px; border: 1px solid transparent;
    border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {text}; border-bottom: 2px solid {primary}; font-weight: 600; }}
QTabBar::tab:hover {{ color: {text}; }}
QTreeWidget, QTableWidget, QListWidget {{ background-color: {background}; alternate-background-color: {surface};
    border: 1px solid {divider}; border-radius: {rinput}px; gridline-color: {divider}; }}
QTreeWidget::item, QTableWidget::item, QListWidget::item {{ min-height: {row}px; }}
QTreeWidget::item:selected, QTableWidget::item:selected, QListWidget::item:selected {{
    background-color: {selected}; color: {selectedText}; }}
QTreeWidget::item:selected:first, QTableWidget::item:selected:first {{ border-left: 3px solid {primary}; }}
QHeaderView::section {{ background-color: {raised}; color: {muted}; border: none; border-bottom: 1px solid {divider};
    padding: {xs}px {sm}px; font-weight: 600; }}
QScrollArea {{ border: none; }}
QToolTip {{ background-color: {raised}; color: {text}; border: 1px solid {border}; }}
QToolButton#sectionHeader {{ background-color: {raised}; border: none; border-radius: 0; border-bottom: 1px solid {divider};
    text-align: left; font-weight: 600; padding: {xs}px {sm}px; min-height: {ctrl_inner}px; }}
QToolButton#sectionHeader:hover {{ background-color: {selected}; }}
QFrame#taskRow {{ background-color: {surface}; border: 1px solid transparent; border-radius: {rinput}px; }}
QFrame#taskRow:hover {{ background-color: {raised}; border-color: {divider}; }}
QLabel#keyStrip {{ background-color: {raised}; border-top: 1px solid {divider}; border-bottom: 1px solid {divider};
    padding: {xs}px {sm}px; }}
QWidget#inspectorHead {{ background-color: {raised}; border-bottom: 1px solid {divider}; }}
QWidget#pageButtons {{ border-top: 1px solid {divider}; }}
QLabel#projectSummary {{ background-color: {raised}; border: 1px solid {divider}; border-radius: {rinput}px; }}
""".format(families=families, mono=mono, body=font["sizes"]["body"], caption=font["sizes"]["caption"],
           section=font["sizes"]["section"], rinput=r["input"], rpanel=r["panel"], ctrl_inner=ctrl - 6,
           row=t["density"][density]["row"] - 8, xl=sp["xl"], xs=sp["xs"], sm=sp["sm"], md=sp["md"], lg=sp["lg"], **c)


def shell_stylesheet(theme=None):
    """QSS de la barre des espaces : fond de la fenêtre FreeCAD (``chrome``), boutons d'espace soulignés par
    l'accent quand ils sont actifs ; états survol / focus / désactivé distincts."""
    t = tokens()
    c = t["themes"][chrome() if theme is None else resolve(theme)]
    sp = t["spacing"]
    return """
QToolBar#CAM2027_Shell {{ border: none; border-bottom: 1px solid {divider}; padding: 2px {sm}px; spacing: 2px; }}
QToolBar#CAM2027_Shell QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 4px;
    padding: 3px {sm}px; color: {text}; }}
QToolBar#CAM2027_Shell QToolButton:hover {{ background-color: {selected}; }}
QToolBar#CAM2027_Shell QToolButton:pressed {{ background-color: {selected}; border-color: {focus}; }}
QToolBar#CAM2027_Shell QToolButton:focus {{ border-color: {focus}; }}
QToolBar#CAM2027_Shell QToolButton:disabled {{ color: {disabledText}; }}
QToolBar#CAM2027_Shell QToolButton#spaceButton {{ font-weight: 600; padding: 4px {md}px;
    border-radius: 0; border-bottom: 3px solid transparent; margin: 0 {xs}px; }}
QToolBar#CAM2027_Shell QToolButton#spaceButton:checked {{ border-bottom: 3px solid {primary}; color: {text}; background: transparent; }}
QToolBar#CAM2027_Shell QToolButton#spaceButton:hover {{ background-color: {selected}; }}
QToolBar#CAM2027_Shell QToolButton#spaceButton:disabled {{ color: {disabledText}; }}
QToolBar#CAM2027_Shell QLabel {{ background: transparent; color: {text}; }}
QToolBar#CAM2027_Shell::separator {{ background-color: {divider}; width: 1px; margin: 4px {xs}px; }}
""".format(xs=sp["xs"], sm=sp["sm"], md=sp["md"], **c)


def apply(widget, theme=None):
    """Pose la feuille de style CAM2027 sur ``widget`` (et donc ses enfants) ; retourne le thème effectif."""
    effective = resolve(theme)
    widget.setStyleSheet(stylesheet(effective))
    widget.setProperty("cam2027Theme", effective)
    return effective


def set_role(widget, role):
    """Rôle visuel d'un widget (``primary``, ``danger``, ``muted``, ``section``, ``warning``)."""
    widget.setProperty("role", role)
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    return widget
