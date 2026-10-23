# SPDX-License-Identifier: LGPL-2.1-or-later
"""Passage des G-code d'essai dans le simulateur GRBL 1.1 de cncjs et comparaison avec le parcours CAM2027.

    python validate.py [dossier des essais]     (Python seul, FreeCAD inutile ; Node 20 ou plus requis)

Le simulateur (``grbl-simulator.js`` du dépôt cncjs) est lu en place, jamais modifié : ``grbl_check.js`` le charge
avec une horloge simulée. Emplacement : variable ``CAM2027_GRBL_SIM``, sinon
``C:\\Users\\damou\\Documents\\claude\\cncjs\\grbl-simulator\\grbl-simulator.js``.

Exige pour chaque fichier : 0 ``error:``, 0 ``ALARM``, et les positions de fin de chaque mouvement, la position
finale et l'enveloppe identiques à ± 0,01 mm à celles du parcours CAM2027 (``trials.json``, écrit par
``build.py``). Écrit ``validation.json`` et ``VALIDATION.md`` dans le dossier des essais ; code de retour 0 si
tout est bon. Le simulateur n'a pas d'axe A : les essais 4e axe se vérifient par ``export.verify`` seulement.
"""

import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

try:
    from . import reference as refmod
except ImportError:
    import reference as refmod  # noqa: E402

DEFAULT_SIM = r"C:\Users\damou\Documents\claude\cncjs\grbl-simulator\grbl-simulator.js"
OUTPUT = os.path.join(HERE, "output")


def simulator_path():
    return os.environ.get("CAM2027_GRBL_SIM") or DEFAULT_SIM


def node_executable():
    return shutil.which("node")


def node_version(node):
    out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
    return out


def run_simulator(nc_paths, out_json, sim=None, node=None):
    """Lance ``grbl_check.js`` ; retourne la liste des rapports (un par fichier)."""
    node = node or node_executable()
    cmd = [node, os.path.join(HERE, "grbl_check.js"), sim or simulator_path(), out_json] + list(nc_paths)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if not os.path.isfile(out_json):
        raise RuntimeError("grbl_check.js n'a rien écrit (code %d) : %s" % (proc.returncode, proc.stderr[-2000:]))
    with open(out_json, encoding="utf-8") as fp:
        return json.load(fp)


def validate(trials_dir=OUTPUT, sim=None, node=None):
    """Valide tous les essais de ``trials_dir`` ; retourne ``(ok, résumé par fichier)``."""
    with open(os.path.join(trials_dir, "trials.json"), encoding="utf-8") as fp:
        manifest = json.load(fp)
    trials = manifest["trials"]
    paths = [os.path.join(trials_dir, t["nc"]) for t in trials]
    raw_path = os.path.join(trials_dir, "validation-raw.json")
    reports = run_simulator(paths, raw_path, sim, node)
    os.remove(raw_path)
    summary = []
    ok = True
    for t, rep in zip(trials, reports):
        problems, worst, matched = refmod.compare(t["reference"], rep)
        item = {"id": t["id"], "lines": rep["lines"], "errors": rep["errors"], "alarms": rep["alarms"],
                "positions": matched, "final": rep["final"], "envelope": rep["envelope"],
                "probes": len(rep["probes"]), "pauses": rep["pauses"], "state": rep["state"],
                "max_difference_mm": worst, "problems": problems}
        item["ok"] = not rep["errors"] and not rep["alarms"] and not problems and rep["state"] == "Idle"
        ok = ok and item["ok"]
        summary.append(item)
    return ok, summary


def _fmt(v):
    return "—" if v is None else ("%.3f" % v).replace(".", ",")


def write_report(trials_dir, ok, summary, sim=None, node=None):
    node = node or node_executable()
    with open(os.path.join(trials_dir, "validation.json"), "w", encoding="utf-8", newline="\n") as fp:
        json.dump({"ok": ok, "simulator": os.path.basename(sim or simulator_path()),
                   "node": node_version(node) if node else None, "files": summary}, fp, indent=1, ensure_ascii=False)
    lines = ["# Validation dans le simulateur GRBL 1.1 (cncjs)", ""]
    lines.append("Résultat : **%s** — %d fichiers, simulateur `grbl-simulator.js` de cncjs (Grbl 1.1h), Node %s, "
                 "positions comparées au parcours CAM2027 à ± 0,01 mm." % (
                     "tout accepté" if ok else "ÉCHEC", len(summary), node_version(node) if node else "?"))
    lines.append("")
    lines.append("| Fichier | Lignes | error: | ALARM | Positions comparées | Écart max (mm) | Position finale X Y Z | Résultat |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for s in summary:
        fin = " ".join(_fmt(v) for v in s["final"]) if s["final"] else "—"
        lines.append("| %s | %d | %d | %d | %d | %s | %s | %s |" % (
            s["id"], s["lines"], len(s["errors"]), len(s["alarms"]), s["positions"], _fmt(s["max_difference_mm"]), fin,
            "OK" if s["ok"] else "; ".join(s["problems"] + [e["response"] for e in s["errors"] + s["alarms"]])))
    lines.append("")
    lines.append("Contrôles en plus de ceux du simulateur (qui accepte sans erreur G81, M6, les mots A, ne lit pas les "
                 "commentaires) : filtre de ligne de GRBL (commentaires, espaces), codes et lettres de GRBL 1.1, groupes "
                 "modaux, mots répétés, mots inutilisés, format des nombres, 80 caractères. Palpage : le simulateur touche une surface "
                 "fictive vers Z -3 et ignore `G10 L20` ; les positions qui dépendent d'un contact sont exclues des deux "
                 "côtés (axe inconnu jusqu'au mouvement absolu suivant). Non vérifié : courses et fins de course (profil "
                 "machine sans courses), axe A (absent du simulateur).")
    lines.append("")
    with open(os.path.join(trials_dir, "VALIDATION.md"), "w", encoding="utf-8", newline="\n") as fp:
        fp.write("\n".join(lines))


def main(argv):
    trials_dir = os.path.abspath(argv[1]) if len(argv) > 1 else OUTPUT
    node = node_executable()
    if node is None:
        print("Node introuvable : validation impossible")
        return 2
    if not os.path.isfile(simulator_path()):
        print("simulateur introuvable : %s (variable CAM2027_GRBL_SIM)" % simulator_path())
        return 2
    ok, summary = validate(trials_dir, node=node)
    write_report(trials_dir, ok, summary, node=node)
    for s in summary:
        print("%-24s %6d lignes  error:%d  ALARM:%d  positions %d  écart max %.4f mm  %s" % (
            s["id"], s["lines"], len(s["errors"]), len(s["alarms"]), s["positions"], s["max_difference_mm"],
            "OK" if s["ok"] else "ÉCHEC " + "; ".join(s["problems"])))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
