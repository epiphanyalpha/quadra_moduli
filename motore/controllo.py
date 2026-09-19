# -*- coding: utf-8 -*-
"""Il controllo indipendente e il verdetto.

Il controllo non legge quello che il programma dichiara di aver fatto: riapre
la bozza, la confronta con l'originale e misura. E' da questa indipendenza che
esce l'unico numero che dice se lo strumento e' usabile - le scritture che il
programma dava per riuscite e che nel documento non ci sono.

Il verdetto non e' mai tutto-o-niente. Mancare dei dati e' normale e si dice;
sbagliare e accorgersene e' un difetto e si dice; sbagliare in silenzio e' la
sola cosa che renderebbe inutile tutto il resto.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import fitz

from riusare.strumenti_documento import Ancora, PagineDiritte, verifica

# Quanti punti aperti si elencano nel racconto. Oltre una dozzina non si legge
# piu' niente: l'elenco completo resta nel verdetto, che e' un dato, e la
# pagina lo mostra come tabella invece che come muro di testo.
ELENCO_MASSIMO = 12

COMPLETO = "completo"
MANCANO_DATI = "mancano_dati"
NON_RIUSCITO = "non_riuscito"
ERRORI_NON_SEGNALATI = "errori_non_segnalati"


def come_si_legge(ancora, valore=None) -> str:
    """La riga del modulo con dentro il valore, per chi legge il rapporto.

    Nel rapporto mostravo l'etichetta che estrae il classificatore, e per un
    campo che sta a inizio riga quell'etichetta e' presa dalla riga prima o da
    quella dopo: si legge 'presso la banca -> COSTRUZIONI RIVAMARE S.R.L.' e
    sembra un errore grosso mentre il valore e' giusto, perche' il campo vero
    diceva 'intestato a'.

    Il modulo non si giudica dall'etichetta: si giudica dalla frase. Qui la
    frase c'e' gia' - e' quella che legge il modello - e basta metterci dentro
    il valore al posto del segnaposto.
    """
    riga = (ancora.contesto or "").strip()
    if not riga:
        return ancora.etichetta or ancora.id
    if valore is not None:
        riga = re.sub(r"«QUI:\d+»", "[ %s ]" % str(valore)[:60], riga)
    riga = re.sub(r"«[^»]*»", "___", riga)
    # i riempitivi del modulo sono rumore in un rapporto: una riga di
    # sessanta puntini non aggiunge niente a chi legge
    riga = re.sub(r"([^\w\s])(?:[ \t]*\1){2,}", "___", riga)
    riga = re.sub(r"(?:_{3,}[ \t]*)+", "___ ", riga)
    return re.sub(r"\s+", " ", riga).strip()[:130]


def _punti_aperti(mappa: dict, note: dict, scritte: set) -> list:
    """Un punto aperto nasce sempre da un campo del modulo rimasto vuoto.

    Le liste di cose da confermare che vivono nel fascicolo non entrano qui se
    il modulo non le chiede: se non c'e' l'ancora, non c'e' il punto aperto.
    """
    ancore = {a["id"]: a for a in mappa["ancore"]}
    aperti, rifiutati = [], []
    for punto in note.get("punti_aperti", []):
        identificativo = punto.get("ancora")
        if identificativo not in ancore:
            rifiutati.append({"punto": punto,
                              "motivo": "non corrisponde a nessun campo del modulo"})
            continue
        if identificativo in scritte:
            rifiutati.append({"punto": punto,
                              "motivo": "ora il fascicolo lo dice: compilato"})
            continue
        a = ancore[identificativo]
        aperti.append({"ancora": identificativo, "pagina": a["pagina"] + 1,
                       "etichetta": a["etichetta"], "tipo": a["tipo"],
                       "chiave": punto.get("chiave", ""),
                       "motivo": punto.get("motivo", "")})
    aperti.sort(key=lambda p: (p["pagina"], p["ancora"]))
    return aperti, rifiutati


def controlla(originale, bozza, mappa: dict, scritture: dict,
              note: dict = None) -> dict:
    note = note or {}
    ancore = {a["id"]: Ancora.da_dict(a) for a in mappa["ancore"]}
    elenco = scritture.get("scritture", [])

    verificate, non_segnalate, non_riuscite = [], [], []
    # i riquadri degli altri campi scritti, pagina per pagina: servono a non
    # attribuire a un campo l'inchiostro del campo confinante
    per_pagina = {}
    for s in elenco:
        a = ancore.get(s["ancora"])
        if a is not None and s.get("scritto"):
            per_pagina.setdefault(a.pagina, []).append((s["ancora"], a.riquadro))

    doc_prima = fitz.open(originale)
    doc_dopo = fitz.open(bozza)
    with PagineDiritte(doc_prima) as prima, PagineDiritte(doc_dopo) as dopo:
        for s in elenco:
            ancora = ancore.get(s["ancora"])
            riga = {"ancora": s["ancora"], "tipo": s["tipo"],
                    "etichetta": s.get("etichetta", ""), "valore": s.get("valore"),
                    "riga": come_si_legge(ancora, s.get("valore")) if ancora else "",
                    "pagina": (ancora.pagina + 1) if ancora else None}
            if not s.get("scritto"):
                riga["motivo"] = s.get("motivo", "")
                non_riuscite.append(riga)
                continue
            if ancora is None:
                riga["motivo"] = "ancora sconosciuta alla mappa"
                non_segnalate.append(riga)
                continue
            altrui = [r for identificativo, r in per_pagina.get(ancora.pagina, [])
                      if identificativo != s["ancora"]]
            esito = verifica(prima[ancora.pagina], dopo[ancora.pagina], ancora,
                             s.get("valore"), altrui)
            riga["motivo"] = esito.motivo
            (verificate if esito.ok else non_segnalate).append(riga)
    doc_prima.close()
    doc_dopo.close()

    scritte = {s["ancora"] for s in elenco if s.get("scritto")}
    aperti, rifiutati = _punti_aperti(mappa, note, scritte)

    if non_segnalate:
        stato = ERRORI_NON_SEGNALATI
    elif non_riuscite:
        stato = NON_RIUSCITO
    elif aperti:
        stato = MANCANO_DATI
    else:
        stato = COMPLETO

    return {"stato": stato,
            "documento": mappa["documento"],
            "campi_totali": len(mappa["ancore"]),
            "verificate": verificate,
            "non_segnalate": non_segnalate,
            "non_riuscite": non_riuscite,
            "punti_aperti": aperti,
            "punti_rifiutati": rifiutati,
            "domande_bloccanti": note.get("domande_bloccanti", [])}


# "Mancano 12 dati che devi inserire tu" su un modulo dove i tre campi
# d'anagrafica erano scritti giusti e gli altri dodici erano marca da bollo,
# timbro e firma. Quelli non mancano: non sono mai stati nostri. La promessa e'
# l'anagrafica, e va detto quello che si e' fatto, non quello che resta.
FRASI = {
    COMPLETO: "Documento completato, nulla in sospeso.",
    MANCANO_DATI: "Anagrafica scritta. Gli altri %d campi del modulo li compili tu.",
    NON_RIUSCITO: "Documento compilato, ma il programma non e' riuscito su %d punti.",
    ERRORI_NON_SEGNALATI: "Attenzione: %d scritture non risultano nel documento.",
}


def racconta(esito: dict) -> str:
    stato = esito["stato"]
    if stato == COMPLETO:
        titolo = FRASI[stato]
    elif stato == MANCANO_DATI:
        titolo = FRASI[stato] % len(esito["punti_aperti"])
    elif stato == NON_RIUSCITO:
        titolo = FRASI[stato] % len(esito["non_riuscite"])
    else:
        titolo = FRASI[stato] % len(esito["non_segnalate"])

    righe = [titolo, ""]
    righe.append("%d campi scritti e verificati su %d campi del modulo."
                 % (len(esito["verificate"]), esito["campi_totali"]))
    for titoletto, chiave in (("Non risultano nel documento", "non_segnalate"),
                              ("Il programma non ce l'ha fatta", "non_riuscite")):
        if esito[chiave]:
            righe.append("")
            righe.append("%s:" % titoletto)
            for r in esito[chiave]:
                righe.append("  pagina %s - %s"
                             % (r["pagina"], r.get("riga") or r["etichetta"]
                                or r["ancora"]))
                righe.append("      %s: %s" % (r["tipo"], r.get("motivo", "")))
    # Un campo senza etichetta non e' una domanda che si possa fare a qualcuno:
    # l'unica cosa da mostrare sarebbe il suo codice interno, `p1.area.057-479`,
    # che non dice niente a chi deve compilare. Si contano e basta.
    con_nome = [p for p in esito["punti_aperti"] if (p["etichetta"] or "").strip()]
    muti = len(esito["punti_aperti"]) - len(con_nome)
    if con_nome:
        righe.append("")
        righe.append("Il resto del modulo lo compili tu, guardando la bozza:")
        # Il motivo e' quasi sempre lo stesso ripetuto: stamparlo accanto a
        # ognuno riempie pagine e nasconde l'unica cosa che serve, cioe' QUALI
        # campi sono. Su un modulo di quattro pagine erano 48 righe identiche.
        for p in con_nome[:ELENCO_MASSIMO]:
            righe.append("  pagina %d - %s" % (p["pagina"], p["etichetta"]))
        avanzano = len(con_nome) - ELENCO_MASSIMO
        if avanzano > 0:
            righe.append("  ... e altri %d, elencati sotto." % avanzano)
    if muti:
        righe.append("")
        righe.append("Altri %d campi non hanno un'etichetta: si vedono solo "
                     "guardando la bozza." % muti)
    if esito["punti_rifiutati"]:
        righe.append("")
        righe.append("Punti aperti che il controllo ha scartato:")
        for r in esito["punti_rifiutati"]:
            righe.append("  %s: %s" % (r["punto"].get("ancora", "?"), r["motivo"]))
    return "\n".join(righe)


def da_cartella(originale, uscita, artefatto) -> dict:
    """Controlla un'esecuzione a partire dalle cartelle che ha prodotto."""
    artefatto, uscita = Path(artefatto), Path(uscita)
    mappa = json.loads((artefatto / "mappa.json").read_text(encoding="utf-8"))
    note_percorso = artefatto / "note.json"
    note = json.loads(note_percorso.read_text(encoding="utf-8")) if note_percorso.is_file() else {}
    scritture = json.loads((uscita / "scritture.json").read_text(encoding="utf-8"))
    return controlla(originale, uscita / "bozza.pdf", mappa, scritture, note)
