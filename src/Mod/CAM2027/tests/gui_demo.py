# SPDX-License-Identifier: LGPL-2.1-or-later
"""Démonstration guidée de l'atelier (à lancer avec FreeCAD.exe, pas FreeCADCmd) :

    scripts\\cam2027.cmd src\\Mod\\CAM2027\\tests\\gui_demo.py

Déroule la chaîne complète pas à pas dans l'interface : une boîte de dialogue
explique chaque étape, « OK » passe à la suivante. FreeCAD reste ouvert à la fin
avec le projet de démonstration, pour continuer à la main.
"""

import os
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
if MOD not in sys.path:
    sys.path.insert(0, MOD)

import FreeCAD
import FreeCADGui

from PySide import QtCore, QtWidgets  # PySide2 ou PySide6 selon la version de FreeCAD

TOTAL = 8


def log(msg):
    FreeCAD.Console.PrintMessage("[gui_demo] %s\n" % msg)


def step(n, title, text):
    log("étape %d : %s" % (n, title))
    QtWidgets.QApplication.processEvents()
    QtWidgets.QMessageBox.information(FreeCADGui.getMainWindow(), "CAM2027 — étape %d/%d : %s" % (n, TOTAL, title), text)


def fit():
    FreeCADGui.SendMsgToActiveView("ViewFit")
    QtWidgets.QApplication.processEvents()


def ensure_tool(lib, tool_type, predicate=lambda t: True):
    """Outil du type demandé dans la bibliothèque utilisateur ; sinon copié depuis la bibliothèque de démarrage."""
    from cam2027.tools.library import starter_library
    from cam2027.tools.model import CuttingPreset, ToolAssembly

    found = [t for t in lib.search(tool_type=tool_type) if predicate(t)]
    if not found:
        starter = starter_library()
        src = [t for t in starter.search(tool_type=tool_type) if predicate(t)][0]
        lib.add_tool(src)
        numbers = [a.output.tool_number for a in lib.assemblies.values()]
        src_asm = starter.assemblies_for_tool(src.id)[0]
        if src_asm.holder_id and src_asm.holder_id not in lib.holders:
            lib.add_holder(starter.holder(src_asm.holder_id))
        src_asm.output.tool_number = max(numbers + [0]) + 1
        src_asm.name = "T%d %s" % (src_asm.output.tool_number, src.name)
        lib.add_assembly(src_asm)
        found = [src]
    tool = found[0]
    if not tool.presets:
        tool.add_preset(CuttingPreset("Demo", spindle_rpm=16000, feed_mm_min=1000, plunge_feed_mm_min=300,
                                      axial_engagement_mm=1.0, radial_engagement_mm=tool.geometry.diameter * 0.4))
    asms = lib.assemblies_for_tool(tool.id)
    if not asms:
        numbers = [a.output.tool_number for a in lib.assemblies.values()]
        asms = [lib.add_assembly(ToolAssembly("T%d %s" % (max(numbers + [0]) + 1, tool.name), tool.id, None,
                                              output={"tool_number": max(numbers + [0]) + 1, "manual_tool_change": True}))]
    return tool, asms[0], tool.presets[0]


def run():
    FreeCADGui.activateWorkbench("CAM2027Workbench")
    from cam2027.gui import state, panels
    from cam2027.project.project import Project
    from tests.test_pipeline import make_part, plate_top_face, plate_top_outer_edges, hole_face

    lib = state.library()
    panels.show_tool_library()
    step(1, "Bibliothèque d'outils",
         "L'atelier CAM2027 est actif (barre d'outils et menu « CAM2027 »).\n\n"
         "Le panneau « Bibliothèque d'outils » en bas montre %d outils, %d porte-outils et %d assemblages, "
         "avec trois onglets : Coupant (géométrie), Préréglages (conditions de coupe) et Assemblage "
         "(porte-outil, sortie, numéro d'outil).\n\n"
         "Chaque projet garde une copie figée de cette bibliothèque : modifier un outil ensuite ne change "
         "pas un projet existant.\n\nOK : créer un projet et importer une pièce."
         % (lib.summary()["tools"], lib.summary()["holders"], lib.summary()["assemblies"]))

    tmp = tempfile.mkdtemp(prefix="cam2027-demo-")
    stepfile = os.path.join(tmp, "plaque-demo.step")
    make_part(stepfile)
    proj = Project.create("Démo CAM2027", lib)
    FreeCADGui.ActiveDocument = FreeCADGui.getDocument(proj.doc.Name)
    panels.ensure_project_panel()
    res = proj.import_model(stepfile, label="Plaque")
    part = res.objects[0]
    FreeCADGui.activeDocument().activeView().viewIsometric()
    fit()
    panels.refresh_project_panel()
    step(2, "Projet et pièce",
         "Commande « Nouveau projet » : un document FreeCAD « Démo CAM2027 » avec l'instantané de la bibliothèque.\n\n"
         "Commande « Importer un modèle » : ici une plaque STEP 80 × 60 × 10 mm générée pour la démo "
         "(poche rectangulaire, îlot cylindrique, avant-trou Ø6,8 pour un filet M8). STL, OBJ, SVG et DXF "
         "sont aussi acceptés.\n\nLe panneau de flux de travail à droite suit les quatre étapes (pièce, brut et "
         "montage, opérations, contrôle et export) avec un bouton par étape.\n\nOK : définir le brut et le montage.")

    proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
    proj.add_clamp("Bride gauche", 10, 20, 15, (-12, 20, 0))
    fit()
    panels.refresh_project_panel()
    sb = proj.stock_bounds()
    step(3, "Brut et montage",
         "Commande « Brut & montage » : brut = boîte autour de la pièce avec 2 mm de marge en XY et 1 mm "
         "au-dessus (%.0f × %.0f × %.0f mm), repère G54, plus une bride visuelle (boîte) à gauche.\n\n"
         "Les brides ne servent qu'à la visualisation : il n'y a pas encore de détection de collision.\n\n"
         "OK : première opération, le surfaçage." % (sb["length"], sb["width"], sb["height"]))

    clone = proj.job.Model.Group[0]
    endmill, asm, preset = ensure_tool(lib, "endmill", lambda t: abs(t.geometry.diameter - 6.0) < 1e-6)
    proj.add_operation("millface", "Surfaçage", asm.id, preset.id, base=[(clone, [plate_top_face(clone)])],
                       params={"StepDown": 1.0, "FinalDepth": 9.0, "StepOver": 50, "ClearEdges": True})
    r = proj.compute()[-1]
    fit()
    panels.refresh_project_panel()
    step(4, "Surfaçage",
         "Commande « Ajouter une opération » avec la face supérieure sélectionnée, stratégie « Surfaçage », "
         "outil %s, préréglage « %s ».\n\n"
         "Le parcours (en vert dans la vue 3D) enlève 1 mm sur toute la face : %d commandes, Z de %.1f à %.1f, "
         "avance %s mm/min copiée depuis le préréglage.\n\n"
         "Dans l'interface, « Ajouter une opération » ouvre ensuite l'éditeur à onglets (Outil, Géométrie, "
         "Hauteurs, Passes, Stratégie, Entrée / sortie / attaches) ; un double-clic dans la liste des "
         "opérations le rouvre.\n\nOK : poche et contour."
         % (endmill.name, preset.name, r["commands"], r["zmin"], r["zmax"], r["feeds"]))

    bottom = None
    for i, f in enumerate(clone.Shape.Faces, 1):
        bb = f.BoundBox
        if f.Surface.__class__.__name__ == "Plane" and abs(bb.ZMax - 4.0) < 1e-6 and abs(bb.ZMin - 4.0) < 1e-6:
            bottom = "Face%d" % i
    proj.add_operation("pocket", "Poche", asm.id, preset.id, base=[(clone, [bottom])],
                       params={"StepDown": 2.0, "StepOver": 40, "FinalDepth": 4.0})
    proj.add_operation("profile", "Contour extérieur", asm.id, preset.id, base=[(clone, [])],
                       params={"StepDown": 5.0, "FinalDepth": 0.0, "Side": "Outside", "Direction": "CW"})
    results = proj.compute()
    fit()
    panels.refresh_project_panel()
    step(5, "Poche et contour",
         "Deux opérations de plus avec la même fraise 6 mm :\n"
         "- « Poche » sur la face du fond (Z 4), passes de 2 mm, recouvrement 40 %% : %d commandes ;\n"
         "- « Contour extérieur », côté extérieur, horaire, jusqu'à Z 0 : %d commandes.\n\n"
         "Chaque opération a son propre ToolController avec les valeurs du préréglage au moment de la "
         "création.\n\nOK : chanfrein des arêtes supérieures." % (results[1]["commands"], results[2]["commands"]))

    vbit, vasm, vpreset = ensure_tool(lib, "vbit", lambda t: abs(t.geometry.tip_included_angle_deg - 90.0) < 1e-6)
    proj.add_operation("chamfer", "Chanfrein", vasm.id, vpreset.id, base=[(clone, plate_top_outer_edges(clone))],
                       params={"Width": 1.0, "ExtraDepth": 0.5, "Direction": "CW", "EntryPoint": 0})
    r = proj.compute()[-1]
    fit()
    panels.refresh_project_panel()
    step(6, "Chanfrein",
         "Stratégie « Chanfreinage / ébavurage » sur les quatre arêtes supérieures avec le V-bit 90° (%s) : "
         "largeur 1 mm + 0,5 mm de surprofondeur. La profondeur découle de l'angle de l'outil : "
         "Z %.2f, %d commandes.\n\nOK : fraisage du filet M8." % (vbit.name, r["zmin"], r["commands"]))

    tm, tasm, tpreset = ensure_tool(lib, "threadmill")
    _op, rec = proj.add_operation("threadmill", "Filet M8", tasm.id, tpreset.id, base=[(clone, [hole_face(clone)])],
                                  params={"ThreadType": "MetricInternal6H", "ThreadName": "M8 x 1.25", "Passes": 2,
                                          "StartDepth": 10.0, "FinalDepth": 0.0, "LeadInOut": True})
    r = proj.compute()[-1]
    fit()
    panels.refresh_project_panel()
    p = rec["params"]
    step(7, "Fraisage de filet",
         "Stratégie « Fraisage de filets » sur l'avant-trou avec la fraise à fileter %s (T%d).\n\n"
         "Le nom « M8 x 1.25 » est résolu depuis les tables FreeCAD : diamètre majeur %.3f, mineur %.3f, "
         "pas %.2f mm, 2 passes hélicoïdales avec arcs d'entrée/sortie : %d commandes, Z de %.1f à %.1f.\n"
         "Un pas hors de la plage de l'outil (%.2f à %.2f mm) serait refusé.\n\n"
         "OK : contrôle et export du G-code."
         % (tm.name, tasm.output.tool_number, p["MajorDiameter"], p["MinorDiameter"], p["Pitch"],
            r["commands"], r["zmin"], r["zmax"], tm.geometry.pitch_min, tm.geometry.pitch))

    text, analysis, issues = proj.preview_gcode()
    out_dir = os.path.join(FreeCAD.getUserAppDataDir(), "CAM2027", "demo")
    os.makedirs(out_dir, exist_ok=True)
    fcstd = os.path.join(out_dir, "demo-plaque.FCStd")
    proj.save(fcstd)
    lines = "\n".join("- %s : %s" % (lvl, msg) for lvl, msg in issues[:8])
    step(8, "Export et contrôles",
         "Commande « Exporter le G-code » : postprocesseur GRBL, %d lignes, enveloppe X %.1f à %.1f, "
         "Y %.1f à %.1f, Z %.1f à %.1f, avance max %s.\n\nContrôles statiques :\n%s\n\n"
         "« non vérifiable » signifie que la donnée machine (courses, broche) n'est pas renseignée dans "
         "« Profil machine » : rien n'est inventé. L'export écrit le fichier .nc et une fiche de préparation ; "
         "aucun envoi automatique à CNCjs.\n\nProjet enregistré : %s\n\n"
         "Fin de la démonstration : FreeCAD reste ouvert, à vous de jouer."
         % (analysis["lines"], analysis["bbox"]["X"][0], analysis["bbox"]["X"][1], analysis["bbox"]["Y"][0],
            analysis["bbox"]["Y"][1], analysis["bbox"]["Z"][0], analysis["bbox"]["Z"][1], analysis["max_feed"],
            lines or "- aucun", fcstd))
    log("OK")


def main():
    try:
        run()
    except Exception:
        tb = traceback.format_exc()
        log("FAILED\n" + tb)
        QtWidgets.QMessageBox.critical(FreeCADGui.getMainWindow(), "CAM2027 — démonstration interrompue", tb)


# laisser la fenêtre principale se montrer avant la première boîte de dialogue
QtCore.QTimer.singleShot(1500, main)
