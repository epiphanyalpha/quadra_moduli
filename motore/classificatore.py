# -*- coding: utf-8 -*-
"""La cascata che assegna a ogni posto scrivibile uno dei sei tipi.

Lista chiusa vuol dire **ordine**, non punteggio: il primo tipo che aggancia
vince, e quello che nessuno aggancia resta non classificato. Non esiste un
settimo tipo e non esiste il ripiego "scrivo li' sotto e speriamo": un posto che
non si sa tipizzare e' un posto dove non si scrive.

Ogni tipo puo' avere piu' di un rilevatore - un quadratino puo' essere un glifo
o un tracciato - perche' il tipo dice come si scrive e come si verifica, non
come lo si riconosce. Aggiungere un modo di riconoscere non allarga la lista.

Le soglie qui dentro sono **relative e misurate sulla pagina stessa**: rapporti
fra larghezza e altezza, scarti percentuali dalla mediana, presenza o assenza di
inchiostro. Non c'e' nessun numero scelto a occhio per un modulo particolare, e
non c'e' nessun elenco di casi noti: e' questo che impedisce alla toppa su
misura di avere un posto dove stare.
"""
from __future__ import annotations

import re

import fitz

from riusare.strumenti_documento import Ancora, inchiostro
from motore import geometria

# --- rapporti, non misure assolute -------------------------------------------
SCARTO_PASSO = 0.10         # quanto puo' variare la larghezza dentro una fila
CELLA_SNELLA = 1.6          # una cella da un carattere e' al piu' 1,6 volte alta
MINIMO_CELLE = 3            # meno di tre celle uguali non fanno una fila
RUN_RIEMPIMENTO = 4         # quanti riempitivi uguali fanno una riga da compilare
SQUADRATURA = 0.25          # quanto un quadratino puo' essere fuori squadra
SQUADRATURA_GREZZA = 0.60   # al primo stadio si scarta solo l'evidente
DPI_GREZZO = 300            # primo stadio: dentro la cache, quindi gratis
LATO_MINIMO = 2.0           # un quadratino piu' piccolo di cosi' non e' un campo
LATO_MASSIMO = 16.0         # piu' grande e' un riquadro, non una casella
PIENO = 0.12                # oltre questa densita' interna e' un segno, non una casella
ANTICIPO_GLIFO = 0.45       # avanzamento minimo (in frazione di corpo) da misurare
AREA_LARGHEZZA_MINIMA = 18.0
AREA_ALTEZZA_MINIMA = 6.0
SOVRAPPOSIZIONE_MASSIMA = 0.35
# Sul modulo compilato a regola d'arte il valore sta *sopra* i puntini, non
# sopra i puntini in senso di sovrapposto: alzato di 4,13 pt su un corpo 7,
# cioe' 0,59 volte il corpo. Scritto sulla stessa base, le lettere e i punti si
# mescolano e il valore diventa faticoso da leggere.
ALZATA = 0.59
ASCENDENTE = 0.80          # quanto sale una maiuscola sopra la base
DISCENDENTE = 0.28         # quanto scende la coda di una 'p' sotto la base


class Presa:
    """Tiene il conto di che cosa e' gia' stato rivendicato da un tipo prima."""

    def __init__(self):
        self.prese = []

    def libero(self, r: fitz.Rect) -> bool:
        superficie = r.get_area()
        if superficie <= 0:
            return False
        for altro in self.prese:
            comune = (fitz.Rect(r) & altro).get_area()
            if comune > superficie * SOVRAPPOSIZIONE_MASSIMA:
                return False
        return True

    def prendi(self, r: fitz.Rect):
        self.prese.append(fitz.Rect(r))


def _id(pagina: int, tipo: str, x: float, y: float) -> str:
    """L'identificativo nasce da un fatto della pagina, mai dal rettangolo in
    cui abbiamo deciso di scrivere.

    Il rettangolo di scrittura e' una nostra convenzione e cambia quando la
    convenzione migliora; il punto di partenza dei puntini, il quadrato
    disegnato, la cella della griglia stanno nel modulo e non si muovono. Se
    l'identificativo seguisse la convenzione, ogni artefatto gia' scritto
    smetterebbe di ritrovare i suoi campi al primo miglioramento.
    """
    return "p%d.%s.%03d-%03d" % (pagina + 1, tipo, round(x), round(y))


def _spazio_sopra(p: geometria.Pagina, x0: float, x1: float, base: float,
                  massimo: float, ingombro: float) -> float:
    """Quanto si puo' salire sopra la base prima di trovare inchiostro.

    Serve a decidere di quanto alzare il valore senza finire addosso alla riga
    di sopra: dove il modulo e' spazioso si alza come nel riferimento, dove e'
    fitto si alza quel che si puo'.

    `ingombro` e' l'altezza del riempitivo stesso: la banda deve cominciare
    sopra di lui, altrimenti si misura come ostacolo la riga che stiamo
    riempiendo e lo spazio risulta sempre zero.
    """
    fondo = base - max(1.0, ingombro)
    cielo = base - massimo
    banda = fitz.Rect(x0, cielo, x1, fondo)
    if banda.is_empty or banda.height <= 0:
        return max(0.0, base - fondo)
    segno, quanti = inchiostro(p._pagina, banda, dpi=150)
    if quanti == 0 or segno is None:
        return massimo
    return max(0.0, base - segno.y1)


def _vuoto(p: geometria.Pagina, r: fitz.Rect, margine: float = 0.8) -> bool:
    dentro = fitz.Rect(r.x0 + margine, r.y0 + margine, r.x1 - margine, r.y1 - margine)
    if dentro.is_empty or dentro.width <= 0 or dentro.height <= 0:
        return False
    return inchiostro(p._pagina, dentro, dpi=150)[1] == 0


# ------------------------------------------------------------- le etichette

_SEGNAPOSTO = re.compile(r"([^\w\s])(?:[ \t]*\1){2,}")


def _ripulisci(testo: str, verso: str = "sinistra") -> str:
    """Toglie dall'etichetta i segnaposto degli *altri* campi.

    Il testo attorno a un campo contiene quasi sempre le righe di puntini e i
    quadratini che appartengono ai campi vicini. Guardando a sinistra
    l'etichetta comincia dopo l'ultimo segnaposto ('dal ..... al' -> 'al');
    guardando a destra finisce prima del primo ('altro .....' -> 'altro').
    """
    if verso == "sinistra":
        ultimo = None
        for m in _SEGNAPOSTO.finditer(testo):
            ultimo = m
        if ultimo is not None:
            testo = testo[ultimo.end():]
    else:
        primo = _SEGNAPOSTO.search(testo)
        if primo is not None:
            testo = testo[:primo.start()]
    testo = re.sub(r"^[^\w(]+", "", testo)
    return re.sub(r"\s+", " ", testo).strip()


def _righe_vicine(p, y, tolleranza):
    return [r for r in p.righe if abs(r.base - y) <= tolleranza]


def _pare_casella(c) -> bool:
    """Filtro a costo zero: un glifo largo e non alfanumerico *potrebbe* essere
    una casella. Non decide niente - serve solo a non trascinare la casella di
    un altro campo dentro l'etichetta di questo, e a non misurare mille punti."""
    return (not c.testo.isalnum() and not c.testo.isspace()
            and c.riquadro.width >= 3.0
            and c.riquadro.width >= c.dimensione * ANTICIPO_GLIFO)


def _a_sinistra(p: geometria.Pagina, r: fitz.Rect, base: float = None,
                da: float = None) -> str:
    """Il testo a sinistra sulla stessa riga, fermandosi al campo precedente.

    Senza il limite `da`, su una riga con piu' campi l'etichetta di ognuno si
    porta dietro quelle di tutti quelli prima: 'Il sottoscritto', poi 'Il
    sottoscritto nato a', poi 'Il sottoscritto nato a il'. E' la stessa regola
    gia' usata per le caselle affiancate.
    """
    base = r.y1 if base is None else base
    pezzi = [c for c in p.caratteri
             if abs(c.origine[1] - base) <= max(2.0, c.dimensione * 0.5)
             and c.origine[0] < r.x0 - 0.2
             and (da is None or c.origine[0] >= da - 0.2)]
    pezzi.sort(key=lambda c: c.origine[0])
    taglio = 0
    for indice, c in enumerate(pezzi):
        if _pare_casella(c):
            taglio = indice + 1
    return _ripulisci("".join(c.testo for c in pezzi[taglio:]))[-90:].strip()


def _a_destra(p: geometria.Pagina, r: fitz.Rect, fermata: float = None) -> str:
    base = (r.y0 + r.y1) / 2.0
    pezzi = [c for c in p.caratteri
             if abs(c.origine[1] - base) <= max(3.0, c.dimensione * 0.75)
             and c.origine[0] >= r.x1 - 0.2
             and (fermata is None or c.origine[0] < fermata - 0.2)]
    pezzi.sort(key=lambda c: c.origine[0])
    return _ripulisci("".join(c.testo for c in pezzi), "destra")[:90].strip()


def _sopra(p: geometria.Pagina, r: fitz.Rect) -> str:
    """Il testo della cella soprastante, se c'e' una griglia; altrimenti la
    banda di pagina che sta appena sopra, limitata alla stessa colonna."""
    candidate = [c for c in p.celle
                 if c.riquadro.y1 <= r.y0 + 1.0
                 and c.riquadro.x1 > r.x0 + 1.0 and c.riquadro.x0 < r.x1 - 1.0]
    if candidate:
        candidate.sort(key=lambda c: -c.riquadro.y1)
        vicina = candidate[0]
        for c in candidate:
            if abs(c.riquadro.y1 - vicina.riquadro.y1) > 1.0:
                break
            testo = _ripulisci(p.testo_in(c.riquadro), "destra")
            if testo:
                return testo[:90]
    banda = fitz.Rect(r.x0 - 1, r.y0 - 20, r.x1 + 1, r.y0 - 0.5)
    return _ripulisci(p.testo_in(banda), "destra")[:90]


def _contesto(p: geometria.Pagina, r: fitz.Rect) -> str:
    """Che cosa si legge intorno al campo.

    Per un buco dentro una frase basta la riga che lo attraversa. Per una cella
    vuota di tabella non la attraversa niente, e il contesto resterebbe vuoto -
    proprio nei campi senza etichetta, cioe' dove serve di piu'. Chi guarda il
    foglio in quel caso legge l'intestazione sopra e la riga accanto: si prende
    la stessa finestra.
    """
    righe = [x for x in p.righe if fitz.Rect(x.riquadro).intersects(r)]
    if not righe:
        righe = _righe_vicine(p, r.y1, 4.0)
    testo = " ".join(x.testo.strip() for x in righe).strip()
    if testo:
        return testo[:200]
    finestra = fitz.Rect(max(0, r.x0 - 90), max(0, r.y0 - 34),
                         r.x1 + 90, r.y1 + 12)
    vicine = [x for x in p.righe if fitz.Rect(x.riquadro).intersects(finestra)]
    vicine.sort(key=lambda x: (x.base, x.riquadro.x0))
    return " ".join(x.testo.strip() for x in vicine)[:200].strip()


# ------------------------------------------------------------- i rilevatori

def _widget(p, presa):
    """L'etichetta di un campo modulo e' quella stampata accanto, non il suo nome.

    Chi ha costruito il PDF li chiama `TextBox3_17`, e quel nome non dice
    niente a nessuno. Il nome che conta e' quello che legge chi compila, ed e'
    scritto sulla pagina esattamente come per gli altri tipi di campo: a
    sinistra sulla stessa riga, o nell'intestazione sopra.
    """
    fuori = []
    per_base = {}
    for w in p.widget:
        per_base.setdefault(round(fitz.Rect(w.rect).y1 / 3.0), []).append(w)
    precedente = {}
    for elenco in per_base.values():
        elenco.sort(key=lambda w: fitz.Rect(w.rect).x0)
        for indice, w in enumerate(elenco):
            precedente[id(w)] = (fitz.Rect(elenco[indice - 1].rect).x1
                                 if indice else None)
    for w in p.widget:
        r = fitz.Rect(w.rect)
        stampata = (_a_sinistra(p, r, da=precedente.get(id(w)))
                    or _sopra(p, r) or _a_destra(p, r))
        interna = (w.field_label or "").strip()
        fuori.append(Ancora(_id(p.numero, "widget", r.x0, r.y0), "widget", p.numero,
                            tuple(r), {"nome": w.field_name,
                                       "genere": w.field_type_string},
                            (stampata or interna or w.field_name or "")[:90],
                            _contesto(p, r)))
        presa.prendi(r)
    return fuori


def _file_di_celle(p, presa):
    """Una fila di celle e' un tratto di griglia con celle uguali, vuote e
    strette quanto un carattere.

    La regolarita' e' il discriminante: le colonne di una tabella normale hanno
    larghezze diversissime fra loro, e quando sono uguali sono larghe molte
    volte la loro altezza. Nessuna delle due misura dipende dal modulo.
    """
    fuori = []
    per_banda = {}
    for c in p.celle:
        per_banda.setdefault(c.riga, []).append(c)
    for banda in sorted(per_banda):
        celle = sorted(per_banda[banda], key=lambda c: c.riquadro.x0)
        i = 0
        while i < len(celle):
            corsa = [celle[i]]
            j = i + 1
            while j < len(celle):
                precedente, attuale = corsa[-1].riquadro, celle[j].riquadro
                if abs(attuale.x0 - precedente.x1) > 1.0:
                    break
                larghezze = [c.riquadro.width for c in corsa] + [attuale.width]
                mediana = sorted(larghezze)[len(larghezze) // 2]
                if max(abs(w - mediana) for w in larghezze) > mediana * SCARTO_PASSO:
                    break
                corsa.append(celle[j])
                j += 1
            if len(corsa) >= MINIMO_CELLE:
                riquadri = [c.riquadro for c in corsa]
                snelle = all(r.width <= r.height * CELLA_SNELLA for r in riquadri)
                vuote = all(_vuoto(p, r, margine=0.6) for r in riquadri)
                unione = fitz.Rect(riquadri[0].x0, riquadri[0].y0,
                                   riquadri[-1].x1, riquadri[-1].y1)
                if snelle and vuote and presa.libero(unione):
                    passo = sum(r.width for r in riquadri) / len(riquadri)
                    fuori.append(Ancora(
                        _id(p.numero, "celle", unione.x0, unione.y0), "celle", p.numero,
                        tuple(unione),
                        {"celle": [tuple(r) for r in riquadri],
                         "quante": len(riquadri), "passo": round(passo, 2)},
                        _sopra(p, unione) or _a_sinistra(p, unione),
                        _contesto(p, unione)))
                    presa.prendi(unione)
            i = j if j > i + 1 else i + 1
    return fuori


def _quadrato_del_glifo(p, carattere):
    """Il bersaglio di una casella e' l'inchiostro misurato, mai il riquadro del
    carattere: a corpo 12 il riquadro e' alto 14,6 pt e il quadrato disegnato
    ne occupa 5,5, piu' in basso. Stimare qui vuol dire crocetta fuori posto."""
    if not _pare_casella(carattere):
        return None
    # Due stadi. Il primo a 300 dpi, dove la pagina e' gia' renderizzata e la
    # misura non costa niente, butta via i glifi che non sono nemmeno
    # lontanamente quadrati - su un documento di prosa sono la quasi totalita'.
    # Solo i superstiti si pagano a 600 dpi, dove la misura e' quella buona.
    grezzo, pixel = inchiostro(p._pagina, carattere.riquadro, dpi=DPI_GREZZO)
    if grezzo is None or pixel == 0:
        return None
    lato_grezzo = max(grezzo.width, grezzo.height)
    if not (LATO_MINIMO - 1.5 <= lato_grezzo <= LATO_MASSIMO + 2.0):
        return None
    if abs(grezzo.width - grezzo.height) > lato_grezzo * SQUADRATURA_GREZZA:
        return None
    segno, quanti = inchiostro(p._pagina, carattere.riquadro, dpi=600)
    if segno is None or quanti == 0:
        return None
    lato = max(segno.width, segno.height)
    if not (LATO_MINIMO <= lato <= LATO_MASSIMO):
        return None
    if abs(segno.width - segno.height) > lato * SQUADRATURA:
        return None
    interno = fitz.Rect(segno.x0 + segno.width * 0.3, segno.y0 + segno.height * 0.3,
                        segno.x1 - segno.width * 0.3, segno.y1 - segno.height * 0.3)
    pieni = inchiostro(p._pagina, interno, dpi=600)[1]
    pixel_interni = max(1.0, interno.width * interno.height * (600 / 72.0) ** 2)
    if pieni / pixel_interni > PIENO:
        return None                      # pieno: e' un segno, non una casella vuota
    return segno


def _caselle(p, presa):
    """Il testo alla destra di una casella e' la sua etichetta, e finisce dove
    comincia la casella successiva *sulla stessa base* - non dove finisce la
    riga di testo, perche' quattro caselle affiancate possono stare in quattro
    righe distinte per chi ha scritto il PDF e su una riga sola per chi guarda.
    """
    fuori = []
    quadrati = []
    for c in p.caratteri:
        segno = _quadrato_del_glifo(p, c)
        if segno is None or not presa.libero(segno):
            continue
        quadrati.append((c, segno))
    per_base = {}
    for c, segno in quadrati:
        chiave = round(c.origine[1] / 3.0)
        per_base.setdefault(chiave, []).append((c, segno))
    for elenco in per_base.values():
        elenco.sort(key=lambda coppia: coppia[1].x0)
        for indice, (c, segno) in enumerate(elenco):
            successiva = (elenco[indice + 1][0].riquadro.x0
                          if indice + 1 < len(elenco) else None)
            fuori.append(Ancora(_id(p.numero, "casella", segno.x0, segno.y0), "casella", p.numero,
                                tuple(segno),
                                {"lato": round(min(segno.width, segno.height), 2),
                                 "origine": "glifo"},
                                _a_destra(p, segno, successiva) or _a_sinistra(p, segno),
                                _contesto(p, segno)))
            presa.prendi(segno)
    for rett in p.rettangoli:
        r = rett["riquadro"]
        lato = max(r.width, r.height)
        if not (LATO_MINIMO <= lato <= LATO_MASSIMO):
            continue
        if abs(r.width - r.height) > lato * SQUADRATURA:
            continue
        if not presa.libero(r) or not _vuoto(p, r, margine=0.5):
            continue
        fuori.append(Ancora(_id(p.numero, "casella", r.x0, r.y0), "casella", p.numero, tuple(r),
                            {"lato": round(min(r.width, r.height), 2),
                             "origine": "tracciato"},
                            _a_destra(p, r) or _a_sinistra(p, r), _contesto(p, r)))
        presa.prendi(r)
    return fuori


def _riempimenti(p, presa):
    """Una fila di riempitivi e' una corsa di caratteri uguali non alfabetici.

    Si segmenta per carattere e non per span: un solo span puo' contenere
    'Citta'.......Via.......', cioe' due campi distinti.
    """
    fuori = []
    per_riga = []
    for c in sorted(p.caratteri, key=lambda c: c.origine[1]):
        # Si raggruppa per riga **vista**, non per riga del PDF. Un tratto di
        # trattini continuo sul foglio puo' essere emesso in tre pezzi
        # distinti, e raggruppando per struttura del file un campo solo
        # diventa tre campi corti: poi chi deve riempirli si trova a inventare
        # tre dati dove ne serviva uno, e la capienza che gli diciamo e' falsa.
        # Distanza dalla prima base, non bin assoluti ne' concatenazioni
        # illimitate: la segmentazione non dipende dall'origine della pagina.
        if per_riga and c.origine[1] - per_riga[-1][0].origine[1] <= geometria.TOLLERANZA:
            per_riga[-1].append(c)
        else:
            per_riga.append([c])
    for riga in per_riga:
        elenco = sorted(riga, key=lambda c: c.origine[0])
        i = 0
        while i < len(elenco):
            segno = elenco[i].testo
            if segno.isalnum() or segno.isspace():
                i += 1
                continue
            j, k = i, i
            while k + 1 < len(elenco):
                prossimo = elenco[k + 1].testo
                if prossimo == segno:
                    precedente, attuale = elenco[j], elenco[k + 1]
                    passo = max(precedente.riquadro.width, attuale.riquadro.width)
                    if attuale.riquadro.x0 - precedente.riquadro.x1 > 2 * passo:
                        break  # un altro campo sulla stessa base
                    j = k = k + 1
                elif prossimo.isspace():      # uno spazio non interrompe la riga
                    k += 1
                else:
                    break
            corsa = [c for c in elenco[i:j + 1] if c.testo == segno]
            if len(corsa) >= RUN_RIEMPIMENTO:
                r = fitz.Rect(corsa[0].riquadro.x0, min(c.riquadro.y0 for c in corsa),
                              corsa[-1].riquadro.x1, max(c.riquadro.y1 for c in corsa))
                base = corsa[0].origine[1]
                dimensione = corsa[0].dimensione
                # l'ingombro da scavalcare e' quello del testo della
                # riga stessa - etichette dei campi vicini comprese: sono
                # accanto, non sopra, e non devono abbassare il valore
                corpo_riga = max(c.dimensione for c in elenco)
                libero = _spazio_sopra(p, r.x0, r.x1, base,
                                       max(dimensione * 2.2, corpo_riga + 4.0),
                                       corpo_riga * 0.95)
                alzata = min(dimensione * ALZATA,
                             max(0.0, libero - dimensione * ASCENDENTE - 0.3))
                scrivibile = fitz.Rect(r.x0, base - alzata - dimensione * ASCENDENTE - 0.3,
                                       r.x1, base + dimensione * DISCENDENTE)
                if presa.libero(scrivibile):
                    fuori.append(Ancora(
                        _id(p.numero, "riempimento", r.x0, base), "riempimento",
                        p.numero, tuple(scrivibile),
                        {"riempitivo": segno, "quanti": len(corsa),
                         "base": round(base, 2), "dimensione": round(dimensione, 2),
                         "alzata": round(alzata, 2)},
                        _a_sinistra(p, scrivibile, base) or _sopra(p, scrivibile),
                        _contesto(p, scrivibile)))
                    presa.prendi(scrivibile)
            i = j + 1
    return fuori


def _tratti(p, presa):
    """Un tratto da compilare e' una linea orizzontale con sopra il vuoto.

    La sottolineatura di un titolo ha inchiostro appena sopra, il bordo di una
    tabella ha un'altra linea a poca distanza: bastano queste due misure per
    tenerli fuori, e nessuna delle due parla di moduli.
    """
    fuori = []
    for s in p.orizzontali:
        if s.lunghezza < 24:
            continue
        r = fitz.Rect(s.da, s.posizione - 1.0, s.a, s.posizione + 1.0)
        vicina = any(abs(altra.posizione - s.posizione) <= 22
                     and altra is not s
                     and min(altra.a, s.a) - max(altra.da, s.da) > s.lunghezza * 0.5
                     for altra in p.orizzontali)
        if vicina:
            continue
        sopra = fitz.Rect(s.da + 0.5, s.posizione - 11.0, s.a - 0.5, s.posizione - 0.8)
        if sopra.height <= 0 or inchiostro(p._pagina, sopra, dpi=150)[1] > 0:
            continue
        righe = _righe_vicine(p, s.posizione, 12.0)
        dimensione = righe[0].dimensione if righe else 9.0
        alzata = min(2.0, max(0.0, _spazio_sopra(p, s.da, s.a, s.posizione,
                                                 dimensione * 2.2, 1.0)
                              - dimensione * ASCENDENTE - 0.3))
        scrivibile = fitz.Rect(s.da, s.posizione - alzata - dimensione * ASCENDENTE - 0.3,
                               s.a, s.posizione + dimensione * DISCENDENTE)
        if not presa.libero(scrivibile):
            continue
        etichetta = _a_sinistra(p, scrivibile, s.posizione) or _sopra(p, scrivibile)
        if not etichetta:
            continue          # una linea senza etichetta e' una riga di stampa
        fuori.append(Ancora(_id(p.numero, "tratto", s.da, s.posizione), "tratto", p.numero,
                            tuple(scrivibile),
                            {"base": round(s.posizione, 2),
                             "dimensione": round(dimensione, 2),
                             "alzata": round(alzata, 2)},
                            etichetta, _contesto(p, scrivibile)))
        presa.prendi(scrivibile)
    return fuori


def _aree(p, presa):
    """Un'area libera e' un riquadro chiuso e vuoto.

    Il vuoto e' la condizione decisiva: e' cosi' che i riquadri che contengono
    l'etichetta restano etichette invece di diventare campi, senza doverli
    elencare da nessuna parte.
    """
    fuori = []
    candidati = [c.riquadro for c in p.celle]
    candidati += [r["riquadro"] for r in p.rettangoli]
    visti = []
    for r in sorted(candidati, key=lambda x: (-x.get_area())):
        if r.width < AREA_LARGHEZZA_MINIMA or r.height < AREA_ALTEZZA_MINIMA:
            continue
        if any((fitz.Rect(r) & v).get_area() > r.get_area() * 0.5 for v in visti):
            continue
        if not presa.libero(r) or not _vuoto(p, r):
            continue
        # La dimensione la detta il riquadro, non l'etichetta: su molti moduli
        # l'intestazione di colonna e' minuscola, e scrivere del corpo
        # dell'etichetta riempie la cella con un valore che non si legge.
        # Il tetto e' il corpo piu' diffuso della pagina, cosi' un riquadro
        # grande non produce un valore gigantesco.
        dimensione = max(5.0, min(r.height * 0.40, p.corpo * 1.3))
        fuori.append(Ancora(_id(p.numero, "area", r.x0, r.y0), "area", p.numero, tuple(r),
                            {"dimensione": round(dimensione, 2)},
                            _sopra(p, r) or _a_sinistra(p, r), _contesto(p, r)))
        presa.prendi(r)
        visti.append(fitz.Rect(r))
    return fuori


# ------------------------------------------------------------- la cascata

CASCATA = (("widget", _widget), ("celle", _file_di_celle), ("casella", _caselle),
           ("riempimento", _riempimenti), ("tratto", _tratti), ("area", _aree))


def _con_i_buchi(p: geometria.Pagina, ancore):
    """Riscrive il contesto come la frase con i buchi al loro posto.

    Prima ogni campo riceveva la riga *senza* i buchi, cioe' una frase da cui
    era stato tolto proprio quello di cui si sta parlando: tre campi della
    stessa riga finivano con lo stesso identico contesto. Cosi' non si
    contestualizza niente.

    La resa giusta e' la riga com'e', con ogni campo segnato dove sta e con
    quanto ci sta: «Il sottoscritto «QUI:36», nato a «p1.area.204-233:32»».
    Il campo di cui si parla e' marcato QUI, gli altri col loro nome.
    """
    per_base = {}
    for a in ancore:
        per_base.setdefault(round(a.rect[3] / 4.0), []).append(a)
    fuori = []
    for a in ancore:
        vicini = sorted(per_base.get(round(a.rect[3] / 4.0), []),
                        key=lambda x: x.rect[0])
        base = (a.rect[1] + a.rect[3]) / 2.0
        pezzi = [(c.origine[0], c.testo) for c in p.caratteri
                 if abs(c.origine[1] - base) <= max(4.0, c.dimensione * 0.9)]
        for v in vicini:
            capienza = max(1, int((v.rect[2] - v.rect[0]) / 4.2))
            segno = "«QUI:%d»" % capienza if v.id == a.id else "«___:%d»" % capienza
            pezzi.append((v.rect[0], " %s " % segno))
        pezzi.sort(key=lambda x: x[0])
        riga = re.sub(r"\s+", " ", "".join(t for _, t in pezzi)).strip()
        fuori.append(Ancora(a.id, a.tipo, a.pagina, a.rect, a.parametri,
                            a.etichetta, (riga or a.contesto)[:260]))
    return fuori


def classifica_pagina(p: geometria.Pagina):
    """Applica la cascata a una pagina gia' misurata. Il primo tipo che aggancia
    vince; quello che nessuno aggancia non diventa un campo."""
    presa = Presa()
    ancore = []
    for _, rilevatore in CASCATA:
        ancore.extend(rilevatore(p, presa))
    ancore.sort(key=lambda a: (a.rect[1], a.rect[0]))
    return _con_i_buchi(p, ancore)


def classifica(doc: fitz.Document):
    """Tutte le pagine del documento, gia' portate a rotazione 0 da chi chiama."""
    ancore = []
    for numero, pagina in enumerate(doc):
        ancore.extend(classifica_pagina(geometria.leggi(pagina, numero)))
    return ancore
