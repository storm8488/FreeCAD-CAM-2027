#!/usr/bin/env node
// SPDX-License-Identifier: LGPL-2.1-or-later
//
// Passage de fichiers G-code dans le simulateur GRBL 1.1 de cncjs (grbl-simulator.js), ligne par ligne avec le
// protocole ok / error, en temps simulé (le simulateur exécute les mouvements en temps réel : horloge et minuteries
// remplacées ici, le fichier du simulateur n'est pas modifié).
//
//     node grbl_check.js <grbl-simulator.js> <sortie.json> <fichier.nc> [<fichier.nc> ...]
//
// Le simulateur accepte sans erreur des codes que GRBL 1.1 refuse (G81, M6, mots A/B/C...), ne lit pas les
// commentaires et n'a pas de mouvement modal : chaque ligne passe d'abord par le filtre de GRBL (protocol.c :
// commentaires et espaces ôtés, majuscules) puis par un contrôle strict des règles de gc_execute_line (codes et
// lettres reconnus, groupes modaux, mots répétés, mots inutilisés, nombres, 80 caractères) ; une ligne refusée
// par ce contrôle compte comme un « error: » et n'est pas envoyée.
//
// Sortie JSON par fichier : réponses error / ALARM, positions de fin de chaque mouvement absolu (repère de
// travail, G91 et palpage exclus comme dans export.analyze_gcode), enveloppe (arcs échantillonnés à 1° avec
// l'interpolation du simulateur), position finale, contacts de palpage.

'use strict';

const fs = require('fs');
const path = require('path');

// -- horloge et minuteries simulées (avant le chargement du simulateur : son constructeur lance setInterval) --
let now = 0;
const timers = [];
Date.now = () => now;
global.setInterval = () => 0; // l'exécuteur du planificateur est appelé ici, pas par une minuterie
global.setTimeout = (fn, ms) => {
    timers.push({ at: now + (ms || 0), fn });
    return timers.length;
};

const [simPath, outPath, ...files] = process.argv.slice(2);
if (!simPath || !outPath || files.length === 0) {
    console.error('usage: node grbl_check.js <grbl-simulator.js> <out.json> <file.nc>...');
    process.exit(2);
}
const GrblSimulator = require(path.resolve(simPath));

// -- règles de GRBL 1.1 (gcode.c) que le simulateur n'applique pas ---------------------------------------
const G_GROUPS = {
    // groupe modal (gc_execute_line) -> codes
    nonmodal: ['4', '10', '28', '28.1', '30', '30.1', '53', '92', '92.1'],
    motion: ['0', '1', '2', '3', '38.2', '38.3', '38.4', '38.5', '80'],
    plane: ['17', '18', '19'],
    distance: ['90', '91'],
    arc_distance: ['91.1'],
    feed_mode: ['93', '94'],
    units: ['20', '21'],
    cutter_comp: ['40'],
    tool_length: ['43.1', '49'],
    wcs: ['54', '55', '56', '57', '58', '59'],
    control: ['61'],
};
const M_GROUPS = {
    stopping: ['0', '1', '2', '30'],
    spindle: ['3', '4', '5'],
    coolant: ['8', '9'], // M7 seulement avec ENABLE_M7 à la compilation (désactivé par défaut)
};
const G_INDEX = {};
for (const [g, codes] of Object.entries(G_GROUPS)) for (const c of codes) G_INDEX[c] = g;
const M_INDEX = {};
for (const [g, codes] of Object.entries(M_GROUPS)) for (const c of codes) M_INDEX[c] = g;
const WORD_LETTERS = new Set('FIJKLNPRSTXYZ'); // GRBL 1.1 de base : 3 axes, pas de A/B/C

function normCode(num) {
    // « 01 » -> « 1 », « 38.20 » -> « 38.2 »
    const v = parseFloat(num);
    return Number.isInteger(v) ? String(v) : String(Math.round(v * 10) / 10);
}

// filtre de protocol.c : commentaires ( ) et ;, espaces, majuscules
function grblFilter(raw) {
    let out = '';
    let paren = false;
    for (const ch of raw) {
        if (paren) {
            if (ch === ')') paren = false;
            continue;
        }
        if (ch === '(') {
            paren = true;
            continue;
        }
        if (ch === ';') break;
        if (ch === ' ' || ch === '\t' || ch === '\r' || ch === '\n') continue;
        out += ch.toUpperCase();
    }
    return out;
}

// contrôle strict d'une ligne filtrée ; retourne null ou « error:N (raison) » ; ``modal`` : mode de mouvement
// en cours (G0..G3, G38.x, G80), mis à jour
function strictCheck(line, modal) {
    if (line.length > 80) return 'error:11 (line longer than 80 characters)';
    if (line[0] === '$') return null;
    const re = /([A-Z])([-+]?(?:\d+\.?\d*|\.\d+))/gy;
    let m;
    let pos = 0;
    const groups = new Set();
    const words = new Set();
    const gcodes = new Set();
    while (pos < line.length) {
        re.lastIndex = pos;
        m = re.exec(line);
        if (!m) return 'error:' + (/[A-Z]/.test(line[pos]) ? '2 (bad number format)' : '1 (expected command letter)');
        pos = re.lastIndex;
        const letter = m[1];
        if (letter === 'G' || letter === 'M') {
            const code = normCode(m[2]);
            const group = (letter === 'G' ? G_INDEX : M_INDEX)[code];
            if (!group) return 'error:20 (unsupported command ' + letter + code + ')';
            const key = letter + group;
            if (groups.has(key)) return 'error:21 (two commands of the same modal group)';
            groups.add(key);
            if (letter === 'G') gcodes.add(code);
        } else {
            if (!WORD_LETTERS.has(letter)) return 'error:20 (unsupported word ' + letter + ')';
            if (words.has(letter)) return 'error:25 (repeated word ' + letter + ')';
            words.add(letter);
        }
    }
    // mots de valeur que la commande n'utilise pas : error:36 (gc_execute_line, fin de la vérification)
    const motion = [...gcodes].find((c) => G_INDEX[c] === 'motion');
    if (motion !== undefined) modal.motion = motion;
    const axes = words.has('X') || words.has('Y') || words.has('Z');
    const arc = (modal.motion === '2' || modal.motion === '3') && (motion !== undefined || axes);
    for (const w of ['I', 'J', 'K', 'R']) {
        if (words.has(w) && !arc) return 'error:36 (unused word ' + w + ')';
    }
    if (words.has('P') && !gcodes.has('4') && !gcodes.has('10')) return 'error:36 (unused word P)';
    if (words.has('L') && !gcodes.has('10')) return 'error:36 (unused word L)';
    return null;
}

const NOT_POSITION = /G(?:10|28|30|53|92|38\.[2-5])(?![\d.])/; // mots d'axe qui ne sont pas une position de travail
const MOTION = /G0*[0-3](?![\d.])/;
const AXIS_WORD = { x: /X[-+.\d]/, y: /Y[-+.\d]/, z: /Z[-+.\d]/ };

function runFile(file) {
    const sim = new GrblSimulator();
    const pending = []; // réponses asynchrones (data)
    sim.on('data', (d) => pending.push(String(d)));
    const report = {
        file: path.basename(file),
        lines: 0,
        sent: 0,
        errors: [],
        alarms: [],
        probes: [],
        pauses: 0,
        points: [],
        envelope: {},
        final: null,
    };
    const env = report.envelope;
    // axes dont la position de travail est connue : écrits par un mouvement absolu, perdus après un palpage,
    // G10 / G92 / G28 / G30 / G53 (règle de export.analyze_gcode) ; le simulateur part de 0 sans le savoir
    const known = { x: false, y: false, z: false };
    const grow = (p) => {
        for (const a of ['x', 'y', 'z']) {
            if (!known[a]) continue;
            const k = a.toUpperCase();
            const v = p[a];
            if (!env[k]) env[k] = [v, v];
            else {
                if (v < env[k][0]) env[k][0] = v;
                if (v > env[k][1]) env[k][1] = v;
            }
        }
    };

    // exécute le planificateur jusqu'au repos ; échantillonne les arcs ; renvoie vrai si un arc a été vu
    const drain = (sampleArcs) => {
        for (let guard = 0; guard < 1e6; guard++) {
            const ms = sim.motionState;
            if (ms.active) {
                if (sampleArcs && ms.type === 'arc' && ms.data) {
                    const steps = Math.max(2, Math.ceil(Math.abs(ms.data.angularTravel) * 180 / Math.PI));
                    for (let k = 1; k < steps; k++) {
                        now = ms.startTime + (ms.endTime - ms.startTime) * k / steps;
                        grow(sim.getCurrentPosition());
                    }
                }
                now = Math.max(now, ms.endTime);
                sim.executePlannerQueue();
                continue;
            }
            if (sim.plannerBuffer.queue.length > 0 || sim.waitingQueue.length > 0) {
                sim.executePlannerQueue();
                continue;
            }
            const due = timers.filter((t) => t.at <= now);
            if (due.length) {
                for (const t of due) timers.splice(timers.indexOf(t), 1);
                for (const t of due) t.fn();
                continue;
            }
            if (timers.length) {
                now = Math.min(...timers.map((t) => t.at));
                continue;
            }
            return;
        }
        throw new Error('planner did not settle');
    };

    const modal = { motion: '0' };
    const text = fs.readFileSync(file, 'utf8');
    const rawLines = text.split(/\r?\n/);
    for (let n = 0; n < rawLines.length; n++) {
        const line = grblFilter(rawLines[n]);
        if (!line) continue;
        report.lines++;
        const strict = strictCheck(line, modal);
        if (strict) {
            report.errors.push({ line: n + 1, text: rawLines[n], response: strict, source: 'strict' });
            continue;
        }
        let response = null;
        sim.processLineAsync(line, (r) => {
            response = r;
        });
        report.sent++;
        drain(sim.parserState.distance === 'G90' && !NOT_POSITION.test(line));
        if (response === null) throw new Error('no response for line ' + (n + 1));
        const all = [response].concat(pending.splice(0));
        for (const r of all) {
            for (const part of r.split(/\r?\n/)) {
                if (part.startsWith('error:')) report.errors.push({ line: n + 1, text: rawLines[n], response: part, source: 'simulator' });
                else if (part.startsWith('ALARM')) report.alarms.push({ line: n + 1, text: rawLines[n], response: part });
                else if (part.startsWith('[PRB:')) report.probes.push({ line: n + 1, response: part });
            }
        }
        if (sim.machineState === 'Alarm' && !report.alarms.length) {
            report.alarms.push({ line: n + 1, text: rawLines[n], response: 'ALARM:' + sim.alarmCode });
        }
        if (/M0*0(?![\d.])|M0*1(?![\d.])/.test(line)) report.pauses++;
        const written = ['x', 'y', 'z'].filter((a) => AXIS_WORD[a].test(line));
        if (NOT_POSITION.test(line)) {
            for (const a of written) known[a] = false;
        } else if (MOTION.test(line) && written.length && sim.parserState.distance === 'G90') {
            for (const a of written) known[a] = true;
            const p = sim.machinePosition;
            const point = ['x', 'y', 'z'].map((a) => (known[a] ? p[a] : null));
            report.points.push(point);
            grow(p);
            report.final = point;
        }
    }
    report.state = sim.machineState;
    return report;
}

const out = files.map(runFile);
fs.writeFileSync(outPath, JSON.stringify(out));
const bad = out.reduce((s, r) => s + r.errors.length + r.alarms.length, 0);
for (const r of out) {
    console.log(`${r.file}: ${r.lines} lines, ${r.errors.length} error, ${r.alarms.length} ALARM, ${r.points.length} positions`);
}
process.exit(bad ? 1 : 0);
