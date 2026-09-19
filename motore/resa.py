# -*- coding: utf-8 -*-
"""La pagina resa come prosa con i buchi numerati.

E' la forma in cui un modulo si puo' far leggere a un modello. Non l'immagine,
non l'elenco dei campi: **il testo della pagina cosi' com'e', con i posti da
riempire segnati dove stanno**, e accanto a ognuno quanti caratteri ci entrano.

    Il sottoscritto «3:36», nato a «4:32» il «5:15»
    codice fiscale «6:21», residente in «7:42» Cap «8:10»
    ...
    L'IMPRESA
    denominazione «21:48» con sede in «22:31» via «23:35»

Serve perche' un campo non si capisce dalla sua etichetta. 'via' alla riga 3 e
'via' alla riga 21 sono due dati diversi, e la differenza sta in quello che c'e'
intorno: la prima frase parla di una persona che risiede, la seconda di
un'impresa che ha sede. Mandare le righe una per una - come facevo prima - toglie
proprio l'informazione che serve, e per giunta ripete lo stesso testo tante volte
quanti sono i buchi di quella riga.

Il numero dentro il segnaposto e' un indirizzo corto: il modello risponde con
quello, e il programma lo ritraduce nell'identificativo dell'ancora.
"""
from __future__ import annotations

import re

import fitz

LARGHEZZA_CARATTERE = 4.2      # quanto occupa in media una lettera scritta
RIGHE_MASSIME = 400


def capienza(ancora) -> int:
    """Quante lettere entrano nel campo. E' meta' dell'indizio: «:15» dopo 'il'
    e' una data, «:10» dopo 'Cap' e' un CAP."""
    larghezza = ancora.rect[2] - ancora.rect[0]
    if ancora.tipo == "celle":
        return int(ancora.parametri.get("quante") or max(1, larghezza / LARGHEZZA_CARATTERE))
    if ancora.tipo == "casella":
        return 1
    return max(1, int(larghezza / LARGHEZZA_CARATTERE))


def rendi(pagina, ancore) -> tuple:
    """La pagina come prosa con i buchi numerati.

    Ritorna (testo, indirizzi) dove `indirizzi` traduce il numero corto
    nell'identificativo dell'ancora.
    """
    numerate = []
    for numero, a in enumerate(sorted(ancore, key=lambda x: (x.rect[1], x.rect[0])), 1):
        numerate.append((numero, a))
    indirizzi = {str(n): a.id for n, a in numerate}

    pezzi = []
    for c in pagina.caratteri:
        pezzi.append((c.origine[1], c.origine[0], c.testo))

    # Un campo va agganciato alla riga di testo a cui appartiene, non alla sua
    # altezza geometrica: un campo modulo sta qualche punto piu' in alto della
    # base delle lettere, e finirebbe su una riga tutta sua sopra la frase.
    basi = sorted({round(r.base, 1) for r in pagina.righe})
    for numero, a in numerate:
        y = a.parametri.get("base") or a.rect[3]
        # Una cella alta non si legge dal bordo inferiore: il suo segnaposto
        # deve seguire l'etichetta nella stessa banda. Preferiamo il testo
        # immediatamente a sinistra, evitando intestazioni di gruppo lontane.
        allineata = None
        if a.tipo in ("widget", "area"):
            vicine = [r for r in pagina.righe
                      if a.rect[1] <= r.base <= a.rect[3]
                      and r.riquadro.x1 <= a.rect[0] + 1
                      and r.testo.strip()]
            if vicine:
                allineata = min(vicine, key=lambda r: (
                    max(0, a.rect[0] - r.riquadro.x1),
                    abs(r.base - (a.rect[1] + a.rect[3]) / 2)))
                y = allineata.base
        vicina = min(basi, key=lambda b: abs(b - y)) if basi else None
        if vicina is not None and abs(vicina - y) <= 8.0:
            y = vicina
        segno = "«%d:%d»" % (numero, capienza(a))
        if a.tipo == "casella" or (a.tipo == "widget" and a.parametri.get("genere") != "Text"):
            segno = "«%d:casella»" % numero
        pezzi.append((y, a.rect[0], " %s " % segno))

    # in ordine di lettura: prima la riga, poi da sinistra a destra
    pezzi.sort(key=lambda x: (round(x[0] / 4.0), x[1]))
    righe, corrente, base = [], [], None
    for y, _, testo in pezzi:
        chiave = round(y / 4.0)
        if base is not None and chiave != base:
            righe.append("".join(corrente))
            corrente = []
        base = chiave
        corrente.append(testo)
    if corrente:
        righe.append("".join(corrente))

    pulite = [re.sub(r"[ \t]+", " ", r).strip() for r in righe]
    pulite = [r for r in pulite if r][:RIGHE_MASSIME]
    return "\n".join(pulite), indirizzi


def rendi_documento(pagine, ancore) -> list:
    """Una resa per pagina: il modello legge una pagina alla volta, come chiunque."""
    per_pagina = {}
    for a in ancore:
        per_pagina.setdefault(a.pagina, []).append(a)
    fuori = []
    for numero, pagina in enumerate(pagine):
        gruppo = per_pagina.get(numero, [])
        if not gruppo:
            continue
        testo, indirizzi = rendi(pagina, gruppo)
        fuori.append({"pagina": numero + 1, "testo": testo, "indirizzi": indirizzi})
    return fuori
