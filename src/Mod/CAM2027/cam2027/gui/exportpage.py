# SPDX-License-Identifier: LGPL-2.1-or-later
"""Page « Exporter le G-code » (espace Vérifier et exporter) : postprocesseur, fichier, récapitulatif avant
export (machine, post, unités, repère, opérations incluses dans l'ordre, outils, contrôles), aperçu du G-code,
contrôles, fiche de réglage. Les protections d'export du projet restent les mêmes (``ExportBlocked``)."""

import os

from .qt import QtGui, QtWidgets
from ..i18n import tr, tr_msg
from ..project import export as exportmod
from ..project.project import ExportBlocked
from . import theme
from .inspector import Page


class ExportPage(Page):
    def __init__(self, proj, parent=None):
        super(ExportPage, self).__init__(tr("Export G-code"), parent)
        self.proj = proj
        body = self.scrolled_body()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(10, 8, 10, 8)
        form = QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        self.post = QtWidgets.QComboBox()
        posts = exportmod.available_postprocessors()
        self.post.addItems(posts)
        if proj.job.PostProcessor in posts:
            self.post.setCurrentText(proj.job.PostProcessor)
        form.addRow(tr("Post processor"), self.post)
        self.args = QtWidgets.QLineEdit(proj.job.PostProcessorArgs)
        form.addRow(tr("Arguments"), self.args)
        default_out = proj.job.PostProcessorOutputFile or os.path.join(
            os.path.dirname(proj.doc.FileName) if proj.doc.FileName else os.path.expanduser("~"),
            (proj.doc.Label or "program") + ".nc")
        self.out = QtWidgets.QLineEdit(default_out)
        browse = QtWidgets.QPushButton(tr("Browse..."))
        browse.clicked.connect(self._pick)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.out, 1)
        row.addWidget(browse)
        form.addRow(tr("Output file"), row)
        lay.addLayout(form)
        self.tabs = QtWidgets.QTabWidget()
        self.preview = QtWidgets.QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        self.checks = QtWidgets.QTextEdit()
        self.checks.setReadOnly(True)
        self.sheet = QtWidgets.QPlainTextEdit()
        self.sheet.setReadOnly(True)
        self.summary = QtWidgets.QTextEdit()
        self.summary.setReadOnly(True)
        self.tabs.addTab(self.summary, tr("Summary"))
        self.tabs.addTab(self.checks, tr("Checks"))
        self.tabs.addTab(self.preview, tr("G-code"))
        self.tabs.addTab(self.sheet, tr("Setup sheet"))
        self.tabs.setToolTip(tr("Summary before export, checks, G-code preview, setup sheet"))
        self.tabs.setMinimumHeight(260)
        lay.addWidget(self.tabs, 1)
        note = QtWidgets.QLabel(tr("Exporting writes a file only. Nothing is sent to the machine."))
        note.setWordWrap(True)
        theme.set_role(note, "muted")
        lay.addWidget(note)
        self.add_buttons(tr("Export G-code"), tr("Close"), extra=((tr("Preview"), self.do_preview),))
        self.primary_button.clicked.disconnect()
        self.primary_button.clicked.connect(self.do_export)
        self.primary_button.setIcon(theme.icon("export-gcode"))
        theme.apply(self)
        self.do_preview()

    def _pick(self):
        p, _f = QtWidgets.QFileDialog.getSaveFileName(self, tr("Output file"), self.out.text(), "G-code (*.nc *.gcode *.ngc)")
        if p:
            self.out.setText(p)

    def do_preview(self):
        from .commands import busy, _format_checks, _format_summary

        proj = self.proj
        try:
            with busy(tr("Post-processing..."), stoppable=proj) as b:
                text, analysis, issues = proj.preview_gcode(self.post.currentText(), self.args.text())
                rows = exportmod.export_summary(proj, analysis, issues)
                sheet_text = exportmod.prep_sheet(proj, [], analysis, issues, [self.out.text()])
        except Exception as exc:
            self.checks.setPlainText(tr("Post-processing failed: {error}", error=tr_msg(exc)))
            return
        if b.stopped:
            return
        self.preview.setPlainText(text)
        self.summary.setHtml(_format_summary(rows))
        self.checks.setHtml(_format_checks(analysis, issues))
        self.sheet.setPlainText(sheet_text)
        blocking = [m for lvl, m in issues if lvl == "error"]
        self.primary_button.setToolTip(tr("Blocked by the checks: {errors}", errors="; ".join(tr_msg(m) for m in blocking))
                                       if blocking else tr("Post-process, check and write the G-code and the setup sheet"))

    def do_export(self):
        from . import panels
        from .commands import busy, _format_checks, _info, _warn
        from ..project import twosided

        proj = self.proj
        try:
            with busy(tr("Post-processing..."), stoppable=proj) as b:
                result = twosided.exporter(proj)(self.out.text(), self.post.currentText(), self.args.text())  # recto-verso : un fichier par face
        except ExportBlocked as exc:
            self.checks.setHtml(_format_checks(exc.analysis, exc.issues))
            self.tabs.setCurrentWidget(self.checks)
            _warn(tr("Export blocked by the checks: {errors}", errors="; ".join(tr_msg(m) for lvl, m in exc.issues if lvl == "error")))
            return
        except Exception as exc:
            _warn(tr("Export failed: {error}", error=tr_msg(exc)))
            return
        if b.stopped:
            return
        self.preview.setPlainText(result["gcode"])
        self.checks.setHtml(_format_checks(result["analysis"], result["issues"]))
        self.sheet.setPlainText(result["sheet_text"])
        _info(tr("Written: {files}\nSetup sheet: {sheet}\nLoad the file in CNCjs yourself; nothing is sent automatically.",
                 files=", ".join(result["files"]), sheet=result["sheet"]))
        panels.refresh_project_panel()

    def apply(self):
        return True  # « Fermer » : l'export se fait par son bouton, jamais à la fermeture


def open_page(proj):
    from . import shell

    shell.show_space("verify")
    return shell.inspector().show_page(ExportPage(proj))
