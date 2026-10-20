# Référence fonctionnelle — Autodesk Fusion (Manufacture + Manufacturing Extension) et Vectric Aspire 12.5

Inventaire factuel établi le 2026-10-20 à partir de la documentation officielle en ligne (help.autodesk.com « Fusion-CAM », docs.vectric.com V12.5). Les éléments non confirmés par une source officielle sont marqués **non vérifié**. Pas de langage marketing.

Légende : **[ME]** = documenté comme faisant partie de la Fusion Manufacturing Extension (payante) ; sans marque = inclus dans Fusion de base ou non précisé par la doc.

---

## 1. Fusion — Stratégies de fraisage 2D

Source : https://help.autodesk.com/cloudhelp/ENU/Fusion-CAM/files/MFG-2D-MILLING-OVERVIEW.htm (liste) ; descriptions : https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/cam_OperationStrategyTypes.htm

| Stratégie (nom actuel) | Fichier doc | Description |
|---|---|---|
| Face | 2D-FACE-READ.htm | Surfaçage rapide du brut |
| 2D Adaptive Roughing (ex-2D Adaptive Clearing) | 2D-ADAPTIVE-READ.htm | Ébauche 2D à engagement constant, sans changements brusques de direction |
| 2D Offset Roughing (ex-2D Pocket) | 2D-POCKET-READ.htm | Ébauche par passes parallèles (offset) à la géométrie |
| 2D Contour | 2D-CONTOUR-READ.htm | Contournage de contours ouverts ou fermés, à différents Z |
| Slot | 2D-SLOT-READ.htm | Rainure en suivant la ligne médiane |
| Trace | 2D-TRACE-READ.htm | Suivi de contours à Z variable, avec ou sans compensation gauche/droite |
| Thread | 2D-THREAD-READ.htm | Fraisage de filetage sur poches/bossages cylindriques |
| Bore | 2D-BORE-READ.htm | Alésage hélicoïdal par sélection directe de cylindres |
| Circular | 2D-CIRCULAR-READ.htm | Fraisage de poches/bossages cylindriques |
| Engrave | 2D-ENGRAVE-READ.htm | Gravure de contours avec outil en V (parois chanfreinées) |
| 2D Chamfer | 2D-CHAMFER-READ.htm | Chanfrein le long de contours |

Perçage (section séparée, https://help.autodesk.com/cloudhelp/ENU/Fusion-CAM/files/MFG-DRILLING-OVERVIEW.htm) :
- **Drill** : sélection et tri automatiques des trous, un diamètre à la fois ; géométrie par faces (associatif), points, plage de diamètres, ou « trous restants d'une opération ». Options : Select Same Diameter, Check for Occlusions, Containment Boundary, Auto-Merge Hole Segments, Order by Depth, Order, Reverse Order.
- Cycles (https://help.autodesk.com/cloudhelp/ENU/Fusion-CAM/files/MFG-REF-DRILL-CMD.htm) : Drilling (rapid out), Counterboring (dwell + rapid out), Chip breaking (retrait partiel), Deep drilling (retrait complet), Break through, Guided deep drilling (gun drilling), Tapping / Left / Right tapping, Tapping with chip breaking, Reaming (feed out), Boring (dwell + feed out), Stop boring, Fine boring (shift), Back-boring, Circular pocket milling, Bore milling, Thread milling, Custom.
- **Hole Recognition [ME]** (https://help.autodesk.com/cloudhelp/ENU/Fusion-CAM/files/LP-READ-IRONHOLERECOGNITION.htm) : analyse du modèle pour détecter les cylindres (tout plan), assignation d'une Action par trou (Spot drilling, Drilling, Counter Boring, Boring, Tapping, Reaming, ou combinaison) modifiable, plusieurs opérations par trou, option Include Partial Holes, regroupement par dimensions identiques.

Autres opérations 2D du moteur : **Jet2D** (découpe jet d'eau / laser / plasma) — source API ci-dessus.

---

## 2. Fusion — Stratégies de fraisage 3D

Source : https://help.autodesk.com/cloudhelp/ENU/Fusion-CAM/files/MFG-3D-MILLING-OVERVIEW.htm (21 entrées). Les ébauches sont « stock-aware » (tiennent compte du brut), les finitions non.

| Stratégie | Fichier doc | Description / notes |
|---|---|---|
| 3D Adaptive Roughing (ex-Adaptive Clearing) | 3D-ADAPTIVE-READ.htm | Ébauche à engagement constant ; Optimal Load ; style Adaptive (stepover variable, avalant seulement) ou Offset |
| 3D Offset Roughing (ex-Pocket Clearing) | 3D-POCKET-READ.htm | Ébauche par niveaux Z, stepover XY constant, avalant + opposition |
| 3+2 Roughing | MFG-3-PLUS-2-READ.htm | Ébauche multi-orientations indexées |
| Steep and Shallow **[ME]** | 3D-STEEP-AND-SHALLOW-READ.htm | Semi-finition/finition : zones raides (passes Contour) + zones plates (passes Scallop/Parallel) en une opération ; paramètres séparés raide/plat ; Avoid Flat Areas ; options 5 axes et évitement de collision (MFG-REF-3D-STEEP-SHALLOW-5X.htm) |
| Flat | 3D-FLAT-READ.htm | Détection automatique des zones planes perpendiculaires à l'outil ; types Offset / Parallel / Profile ; Multiple Depths |
| Parallel | 3D-PARALLEL-READ.htm | Passes parallèles en XY suivant la surface en Z |
| Scallop | 3D-SCALLOP-READ.htm | Passes à distance constante le long de la surface (offset 3D) |
| Contour | 3D-CONTOUR-READ.htm | Finition des parois raides à Z constant (modes multi-axes via [ME]) |
| Ramp | 3D-RAMP-READ.htm | Descente en rampe le long des parois raides |
| Pencil | 3D-PENCIL-READ.htm | Reprise des angles intérieurs / petits congés |
| Horizontal | 3D-HORIZONTAL-READ.htm | Détection des zones planes et passes offset (ancêtre de Flat) |
| Spiral | 3D-SPIRAL-READ.htm | Spirale depuis un centre dans une limite |
| Radial | 3D-RADIAL-READ.htm | Passes rayonnantes depuis un centre, arrêt possible avant le centre |
| Morphed Spiral | 3D-MORPHED-SPIRAL-READ.htm | Spirale morphée sur la limite sélectionnée |
| Project | 3D-PROJECT-READ.htm | Projection de contours sur la surface (centre outil) |
| Blend | MFG-MULTI-AXIS-BLEND-READ.htm | Passes entre courbes de départ/fin (+ intermédiaires) sur surfaces guides ; contre-dépouilles possibles en 3 axes avec outils lollipop/dovetail ; statut ME non précisé |
| Morph | 3D-MORPH-READ.htm | Passes entre deux chaînes de courbes ou plus ; statut ME non précisé |
| Corner **[ME]** | 3D-CORNER-READ.htm | Reprise des zones laissées par un outil de référence (Reference Tool, Detection Limit, Threshold Angle) |
| Flow | 3D-FLOW-V2-OVERVIEW.htm | Suivi des isocourbes U/V d'une face ; modes multi-axes via [ME] |
| Deburr **[ME]** | MFG-MULTI-AXIS-DEBURR-READ.htm | Ébavurage : chanfrein ou congé sur arêtes, 3/4/5 axes |
| Geodesic | MFG-MULTI-AXIS-GEODESIC-READ.htm | Finition de surfaces libres et contre-dépouilles, passes Blend ou Scallop ; 3/4/5 axes ([ME] requis pour 4/5 axes) |

Rest machining (reprise) — présent sur les opérations 3D (réf. 3D Adaptive : https://help.autodesk.com/cloudhelp/ENU/Fusion-CAM/files/GUID09E44604-DAD8-47D6-ADC6-C100869DE724.htm) : case Rest Machining, Source = From previous operation(s) / From file / From bodies / From setup stock, Ignore Stock Less Than. Report du brut entre montages : Setup > Stock > Mode « From Preceding Setup » + « Continue Rest Machining » (https://help.autodesk.com/cloudhelp/ENU/Fusion-CAM/files/MFG-CONTINUE-REST-MACHINING.htm). Le moteur expose aussi une stratégie « RestFinishing » (source API).

Onglets communs (réf. 3D Adaptive) : Tool (outil, coolant, feeds & speeds, Shaft & Holder : Disabled / Pull away / Trimmed / Detect tool length / Fail on collision) ; Geometry (Machining Boundary : Bounding box / Silhouette / Selection / None ; Tool Containment Inside / Center / Outside ; Additional Offset ; Tool Orientation ; Model) ; Heights (Clearance / Retract / Top / Bottom) ; Passes (Tolerance, Optimal Load, Direction, Stepdown, Fine Stepdown, Stock to Leave radial/axial, Smoothing, Feed Optimization…) ; Linking (Retraction Policy, Stay-Down, leads, Ramp Type Predrill/Plunge/Helix, Entry Positions…).

---

## 3. Fusion — Multi-axes

Source : https://help.autodesk.com/cloudhelp/ENU/Fusion-CAM/files/MFG-MULTI-AXIS-MILLING-OVERVIEW.htm

Inclus sans extension : réglages d'orientation d'outil (3+2) et le toolpath « 4th axis wrap » (enroulement 4e axe).

Accessibles via **[ME]** (liste de la page) : 3D Contour (modes multi-axes), 3D Flow, Swarf, Multi-Axis Contour, Multi-Axis Roughing, Rotary, Rotary Roughing, Rotary Contour, Multi-Axis Finishing, réglages 5 axes / évitement de collision, géométrie de dégagement 4-5 axes.

| Stratégie | Fichier doc | Description |
|---|---|---|
| Swarf **[ME]** | MFG-MULTI-AXIS-SWARF.htm | Usinage par le flanc de l'outil (parois inclinées) ; Drive Mode contours ou surfaces ; Tool Offset |
| Advanced Swarf | MFG-MULTI-AXIS-ADV-SWARF.htm | Flank milling avec courbes guides haut/bas, toute la longueur de coupe |
| Multi-Axis Contour **[ME]** | MFG-MULTI-AXIS-CONTOUR-READ.htm | Suivi de courbes 3D (arêtes ou projetées), outil normal à la surface par défaut, contrôles d'inclinaison |
| Multi-Axis Roughing | MFG-MULTI-AXIS-CLEARING-OVERVIEW.htm | Ébauche multi-axes |
| Multi-Axis Finishing | MFG-MULTI-AXIS-FINISHING.htm | Finition multi-axes |
| Rotary Parallel **[ME]** | MFG-MULTI-AXIS-ROTARY.htm | Finition 4e axe continu ; styles Spiral / Line / Circular ; plage angulaire limitable ; Tool Offset |
| Rotary Roughing | MFG-MULTI-AXIS-ROTARY-POCKET-READ.htm | Ébauche rotative |
| Rotary Contour | MFG-MULTI-AXIS-ROTARY-CONTOUR-READ.htm | Contournage rotatif |

---

## 4. Fusion — Ce qu'ajoute la Manufacturing Extension (confirmé par les pages d'aide)

- Stratégies : Steep and Shallow, Corner, Deburr, Rotary (Parallel/Roughing/Contour), Swarf, Multi-Axis Contour/Roughing/Finishing, modes multi-axes de Contour et Flow, Geodesic 4/5 axes, 3+2 avec évitement de collision (sources sections 2-3).
- Hole Recognition (perçage automatique multi-outils) — section 1.
- Modifications de parcours (https://help.autodesk.com/cloudhelp/ENU/Fusion-CAM/files/MFG-TOOLPATH-MODIFY-OVERVIEW.htm, « part of an extension ») : Toolpath trimming (polygone / plan / limite, option garder les deux côtés, seuls leads/links recalculés), Delete passes or segments, Replace tool, Tool entry positions, Leads and links modification (par segment, groupe ou parcours entier, sans recalcul), Move Start Points.
- Inspection / palpage (https://help.autodesk.com/cloudhelp/ENU/Fusion-CAM/files/MFG-PART-ALIGNMENT-OVERVIEW.htm) : Part Alignment (Inspect Surface → post → exécution sur machine → import résultats → correction WCS, transformation 3/4/5 axes, scatter plot avant/après) ; Live Part Alignment (via Machine Connector, translation ≤ 3 axes). Probe WCS reste inclus dans Fusion de base ; Probe Geometry / Surface Inspection font partie de l'extension (source : page marketing, **non vérifié** sur l'aide).
- Nesting (https://help.autodesk.com/cloudhelp/ENU/Fusion-CAM/files/NST-GET-STARTED.htm) : Nest Preparation, Component Sources, Nest Study (création, édition, comparaison), nests multi-feuilles avec matériaux et quantités, pièces tôle et non-tôle, export DXF, Manufacturing Models pour parcours/NC, rapports. Sans extension : seulement Compare et consultation de rapports.
- Additive : l'extension regroupe les anciennes extensions « Nesting & Fabrication » et « Additive Build » (source : page produit Autodesk, **non vérifié** dans l'aide).
- Rest machining entre montages (Continue Rest Machining) : page d'aide sans mention d'extension → considéré inclus.

---

## 5. Fusion — Modèle de données de la bibliothèque d'outils

Source : https://help.autodesk.com/cloudhelp/ENU/Fusion-CAM/files/GUID-A0197982-0082-45AF-B848-8D62CAF57C49.htm (Milling or Hole Making tool reference) ; https://help.autodesk.com/cloudhelp/ENU/Fusion-CAM/files/MFG-TOOL-LIBRARY-OVERVIEW.htm

Catégories d'outils : Milling, Turning, Cutting (jet d'eau / laser / plasma), Touch Probes, Holders. Bibliothèques : Documents, Fusion Library (par procédé et unité), Vendor, Hub Libraries, Cloud, Local (outils personnalisés créables dans Documents/Local/Cloud). Expressions possibles dans les champs (MFG-REF-LIB-EXPRESSION.htm).

Onglet **General** : Description, Vendor, Product id, Product Link.

Onglet **Cutter** : Type (ex. flat, ball, bull nose, chamfer, tapered… ; liste complète : MFG-TOOL-LIBRARY-SUPPORTED-TOOLS.htm, non relue), Unit (mm / inch), Clockwise spindle rotation, Number of flutes, Material (Unspecified, HSS, Ti Coated, Carbide, Ceramic). Géométrie : Diameter, Shaft diameter, Overall length, Length below holder, Shoulder length, Flute length, Corner radius, Tip angle, Tip diameter, Tip length, Taper angle (= demi-angle), Included angle (= 2 × taper), Thread pitch, Number of teeth, Thread profile angle. Pas de champ « Body length » séparé dans ce formulaire (le post-processeur expose `bodyLength`, voir ci-dessous). Champ « Coating » : **non vérifié** (absent de la page de référence).

Onglet **Shaft** : segments empilés entre outil et porte-outil ; par segment : Height, Upper diameter, Lower diameter.

Onglet **Holder** : optionnel (visualisation + détection de collision) ; Holder description, product ID, product link, vendor ; géométrie par segments (même structure hauteur / diamètres, onglet « Holder Geometry »).

Onglet **Cutting data** (plusieurs presets par outil, MFG-CREATE-TOOL-PRESET.htm) :
- Speed : Spindle speed (RPM), Surface speed (m/min ou ft/min), Ramp spindle speed.
- Feedrates : Cutting feedrate, Feed per tooth, Lead-in feedrate, Lead-out feedrate, Ramp feedrate.
- Vertical feedrates : Plunge feedrate, Feed per revolution.
- Passes and linking : Use stepdown + Stepdown, Use stepover + Stepover, Coolant (options dépendant de la machine).
- « Retract feedrate » n'apparaît pas dans la page de référence outil (il existe au niveau opération) — **non vérifié** côté preset.

Onglet **Post processor** : Number (numéro d'outil), Length offset, Diameter offset, Turret, Comment, Manual tool change, Live Tool, Break control.

Propriétés vues par les post-processeurs (https://cam.autodesk.com/posts/reference/classTool.html) : number, turret, diameterOffset, lengthOffset, compensationOffset, holderNumber, manualToolChange, breakControl, liveTool, spindleRPM, rampingSpindleRPM, surfaceSpeed, maximumSpindleSpeed, threadPitch, numberOfFlutes, diameter, cornerRadius, taperAngle, fluteLength, shoulderLength, shaftDiameter, bodyLength, overallLength, shaft, holder (holderDiameter, holderTipDiameter, holderLength), coolant, material, type, unit, comment, vendor, productId, + champs tournage et jet (jetDiameter, kerfWidth, cutHeight, pierceHeight, pressure, pierceTime, abrasiveFlowRate, piercePower, cutPower, assistGas).

### Formats d'import/export (https://help.autodesk.com/cloudhelp/ENU/Fusion-CAM/files/MFG-REF-LIBRARY-EXP-IMP.htm)

| Format | Import | Export | Note |
|---|---|---|---|
| .tools | oui | oui (défaut) | version zippée du .json, même contenu |
| .json | oui | oui | format natif Fusion |
| .hsmlib | oui | oui | échange Inventor HSM / HSMWorks |
| .csv | oui | oui | éditable tableur ; les expressions ne sont pas exportées |
| .zip (GTC package) | oui | non | Generic Tool Catalog |
| .p21 | oui | non | fichier paramètres P21 |

### Structure du JSON (**non vérifié** — reconstituée d'exports réels, aucune spec publique officielle ; à confirmer sur un export)

```
{ "version": <int>, "data": [ <outil>, ... ] }
outil : { "type": "flat end mill" | "ball end mill" | "bull nose end mill" | "chamfer mill" | "face mill" |
          "slot mill" | "radius mill" | "dovetail mill" | "tapered mill" | "lollipop mill" | "thread mill" |
          "form mill" | "drill" | "spot drill" | "center drill" | "counter bore" | "countersink" | "reamer" |
          "boring bar" | "tap right hand" | "tap left hand" | "probe" | ...,
          "guid", "description", "vendor", "product-id", "product-link", "unit": "millimeters"|"inches",
          "BMC": matière (ex. "carbide","hss"), "GRADE",
          "geometry": { "DC": diamètre, "SFDM": diam. queue, "OAL": longueur totale, "LB": long. sous porte-outil,
                        "LCF": long. de coupe, "shoulder-length", "RE": rayon de coin, "TA": angle de pointe,
                        "SIG": angle de cône, "tip-diameter", "tip-length", "NOF": nb de dents, "NT": nb dents filetage,
                        "TP": pas, "CSP": rotation horaire, "HAND": true },
          "start-values": { "presets": [ { "guid", "name", "description", "n": vitesse broche, "n_ramp",
                        "v_c": vitesse de coupe, "v_f": avance de coupe, "f_z": avance/dent, "f_n": avance/tour,
                        "v_f_leadIn", "v_f_leadOut", "v_f_plunge", "v_f_ramp", "v_f_retract",
                        "use-stepdown", "stepdown", "use-stepover", "stepover", "tool-coolant": "disabled"|"flood"|... } ] },
          "post-process": { "number", "length-offset", "diameter-offset", "turret", "comment",
                            "manual-tool-change", "live", "break-control" },
          "shaft":  { "type": "shaft",  "segments": [ { "height", "upper", "lower" } ] },
          "holder": { "type": "holder", "guid", "description", "vendor", "product-id", "product-link", "unit",
                      "segments": [ { "height", "upper", "lower" } ] } }
```
Confirmé indirectement : la source RobbJack (https://robbjack.com/downloads/fusion-360) décrit les presets par n, v_c, f_z, v_f + plunge/ramp ; l'API Fusion expose `Tool.toJson()` / `createFromJson()` (https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/cam_Tool.htm).

---

## 6. Vectric Aspire 12.5 — Outils de dessin (Design)

Source : table des matières https://docs.vectric.com/docs/V12.5/Aspire/ENU/Help/page/single-page/index.html et pages « form/… ».

- Création : Draw Line/Polyline, Arc (3 points, centre-début-fin), Circle, Ellipse, Rectangle, Polygon, Star, Freehand, Create Text (texte / texte dans boîte, police, alignement, ancrage, crénage, interligne, arc), Text On A Curve, Convert text to Curves, Dimensions (éditables par poignées en 12.5), Create Fillets.
- Sélection / transformation : Interactive Selection Mode, Object/Vector Selection, Transform Mode, Move, Rotate, Mirror, Set Size, Alignment Tools, Distort Object, Smart part selection (clic droit : tout ce qui est dans une limite, 12.5).
- Nœuds / édition : Node Editing Mode, Join Open Vectors (ligne droite / courbe lisse / déplacement des extrémités), Extend, Trim, Interactive Vector Trim, Offset Vectors, Fit Curves To Vectors, Weld, Vector Validator, Vector Unwrapper.
- Booléens / limites : Overlap (union), Subtract, Vector Boundary, Vector Texture.
- Copies / disposition : Circular Copy, Array Copy, Copy Along Vectors, Nest Parts (12.5 : nesting sur feuille choisie), Plate Production (12.5 : une feuille par plaque).
- Organisation : Group/Ungroup, Layer Management (12.5 : duplication, glisser-déposer, filtrage des calques vides), Sheets (12.5 : duplication avec contenu), Clipart Tab.
- Bitmaps : Import Bitmap/Vectors (12.5 : WebP), Trace Bitmap, Edit Picture, Crop Bitmap, fondu couleur conservée.
- Vue 3D : dessin, édition de nœuds, texte, fillet, trim directement en vue 3D ; grille / guides en 3D ; mode orthographique (12.0).

## 7. Aspire 12.5 — Parcours 2D / 2,5D

Sources : pages form/… listées ; ex. https://docs.vectric.com/docs/V12.5/Aspire/ENU/Help/form/uiProfileMachineForm/index.html

| Parcours | Résumé des options (doc V12.5) |
|---|---|
| 2D Profile | extérieur / intérieur / sur le vecteur (gauche/droite pour vecteurs ouverts) ; Start/Cut Depth ; passes multiples (variation ≤ 15 % ou Maintain Exact Step Depth, édition manuelle, dernière passe par épaisseur restante) ; avalant/opposition ; Allowance, Last pass allowance ; Tabs 2D ou 3D triangulaires ; rampes Smooth / Zig Zag / Spiral ; leads droits ou circulaires + overcut ; ordre (sélection, G→D, B→H, grille) ; points de départ ; coins (Sharp external, Sharp internal 3D avec V-bit) ; projection sur modèle 3D |
| Pocketing | stratégies Offset ou Raster (angle 0–90°) ; passe de profil First/Last/None ; avalant/opposition ; Pocket allowance ; plusieurs outils (Larger Area Clearance) ; rampes ; profondeurs par passes ; projection 3D ; 12.5 : moins de retraits entre passes |
| Drilling | Start/Cut Depth ; peck drilling (Pass Depth de la base d'outils, Retract Gap fixe ou relatif) ; Dwell (si post le supporte) ; centres des vecteurs fermés ; ordre conservé ou optimisé ; Drill Bank (Advanced Machining Module) ; 12.5 : visualisation du peck |
| Quick Engraving | Depth/Pressure (diamant à ressort) ; Outline ou Fill (3 motifs) ; Nose cone ; Number of Passes ; sortie immédiate |
| V-Carve / Engraving | V-bit à angle constant, profondeur variable ; Start Depth ; Flat Depth (fond plat) ; Use Clearance Tools (end mill / ball nose / engraving) |
| Photo V-Carve | Start Depth, Max Carving Depth, Stepover Retract ; Raster, Hatch ou Selected Vectors ; Line Spacing / Angle |
| Sketch Carving (12.0) / Laser Sketch Engraving (12.5, module laser) | gravure « croquis » depuis bitmap ou modèle 3D ; Flat Depth ; outils ball/tapered/V/engraving ; Line Thickness ; 12.5 : aperçu 3D |
| Prism Carving | Start Depth ; Prism Depth ; Set Depth for Full Prism (évite le sommet tronqué) |
| Moulding | profil ouvert extrudé le long d'un rail ; Vary Stepover ; Skip Flat Regions ; Larger Area Clearance Tool ; Create Sharp Corners ; Boundary Offset |
| Fluting | profondeur variable le long de vecteurs ; Start/Flute Depth ; Ramp over complete length / at Start / Start and End, Linear ou Smooth |
| Texture | texture aléatoire dans vecteurs ou motif depuis vecteurs ; Max Cut Depth, Min Depth %, Max/Min Cut Length, Max Overlap %, Variation ; Stepover, Angle, Boundary Offset |
| Chamfer | outil angulaire (angle de l'outil) ou boule (angle manuel, passes fines) |
| Thread Milling | filetage hélicoïdal interne/externe, outil mono/multi-points ; pitch prédéfini ou saisi ; Fit tolerance ; sens filet et de coupe |
| Inlay | mâle Straight ou Stepped (Step Depth/Width) ; femelle Pocket ou Hole ; Allowance de jeu |
| VCarve Inlay (12.0) | génère Pocket + Plug (même V-bit) ; Pocket Depth, Glue Gap, Surface Clearance ; outils de dégagement ; feuille de destination du plug |
| Merged Toolpath | fusion des parcours visibles, ordre optimisé, Merge By Part, vitesses ajustées |
| Array Copy Toolpath | grille lignes/colonnes, Offset ou Gap, Minimize Tool Changes |
| Laser Cut – Fill, Laser Picture (module laser) | kerf, remplissage hachures ; gravure photo par puissance |
| Gadgets | Drag Knife, Keyhole, Create Rounding Toolpath (rotatif), Wrapped Fluting Layout |
| Rotary | job rotatif (Job Setup – Rotary : longueur, diamètre, Z zéro sur axe ou surface, orientation X/Y) ; enroulement des parcours plats autour du cylindre, vue wrapped/flat ; post-processeur rotatif requis (formulation « wrap » vérifiée sur doc V9.0, page V12.5 Material Setup – Rotary confirme diamètre / Z-Zero / position du modèle) |
| Outils transverses | Toolpath Tiling Manager, Toolpath Templates, Toolpath Tabs, Vector Selector, Estimating Machining Times (12.5 : accélération), Preview Toolpaths (12.5 : couleur de surface), Save Toolpaths (fichiers séparés ou ATC), Keep-out zones (12.0) |

« Area clearance » n'est pas un parcours autonome : c'est l'option « Larger Area Clearance Tool / Use Clearance Tools » des parcours Pocket, V-Carve, Moulding, VCarve Inlay.

## 8. Aspire 12.5 — 3D : parcours et modélisation

Sources : https://docs.vectric.com/docs/V12.5/Aspire/ENU/Help/form/Rough%20Machining%20Toolpath/index.html ; …/form/Finish%20Machining%20Toolpath/index.html ; …/form/component-tree/index.html

- **3D Rough** : Z Level (poches 2D par niveau) ou 3D Raster ; direction Along X / Along Y, Reverse step direction (Z Level) ; profil First/Last/None ; Machining allowance ; Boundary offset ; limite Model Boundary / Material Boundary / Selected Vector(s) / Selected Level.
- **3D Finish** : Offset (avalant/opposition) ou Raster (angle 0–90°) ; mêmes limites + Boundary Offset ; Stepover (≈ 8–12 % du diamètre conseillé) ; Stepover Retract (Offset) ; **reprise** : sélection de plusieurs outils, chacun usine ce que le précédent n'a pas atteint (Minimum Detail, Boundary Offset). Pas de stratégie « Rest » séparée.
- **Composants / relief** : arbre de composants combiné du bas vers le haut ; modes de combinaison Add, Subtract, Merge (garde le plus haut), Low (garde le plus bas), Multiply, Group ; niveaux (Levels) ; propriétés Total/Shape/Base Height, Fade, Tilt, Appearance. Outils : Create Shape (Flat, Round, Angled, Smooth, Custom ; 12.0), Two Rail Sweep, Extrude and Weave, Turn and Spin, Slice Model, 3D Segmenting, Scale Model Height, Offset Model, Add Draft, Sculpting, Smooth, Emboss, Baking (12.5 : menu contextuel), Level Clipping, Replace Below, Create Zero Plane, Create Texture Area, Create Cross Section Vector, Component from Bitmap / from Visible Model, Clearing/Splitting Components, Export STL/OBJ.
- **Double face** : Job Setup – Double Sided (Flip Direction, Z zéro, Zero off same side), bascule Top/Bottom, Multi Sided View, import 3D avec « Create both sides », Scale Model Height sur les deux faces.
- **Rotatif** : Job Setup – Rotary ; import STL en job rotatif (Orientate 3D Model Rotary, 12.5 : gizmo d'orientation) ; guides « Modelling 3D Rotary Projects » (zero plane cone, Two Rail Sweep, Vector Unwrapper, level-wrapping) ; conseil doc : parcours 3D séparés pour des diamètres très différents (distorsion du wrap).

## 9. Aspire — Nouveautés 12.0 et 12.5 (résumé)

Sources : https://docs.vectric.com/docs/V12.0/Aspire/ENU/Help/page/whats-new ; https://docs.vectric.com/docs/V12.5/Aspire/ENU/Help/page/whats-new/index.html

- 12.0 : nouvelle interface (DPI, panneau vecteurs+composants unifié), vue orthographique, contrôle de vue 3D, barre de visibilité, import unifié 2D, Sketch Carving, VCarve Inlay, Keep-out zones, 4 nouveaux outils de forme 3D (Angled, Rounded, Smooth, Flat Plane), coupe 3D → vecteurs, dessin et vecteurs en vue 3D.
- 12.5 : aperçu 3D du Sketch Carving, couleur de surface en prévisualisation, pochage avec moins de retraits, estimation de temps avec accélération, transfert de parcours entre feuilles, Laser Sketch Engraving, statut visuel des parcours, groupes de parcours liés aux feuilles, nom d'outil dans les noms de parcours multi-outils, visualisation du peck ; édition de nœuds / texte / fillet / trim en vue 3D, dimensions éditables, sélection intelligente, duplication de feuille, polyline 4 modes de saisie, nesting sur feuille choisie, plaques sur feuilles séparées, WebP, grille/guides 3D, menus redimensionnables, gizmo d'orientation rotatif, calques (dupliquer, glisser, filtrer), baking par menu contextuel. 12.5 gratuite pour les détenteurs de 12.

---

## 10. Points non vérifiés / limites de cet inventaire

- Schéma JSON de la bibliothèque Fusion (section 5) : non documenté officiellement ; clés reconstituées, à valider sur un export `.json` réel.
- Champ « Coating » et « Body length » dans le formulaire outil Fusion : non trouvés dans la page de référence.
- Statut Manufacturing Extension de Blend, Morph, Multi-Axis Roughing/Finishing, Advanced Swarf : non explicité page par page (les pages de synthèse les rattachent à l'extension pour les modes multi-axes).
- Probing géométrique / Surface Inspection comme fonction d'extension : affirmé par les pages produit, non relu dans l'aide.
- Texte exact de la page V12.5 « Rotary Machining and Wrapping » : non relu (la page V9.0 a servi pour la formulation « wrap »).
