# SPDX-License-Identifier: LGPL-2.1-or-later
"""Panneau contextuel (à droite) : une seule tâche à la fois (éditeur d'opération, brut, machine, export,
vérification…), posée dans le dock « CAM2027_Inspector » de la coquille.

Une **page** (``Page``) remplace un dialogue : même vocabulaire (``accept`` / ``reject`` / ``done`` /
``finished``), mais non modale et à sa place dans la fenêtre. Changer de page quand la page courante a des
modifications non appliquées demande explicitement quoi en faire (appliquer, abandonner, rester).

Les scénarios d'interface branchent ``page_hook`` : le pilote reçoit la page comme il recevait un dialogue
(titre, remplissage, acceptation) et le flux reste synchrone.
"""

from .qt import QtCore, QtWidgets
from ..i18n import tr
from . import theme

#: scénarios : fonction(page) -> True si la page a été traitée (remplie, acceptée ou refusée) sur place
page_hook = None


class Page(QtWidgets.QWidget):
    """Page du panneau contextuel : titre, corps, barre de boutons ; ``apply()`` fait le travail."""

    finished = QtCore.Signal(int)
    #: page de saisie (remplacée par le pilote des scénarios comme un dialogue) ou page de travail (éditeur)
    dialog_like = True

    def __init__(self, title, parent=None):
        super(Page, self).__init__(parent)
        self.setWindowTitle(title)
        self.result = None
        self._done = False
        self.primary_button = None
        self.outer = QtWidgets.QVBoxLayout(self)
        self.outer.setContentsMargins(0, 0, 0, 0)
        self.outer.setSpacing(0)

    # -- construction ------------------------------------------------------------------------------

    def scrolled_body(self):
        """Corps dans une zone défilante (formulaires longs, 150 / 200 %) ; retourne le widget du corps."""
        body = QtWidgets.QWidget()
        area = QtWidgets.QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QtWidgets.QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        area.setWidget(body)
        self.outer.addWidget(area, 1)
        self.scroll_area = area
        return body

    def add_buttons(self, primary, cancel=None, extra=()):
        """Barre de boutons : ``primary`` (action principale, pleine largeur), puis ``extra`` [(libellé, fonction)]
        et ``cancel`` sur une seconde ligne : lisible dans un panneau de 360 px."""
        bar = QtWidgets.QWidget()
        bar.setObjectName("pageButtons")
        col = QtWidgets.QVBoxLayout(bar)
        col.setContentsMargins(8, 6, 8, 8)
        col.setSpacing(4)
        self.primary_button = QtWidgets.QPushButton(primary)
        theme.set_role(self.primary_button, "primary")
        self.primary_button.setDefault(True)
        self.primary_button.clicked.connect(self.accept)
        col.addWidget(self.primary_button)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(4)
        self.extra_buttons = {}
        for label, slot in extra:
            b = QtWidgets.QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
            self.extra_buttons[label] = b
        self.cancel_button = None
        if cancel:
            self.cancel_button = QtWidgets.QPushButton(cancel)
            self.cancel_button.clicked.connect(self.reject)
            row.addWidget(self.cancel_button)
        if extra or cancel:
            col.addLayout(row)
        self.outer.addWidget(bar)
        return bar

    # -- cycle de vie --------------------------------------------------------------------------------

    def has_unsaved_changes(self):
        return False

    def apply(self):
        """Fait le travail de la page ; retourne True si la page peut se fermer."""
        return True

    def accept(self):
        if self.apply():
            self.done(1)

    def reject(self):
        self.done(0)

    def done(self, code):
        if self._done:
            return
        self._done = True
        self.result = code
        self.finished.emit(code)

    def is_done(self):
        return self._done


class Inspector(QtWidgets.QWidget):
    """Conteneur : barre de titre (titre de la page, fermeture) et la page courante."""

    def __init__(self, parent=None):
        super(Inspector, self).__init__(parent)
        self.setObjectName("CAM2027_InspectorWidget")
        self.page = None
        self.on_empty = None  # fonction appelée quand la dernière page se ferme (la coquille masque le dock)
        self.on_page = None  # fonction appelée quand une page s'ouvre (la coquille montre le dock)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QtWidgets.QWidget()
        head.setObjectName("inspectorHead")
        hl = QtWidgets.QHBoxLayout(head)
        hl.setContentsMargins(10, 6, 6, 6)
        self.title = QtWidgets.QLabel()
        theme.set_role(self.title, "section")
        hl.addWidget(self.title, 1)
        self.close_button = QtWidgets.QToolButton()
        self.close_button.setText("✕")
        self.close_button.setToolTip(tr("Close this panel"))
        self.close_button.setAutoRaise(True)
        self.close_button.clicked.connect(self.close_page)
        hl.addWidget(self.close_button)
        lay.addWidget(head)
        self.holder = QtWidgets.QVBoxLayout()
        self.holder.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(self.holder, 1)
        self.empty = QtWidgets.QLabel(tr("No task open. Pick an item in the navigator on the left."))
        self.empty.setWordWrap(True)
        self.empty.setAlignment(QtCore.Qt.AlignTop)
        self.empty.setContentsMargins(10, 10, 10, 10)
        theme.set_role(self.empty, "muted")
        self.holder.addWidget(self.empty)

    # -- pages ------------------------------------------------------------------------------------------

    def show_page(self, page):
        """Pose ``page`` dans le panneau ; retourne la page, ou None si la page courante a refusé de céder la
        place (modifications non appliquées gardées)."""
        if page_hook is not None and page.dialog_like and page_hook(page):
            return page
        if self.page is not None and self.page is not page and not self.release():
            page.done(0)
            return None
        self.page = page
        self.empty.hide()
        page.setParent(self)
        self.holder.addWidget(page, 1)
        page.show()
        self.title.setText(page.windowTitle())
        page.finished.connect(lambda code, p=page: self._page_finished(p))
        self.show()
        if self.on_page is not None:
            self.on_page(page)
        return page

    def sizeHint(self):
        return QtCore.QSize(440, 700)

    def release(self):
        """Libère la page courante ; demande quoi faire des modifications non appliquées. False = rester."""
        page = self.page
        if page is None:
            return True
        if page.has_unsaved_changes():
            box = QtWidgets.QMessageBox(self.window())
            box.setWindowTitle("CAM2027")
            box.setText(tr("{title}: changes not applied yet.", title=page.windowTitle()))
            box.setInformativeText(tr("Apply them, discard them, or stay on this panel?"))
            apply_b = box.addButton(tr("Apply"), QtWidgets.QMessageBox.AcceptRole)
            box.addButton(tr("Discard"), QtWidgets.QMessageBox.DestructiveRole)
            stay = box.addButton(tr("Stay"), QtWidgets.QMessageBox.RejectRole)
            box.setDefaultButton(stay)
            answer = _ask(box)
            if answer is stay:
                return False
            if answer is apply_b:
                if not page.apply():
                    return False
        page.done(0 if page.result is None else page.result)
        return True

    def close_page(self):
        if self.page is None:
            return
        if self.page.has_unsaved_changes():
            if not self.release():
                return
        else:
            self.page.reject()

    def _page_finished(self, page):
        if page is not self.page:
            return
        self.page = None
        self.holder.removeWidget(page)
        page.hide()
        page.setParent(None)
        page.deleteLater()
        self.title.setText("")
        self.empty.show()
        if self.on_empty is not None:
            self.on_empty()


#: scénarios : remplace la boîte de question (bouton cliqué) ; None = boîte réelle
ask_hook = None


def _ask(box):
    if ask_hook is not None:
        return ask_hook(box)
    box.exec() if hasattr(box, "exec") else box.exec_()
    return box.clickedButton()
