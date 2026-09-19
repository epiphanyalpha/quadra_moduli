# -*- coding: utf-8 -*-
"""Il contratto dei sei tipi di campo: come si scrive, come si verifica.

Questa e' l'unica libreria comune. Non sa niente di moduli, enti o clienti (V3),
e nessuno script ne importa un altro (V2): gli script importano solo questo file.

Un tipo di campo esiste qui se e solo se porta con se' due cose:

    scrivi(pagina, ancora, valore)            -> come si scrive quel tipo
    verifica(prima, dopo, ancora, valore)     -> la post-condizione di quel tipo

La lista e' chiusa a sei. Un modo nuovo di riconoscere un quadratino e' un
rilevatore in piu' nel motore, non un tipo in piu' qui: il tipo e' definito da
come si scrive e come si verifica, non da come lo si riconosce.

Due regole che valgono per tutti i tipi:

  * non si tronca e non si stima in silenzio. Se il valore non entra, la
    scrittura fallisce e lo dice: un campo lasciato vuoto e' normale, un campo
    sbagliato senza avviso no.
  * la geometria arriva gia' misurata dentro l'ancora. Qui non si stima mai un
    rettangolo a partire da un carattere o da un'etichetta.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

import fitz

TIPI = ("widget", "celle", "casella", "riempimento", "tratto", "area")

CARATTERE = "helv"          # base-14: nessun font da incorporare, latino completo
DPI_MISURA = 600            # per misurare inchiostro su forme piccole
DPI_CONTROLLO = 300         # per le post-condizioni su aree grandi
SOGLIA_SCURO = 160          # 0 = nero, 255 = bianco


# ---------------------------------------------------------------- dati comuni

@dataclass(frozen=True)
class Ancora:
    """Un posto scrivibile, gia' misurato, con il suo tipo.

    `rect` e' sempre in spazio pagina non ruotato ed e' gia' il bersaglio
    definitivo: per una casella e' il quadrato disegnato misurato, non il
    riquadro del carattere.
    """
    id: str
    tipo: str
    pagina: int
    rect: tuple
    parametri: dict = field(default_factory=dict)
    etichetta: str = ""
    contesto: str = ""

    def __post_init__(self):
        if self.tipo not in TIPI:
            raise ValueError("tipo sconosciuto: %r; i tipi sono %s" % (self.tipo, TIPI))

    @property
    def riquadro(self) -> fitz.Rect:
        return fitz.Rect(self.rect)

    def a_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def da_dict(d: dict) -> "Ancora":
        return Ancora(id=d["id"], tipo=d["tipo"], pagina=d["pagina"],
                      rect=tuple(d["rect"]), parametri=d.get("parametri", {}),
                      etichetta=d.get("etichetta", ""), contesto=d.get("contesto", ""))


@dataclass
class Esito:
    """Esito di una scrittura o di una verifica. `motivo` e' scritto per Bianca."""
    ok: bool
    motivo: str = ""
    misura: dict = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.ok


# -------------------------------------------------------- rotazione e misura

class PagineDiritte:
    """Porta tutte le pagine a rotazione 0 e la ripristina all'uscita.

    Disegni e testo li restituisce PyMuPDF sempre in spazio non ruotato, il
    render no. Lavorando a rotazione 0 esiste un solo sistema di coordinate e
    non servono conversioni sparse per il codice.
    """

    def __init__(self, doc: fitz.Document):
        self.doc = doc
        self._rotazioni = []

    def __enter__(self) -> fitz.Document:
        self._rotazioni = [p.rotation for p in self.doc]
        for p in self.doc:
            if p.rotation:
                p.set_rotation(0)
        return self.doc

    def __exit__(self, *_):
        for p, r in zip(self.doc, self._rotazioni):
            if r:
                p.set_rotation(r)
        return False


SOGLIA_CACHE = 4            # dopo quante misure sulla stessa pagina conviene tenerla
DPI_CACHE = 320             # oltre questa risoluzione il ritaglio costa meno
_conta_misure = {}
_pagine_rese = {}


def _chiave(pagina: fitz.Page, dpi: int):
    return (id(pagina.parent), pagina.number, dpi, pagina.rotation)


def svuota_misure(pagina: fitz.Page = None):
    """Butta le pagine gia' renderizzate. Va chiamata appena si scrive.

    La cache vale finche' la pagina non cambia: misurare su un render vecchio
    direbbe che una scrittura non c'e'."""
    if pagina is None:
        _pagine_rese.clear()
        _conta_misure.clear()
        return
    for dpi in (DPI_MISURA, DPI_CONTROLLO, 150, 200):
        _pagine_rese.pop(_chiave(pagina, dpi), None)
        _conta_misure.pop(_chiave(pagina, dpi), None)


def _scandisci(pm, colonne, righe, soglia: int):
    """Il riquadro dei pixel scuri dentro una finestra del pixmap, e quanti."""
    dati, passo, n = pm.samples, pm.stride, pm.n
    x0, x1 = colonne
    y0, y1 = righe
    cx0, cy0, cx1, cy1, conta = x1, y1, -1, -1, 0
    for riga in range(y0, y1):
        base = riga * passo + x0 * n
        striscia = dati[base:base + (x1 - x0) * n:n]
        if not striscia or min(striscia) >= soglia:
            continue
        if riga < cy0:
            cy0 = riga
        cy1 = riga
        for indice, valore in enumerate(striscia):
            if valore < soglia:
                conta += 1
                col = x0 + indice
                if col < cx0:
                    cx0 = col
                if col > cx1:
                    cx1 = col
    if conta == 0:
        return None, 0
    return (cx0, cy0, cx1, cy1), conta


def inchiostro(pagina: fitz.Page, rect, dpi: int = DPI_CONTROLLO,
               soglia: int = SOGLIA_SCURO):
    """Misura l'inchiostro dentro `rect`: (riquadro dei pixel scuri, quanti).

    E' l'unica primitiva di misura del progetto: la usano il classificatore per
    misurare un quadratino e il controllo per verificare ogni tipo. Misurare,
    non stimare.

    Ritagliare il render campo per campo fa ridisegnare la pagina a ogni misura,
    e su un modulo fitto sono centinaia di volte. Dopo qualche misura sulla
    stessa pagina conviene tenersela intera e leggerne le finestre: e' la stessa
    misura, pagata una volta.
    """
    r = fitz.Rect(rect) & pagina.rect
    if r.is_empty or r.width <= 0 or r.height <= 0:
        return None, 0
    k = dpi / 72.0
    chiave = _chiave(pagina, dpi)
    _conta_misure[chiave] = _conta_misure.get(chiave, 0) + 1

    # Ad alta risoluzione la pagina intera costa piu' di tanti ritagli: MuPDF
    # rasterizza solo il ritaglio, e un A4 a 600 dpi e' 35 MB da disegnare.
    # La pagina tenuta da parte conviene solo dove il render e' leggero.
    if dpi <= DPI_CACHE and _conta_misure[chiave] >= SOGLIA_CACHE:
        pm = _pagine_rese.get(chiave)
        if pm is None:
            pm = pagina.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, annots=True)
            if len(_pagine_rese) >= 3:
                _pagine_rese.clear()
            _pagine_rese[chiave] = pm
        colonne = (max(0, int(r.x0 * k) - pm.x),
                   min(pm.width, int(r.x1 * k) + 1 - pm.x))
        righe = (max(0, int(r.y0 * k) - pm.y),
                 min(pm.height, int(r.y1 * k) + 1 - pm.y))
        if colonne[1] <= colonne[0] or righe[1] <= righe[0]:
            return None, 0
    else:
        pm = pagina.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, clip=r, annots=True)
        colonne, righe = (0, pm.width), (0, pm.height)
        if pm.width == 0 or pm.height == 0:
            return None, 0

    finestra, conta = _scandisci(pm, colonne, righe, soglia)
    if conta == 0:
        return None, 0
    cx0, cy0, cx1, cy1 = finestra
    return fitz.Rect((pm.x + cx0) / k, (pm.y + cy0) / k,
                     (pm.x + cx1 + 1) / k, (pm.y + cy1 + 1) / k), conta


def _corona(r: fitz.Rect, spessore: float):
    """I quattro rettangoli attorno a `r`: servono a dire 'fuori non si tocca'."""
    e = fitz.Rect(r.x0 - spessore, r.y0 - spessore, r.x1 + spessore, r.y1 + spessore)
    return [fitz.Rect(e.x0, e.y0, e.x1, r.y0),
            fitz.Rect(e.x0, r.y1, e.x1, e.y1),
            fitz.Rect(e.x0, r.y0, r.x0, r.y1),
            fitz.Rect(r.x1, r.y0, e.x1, r.y1)]


def _conta(pagina, rect, dpi, soglia=SOGLIA_SCURO) -> int:
    return inchiostro(pagina, rect, dpi=dpi, soglia=soglia)[1]


def _sbordo(prima, dopo, r: fitz.Rect, spessore: float, dpi: int, altrui=()) -> int:
    """Quanto inchiostro nuovo e' finito attorno al campo *senza appartenere a
    nessun altro campo*.

    Due campi confinanti si toccano: il testo del vicino cade dentro la corona
    di questo. Senza questa sottrazione ogni riga piena di campi affiancati
    produrrebbe errori inventati, e un controllo che grida al lupo si smette di
    leggere - che e' il modo piu' rapido di perdere gli errori veri.
    """
    totale = 0
    for pezzo in _corona(r, spessore):
        guadagno = _aumento(prima, dopo, pezzo, dpi)
        if guadagno <= 0:
            continue
        for a in altrui:
            comune = fitz.Rect(pezzo) & fitz.Rect(a)
            if comune.is_empty or comune.width <= 0 or comune.height <= 0:
                continue
            guadagno -= max(0, _aumento(prima, dopo, comune, dpi))
        totale += max(0, guadagno)
    return totale


def _righe_con_inchiostro_nuovo(prima, dopo, rect, dpi: int, soglia: int):
    """Le righe di pixel dove e' comparso qualcosa, e quanto inchiostro c'era
    gia' su quelle stesse righe.

    Serve a misurare la leggibilita', che non e' la stessa cosa della
    correttezza: un valore scritto sulla riga dei puntini e' nel campo giusto,
    si rilegge anche dal testo, e a occhio e' un pasticcio. Se le lettere
    occupano le stesse righe dei puntini, sono mescolate a quelli.
    """
    r = fitz.Rect(rect)
    pa = prima.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, clip=r, annots=True)
    pb = dopo.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, clip=r, annots=True)
    if pa.width != pb.width or pa.height != pb.height or pa.width == 0:
        return 0, 0
    da, db = pa.samples, pb.samples
    na, nb = pa.n, pb.n
    nuovi = vecchi = 0
    for riga in range(pb.height):
        base_a = riga * pa.stride
        base_b = riga * pb.stride
        sa = da[base_a:base_a + pa.width * na:na]
        sb = db[base_b:base_b + pb.width * nb:nb]
        nuovi_riga = sum(1 for i in range(len(sb))
                         if sb[i] < soglia <= sa[i])
        if not nuovi_riga:
            continue
        nuovi += nuovi_riga
        vecchi += sum(1 for v in sa if v < soglia)
    return nuovi, vecchi


SOVRAPPOSTO = 0.12
"""Quanto inchiostro gia' stampato puo' condividere le righe del valore.

Misurato scrivendo gli stessi valori nei due modi sullo stesso modulo: sopra i
riempitivi il rapporto sta fra 0,00 e 0,01, sopra i riempitivi in senso di
addosso sta fra 0,27 e 1,18. Fra i due casi c'e' un ordine di grandezza, e la
soglia sta comoda in mezzo: non e' un numero scelto, e' un numero misurato.
"""


def _illeggibile(prima, dopo, banda) -> str:
    """Il valore c'e' ed e' nel posto giusto: si riesce anche a leggere?

    Essere nel campo giusto e rileggersi dal testo non basta. Un valore scritto
    sulla riga dei puntini supera tutte e due le prove e a occhio e' un
    pasticcio - ed e' proprio il difetto che questo progetto ha gia' trovato
    guardando una pagina, senza poi saperlo misurare.
    """
    nuovi, vecchi = _righe_con_inchiostro_nuovo(prima, dopo, banda,
                                                DPI_CONTROLLO, SOGLIA_SCURO)
    if nuovi and vecchi > nuovi * SOVRAPPOSTO:
        return ("il valore si mescola a quello che il modulo ha gia' stampato: "
                "e' nel posto giusto ma si legge male")
    return ""


def larghezza_testo(testo: str, dimensione: float, carattere: str = CARATTERE) -> float:
    return fitz.get_text_length(testo, fontname=carattere, fontsize=dimensione)


def _testo_in(pagina: fitz.Page, rect) -> str:
    return pagina.get_text("text", clip=fitz.Rect(rect)) or ""


def _semplice(t: str) -> str:
    return "".join(c for c in t.casefold() if c.isalnum())


# -------------------------------------------------------------- le scritture

def scrivi(pagina: fitz.Page, ancora: Ancora, valore) -> Esito:
    """Scrive `valore` secondo il tipo dell'ancora. Unico ingresso."""
    svuota_misure(pagina)          # la pagina cambia: i render fatti non valgono piu'
    return _SCRITTURE[ancora.tipo](pagina, ancora, valore)


def _scrivi_celle(pagina, ancora, valore) -> Esito:
    celle = [fitz.Rect(c) for c in ancora.parametri["celle"]]
    testo = "" if valore is None else str(valore)
    if not testo:
        return Esito(False, "valore vuoto")
    if len(testo) > len(celle):
        return Esito(False, "il valore ha %d caratteri e le celle sono %d: non si tronca"
                     % (len(testo), len(celle)))
    for segno, cella in zip(testo, celle):
        if segno == " ":
            continue
        dim = min(cella.height * 0.62, cella.width * 1.15)
        while dim > 3 and larghezza_testo(segno, dim) > cella.width * 0.74:
            dim -= 0.25
        larg = larghezza_testo(segno, dim)
        x = cella.x0 + (cella.width - larg) / 2.0
        y = cella.y0 + (cella.height + dim * 0.72) / 2.0
        pagina.insert_text((x, y), segno, fontname=CARATTERE, fontsize=dim,
                           color=(0, 0, 0))
    return Esito(True, "%d caratteri in %d celle" % (len(testo), len(celle)))


def _scrivi_casella(pagina, ancora, valore) -> Esito:
    if not isinstance(valore, bool):
        return Esito(False, "una casella richiede True o False, non testo o numeri")
    if not valore:
        return Esito(True, "lasciata vuota")
    r = ancora.riquadro
    lato = min(r.width, r.height)
    if lato <= 0:
        return Esito(False, "quadrato non misurato")
    m = lato * 0.22                      # il segno resta dentro il quadrato
    spessore = max(0.55, lato * 0.13)
    d = fitz.Rect(r.x0 + m, r.y0 + m, r.x1 - m, r.y1 - m)
    pagina.draw_line((d.x0, d.y0), (d.x1, d.y1), color=(0, 0, 0), width=spessore)
    pagina.draw_line((d.x0, d.y1), (d.x1, d.y0), color=(0, 0, 0), width=spessore)
    return Esito(True, "crocetta in un quadrato di %.1f pt" % lato)


# Misurati sul modulo compilato a regola d'arte: il valore comincia 2,5 pt dopo
# l'inizio della riga e sta 4,13 pt sopra la base dei puntini, a corpo 7.
INSETTO_RIGA = 2.4


def _senza_eco(testo: str, etichetta: str):
    """Toglie dal valore l'etichetta che il modulo ha gia' stampato accanto.

    Il modulo stampa un'etichetta e poi la riga da riempire; il fascicolo spesso
    conserva il valore con l'etichetta gia' dentro. Scritti uno dopo l'altro si
    legge la stessa parola due volte. La regola confronta soltanto l'etichetta
    misurata con il valore - non sa che cosa significhino - e dice sempre che
    cosa ha tolto.
    """
    breve = etichetta.strip(" .:_-/")
    testo_pulito = testo.lstrip()
    if len(breve) < 2 or len(testo_pulito) <= len(breve):
        return testo, ""
    if testo_pulito[:len(breve)].casefold() != breve.casefold():
        return testo, ""
    if testo_pulito[len(breve)].isalnum():
        return testo, ""
    resto = testo_pulito[len(breve):].lstrip(" .:,/")
    return (resto, breve) if resto else (testo, "")


def _scrivi_su_riga(pagina, ancora, valore, alzata_minima: float) -> Esito:
    r = ancora.riquadro
    testo = "" if valore is None else str(valore)
    if not testo:
        return Esito(False, "valore vuoto")
    testo, eco = _senza_eco(testo, ancora.etichetta)
    dim = float(ancora.parametri.get("dimensione", 8.0))
    minima = 5.0
    larghezza_utile = r.width - INSETTO_RIGA - 0.6
    while dim > minima and larghezza_testo(testo, dim) > larghezza_utile:
        dim -= 0.25
    if larghezza_testo(testo, dim) > larghezza_utile:
        return Esito(False, "il valore non entra: servono %.0f pt su %.0f"
                     % (larghezza_testo(testo, minima), larghezza_utile))
    # l'alzata la misura il classificatore sulla pagina: dove c'e' spazio il
    # valore sta sopra la riga come su un modulo compilato bene, dove non ce
    # n'e' sta piu' basso invece di finire addosso alla riga di sopra
    alzata = float(ancora.parametri.get("alzata", alzata_minima))
    base = float(ancora.parametri.get("base", r.y1)) - alzata
    pagina.insert_text((r.x0 + INSETTO_RIGA, base), testo, fontname=CARATTERE,
                       fontsize=dim, color=(0, 0, 0))
    detto = "scritto a %.1f pt sulla riga" % dim
    if eco:
        detto += "; tolta l'eco dell'etichetta %r gia' stampata dal modulo" % eco
    return Esito(True, detto)


def _scrivi_riempimento(pagina, ancora, valore) -> Esito:
    return _scrivi_su_riga(pagina, ancora, valore, alzata_minima=0.4)


def _scrivi_tratto(pagina, ancora, valore) -> Esito:
    return _scrivi_su_riga(pagina, ancora, valore, alzata_minima=1.6)


def _scrivi_area(pagina, ancora, valore) -> Esito:
    r = ancora.riquadro
    testo = "" if valore is None else str(valore)
    if not testo:
        return Esito(False, "valore vuoto")
    dentro = fitz.Rect(r.x0 + INSETTO_RIGA, r.y0 + 0.8,
                       r.x1 - INSETTO_RIGA, r.y1 - 0.8)
    dim = min(float(ancora.parametri.get("dimensione", 9.0)), dentro.height * 0.86)
    # Un valore che sta su una riga sola si centra in altezza, come lo
    # scriverebbe una persona: appoggiato in alto il riquadro sembra sfuggito,
    # non compilato.
    if larghezza_testo(testo, dim) <= dentro.width:
        base = (r.y0 + r.y1) / 2.0 + dim * 0.34
        pagina.insert_text((dentro.x0, base), testo, fontname=CARATTERE,
                           fontsize=dim, color=(0, 0, 0))
        return Esito(True, "scritto a %.1f pt, centrato nel riquadro" % dim)
    while dim >= 4.5:
        if pagina.insert_textbox(dentro, testo, fontname=CARATTERE, fontsize=dim,
                                 align=0, color=(0, 0, 0)) >= 0:
            return Esito(True, "scritto a %.1f pt dentro il riquadro" % dim)
        dim -= 0.25
    return Esito(False, "il valore non entra nel riquadro nemmeno a 4,5 pt")


def _scrivi_widget(pagina, ancora, valore) -> Esito:
    bersaglio = ancora.parametri.get("nome")
    for w in pagina.widgets():
        if w.field_name != bersaglio:
            continue
        if w.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
            if not isinstance(valore, bool):
                return Esito(False, "una casella richiede True o False, non testo o numeri")
            w.field_value = w.on_state() if valore else "Off"
        else:
            w.field_value = "" if valore is None else str(valore)
        w.update()
        return Esito(True, "campo %r valorizzato" % bersaglio)
    return Esito(False, "campo %r non trovato nella pagina" % bersaglio)


_SCRITTURE = {"celle": _scrivi_celle, "casella": _scrivi_casella,
              "riempimento": _scrivi_riempimento, "tratto": _scrivi_tratto,
              "area": _scrivi_area, "widget": _scrivi_widget}


# -------------------------------------------------------------- le verifiche

def verifica(prima: fitz.Page, dopo: fitz.Page, ancora: Ancora, valore,
             altrui=()) -> Esito:
    """Riapre il risultato e controlla la post-condizione del tipo.

    Non guarda mai quello che la scrittura ha dichiarato: confronta il documento
    prima e dopo. E' questa indipendenza che produce il numero degli errori non
    segnalati.

    `altrui` sono i riquadri degli altri campi scritti nella stessa pagina:
    servono a non attribuire a questo campo l'inchiostro del campo accanto.
    """
    return _VERIFICHE[ancora.tipo](prima, dopo, ancora, valore, tuple(altrui))


def _aumento(prima, dopo, rect, dpi) -> int:
    return _conta(dopo, rect, dpi) - _conta(prima, rect, dpi)


def _verifica_celle(prima, dopo, ancora, valore, altrui=()) -> Esito:
    """Tre condizioni, tutte e tre misurate: ogni carattere previsto ha lasciato
    inchiostro nella sua cella, nessuna cella di troppo si e' sporcata, e nessun
    divisore e' stato scavalcato. La terza e' quella che coglie il difetto
    classico: un blocco di testo unico scritto sopra la fila."""
    celle = [fitz.Rect(c) for c in ancora.parametri["celle"]]
    testo = str(valore or "")
    vuote, invase, scavalcati = [], [], []
    for i, cella in enumerate(celle):
        atteso = i < len(testo) and testo[i] != " "
        dentro = fitz.Rect(cella.x0 + 0.6, cella.y0, cella.x1 - 0.6, cella.y1)
        guadagno = _aumento(prima, dopo, dentro, DPI_MISURA)
        if atteso and guadagno <= 0:
            vuote.append(i + 1)
        elif not atteso and guadagno > 2:
            invase.append(i + 1)
        if i:
            x = cella.x0
            divisorio = fitz.Rect(x - 0.6, cella.y0 + 0.6, x + 0.6, cella.y1 - 0.6)
            if _aumento(prima, dopo, divisorio, DPI_MISURA) > 2:
                scavalcati.append(i)
    guai = []
    if scavalcati:
        guai.append("caratteri a cavallo di %d divisori su %d"
                    % (len(scavalcati), len(celle) - 1))
    if vuote:
        guai.append("celle rimaste vuote: %s" % vuote)
    if invase:
        guai.append("celle sporcate senza motivo: %s" % invase)
    if guai:
        return Esito(False, "; ".join(guai),
                     {"scavalcati": scavalcati, "vuote": vuote, "invase": invase})
    return Esito(True, "%d caratteri, nessuno a cavallo dei divisori" % len(testo),
                 {"celle": len(celle)})


def _verifica_casella(prima, dopo, ancora, valore, altrui=()) -> Esito:
    if not isinstance(valore, bool):
        return Esito(False, "una casella richiede True o False, non testo o numeri")
    r = ancora.riquadro
    dentro = fitz.Rect(r.x0 + 0.4, r.y0 + 0.4, r.x1 - 0.4, r.y1 - 0.4)
    guadagno = _aumento(prima, dopo, dentro, DPI_MISURA)
    sbordo = _sbordo(prima, dopo, r, 1.5, DPI_MISURA, altrui)
    if not valore:
        if guadagno > 2 or sbordo > 2:
            return Esito(False, "la casella doveva restare vuota")
        return Esito(True, "vuota come previsto")
    area_px = (r.width * r.height) * (DPI_MISURA / 72.0) ** 2
    if guadagno < area_px * 0.02:
        return Esito(False, "nessun segno dentro il quadrato")
    if sbordo > max(6, area_px * 0.01):
        return Esito(False, "segno fuori dal quadrato (%d pixel intorno)" % sbordo)
    return Esito(True, "crocetta dentro il quadrato, niente fuori",
                 {"pixel_dentro": guadagno, "pixel_fuori": sbordo})


def _verifica_riga(prima, dopo, ancora, valore, altezza: float, altrui=()) -> Esito:
    r = ancora.riquadro
    banda = fitz.Rect(r.x0 - 0.5, r.y0 - altezza, r.x1 + 0.5, r.y1 + 1.0)
    if _aumento(prima, dopo, banda, DPI_CONTROLLO) <= 0:
        return Esito(False, "niente di scritto sulla riga")
    atteso, _ = _senza_eco(str(valore or ""), ancora.etichetta)
    testo = _semplice(atteso)
    letto = _semplice(_testo_in(dopo, banda))
    if testo and testo not in letto:
        return Esito(False, "il valore non si rilegge dalla riga")
    if _sbordo(prima, dopo, r, 2.0, DPI_CONTROLLO, altrui) > 8:
        return Esito(False, "il testo esce dalla riga: finisce sull'etichetta o "
                            "sul campo accanto")
    guaio = _illeggibile(prima, dopo, banda)
    if guaio:
        return Esito(False, guaio)
    return Esito(True, "valore rileggibile sulla riga")


def _verifica_riempimento(prima, dopo, ancora, valore, altrui=()) -> Esito:
    return _verifica_riga(prima, dopo, ancora, valore, 2.0, altrui)


def _verifica_tratto(prima, dopo, ancora, valore, altrui=()) -> Esito:
    return _verifica_riga(prima, dopo, ancora, valore, 10.0, altrui)


def _verifica_area(prima, dopo, ancora, valore, altrui=()) -> Esito:
    r = ancora.riquadro
    dentro = fitz.Rect(r.x0 + 0.5, r.y0 + 0.3, r.x1 - 0.5, r.y1 - 0.3)
    if _aumento(prima, dopo, dentro, DPI_CONTROLLO) <= 0:
        return Esito(False, "il riquadro e' rimasto vuoto")
    sbordo = _sbordo(prima, dopo, r, 2.0, DPI_CONTROLLO, altrui)
    if sbordo > 8:
        return Esito(False, "scritto fuori dal riquadro (%d pixel intorno)" % sbordo)
    testo = _semplice(str(valore or ""))
    letto = _semplice(_testo_in(dopo, fitz.Rect(r.x0 - 1, r.y0 - 1, r.x1 + 1, r.y1 + 1)))
    if testo and testo not in letto:
        return Esito(False, "il valore non si rilegge dal riquadro")
    guaio = _illeggibile(prima, dopo, dentro)
    if guaio:
        return Esito(False, guaio)
    return Esito(True, "valore rileggibile dentro il riquadro")


def _verifica_widget(prima, dopo, ancora, valore, altrui=()) -> Esito:
    bersaglio = ancora.parametri.get("nome")
    for w in dopo.widgets():
        if w.field_name == bersaglio:
            if w.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
                if not isinstance(valore, bool):
                    return Esito(False, "una casella richiede True o False, non testo o numeri")
                atteso = w.on_state() if valore else "Off"
            else:
                atteso = "" if valore is None else str(valore)
            if w.field_value == atteso or str(w.field_value) == str(atteso):
                return Esito(True, "campo valorizzato")
            return Esito(False, "il campo vale %r, atteso %r" % (w.field_value, atteso))
    return Esito(False, "campo %r sparito dal documento" % bersaglio)


_VERIFICHE = {"celle": _verifica_celle, "casella": _verifica_casella,
              "riempimento": _verifica_riempimento, "tratto": _verifica_tratto,
              "area": _verifica_area, "widget": _verifica_widget}


# ----------------------------------------------------------------- impronta

def firmato(percorso) -> bool:
    """Il PDF porta gia' una firma digitale applicata.

    Non e' una questione di livelli sovrapposti: la firma copre un intervallo di
    byte del file, e qualunque scrittura - anche una lettera - cambia quei byte
    e la rende non valida. Su un documento gia' firmato non si scrive: si
    compila prima e si firma dopo.

    Il segno e' `/ByteRange`, che compare solo quando la firma e' stata
    davvero apposta. Un campo firma ancora vuoto non ce l'ha, e quel documento
    si puo' compilare tranquillamente.
    """
    from pathlib import Path as _Path
    with open(_Path(percorso), "rb") as f:
        return b"/ByteRange" in f.read()


def impronta(percorso) -> str:
    """SHA-256 del file: uno script si rifiuta di girare su un'edizione diversa."""
    import hashlib
    h = hashlib.sha256()
    with open(percorso, "rb") as f:
        for pezzo in iter(lambda: f.read(1 << 16), b""):
            h.update(pezzo)
    return h.hexdigest()
