# -*- coding: utf-8 -*-
"""La mappa dei campi: il modulo tradotto in dati, prima che l'AI intervenga.

La mappa e' l'unico ponte fra il modulo e il modello. Il modello non riceve
coordinate da inventare: riceve ancore gia' misurate e tipizzate, e decide solo
la parte che e' giudizio - quale dato del fascicolo va su quale ancora, e quali
ancore vanno lasciate vuote perche' il fascicolo non lo dice.

Conseguenza voluta: ogni ancora rimasta senza valore *e'* un dato mancante, con
pagina e motivo gia' dentro. La lista dei punti aperti e' una proiezione della
mappa, e non puo' nascere altrove.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import fitz

from riusare.strumenti_documento import Ancora, PagineDiritte, impronta, svuota_misure
from motore import classificatore, geometria, resa


def costruisci(percorso) -> dict:
    percorso = Path(percorso)
    # La cache delle misure appartiene al documento aperto, non al processo.
    # Non conservare render associati a id Python di documenti gia' chiusi.
    svuota_misure()
    doc = fitz.open(percorso)
    try:
        with PagineDiritte(doc) as diritto:
            ancore, rese = [], []
            for numero, pagina in enumerate(diritto):
                misurata = geometria.leggi(pagina, numero)
                trovate = classificatore.classifica_pagina(misurata)
                ancore.extend(trovate)
                if trovate:
                    # la pagina resa a prosa con i buchi numerati: e' la forma
                    # in cui il modulo si puo' far leggere a un modello
                    testo, indirizzi = resa.rendi(misurata, trovate)
                    rese.append({"pagina": numero + 1, "testo": testo,
                                 "indirizzi": indirizzi})
            pagine = [{"numero": i + 1, "larghezza": round(p.rect.width, 2),
                       "altezza": round(p.rect.height, 2)}
                      for i, p in enumerate(diritto)]
    finally:
        doc.close()
        svuota_misure()
    return {"documento": percorso.name,
            "impronta": impronta(percorso),
            "pagine": pagine,
            "rese": rese,
            "ancore": [a.a_dict() for a in ancore]}


def ancore(mappa: dict):
    return [Ancora.da_dict(d) for d in mappa["ancore"]]


def conteggio(mappa: dict) -> dict:
    conti = {}
    for a in mappa["ancore"]:
        conti[a["tipo"]] = conti.get(a["tipo"], 0) + 1
    return conti


def riassunto(mappa: dict, larghezza_etichetta: int = 52) -> str:
    """La mappa in forma leggibile: e' questo che va nel messaggio al modello."""
    righe = ["%s  (%d pagine, %d ancore)"
             % (mappa["documento"], len(mappa["pagine"]), len(mappa["ancore"]))]
    conti = conteggio(mappa)
    righe.append("tipi: " + ", ".join("%s %d" % (t, n) for t, n in sorted(conti.items())))
    pagina_corrente = None
    for d in mappa["ancore"]:
        if d["pagina"] != pagina_corrente:
            pagina_corrente = d["pagina"]
            righe.append("")
            righe.append("--- pagina %d" % (pagina_corrente + 1))
        extra = ""
        if d["tipo"] == "celle":
            extra = " [%d celle]" % d["parametri"]["quante"]
        elif d["tipo"] == "casella":
            extra = " [lato %.1f]" % d["parametri"]["lato"]
        elif d["tipo"] == "riempimento":
            extra = " [%d '%s']" % (d["parametri"]["quanti"], d["parametri"]["riempitivo"])
        etichetta = (d["etichetta"] or "(senza etichetta)")[:larghezza_etichetta]
        righe.append("  %-26s %-12s %-*s%s"
                     % (d["id"], d["tipo"], larghezza_etichetta, etichetta, extra))
    return "\n".join(righe)


def salva(mappa: dict, percorso) -> Path:
    percorso = Path(percorso)
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text(json.dumps(mappa, ensure_ascii=False, indent=1), encoding="utf-8")
    return percorso


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("uso: python -m motore.mappa <modulo.pdf> [mappa.json]")
    m = costruisci(sys.argv[1])
    print(riassunto(m))
    if len(sys.argv) > 2:
        print("\nscritta in", salva(m, sys.argv[2]))
