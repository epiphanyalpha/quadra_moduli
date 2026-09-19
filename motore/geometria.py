# -*- coding: utf-8 -*-
"""Le evidenze misurate di una pagina, prima di qualunque interpretazione.

Qui non si decide che cosa sia un campo: si raccoglie soltanto quello che la
pagina contiene davvero, da tutte e tre le fonti, perche' nessuna da sola basta.

  * i tracciati vettoriali (`get_drawings`), che non dipendono dalla risoluzione
    e sono l'unico posto dove si vedono i divisori di una fila di celle;
  * il testo a livello di *carattere*, perche' un solo span puo' contenere due
    campi distinti;
  * il render, usato solo per misurare inchiostro, mai per riconoscere.

Nessuna funzione di questo file sa che cosa sia un modulo, un ente o un cliente.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import fitz

TOLLERANZA = 0.8          # due tracciati entro 0,8 pt sono lo stesso tracciato
SPESSORE_MASSIMO = 3.0    # oltre questo un "tratto" e' una fascia, non una linea


# --------------------------------------------------------------- strumenti

def raggruppa(valori, tolleranza: float = TOLLERANZA):
    """Raggruppa valori vicini e restituisce (rappresentante, [valori])."""
    gruppi = []
    for v in sorted(valori):
        if gruppi and v - gruppi[-1][-1] <= tolleranza:
            gruppi[-1].append(v)
        else:
            gruppi.append([v])
    return [(sum(g) / len(g), g) for g in gruppi]


def _unisci_intervalli(intervalli, gioco: float = 1.0):
    fusi = []
    for a, b in sorted(intervalli):
        if fusi and a - fusi[-1][1] <= gioco:
            fusi[-1][1] = max(fusi[-1][1], b)
        else:
            fusi.append([a, b])
    return [tuple(x) for x in fusi]


@dataclass
class Segmento:
    posizione: float      # x per i verticali, y per gli orizzontali
    da: float
    a: float

    @property
    def lunghezza(self) -> float:
        return self.a - self.da

    def copre(self, da: float, a: float, margine: float = 0.6) -> bool:
        return self.da <= da + margine and self.a >= a - margine


@dataclass
class Carattere:
    testo: str
    riquadro: fitz.Rect          # riquadro di riga del glifo (serve come ritaglio)
    origine: tuple               # punto di base
    dimensione: float
    carattere: str               # nome del font
    riga: int                    # indice della riga di testo che lo contiene


@dataclass
class Riga:
    indice: int
    testo: str
    riquadro: fitz.Rect
    base: float
    dimensione: float


@dataclass
class Cella:
    riquadro: fitz.Rect
    riga: int                    # indice della banda orizzontale
    colonna: int


@dataclass
class Pagina:
    """Tutto quello che si e' misurato di una pagina, gia' in spazio diritto."""
    numero: int
    riquadro: fitz.Rect
    verticali: list = field(default_factory=list)
    orizzontali: list = field(default_factory=list)
    rettangoli: list = field(default_factory=list)
    caratteri: list = field(default_factory=list)
    righe: list = field(default_factory=list)
    celle: list = field(default_factory=list)
    widget: list = field(default_factory=list)
    corpo: float = 9.0           # il corpo piu' diffuso nella pagina

    def testo_in(self, rect, margine: float = 0.0) -> str:
        r = fitz.Rect(rect) + (-margine, -margine, margine, margine)
        dentro = [c for c in self.caratteri
                  if fitz.Rect(c.riquadro).intersects(r)
                  and r.contains(fitz.Point(c.origine[0] + 0.1, c.origine[1] - 0.1))]
        dentro.sort(key=lambda c: (c.riga, c.origine[0]))
        pezzi, riga_corrente = [], None
        for c in dentro:
            if riga_corrente is not None and c.riga != riga_corrente:
                pezzi.append(" ")
            pezzi.append(c.testo)
            riga_corrente = c.riga
        return "".join(pezzi).strip()

    def ha_inchiostro(self, rect, dpi: int = 150) -> bool:
        from riusare.strumenti_documento import inchiostro
        return inchiostro(self._pagina, rect, dpi=dpi)[1] > 0

    _pagina: fitz.Page = None


# ------------------------------------------------------------- estrazione

def _tracciati(pagina: fitz.Page):
    """Verticali e orizzontali, dai segmenti e dai lati di ogni rettangolo.

    I lati di un rettangolo pieno contano quanto quelli di uno tracciato: per
    chi guarda la pagina un cambio di fondo e' un bordo come un altro, e certi
    moduli disegnano le tabelle solo con i fondini.
    """
    vert, oriz, rett = [], [], []
    for d in pagina.get_drawings():
        spessore = d.get("width") or 0
        for it in d["items"]:
            if it[0] == "l":
                a, b = it[1], it[2]
                if abs(a.x - b.x) <= TOLLERANZA and abs(a.y - b.y) > TOLLERANZA:
                    vert.append((a.x, min(a.y, b.y), max(a.y, b.y)))
                elif abs(a.y - b.y) <= TOLLERANZA and abs(a.x - b.x) > TOLLERANZA:
                    oriz.append((a.y, min(a.x, b.x), max(a.x, b.x)))
            elif it[0] in ("re", "qu"):
                r = fitz.Rect(it[1]) if it[0] == "re" else fitz.Rect(it[1].rect)
                r.normalize()
                if r.width <= 0 or r.height <= 0:
                    continue
                rett.append({"riquadro": r, "pieno": d.get("fill") is not None,
                             "spessore": spessore})
                if r.height > TOLLERANZA:
                    vert.append((r.x0, r.y0, r.y1))
                    vert.append((r.x1, r.y0, r.y1))
                if r.width > TOLLERANZA:
                    oriz.append((r.y0, r.x0, r.x1))
                    oriz.append((r.y1, r.x0, r.x1))
    return _fondi(vert), _fondi(oriz), rett


def _fondi(grezzi):
    """Un tracciato spezzato in dieci pezzi e' un tracciato solo."""
    per_posizione = {}
    for pos, a, b in grezzi:
        per_posizione.setdefault(pos, []).append((a, b))
    fusi = []
    for rappresentante, membri in raggruppa(list(per_posizione)):
        intervalli = []
        for m in membri:
            intervalli.extend(per_posizione[m])
        for a, b in _unisci_intervalli(intervalli):
            fusi.append(Segmento(rappresentante, a, b))
    return sorted(fusi, key=lambda s: (s.posizione, s.da))


def _testo(pagina: fitz.Page):
    caratteri, righe = [], []
    for blocco in pagina.get_text("rawdict")["blocks"]:
        for linea in blocco.get("lines", []):
            indice = len(righe)
            pezzi, basi, dimensioni = [], [], []
            for span in linea.get("spans", []):
                for ch in span["chars"]:
                    caratteri.append(Carattere(ch["c"], fitz.Rect(ch["bbox"]),
                                               tuple(ch["origin"]), span["size"],
                                               span["font"], indice))
                    pezzi.append(ch["c"])
                    basi.append(ch["origin"][1])
                    dimensioni.append(span["size"])
            if not pezzi:
                continue
            righe.append(Riga(indice, "".join(pezzi), fitz.Rect(linea["bbox"]),
                              sum(basi) / len(basi),
                              max(set(dimensioni), key=dimensioni.count)))
    return caratteri, righe


def _celle(verticali, orizzontali, altezza_minima: float = 3.5,
           larghezza_minima: float = 2.0):
    """Ricostruisce celle delimitate da segmenti connessi localmente.

    E' da qui che arrivano sia le file di celle strette sia le aree libere: la
    stessa costruzione, letta con due misure diverse.
    """
    celle = []
    posizioni_y = [p for p, _ in raggruppa([s.posizione for s in orizzontali])]
    livelli = [[s for s in orizzontali if abs(s.posizione - y) <= TOLLERANZA]
               for y in posizioni_y]
    for i, y0 in enumerate(posizioni_y):
        sopra = livelli[i]
        for j in range(i + 1, len(posizioni_y)):
            y1, sotto = posizioni_y[j], livelli[j]
            if y1 - y0 < altezza_minima:
                continue
            # Solo montanti connessi ai due bordi; linee in altre parti della
            # pagina non dividono la griglia locale.
            montanti = [s for s in verticali if s.copre(y0, y1)
                        and any(t.copre(s.posizione, s.posizione) for t in sopra)
                        and any(t.copre(s.posizione, s.posizione) for t in sotto)]
            xs = [p for p, _ in raggruppa([s.posizione for s in montanti])]
            colonna = 0
            for x0, x1 in zip(xs, xs[1:]):
                if x1 - x0 < larghezza_minima:
                    continue
                if not any(s.copre(x0, x1) for s in sopra):
                    continue
                if not any(s.copre(x0, x1) for s in sotto):
                    continue
                # Non produrre rettangoli che inglobano piu' righe reali.
                if any(s.copre(x0, x1) for livello in livelli[i + 1:j] for s in livello):
                    continue
                celle.append(Cella(fitz.Rect(x0, y0, x1, y1), (i, j), colonna))
                colonna += 1
    # Le bande identificano una coppia di bordi, anche in tabelle affiancate
    # con altezze differenti. Manteniamo l'indice intero usato dai chiamanti.
    bande = {b: n for n, b in enumerate(sorted({c.riga for c in celle}))}
    for c in celle:
        c.riga = bande[c.riga]
    return celle


def leggi(pagina: fitz.Page, numero: int) -> Pagina:
    """Misura una pagina gia' portata a rotazione 0."""
    verticali, orizzontali, rettangoli = _tracciati(pagina)
    caratteri, righe = _testo(pagina)
    corpi = [round(c.dimensione, 1) for c in caratteri if c.testo.isalnum()]
    corpo = max(set(corpi), key=corpi.count) if corpi else 9.0
    p = Pagina(numero=numero, corpo=corpo, riquadro=fitz.Rect(pagina.rect),
               verticali=verticali, orizzontali=orizzontali, rettangoli=rettangoli,
               caratteri=caratteri, righe=righe,
               celle=_celle(verticali, orizzontali),
               widget=list(pagina.widgets()))
    p._pagina = pagina
    return p
