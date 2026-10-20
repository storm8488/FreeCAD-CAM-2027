# CAM2027 — Architecture et décisions

## Décisions structurantes (jalon A, 20 octobre 2026)

| Sujet | Décision | Raison |
|---|---|---|
| Base amont | Fork `storm8488/FreeCAD-CAM-2027` de `FreeCAD/FreeCAD`, branche `cam2027` créée depuis le tag **1.1.4** (commit `4fd3bf320d9566a27e60069fc8387448aaa3a094`, 28 sept. 2026, dernière stable). | 1.1.x est la stable courante ; son système d'outils (« assets ») est celui qui évoluera. 26.3rc2 (8–18 oct.) est une candidate, pas une base. `main` bouge chaque jour. |
| Exécution | Atelier Python `src/Mod/CAM2027` chargé par `-M` dans la **distribution officielle 1.0.2** installée ; compatible 1.1.x via `cam2027.compat`. | Aucun compilateur/CMake sur la machine : la compilation du fork est bloquée. L'atelier reste portable (pur Python/Qt). |
| Forme du produit | Atelier dédié dans FreeCAD d'abord ; application indépendante seulement après prototype chiffré. | CAM n'est pas une bibliothèque autonome : Job, Stock, ToolController, ops et posts dépendent du document FreeCAD. |
| Bibliothèque d'outils | Modèle propre (JSON `.cam2027tools`) séparé du ToolBit FreeCAD ; pont `bridge.py` vers ToolBit/ToolController au moment de créer une opération. | Le ToolBit FreeCAD n'a ni porte-outil, ni préréglages, ni données de sortie. Les champs suivent l'onglet « Coupant » de Fusion pour chaque type. |
| Valeurs d'opération | Copiées du préréglage à la création (ToolController dédié par opération) + registre JSON dans le document. | « Modifier un préréglage ne change pas une opération existante ». |
| Instantané | Chaque projet contient une copie complète de la bibliothèque (`CAM2027Project.LibrarySnapshot`). | Une modification de bibliothèque ne modifie jamais silencieusement un projet. |
| Unités | mm, mm/min, tr/min, m/min, degrés — fixes en interne ; chaînes avec unités acceptées en entrée. | Pas d'ambiguïté métrique/pouces dans les fichiers. |
| Angles | `tip_included_angle_deg` = angle inclus ; `taper_half_angle_deg` = demi-angle (angle de dépouille Fusion). | Convention explicite demandée. |
| Identifiants | UUID4 pour outils, porte-outils, assemblages, préréglages, machines ; références par id, jamais par nom. | Renommages et doublons sans casse. |
| Versions de données | `DATA_VERSION` + `migrate()` ; un fichier plus récent est refusé, un plus ancien migré. | Évolutions de schéma contrôlées. |
| Traduction | Chaînes anglaises dans le code, catalogue `i18n/fr.json`, langue suivant FreeCAD ou `CAM2027_LANG`. | `lrelease` absent de la distribution Windows ; conversion `.ts` possible plus tard. |
| 4e axe | Présent dans le modèle machine dès maintenant (`RotaryAxis`, A autour de X, tous champs `None` tant qu'inconnus) et dans les contrôles d'export (mots A/B/C). | Conception XYZA dès le départ, sans inventer les caractéristiques de la machine. |
| CNCjs | Export fichier + fiche ; aucun envoi, aucun mouvement. | Exigence de sécurité. |

## Environnement mesuré (20 oct. 2026)

- CPU i7-13700KF (16 c / 24 t), 64 Go RAM, GPU AMD Radeon RX 7900 XTX, 115 Go libres.
- FreeCAD 1.0.2 (révision 39319), Python 3.11, PySide2 5.15.15, OpenCamLib présent
  (`opencamlib/ocl.pyd`), 37 postprocesseurs dont `grbl`.
- Absents : MSVC, CMake, Ninja, 7-Zip, conda. `gh` authentifié (`storm8488`, scopes repo).

## Découpage des modules

```
src/Mod/CAM2027/
  Init.py, InitGui.py          enregistrement FreeCAD (console / GUI)
  cam2027/
    version.py                 __version__, DATA_VERSION, base épinglée
    compat.py                  version FreeCAD, API outils legacy/assets, OCL
    units.py, ids.py, i18n.py  unités, identifiants, traduction
    tools/
      model.py                 ToolDefinition, ToolGeometry, Holder, ToolAssembly,
                               OutputData, CuttingPreset (relations n/Vc, Vf/fz)
      library.py               ToolLibrary (JSON, recherche, favoris, édition groupée,
                               instantané, migration), bibliothèque de démarrage
      fusion_import.py         import .json/.tools Fusion + rapport de conversion
      bridge.py                -> ToolBit / ToolController FreeCAD (1.0 et 1.1)
    project/
      machine.py               MachineProfile + RotaryAxis (inconnu = None)
      docobjects.py            objet CAM2027Project (instantané, machine, registre)
      importers.py             STEP/STL/OBJ/SVG/DXF
      stock.py                 brut (Path.Main.Stock), repères G54.., brides visuelles
      operations.py            stratégies FreeCAD exposées + limites, résumé de parcours
      export.py                postprocesseur, analyse G-code, contrôles, fiche
      project.py               Project : create/open, import, job, opérations, export, save
    gui/
      qt.py, state.py          PySide2/6, bibliothèque et projet actifs
      preview.py               aperçu 2D coté de l'assemblage
      panels.py                panneau bibliothèque (3 onglets) + panneau projet
      commands.py              9 commandes (barre d'outils / menu)
    i18n/fr.json
  tests/                       unittest exécutés par FreeCADCmd ; gui_smoke.py pour FreeCAD.exe
```

Dépendances : `gui` → `project` → `tools` → (`units`, `ids`, `compat`). `tools/model.py`
et `tools/library.py` n'importent pas FreeCAD (testables hors FreeCAD).

## Séparation des données

| Domaine | Où | Format |
|---|---|---|
| Documents et géométrie | document FreeCAD (`Part::Feature`, clones du Job) | `.FCStd` |
| Outils et assemblages | `ToolLibrary` utilisateur + instantané projet | JSON |
| Matières, machines, montages | `MachineProfile` (projet), brides (`CAM2027Fixture`) | JSON / objets |
| Opérations et calculs | objets `Path::FeaturePython` du Job + registre `OperationRegistry` | document + JSON |
| Ordonnancement et caches | ordre du groupe `Operations` ; recalcul par FreeCAD (pas de cache propre) | — |
| Simulation et vérification | analyse statique du G-code (`export.verify`) — pas de simulation matière | — |
| Postprocesseurs | ceux de FreeCAD (`Path.Post`) | scripts Python |
| Interface | `cam2027.gui` | Qt |

## Compatibilité 1.0.2 / 1.1.4

`compat.tool_api()` renvoie `legacy` (1.0, `Path.Tool.Bit.Factory`) ou `assets` (1.1,
`Path.Tool.toolbit.ToolBit.from_dict` + `attach_to_doc`). Seul `bridge.create_toolbit`
en dépend. Les deux branches sont exécutées par la suite de tests (1.0.2 installée et
1.1.4 portable). Qt : PySide2 sur 1.0, PySide6 sur 1.1 (`gui/qt.py`, `exec_dialog`).

## Intégration amont

Le fork ne modifie aucun fichier de FreeCAD : tout vit dans `src/Mod/CAM2027`, `docs/cam2027`
et `scripts/`. Mettre à jour la base = `git fetch upstream && git merge <tag>` sans conflit
attendu.
