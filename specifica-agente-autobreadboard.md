# Specifica di implementazione — AutoBreadboard

## 1. Missione

Implementare una web application che riceva una netlist elettronica e produca un layout realizzabile su **breadboard** per componenti **esclusivamente THT** (*through-hole technology*).

L'applicazione deve:

1. importare o ricevere una rappresentazione normalizzata di componenti, pin e net;
2. modellare accuratamente la geometria e le connessioni interne di una breadboard;
3. proporre il placement dei componenti;
4. generare jumper per completare le connessioni;
5. verificare elettricamente il layout risultante rispetto alla netlist richiesta;
6. permettere correzioni manuali con verifica immediata;
7. esportare una guida di montaggio leggibile: immagine/SVG, BOM, elenco jumper e diagnostica.

Il prodotto non deve promettere un “layout elettricamente perfetto”. Deve generare un **layout iniziale costruibile e verificato**, quindi rendere semplici la revisione e l'editing manuale.

Nome interno provvisorio: `autobreadboard`.

---

## 2. Scope e vincoli

### 2.1 MVP supportato

Supportare inizialmente:

- breadboard standard **half-size da circa 400 tie-point**;
- griglia da 2,54 mm / 0,1";
- rail configurabili e potenzialmente spezzate;
- componenti THT:
  - DIP-8, DIP-14, DIP-16, DIP-20, DIP-28;
  - resistori assiali;
  - diodi assiali;
  - condensatori ceramici/film a due terminali;
  - condensatori elettrolitici radiali;
  - LED;
  - transistor TO-92;
  - pulsanti tact THT;
  - header 1×N;
  - connettori semplici a 2–4 pin;
- jumper in filo;
- netlist JSON normalizzata;
- editor manuale con drag, rotazione, lock e modifica jumper;
- verifica open/short;
- export SVG, PNG, JSON, BOM e CSV dei jumper.

### 2.2 Non-scope MVP

Escludere esplicitamente dall'autorouting iniziale:

- SMD;
- RF e antenna;
- USB, Ethernet, LVDS e segnali veloci;
- alimentazione da rete o tensioni pericolose;
- layout di convertitori switching discreti;
- alte correnti su rail standard di breadboard;
- package non modellati;
- promessa di ottimalità globale;
- import diretto e completo di tutti i formati KiCad nella prima milestone.

Il sistema può accettare tali net/classi ma deve produrre warning, richiedere override esplicito o rifiutare l'autorouting in base alla configurazione.

### 2.3 Principio di sicurezza

Mostrare sempre una nota nel prodotto:

> La breadboard è destinata a prototipi a bassa tensione e bassa energia. Verificare limiti di corrente, polarità, tensioni e sicurezza prima di alimentare il circuito.

Non dichiarare che un circuito è “sicuro” solo perché la netlist è connessa correttamente.

---

## 3. Architettura proposta

### 3.1 Stack

Usare una web application TypeScript end-to-end:

| Area | Scelta consigliata |
|---|---|
| Frontend | React + TypeScript |
| Build | Vite |
| Stato UI | Zustand |
| Rendering | SVG nel MVP; Canvas/WebGL solo se necessario in futuro |
| Algoritmi solver | TypeScript in Web Worker |
| Parsing | JSON normalizzato inizialmente; parser KiCad in modulo separato |
| Validazione | Union-Find / Disjoint Set Union |
| Test | Vitest + Playwright |
| Formattazione | ESLint + Prettier |

Organizzare il dominio in un package indipendente dalla UI:

```text
packages/
  core/             # Modello dominio, placement, router, validatore
  footprints/       # Libreria package/footprint breadboard
  io/               # JSON import/export, in futuro KiCad adapter
  renderer/         # SVG layout primitives e rendering
apps/
  web/              # React app
```

Se il repository deve essere inizialmente semplice, usare un singolo progetto con cartelle equivalenti. Mantenere comunque confini netti tra `core`, `io` e UI.

### 3.2 Principi architetturali

- Il solver non deve dipendere da React, DOM, SVG o browser API.
- Il modello elettrico deve essere distinto dal modello grafico/fisico.
- Ogni trasformazione deve essere deterministica per un seed dato.
- Ogni layout modificato deve poter essere validato senza rieseguire il solver.
- Il formato di progetto deve essere versionato.
- Il modello board deve poter rappresentare sia breadboard sia, in futuro, perfboard/millefori.

---

## 4. Modello del dominio

### 4.1 Coordinate discrete

La board usa coordinate discrete, non coordinate continue.

```ts
export type HoleId = string;
export type ComponentRef = string;
export type NetId = string;

export type GridPoint = {
  col: number;
  row: string;
};

export type Point = {
  x: number;
  y: number;
};
```

Esempio di identificatori:

```text
a1, b1, c1, d1, e1
f1, g1, h1, i1, j1
rail-top-plus-1
rail-bottom-minus-30
```

### 4.2 Board fisica ed elettrica

La breadboard **non** è una matrice di fori isolati. Modellare separatamente:

- `holes`: fori fisici e coordinate;
- `electricalGroups`: gruppi internamente connessi;
- `zones`: aree e vincoli fisici;
- `rails`: segmenti di rail, inclusi i break;
- `centerGap`: canale centrale che deve essere rispettato da DIP e moduli;
- `occupancy`: stato derivato dal placement.

```ts
export type Hole = {
  id: HoleId;
  point: Point;
  grid: GridPoint;
  enabled: boolean;
  label: string;
};

export type ElectricalGroup = {
  id: string;
  holeIds: HoleId[];
  kind: "tie-point" | "rail" | "custom";
};

export type BoardZone = {
  id: string;
  kind: "main" | "rail" | "center-gap" | "reserved";
  polygon: Point[];
};

export type BreadboardModel = {
  id: string;
  version: 1;
  pitchMm: 2.54;
  holes: Hole[];
  electricalGroups: ElectricalGroup[];
  zones: BoardZone[];
  metadata: {
    columns: number;
    railConfiguration: string;
  };
};
```

Per una breadboard classica:

```text
A17–E17 sono collegati internamente.
F17–J17 sono collegati internamente.
A17–E17 non sono collegati a F17–J17.
Le rail sono segmenti separati configurabili.
```

Non hardcodare l'ipotesi che una rail sia continua per tutta la sua lunghezza.

### 4.3 Netlist

Usare un formato interno semplice e indipendente da KiCad.

```ts
export type NetClass =
  | "ground"
  | "power"
  | "high-current"
  | "analog-sensitive"
  | "clock"
  | "switching"
  | "digital"
  | "low-priority"
  | "custom";

export type PinRef = {
  componentRef: ComponentRef;
  pin: string;
};

export type Net = {
  id: NetId;
  name: string;
  pins: PinRef[];
  netClass: NetClass;
  priority: number;
  constraints?: NetConstraint[];
};

export type NetConstraint =
  | { type: "max-length-mm"; value: number }
  | { type: "prefer-rail" }
  | { type: "avoid-zone"; zoneId: string }
  | { type: "must-be-local"; componentRef: ComponentRef }
  | { type: "manual"; note: string };
```

Classificare automaticamente soltanto come suggerimento. Esempi:

- `GND`, `AGND`, `DGND` → `ground`;
- `VCC`, `+3V3`, `+5V`, `VIN` → `power`;
- `SCL`, `SDA`, `UART`, `GPIO` → `digital`;
- `XTAL`, `OSC`, `CLK` → `clock`;
- `SW`, `PHASE` → `switching`.

L'utente deve poter modificare la classe e la priorità di ogni net. Non trattare euristiche di naming come verità elettrica.

### 4.4 Componenti e footprint

Separare simbolo/logica, footprint breadboard e placement effettivo.

```ts
export type Component = {
  ref: ComponentRef;
  value?: string;
  footprintId: string;
  pins: string[];
  locked?: boolean;
  tags?: string[];
};

export type Orientation = 0 | 90 | 180 | 270;

export type RelativeHole = {
  x: number;
  y: number;
};

export type BreadboardFootprint = {
  id: string;
  displayName: string;
  pinOffsets: Record<string, RelativeHole>;
  bodyCells: RelativeHole[];
  supportedOrientations: Orientation[];
  placementRules: PlacementRule[];
  geometry: FootprintGeometry;
};

export type PlacementRule =
  | { type: "must-straddle-center-gap" }
  | { type: "must-be-on-main-area" }
  | { type: "must-be-on-board-edge" }
  | { type: "allowed-zones"; zoneIds: string[] }
  | { type: "min-clearance-holes"; value: number };

export type FootprintGeometry = {
  pinsPerSide?: number;
  nominalBodyWidthMm?: number;
  nominalBodyLengthMm?: number;
  flexibleLeadSpan?: {
    minHoles: number;
    maxHoles: number;
    orientations: Array<"horizontal" | "vertical">;
  };
};
```

#### Footprint obbligatori MVP

Implementare con test unitari:

- `DIP-8`, `DIP-14`, `DIP-16`, `DIP-20`, `DIP-28`;
- `AXIAL-R` con pitch flessibile;
- `AXIAL-DIODE` con pitch flessibile e marker catodo;
- `RADIAL-CAP-2P`;
- `ELECTROLYTIC-CAP-2P` con polarità;
- `LED-2P` con anodo/catodo;
- `TO-92` con mapping pin definito dal componente;
- `TACT-SW-4P` con le coppie internamente collegate esplicitate;
- `HEADER-1xN`;
- `CONN-1xN`.

I footprint flessibili devono generare pose possibili per ogni lead-span ammesso. Per un resistore assiale, la distanza tra i due pin deve essere un multiplo della griglia e avere un costo associato: lead span più naturale/preferito = costo inferiore.

### 4.5 Placement e jumper

```ts
export type ComponentPlacement = {
  componentRef: ComponentRef;
  anchorHoleId: HoleId;
  orientation: Orientation;
  pinHoles: Record<string, HoleId>;
  occupiedHoleIds: HoleId[];
  locked: boolean;
};

export type JumperPath = {
  points: Point[];
  layer: "lower" | "upper";
};

export type Jumper = {
  id: string;
  netId: NetId;
  startHoleId: HoleId;
  endHoleId: HoleId;
  path: JumperPath;
  color?: string;
  estimatedLengthMm: number;
  locked: boolean;
};

export type Layout = {
  version: 1;
  boardId: string;
  placements: ComponentPlacement[];
  jumpers: Jumper[];
  manualElectricalLinks?: Array<{ holeA: HoleId; holeB: HoleId; netId?: NetId }>;
};
```

Un jumper collega elettricamente due fori. Il percorso grafico serve per leggibilità, stima lunghezza, collisioni e istruzioni; non deve essere confuso con una pista PCB che occupa ogni foro intermedio.

---

## 5. Pipeline funzionale

Implementare il flusso seguente.

```text
Netlist JSON
  → validazione input
  → mappatura componenti/footprint
  → classificazione net e cluster
  → placement vincolato
  → routing jumper
  → rip-up/reroute se necessario
  → verifica elettrica
  → scoring + warning
  → rendering ed export
```

### 5.1 Validazione input

Prima di risolvere:

- ogni `Component.ref` deve essere univoco;
- ogni pin referenziato da una net deve esistere;
- un pin non deve appartenere a due net logiche diverse;
- ogni componente deve avere footprint supportato;
- il board model deve esistere;
- le net con meno di due pin possono essere warning, non errore;
- rilevare naming ambiguo e componenti non mappati.

Restituire errori strutturati e mostrabili in UI.

### 5.2 Clustering

Costruire un grafo di connettività componente–net. Generare cluster prima del placement:

- un IC attivo e componenti direttamente collegati a pin critici;
- condensatori di bypass associati al loro IC;
- quarzo e condensatori associati a MCU;
- transistor e resistenze/diodi direttamente associati;
- regolatore e condensatori di input/output;
- connettori e protezioni associate.

Il clustering può iniziare rule-based; non implementare community detection complessa nel MVP.

Esempi di regole iniziali:

- componente `DIP-*`: è un anchor;
- net `clock`: elementi collegati a un DIP sono cluster localmente al DIP;
- condensatore su net `power` + `ground` collegato a un IC: trattarlo come bypass candidato;
- resistore collegato a un transistor e a una net digitale: candidato `base/gate` locale;
- condensatore di alimentazione di un regolatore: locale al regolatore.

Esporre in UI il cluster calcolato e permettere all'utente di forzare vicinanza o separazione in una fase successiva.

---

## 6. Placement

### 6.1 Ordine di placement

Usare un ordine in cui le parti più vincolate vengono piazzate per prime:

1. componenti `locked` dall'utente;
2. connettori/footprint con vincolo bordo;
3. DIP e moduli rigidi;
4. componenti ad alta area o con pochi placement validi;
5. cluster critici locali;
6. componenti assiali e passivi flessibili;
7. LED, pulsanti e elementi a bassa priorità.

Per DIP, generare pose valide che attraversino il canale centrale. Non piazzare un DIP su una sola metà della breadboard.

### 6.2 Generazione pose

Per ciascun componente, generare tutte le pose consentite sul board:

- tutte le anchor hole compatibili;
- tutte le orientazioni supportate;
- tutti gli span consentiti per i package flessibili;
- applicare `placementRules`;
- calcolare `pinHoles`, `occupiedHoleIds`, body bounds e clearance;
- scartare pose fuori board, su gap, su rail non compatibili o in collisione.

Cache delle pose: la generazione deve essere calcolata una volta per footprint/board e filtrata in base allo stato occupazione.

### 6.3 Funzione costo placement

Per una pose candidata usare una funzione costo a pesi configurabili:

\[
C_{placement} =
 w_d D_{weighted}
+ w_c P_{congestion}
+ w_m P_{mechanical}
+ w_r P_{criticalRules}
+ w_a P_{accessibility}
+ w_o P_{overlap}
\]

Dove:

- `D_weighted`: distanza Manhattan pesata fra pin della pose e terminali già piazzati appartenenti alla stessa net;
- `P_congestion`: penalità per densità elevata nelle vicinanze;
- `P_mechanical`: penalità di orientamento o span poco pratico;
- `P_criticalRules`: penalità elevata per violazioni di net critiche;
- `P_accessibility`: penalità se connettori/LED/pulsanti non rimangono accessibili;
- `P_overlap`: infinito per collisioni fisiche o fori già occupati.

Distanza base:

\[
d((x_1,y_1),(x_2,y_2)) = |x_1-x_2| + |y_1-y_2|
\]

Usare pesi iniziali configurabili, non hardcoded nel solver. Esempio di preset:

```ts
const placementWeights = {
  weightedDistance: 1,
  congestion: 15,
  mechanical: 10,
  criticalRule: 500,
  accessibility: 25,
  overlap: 1_000_000,
};
```

### 6.4 Strategia MVP

Implementare:

1. greedy placement ordinato per difficoltà;
2. scelta della pose valida con score minimo;
3. local search successiva;
4. restart casuali con seed controllabile;
5. mantenere la migliore soluzione valida o parzialmente valida.

La local search deve supportare mosse:

- traslare un componente;
- ruotarlo;
- cambiare lead-span di componente assiale;
- scambiare due componenti compatibili;
- spostare un cluster;
- rilocare un componente non locked.

### 6.5 Ottimizzazione avanzata

Dopo MVP, aggiungere simulated annealing:

```text
stato iniziale: greedy placement
mossa: spostamento, rotazione, swap, cluster move
energia: score placement + risultati routing
accettazione:
  sempre se migliora
  probabilistica se peggiora, in funzione della temperatura
raffreddamento: geometrico o adattivo
```

Non usare simulated annealing prima che siano presenti test, metriche e un solido greedy baseline.

---

## 7. Routing

### 7.1 Concetto chiave

Su una breadboard un jumper può collegare direttamente due fori: non deve necessariamente attraversare nodi intermedi. Quindi il router deve distinguere:

- **connessione elettrica**: un jumper unisce due fori;
- **percorso grafico**: il filo disegnato può avere segmenti e bend point;
- **congestione visiva/fisica**: molti jumper nella stessa area sono penalizzati;
- **cortocircuito**: dipende dai nodi elettrici, non dall'incrocio visivo dei fili.

Nel primo router usare jumper diretti, con percorso Manhattan semplice. A* è necessario nella fase “lane-aware” per scegliere corridoi visivi e evitare component bodies/zones.

### 7.2 Stato elettrico

Usare Union-Find/DSU.

Inizializzazione:

1. creare un elemento per ogni hole;
2. unire i hole di ogni `ElectricalGroup` della breadboard;
3. aggiungere le connessioni interne dei componenti, se un footprint le definisce;
4. aggiungere i jumper esistenti/manuali;
5. associare ogni pin collocato al suo hole.

Non unire automaticamente pin appartenenti a net diverse. La DSU serve a ricostruire le componenti connesse fisicamente; la comparazione con la netlist target avviene nella fase di verifica.

### 7.3 Net multi-terminale

Per una net con più terminali, costruire un albero di connessione, non una stella cieca.

MVP: approssimazione greedy di Steiner tree.

1. per ogni scelta possibile del root terminal/rail, inizializzare un tree;
2. aggiungere il terminale non connesso con costo minimo verso un nodo già nel tree;
3. scegliere come endpoint il hole/gruppo elettrico più conveniente;
4. aggiungere il jumper;
5. ripetere fino a unire tutti i terminali;
6. provare root alternativi se il costo è alto;
7. conservare l'albero a costo minimo.

Dare preferenza a `rail` per net `power` e `ground`, ma solo se la rail assegnata non è spezzata o satura e se è elettricamente sensata.

### 7.4 Routing order

Ordinare le net per rigidità e criticità:

1. `switching`, `clock`, `analog-sensitive`, `high-current` — se ammessi;
2. power e ground;
3. net multi-terminale;
4. net con distanza alta o pochi endpoint liberi;
5. digital normali;
6. LED, pulsanti e low-priority.

La UI deve avvisare se classi critiche vengono instradate sulla breadboard; non mascherare il rischio con un buon punteggio.

### 7.5 Cost function router

\[
C_{route} =
 w_l L
+ w_j J
+ w_x X
+ w_g G
+ w_z Z
+ w_k K
+ w_u U
\]

Dove:

- `L`: lunghezza totale stimata;
- `J`: numero jumper;
- `X`: crossing e overlay visivo;
- `G`: congestione locale;
- `Z`: attraversamento di zone sfavorite;
- `K`: violazioni di classe/criticità;
- `U`: terminali o net non instradati.

`U` deve avere un peso enormemente maggiore degli altri costi.

Preset iniziale:

```ts
const routingWeights = {
  lengthMm: 1,
  jumperCount: 12,
  crossing: 40,
  congestion: 30,
  avoidZone: 100,
  criticalViolation: 500,
  unroutedTerminal: 10_000,
};
```

### 7.6 Rip-up and reroute

Quando una net non è instradabile o il routing supera soglie di congestione:

1. individuare jumper non locked a basso peso che usano la stessa zona;
2. rimuovere gli ultimi `k` jumper o quelli con maggiore costo marginale;
3. aumentare temporaneamente il costo delle zone congestionate;
4. instradare prima la net fallita;
5. reinstradare le net rimosse;
6. limitare il numero di tentativi;
7. se fallisce, restituire soluzione parziale con diagnostica esplicita.

Non cancellare o modificare jumper locked/manuali senza azione dell'utente.

### 7.7 A* lane-aware: fase successiva

Implementare solo dopo il jumper router diretto.

Costruire un grafo di corsie sopra/sotto la board:

- nodi: punti di routing fra righe/colonne;
- edge: segmenti ortogonali;
- ostacoli: body component, zone riservate;
- costo: lunghezza + congestione + crossing + cambio layer;
- layer: `lower` e `upper` con policy configurabile.

Usare A* con euristica Manhattan ammissibile. Prevedere un livello “upper” che consenta crossing con penalità; gli incroci di fili isolati non sono automaticamente short elettrici.

---

## 8. Verifica elettrica

La verifica è una feature core, non un dettaglio UI.

### 8.1 Obiettivi

Per il layout generato o modificato manualmente, rilevare:

- pin della stessa net target non connessi: `open`;
- pin appartenenti a net target diverse nello stesso componente connesso fisico: `short`;
- pin senza placement: `unplaced-pin`;
- componente non piazzato: `unplaced-component`;
- jumper endpoint non valido;
- collisione meccanica;
- rail usata come continua quando il modello la dichiara spezzata;
- vincolo critico violato;
- warning di affidabilità/uso breadboard.

### 8.2 Algoritmo

1. creare DSU con tutti gli hole;
2. unire gruppi interni della board;
3. unire endpoint di ogni jumper;
4. per ciascun pin collocato, trovare il suo root DSU;
5. costruire `physicalRoot -> Set<targetNetId>`;
6. se un root contiene più target net, segnala short;
7. per ogni net target, verificare che tutti i suoi pin risultino nello stesso root o nella configurazione prevista;
8. produrre una lista di problemi con riferimenti cliccabili in UI.

Nota: le connessioni interne di un componente non devono in generale essere trattate come corto fra i suoi pin. I componenti sono elementi elettrici, non jumper. Il validatore topologico valuta soltanto la connettività dei conduttori della breadboard, dei jumper, delle rail e dei ponti espliciti. La netlist definisce già il fatto che due pin dello stesso componente possano appartenere a net diverse.

### 8.3 Severity

```ts
type DiagnosticSeverity = "error" | "warning" | "info";

type Diagnostic = {
  id: string;
  severity: DiagnosticSeverity;
  code: string;
  message: string;
  relatedHoleIds?: HoleId[];
  relatedComponentRefs?: ComponentRef[];
  relatedNetIds?: NetId[];
  suggestion?: string;
};
```

Errori bloccanti: short, componente mancante, pin out of board, jumper endpoint invalido, collisione pin.

Warning: rail potenzialmente spezzata, net critica lunga, congestionamento, rail high-current, body clearance insufficiente, package non perfettamente modellato.

---

## 9. UX e interazione

### 9.1 Layout editor

La UI deve avere almeno:

- canvas/SVG della breadboard;
- coordinate e rail riconoscibili;
- componenti con `ref`, valore e polarità;
- jumper colorati e numerati;
- selezione componente/net/jumper;
- drag and drop dei componenti;
- rotazione;
- lock/unlock;
- aggiungi/elimina/modifica jumper;
- evidenziazione di una net;
- vista topologica dei gruppi interni;
- pannello diagnostica;
- pulsante `Auto-place`, `Auto-route`, `Validate`, `Optimize`;
- seed e preset dei pesi in una sezione avanzata;
- undo/redo.

### 9.2 Editing corretto

Dopo ogni modifica manuale:

1. aggiornare occupancy;
2. ricalcolare le connessioni fisiche interessate;
3. eseguire validazione incrementale, o completa nel MVP;
4. aggiornare problemi e score;
5. non spostare automaticamente altri componenti salvo comando esplicito.

### 9.3 Visual language

Usare convenzioni:

- rail e net di alimentazione: rosso;
- ground: nero o grigio scuro;
- segnali: palette distinguibile;
- warning: giallo/arancione;
- errori: rosso;
- componenti locked: icona lucchetto;
- net evidenziata: alta opacità, resto attenuato.

La visualizzazione non deve far sembrare che i fori della stessa tie-point siano componenti indipendenti: mostrare, almeno in una modalità, i gruppi interni con una lieve evidenza.

### 9.4 Istruzioni montaggio

L'output deve essere ordinato e utilizzabile al banco:

1. piazza componenti rigidi;
2. piazza componenti passivi;
3. aggiungi jumper corti;
4. aggiungi jumper lunghi;
5. collega alimentazione per ultima.

Per ogni jumper, includere:

```text
J12 — Net: GND — da e17 a rail-bottom-minus-17 — nero — 58 mm — layer upper
```

Non suggerire di alimentare automaticamente il circuito; includere sempre una fase “verifica continuità e polarità prima dell'alimentazione”.

---

## 10. Formato JSON progetto

Definire un formato versionato. Esempio minimo:

```json
{
  "format": "autobreadboard-project",
  "version": 1,
  "board": {
    "modelId": "half-400-standard-split-rails"
  },
  "components": [
    {
      "ref": "U1",
      "value": "74HC14",
      "footprintId": "DIP-14",
      "pins": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14"]
    },
    {
      "ref": "R1",
      "value": "10k",
      "footprintId": "AXIAL-R",
      "pins": ["1", "2"]
    }
  ],
  "nets": [
    {
      "id": "net-gnd",
      "name": "GND",
      "netClass": "ground",
      "priority": 100,
      "pins": [
        { "componentRef": "U1", "pin": "7" },
        { "componentRef": "R1", "pin": "2" }
      ]
    },
    {
      "id": "net-sig",
      "name": "SIG",
      "netClass": "digital",
      "priority": 30,
      "pins": [
        { "componentRef": "U1", "pin": "1" },
        { "componentRef": "R1", "pin": "1" }
      ]
    }
  ],
  "layout": {
    "placements": [],
    "jumpers": []
  },
  "settings": {
    "seed": 12345,
    "solverPreset": "balanced"
  }
}
```

Garantire round-trip senza perdita: import → modifica → export → import deve conservare tutti i campi noti, lock, posizionamenti, jumper manuali, seed e override.

---

## 11. Import KiCad

### 11.1 Strategia

Non bloccare MVP sull'import nativo KiCad. Implementare prima JSON normalizzato e fixtures di test.

Poi aggiungere un adapter che:

1. legge un `.kicad_sch` o un export intermedio;
2. estrae simboli, reference, pin e net;
3. mappa ogni componente a un `BreadboardFootprint`;
4. chiede intervento utente se la mappatura è ambigua;
5. produce il JSON interno.

KiCad usa file S-expression; l'adapter deve essere isolato in `io/kicad` e non deve contaminare il core solver.

### 11.2 Mapping necessario

Il mapping KiCad footprint → breadboard footprint non è sempre 1:1. Gestire una tabella override:

```ts
type FootprintMapping = {
  kicadFootprintPattern: string;
  breadboardFootprintId: string;
  pinMap?: Record<string, string>;
};
```

Esempi:

```text
Package_DIP:DIP-14_W7.62mm → DIP-14
Resistor_THT:R_Axial_*      → AXIAL-R
Diode_THT:D_DO-*            → AXIAL-DIODE
Package_TO_SOT_THT:TO-92_*  → TO-92
```

L'utente deve poter scegliere la footprint breadboard e confermare l'ordine reale dei pin, specialmente per moduli e transistor.

---

## 12. API del core solver

Progettare API pure e testabili:

```ts
export type SolveRequest = {
  board: BreadboardModel;
  netlist: {
    components: Component[];
    nets: Net[];
  };
  initialLayout?: Layout;
  options: SolverOptions;
};

export type SolverOptions = {
  seed: number;
  maxPlacementRestarts: number;
  maxLocalSearchIterations: number;
  maxRipupIterations: number;
  placementWeights: Record<string, number>;
  routingWeights: Record<string, number>;
  allowCriticalNetClasses: boolean;
};

export type SolveResult = {
  layout: Layout;
  score: LayoutScore;
  diagnostics: Diagnostic[];
  trace?: SolverTrace;
};

export function solve(request: SolveRequest): SolveResult;
export function place(request: SolveRequest): PlacementResult;
export function route(request: RouteRequest): RouteResult;
export function validate(request: ValidateRequest): ValidationResult;
export function score(request: ScoreRequest): LayoutScore;
```

`SolverTrace` deve rendere possibile il debug e, in futuro, la visualizzazione delle decisioni:

- ordine placement;
- pose candidate migliori;
- cause di rifiuto;
- net routing fallite;
- rip-up effettuati;
- score per iterazione;
- seed effettivo.

---

## 13. Testing obbligatorio

### 13.1 Unit test

Scrivere test per:

- costruzione delle tie-point groups di ogni board supportata;
- rail spezzate;
- trasformazioni footprint/orientamento;
- vincolo DIP sul canale centrale;
- collisioni hole e body;
- mapping pin → hole;
- calcolo distanza;
- DSU;
- riconoscimento open;
- riconoscimento short;
- net multi-terminale;
- stima lunghezza jumper;
- rendering path Manhattan;
- serializzazione/deserializzazione JSON;
- determinismo dato lo stesso seed.

### 13.2 Fixture circuiti

Aggiungere fixture versionate almeno per:

1. LED + resistenza + connettore a 2 pin.
2. Pulsante con pull-up/pull-down.
3. DIP-8 con bypass e LED.
4. 74HC14 DIP-14 con alimentazione, ingressi e LED.
5. Transistor TO-92 + resistenza base + LED/carico a bassa potenza.
6. MCU DIP piccolo o modulo header semplice, se la footprint è disponibile.
7. Caso con rail spezzate.
8. Caso impossibile che deve ritornare diagnostica, non crash.
9. Caso con short indotto manualmente.
10. Caso con un componente locked e un jumper manuale.

Per ogni fixture mantenere:

- input JSON;
- layout atteso o proprietà attese;
- diagnostica attesa;
- screenshot SVG opzionale per visual regression.

### 13.3 Property-based test

Se possibile usare `fast-check` per testare:

- nessun hole viene occupato da due pin senza diagnostica;
- una rotazione seguita dalla rotazione inversa conserva la footprint;
- layout esportato/importato conserva i dati;
- il validatore non classifica un layout come valido in presenza di due net target diverse nello stesso gruppo fisico;
- il solver non crasha su netlist parzialmente valide: deve restituire diagnostica.

---

## 14. Metriche e quality bar

Una soluzione è “buona” se:

- non contiene errori elettrici topologici;
- il maggior numero possibile di net è instradato;
- componenti e jumper non hanno collisioni;
- le net critiche rispettano i vincoli o producono warning chiari;
- il layout è riproducibile dato lo stesso seed;
- il rendering è leggibile e esportabile;
- l'utente può correggere manualmente il risultato senza rompere la verifica.

Metriche minime da mostrare:

```text
Componenti piazzati: 18 / 18
Net completate: 24 / 25
Jumper: 31
Lunghezza jumper stimata: 1.82 m
Crossing visivi: 4
Errori: 0
Warning: 3
Score: 742
```

Non usare il singolo score come prova di qualità elettrica. Mostrare sempre anche errori, warning, net incomplete e vincoli violati.

---

## 15. Milestone

### M0 — Fondazioni

Deliverable:

- monorepo o struttura equivalente;
- TypeScript, lint, format, test;
- modello JSON;
- board `half-400-standard-split-rails`;
- rendering SVG statico;
- fixture LED + R;
- DSU e validatore base.

Definition of done:

- un layout manuale con un jumper corretto è riconosciuto come connesso;
- un jumper che unisce due net differenti produce errore short;
- import/export JSON è lossless.

### M1 — Editor manuale verificato

Deliverable:

- footprint MVP;
- placement manuale;
- drag/rotate/lock;
- aggiunta/modifica jumper;
- evidenziazione net;
- diagnostica live;
- BOM e jumper list;
- export SVG/PNG/JSON/CSV.

Definition of done:

- un utente può progettare manualmente un circuito THT piccolo e verificarlo;
- tutti i fixture manuali superano i test;
- nessun errore bloccante silenzioso.

### M2 — Auto-placement assistito

Deliverable:

- generazione pose;
- greedy placer;
- component ordering;
- cluster rule-based;
- local search;
- seed e trace;
- preview di proposta placement senza auto-routing.

Definition of done:

- i fixture supportati ottengono un placement senza collisioni;
- DIP attraversano sempre il canale centrale;
- componenti locked restano invariati;
- esiste una spiegazione/traccia delle pose scelte.

### M3 — Autorouter diretto

Deliverable:

- connessione net multi-terminale;
- preferenza rail;
- scoring jumper;
- rip-up/reroute base;
- diagnostica net non instradate;
- integrazione placement → routing → validate.

Definition of done:

- fixture semplici producono layout completamente connessi;
- layout con net impossibili restituiscono un risultato parziale e motivato;
- validatore rileva qualsiasi short introdotto dal router.

### M4 — Ottimizzazione e qualità output

Deliverable:

- local search con feedback routing;
- preset qualità/velocità;
- istruzioni di montaggio ordinate;
- export PDF opzionale;
- visual regression test;
- misurazione performance.

Definition of done:

- un progetto tipico da 10–20 componenti dà risultato entro pochi secondi in browser;
- la lista jumper è coerente con il layout;
- layout e istruzioni sono riproducibili.

### M5 — KiCad adapter e lane-aware routing

Deliverable:

- import sperimentale `.kicad_sch` o export KiCad intermedio;
- UI per mapping componenti;
- A* su corsie per jumper con rendering più ordinato;
- supporto board full-size 830;
- plugin/CLI opzionale per conversione.

Definition of done:

- un progetto KiCad THT compatibile può essere importato, mappato e trasformato in layout modificabile;
- import ambiguo richiede conferma invece di inventare pinout o footprint.

---

## 16. Decisioni da non sbagliare

1. **Non trattare la breadboard come PCB.** I cinque fori interni connessi sono un unico nodo elettrico.
2. **Non affidarti al solo shortest path.** Serve placement vincolato, ordinamento delle net, scoring e riparazione iterativa.
3. **Non trattare gli incroci visivi come corti.** Due jumper isolati possono incrociarsi; devono però essere penalizzati come complessità/leggibilità.
4. **Non usare componenti come conduttori.** Un resistore o un IC non unisce topologicamente le sue net nel validatore.
5. **Non assumere rail continue.** Ogni modello board deve dichiarare segmenti e interruzioni.
6. **Non inventare pinout.** Se footprint, pin mapping o modello di breadboard è ambiguo, richiedere input utente.
7. **Non sovrascrivere modifiche manuali.** Lock e jumper manuali sono vincoli hard.
8. **Non nascondere fallimenti del solver.** Restituire layout parziale, diagnostica e indicazioni di intervento.
9. **Non ottimizzare solo la lunghezza.** Layout costruibile, leggibile e verificabile è più importante di pochi millimetri in meno.
10. **Non promettere qualità elettrica universale.** Net critiche, alta corrente, RF e switching richiedono warning espliciti o esclusione.

---

## 17. Prompt operativo per l'agente

Usare questa sezione come istruzione concreta durante l'implementazione.

> Implementa `autobreadboard` in milestone, senza saltare alla generazione automatica prima di avere un modello board corretto e un validatore affidabile. Parti da una breadboard half-size 400 tie-point con rail spezzate configurabili e solo componenti THT. Mantieni `core` puro e testabile, con UI React separata. Il sistema deve distinguere in modo rigoroso griglia fisica, gruppi elettrici interni della breadboard, placement dei componenti e jumper. Implementa prima editor manuale + validazione DSU; poi greedy placement; poi routing multi-terminale; infine ottimizzazione e import KiCad. Non dichiarare mai validità elettrica oltre alla connettività topologica. Per ogni feature aggiungi test unitari e almeno una fixture. Non cambiare automaticamente placement o jumper locked dall'utente. Quando non esiste una soluzione, restituisci un layout parziale con errori espliciti, non un layout apparentemente corretto.

---

## 18. Criterio di completamento finale

Il progetto è pronto per un primo utilizzo quando un utente può:

1. caricare una netlist JSON THT;
2. selezionare una breadboard reale supportata;
3. confermare footprint e pinout;
4. bloccare componenti desiderati;
5. ottenere placement e jumper suggeriti;
6. vedere net non connesse, corti e warning;
7. correggere manualmente il layout;
8. ottenere una validazione aggiornata;
9. esportare una guida di montaggio e una lista jumper;
10. riprodurre lo stesso risultato con stesso input, preset e seed.

La priorità assoluta è: **correttezza topologica verificabile, modificabilità manuale e chiarezza costruttiva**. L'ottimizzazione automatica è importante, ma viene dopo questi tre requisiti.
