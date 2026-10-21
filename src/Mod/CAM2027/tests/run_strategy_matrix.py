# SPDX-License-Identifier: LGPL-2.1-or-later
"""Matrice stratégies × pièces : chaque case dans son propre CAM2027.exe, avec une limite de temps.

    python src\\Mod\\CAM2027\\tests\\run_strategy_matrix.py [--exe C:\\...\\CAM2027.exe] [--timeout 240]
                                                         [--files plate;dome;C:\\...\\piece.stl] [--out dossier]

Une case est en défaut si : plantage (processus mort sans résultat), dépassement du temps (interface figée),
exception, opération en échec, refus sans message, entaille ou collision. Rapport : ``matrix.txt`` et
``matrix.json`` dans le dossier de sortie.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STRATEGIES = ["profile", "pocket", "pocket2d", "adaptive", "drilling", "millface", "engrave", "vcarve", "helix",
              "slot", "rough3d", "surface3d", "waterline", "threadmill", "chamfer"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=os.path.join(os.environ["USERPROFILE"], "CAM2027", "bin", "CAM2027.exe"))
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--files", default="plate;dome")
    ap.add_argument("--strategies", default=",".join(STRATEGIES))
    ap.add_argument("--out", default=os.path.join(tempfile.gettempdir(), "cam2027-matrix"))
    ap.add_argument("--jobs", type=int, default=1, help="cases run at the same time (each in its own CAM2027.exe)")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    script = os.path.join(os.path.dirname(args.exe), "..", "Mod", "CAM2027", "tests", "strategy_matrix_run.py")
    cases = [(f, s) for f in [x for x in args.files.split(";") if x] for s in args.strategies.split(",")]

    def run_case(case):
        f, s = case
        tag = "%s__%s" % (os.path.splitext(os.path.basename(f))[0][:20], s)
        out = os.path.join(args.out, tag + ".json")
        for p in (out, out + ".fault.txt"):
            if os.path.exists(p):
                os.remove(p)
        home = tempfile.mkdtemp(prefix="cam2027-mxhome-")
        env = dict(os.environ, FREECAD_USER_HOME=home, CAM2027_LANG="fr", CAM2027_MATRIX_FILE=f,
                   CAM2027_MATRIX_STRATEGY=s, CAM2027_MATRIX_OUT=out)
        t0 = time.time()
        try:
            proc = subprocess.run([args.exe, script], env=env, timeout=args.timeout,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            code = proc.returncode
            timed_out = False
        except subprocess.TimeoutExpired:  # subprocess.run tue le processus figé
            code, timed_out = None, True
        dt = time.time() - t0
        res = json.load(open(out, encoding="utf-8")) if os.path.isfile(out) else {}
        fault = open(out + ".fault.txt", encoding="utf-8", errors="replace").read() if os.path.isfile(out + ".fault.txt") else ""
        outcome = res.get("outcome")
        if timed_out:
            outcome = "TIMEOUT (last step: %s)" % (res.get("steps") or [["start"]])[-1][0]
        elif outcome is None:
            outcome = "CRASH (exit %s)" % code
        problem = None
        if timed_out or outcome.startswith("CRASH") or outcome in ("exception", "failed", "refused-silently", "no-job"):
            problem = outcome
        check = res.get("check") or {}
        if check.get("gouge_max", 0) > 0.05:
            problem = "gouge %.2f mm" % check["gouge_max"]
        events = sorted(set(check.get("events") or []))
        if events == ["undrilled"]:  # filetage seul : le trou n'est pas percé, c'est le défaut attendu
            events = []
        if events:
            problem = (problem + "; " if problem else "") + "collisions %s" % events
        row = {"file": f, "strategy": s, "outcome": outcome, "seconds": round(dt, 1), "problem": problem,
               "tool": res.get("tool"), "messages": [m[1][:160] for m in res.get("messages", [])],
               "summary": res.get("summary"), "check": check, "traceback": res.get("traceback"),
               "steps": res.get("steps"),
               "fault": fault[:1500] if "Fatal" in fault or "exception" in fault else ""}
        print("%-28s %-11s %-34s %6.1fs %s" % (os.path.basename(f)[:28], s, outcome[:34], dt, problem or ""))
        sys.stdout.flush()
        return row

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:  # chaque case : son propre CAM2027.exe
        rows = list(pool.map(run_case, cases))
    json.dump(rows, open(os.path.join(args.out, "matrix.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    lines = ["%-28s %-11s %-34s %6.1fs %s | %s" % (os.path.basename(r["file"])[:28], r["strategy"], r["outcome"][:34],
                                                    r["seconds"], r["problem"] or "ok", " / ".join(r["messages"])[:200])
             for r in rows]
    bad = [r for r in rows if r["problem"]]
    lines.append("%d case(s), %d problem(s)" % (len(rows), len(bad)))
    open(os.path.join(args.out, "matrix.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(lines[-1])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
