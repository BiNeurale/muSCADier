// ============================================================================
//  noce_moscata_albero.scad  —  Albero di Myristica fragrans  (FILE UNICO)
// ----------------------------------------------------------------------------
//  Versione OTTIMIZZATA per caricamento immediato e render F6 (CGAL) rapido:
//    • NESSUNA operazione booleana sull'albero (solo union di primitive)
//      -> CGAL molto piu' veloce (niente difference/intersection da valutare).
//    • Geometria leggera: pochi facet, foglie a un solo solido, fogliame rado.
//    • Output dimensionato per software 3D (Blender & co.): vedi SCALA.
//  Autosufficiente: nessun include/use. Basta aprirlo e premere F5/F6.
// ============================================================================

/* ====== SCALA / DIMENSIONI DELL'OUTPUT =====================================
   I moduli sono modellati in "unita' di progetto" (albero ~738 di altezza).
   SCALA scala UNA volta tutto l'output finale (scale(SCALA) in fondo).
   Con 1/75 l'albero e' ~9.8 unita' (~5x il cubo base di Blender = 2 unita'):
   lettura naturale "1 unita' ~ 1 metro" = noce moscata adulta (5-13 m).
     • albero piu' PICCOLO  -> aumenta il divisore (es. 1/120 ~ 6 unita')
     • scala fisica di stampa (OpenSCAD = mm) -> SCALA = 1  (ingombro in mm)
   Nota: scale() agisce DOPO la mesh, quindi i facet restano a piena
   risoluzione e la levigatezza non si perde. */
SCALA = 1/75;

/* ====== VELOCITA' F6 (CGAL) — LEGGERE =====================================
   F5 (anteprima) e' sempre istantaneo. Per un F6 (render/STL) RAPIDO conta il
   BACKEND geometrico di OpenSCAD:
     • OpenSCAD recente (>= 2023.06): abilita il backend MANIFOLD
         Preferenze ▸ Features ▸ "Manifold"  (nelle build 2025 e' gia' di default)
       -> l'unione di centinaia di foglie diventa un F6 di ~1 secondo, anche
          alzando i parametri di dettaglio qui sotto.
     • OpenSCAD vecchio (backend CGAL-Nef, es. 2021): l'unione di molti solidi
       e' quasi-quadratica e resta lenta per QUALSIASI albero con foglie: in tal
       caso aggiorna OpenSCAD, oppure usa il PRESET TURBO qui sotto.
   Questo modello e' comunque gia' ottimizzato: SOLE primitive, ZERO booleane. */

/* ====== PERFORMANCE / DETTAGLIO ============================================
   Governano il tempo di F6. I default sono un buon compromesso (con Manifold
   sono istantanei). Per una chioma piu' folta aumenta FOGLIE, poi MAIN /
   RAMIFICAZ / PROFONDITA.
   PRESET TURBO (F6 piu' rapido possibile, chioma rada, utile su backend Nef):
       PROFONDITA=2  RAMIFICAZ=2  MAIN=2  FOGLIE=3  FACET_SFERA=8  FACET_RAMO=5 */
PROFONDITA  = 2;    // livelli di ramificazione (il piu' incisivo sul tempo)
RAMIFICAZ   = 3;    // rami figli per nodo
MAIN        = 3;    // rami primari (oltre alla cima centrale)
FOGLIE      = 5;    // foglie per ciuffo apicale
FACET_SFERA = 12;   // $fn dei frutti
FACET_RAMO  = 7;    // $fn di rami e tronco
FOGLIA_N    = 11;   // vertici del profilo fogliare (per lato)
TERRENO     = true; // disco di terreno sotto l'albero

SEED = 42;          // seme casuale globale (riproducibile: stesso seme=stesso albero)

/* ====== FORMA ============================================================== */
TRONCO_H    = 240;
TRONCO_R    = 16;
FOGLIA_L    = 50;     // lunghezza foglia
FOGLIA_W    = 20;     // larghezza foglia
FOGLIA_SP   = 0.8;    // spessore lamina
FRUTTO_R    = 6;      // raggio frutto sull'albero (ridotto: prima 10, ~10x reale)
FRUTTO_Z    = 1.10;   // leggero allungamento (forma ovoide)
PROB_FRUTTO = 0.35;   // probabilita' di frutto su un apice [0..1]

/* ====== COLORI ============================================================= */
C_LEGNO   = [0.36, 0.25, 0.13];
C_LEGNO_S = [0.30, 0.21, 0.11];
C_FOGLIA  = [0.13, 0.35, 0.13];
C_FRUTTO  = [0.86, 0.72, 0.32];
C_TERRENO = [0.34, 0.28, 0.18];

// ---- Profilo 2D della lamina (ellittico-lanceolata) ------------------------
function _profilo(L, W, n) =
    concat(
        [ for (i=[0:n])    let(f=i/n) [ L*f,  W*pow(sin(180*f),0.8)*(1-0.2*f) ] ],
        [ for (i=[n:-1:0]) let(f=i/n) [ L*f, -W*pow(sin(180*f),0.8)*(1-0.2*f) ] ]
    );

// ---- Foglia: UN solo solido (lamina estrusa), nessuna nervatura ------------
module foglia() {
    color(C_FOGLIA)
        linear_extrude(height=FOGLIA_SP)
            polygon(_profilo(FOGLIA_L, FOGLIA_W, FOGLIA_N));
}

// ---- Frutto: ellissoide + peduncolo. NESSUNA booleana ----------------------
module frutto() {
    color(C_FRUTTO) scale([1,1,FRUTTO_Z]) sphere(r=FRUTTO_R, $fn=FACET_SFERA);
    color(C_LEGNO)  translate([0,0,FRUTTO_R*FRUTTO_Z*0.9])
                        cylinder(h=FRUTTO_R*0.5, r=FRUTTO_R*0.12, $fn=6);
}

// ---- Ciuffo di foglie a spirale (fillotassi) attorno a un apice ------------
module ciuffo(seed) {
    az = rands(-15, 15, FOGLIE, seed);
    dp = rands(35, 72, FOGLIE, seed+1);
    sc = rands(0.75, 1.05, FOGLIE, seed+2);
    for (i=[0:FOGLIE-1])
        rotate([0,0, i*360/FOGLIE + az[i]])
            rotate([0, 55+dp[i], 0]) scale(sc[i]) foglia();
}

// ---- Ramo ricorsivo (solo cilindri; foglie/frutto agli apici) --------------
module ramo(len, rad, liv, seed) {
    color(C_LEGNO) cylinder(h=len, r1=rad, r2=rad*0.70, $fn=FACET_RAMO);
    if (liv > 0)
        translate([0,0,len])
            for (a=[0:RAMIFICAZ-1]) {
                j = rands(-13, 13, 1, seed+a)[0];
                rotate([0,0, a*360/RAMIFICAZ + liv*23 + j])
                    rotate([30+(PROFONDITA-liv)*3, 0, 0])
                        ramo(len*0.72, rad*0.66, liv-1, seed*3+a+1);
            }
    else
        translate([0,0,len]) {
            ciuffo(seed);
            if (rands(0,1,1,seed+99)[0] < PROB_FRUTTO)
                translate([0,0,-FRUTTO_R*0.4]) rotate([180,0,0])
                    translate([0,0, FRUTTO_R*FRUTTO_Z]) frutto();
        }
}

// ---- Tronco con svasatura radicale ----------------------------------------
module tronco() {
    color(C_LEGNO_S)
        for (a=[0:60:300])
            rotate([0,0,a]) translate([TRONCO_R*0.8,0,6])
                rotate([12,0,0]) cylinder(h=26, r1=TRONCO_R*0.42, r2=2, $fn=6);
    color(C_LEGNO)
        cylinder(h=TRONCO_H, r1=TRONCO_R, r2=TRONCO_R*0.72, $fn=FACET_RAMO+3);
}

// ---- Albero completo -------------------------------------------------------
module albero() {
    if (TERRENO)
        color(C_TERRENO) translate([0,0,-3]) cylinder(h=3, r=TRONCO_H*0.70, $fn=48);
    tronco();
    translate([0,0,TRONCO_H]) {
        for (a=[0:MAIN-1])
            rotate([0,0, a*360/MAIN + 15]) rotate([30,0,0])
                ramo(TRONCO_H*0.55, TRONCO_R*0.70, PROFONDITA, a+7);
        rotate([6,0,0]) ramo(TRONCO_H*0.72, TRONCO_R*0.72, PROFONDITA, 99); // cima
    }
}

// ---- Output finale, scalato per i software 3D ------------------------------
scale(SCALA) albero();
