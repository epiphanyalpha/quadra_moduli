# -*- coding: utf-8 -*-
"""La lavorazione di un modulo, dall'arrivo del PDF al verdetto.

Un generatore di passi, cosi' la chat puo' raccontare quello che sta succedendo
mentre succede. L'ordine non e' casuale:

  1. si misura           - deterministico, nessun costo
  2. si chiede se il modulo e' di questa impresa - l'unica domanda bloccante
  3. il modello scrive valori()                  - il giudizio
  4. le guardie          - se parlano, non si salva
  5. si esegue isolato   - codice di un modello non gira mai in chiaro
  6. si controlla        - indipendente da quello che il programma dichiara
  7. si corregge         - con le pagine vere davanti, non a memoria

Dalla seconda volta in poi i passi 2, 3 e 7 saltano: c'e' gia' l'artefatto.
"""
from __future__ import annotations

import json
from pathlib import Path

import esecuzione
from motore import agente, compilatore, controllo, soggetti
from motore import mappa as modulo_mappa
from riusare.strumenti_documento import firmato

TENTATIVI = 3

# Le fasi, come le vedrebbe chi guarda lavorare. Non sono i passi: i passi sono
# quindici e cambiano, le fasi sono cinque e restano. Stanno qui e non nella
# pagina perche' chi aggiunge un passo deve dirgli a quale fase appartiene,
# altrimenti la barra mente senza che nessuno se ne accorga.
FASI = (
    ("lettura",    "Leggo il modulo"),
    ("pertinenza", "Controllo che sia tuo"),
    ("decisione",  "Decido che cosa scrivere"),
    ("scrittura",  "Scrivo sulla bozza"),
    ("verifica",   "Rileggo e verifico"),
)

FASE_DI_PASSO = {
    "rifiuto": None,              # non si comincia nemmeno
    "misura": "lettura",
    "mappa": "lettura",
    "pertinenza": "pertinenza",
    "pertinenza_ok": "pertinenza",
    "domanda_bloccante": "pertinenza",
    "riuso": "decisione",
    "valori": "decisione",
    "guardia": "decisione",
    "correzione": "decisione",
    "esecuzione": "scrittura",
    "errore": "scrittura",
    "controllo": "verifica",
    "verdetto": "verifica",
}


def fase(passo: dict):
    """A quale fase appartiene un passo, e a che punto sta (1..5)."""
    nome = FASE_DI_PASSO.get(passo.get("passo"))
    if nome is None:
        return None, 0
    ordine = [n for n, _ in FASI].index(nome) + 1
    return nome, ordine


def _guai_da_verdetto(verdetto: dict) -> str:
    righe = []
    for r in verdetto["non_segnalate"]:
        righe.append("- %s (%s, pagina %s): il programma diceva di averlo scritto, "
                     "ma nel documento non c'e': %s"
                     % (r["ancora"], r["etichetta"], r["pagina"], r.get("motivo", "")))
    for r in verdetto["non_riuscite"]:
        righe.append("- %s (%s, pagina %s): scrittura non riuscita: %s"
                     % (r["ancora"], r["etichetta"], r["pagina"], r.get("motivo", "")))
    return "\n".join(righe)


def artefatto_esistente(radice: Path, mappa: dict):
    """L'artefatto gia' fatto per **questo documento**, comunque si chiami.

    La cartella porta nome e impronta, ma a identificare il documento e' solo
    l'impronta: lo stesso modulo scaricato da due comuni si chiama in due modi,
    e cercarlo per nome lo fa ricompilare da capo - una chiamata al modello
    pagata per riavere quello che c'era gia'. Successo davvero, rinominando un
    file di prova: 27 scritture diventate 17, senza che niente lo dicesse.

    L'impronta intera resta controllata dal programma quando parte, quindi una
    collisione sugli otto caratteri fa fallire il salvataggio, non uno scambio.
    """
    esatta = compilatore.cartella(radice, mappa)
    if (esatta / "programma.py").is_file():
        return esatta
    marchio = mappa["impronta"][:8]
    candidati = [c for c in (radice / "compilatori").glob("*_" + marchio)
                 if (c / "programma.py").is_file()]
    if not candidati:
        return None
    # Se per lo stesso documento ce n'e' piu' d'uno, vince il piu' vecchio: e'
    # quello che e' stato usato e guardato, mentre i successivi nascono da
    # incidenti - un file rinominato, una corsa ripetuta. Due compilazioni
    # dello stesso modulo non si somigliano: misurate 27 scritture contro 17.
    return min(candidati, key=lambda c: (c / "programma.py").stat().st_mtime)


def lavora(radice: Path, pdf, fascicolo: dict, cartella_lavoro: Path,
           riusa: bool = True, pertinenza_confermata: bool = False):
    """Genera dizionari {passo, testo, ...}. L'ultimo ha sempre 'verdetto'."""
    pdf = Path(pdf)
    cartella_lavoro = Path(cartella_lavoro)
    cartella_lavoro.mkdir(parents=True, exist_ok=True)

    # Prima di tutto: su un PDF gia' firmato non si scrive. Scriverci dentro
    # invaliderebbe la firma, e il danno non si vede finche' qualcuno non la
    # verifica. Va detto qui, perche' piu' avanti il modulo firmato sembra
    # soltanto un modulo senza campi e il motivo vero si perde.
    if firmato(pdf):
        yield {"passo": "rifiuto", "verdetto": None,
               "testo": "Questo PDF ha gia' una firma digitale applicata.\n"
                        "Scriverci dentro la renderebbe non valida: si compila "
                        "prima e si firma dopo.\nChiedi il modulo vuoto, non "
                        "firmato. Non ho scritto niente."}
        return

    yield {"passo": "misura", "testo": "Misuro il modulo."}
    mappa = modulo_mappa.costruisci(pdf)
    yield {"passo": "mappa", "mappa": mappa,
           "testo": "%d campi riconosciuti: %s."
                    % (len(mappa["ancore"]),
                       ", ".join("%s %d" % (t, n) for t, n
                                 in sorted(modulo_mappa.conteggio(mappa).items())))}

    gia_fatto = artefatto_esistente(radice, mappa) if riusa else None
    if gia_fatto is not None:
        yield {"passo": "riuso", "artefatto": str(gia_fatto),
               "testo": "Questo modulo l'ho gia' compilato una volta: riuso il "
                        "programma, senza chiamare il modello."}
        codice = (gia_fatto / "programma.py").read_text(encoding="utf-8")
        note = json.loads((gia_fatto / "note.json").read_text(encoding="utf-8"))
        yield from _esegui_e_controlla(pdf, fascicolo, cartella_lavoro, codice,
                                       mappa, note, gia_fatto)
        return

    if not agente.disponibile():
        raise agente.ModelloAssente(
            "Questo modulo non ha ancora un programma e il modello non e' "
            "configurato: non posso compilarlo.")

    if pertinenza_confermata:
        # Chi lavora ha gia' risposto alla domanda. Non si richiede al modello:
        # costerebbe una seconda chiamata per riavere la stessa risposta, e la
        # risposta che conta adesso e' quella di chi conosce la gara.
        yield {"passo": "pertinenza_ok",
               "testo": "Mi hai confermato che il modulo e' di questa impresa: vado avanti."}
    else:
        yield {"passo": "pertinenza",
               "testo": "Controllo che il modulo sia di questa impresa."}
        figure = agente.immagini(pdf, pagine={0})
        giudizio = agente.pertinenza(agente.testo_prima_pagina(pdf), fascicolo, figure)
        if not giudizio.get("pertinente", True):
            yield {"passo": "domanda_bloccante", "verdetto": None,
                   "domanda": giudizio.get("domanda") or giudizio.get("motivo"),
                   "testo": "Mi fermo prima di lavorare: %s" % giudizio.get("motivo", "")}
            return
        yield {"passo": "pertinenza_ok",
               "testo": giudizio.get("motivo", "Modulo pertinente.")}

    riassunto = modulo_mappa.riassunto(mappa)
    tutte = agente.immagini(pdf)
    guai, ultimo = "", None
    for tentativo in range(1, TENTATIVI + 1):
        yield {"passo": "valori", "tentativo": tentativo,
               "testo": "Decido che cosa va in ogni campo (tentativo %d)." % tentativo}
        codice_valori, note = agente.valori(mappa, fascicolo, riassunto,
                                            ultimo or tutte, guai)
        try:
            artefatto = compilatore.salva(radice, mappa, codice_valori, note)
        except Exception as fermata:                       # guardie
            guai = "Le guardie hanno rifiutato il programma:\n%s" % fermata
            yield {"passo": "guardia", "testo": str(fermata)}
            continue

        codice = (artefatto / "programma.py").read_text(encoding="utf-8")
        passi = list(_esegui_e_controlla(pdf, fascicolo, cartella_lavoro, codice,
                                         mappa, note, artefatto))
        for p in passi:
            yield p
        verdetto = passi[-1].get("verdetto")
        if verdetto is None or verdetto["stato"] in (controllo.COMPLETO,
                                                     controllo.MANCANO_DATI):
            return
        guai = _guai_da_verdetto(verdetto)
        ultimo = agente.immagini(Path(passi[-1]["bozza"]))
        yield {"passo": "correzione",
               "testo": "Il controllo ha trovato dei problemi: riguardo le pagine "
                        "e correggo."}


def _esegui_e_controlla(pdf, fascicolo, cartella_lavoro, codice, mappa, note,
                        artefatto):
    yield {"passo": "esecuzione", "testo": "Eseguo il programma, isolato."}
    esito = esecuzione.esegui_al_meglio(codice, pdf, cartella_lavoro, fascicolo)
    if not esito["riuscita"]:
        yield {"passo": "errore", "verdetto": None, "esecuzione": esito,
               "testo": "Il programma non ha prodotto la bozza.\n%s"
                        % (esito["stderr"] or esito["stdout"])}
        return
    yield {"passo": "controllo", "testo": "Riapro la bozza e verifico ogni scrittura."}
    scritture = json.loads(Path(esito["scritture"]).read_text(encoding="utf-8"))
    verdetto = controllo.controlla(pdf, esito["bozza"], mappa, scritture, note)
    (Path(esito["uscita"]) / "verdetto.json").write_text(
        json.dumps(verdetto, ensure_ascii=False, indent=1), encoding="utf-8")
    # Le scritture finite dove il foglio parla di un altro soggetto. Il
    # controllo materiale non puo' vederle - sono dentro il campo, leggibili,
    # col dato giusto - ed e' esattamente li' che il motore sbaglia.
    avvisi = soggetti.avvertimenti(mappa, [r["ancora"] for r in verdetto["verificate"]])
    verdetto["soggetti_da_controllare"] = avvisi
    yield {"passo": "verdetto", "verdetto": verdetto, "bozza": esito["bozza"],
           "artefatto": str(artefatto), "avvisi": avvisi,
           "testo": controllo.racconta(verdetto)}
