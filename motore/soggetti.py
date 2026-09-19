# -*- coding: utf-8 -*-
"""Di chi parla questo pezzo di modulo.

Il motore sa scrivere: su 91 moduli mai visti, 954 scritture, tutte dentro il
loro campo, nessuno sbordo. Quello che non sa fare e' capire **di chi** si sta
parlando. I tre fallimenti misurati il 18/09/2026 sono lo stesso errore:

    modello_voltura        il blocco era del NUOVO TITOLARE
    dmse allegato I        il blocco era del RESPONSABILE DELL'IMPIANTO
    domanda-partecipazione la pagina era del SOGGETTO CESSATO DALLA CARICA

In tutti e tre il dato scritto era giusto e il soggetto sbagliato. E nel terzo
c'e' un aggravante: quella pagina non andava compilata affatto, perche' esiste
solo se un amministratore e' cessato nell'ultimo anno.

Qui non si indovina chi sia il soggetto: si riconosce **quando il foglio dice
di stare parlando di qualcun altro**. E' una lista chiusa di formule che sulla
modulistica pubblica italiana introducono un soggetto diverso dal concorrente,
oppure una sezione condizionale. Vale come avvertimento, non come verdetto: la
decisione di scrivere o no resta di chi chiama.

Perche' una lista di parole e non un modello: la formula e' stampata sul foglio
e non cambia, mentre il giudizio su chi sia il soggetto e' esattamente la cosa
che il modello sbaglia. Qui serve un riflesso, non un'opinione.
"""
from __future__ import annotations

import re

# Quanto sopra il campo si guarda. Sei righe coprono l'intestazione di sezione
# e la frase che la introduce, senza arrivare al blocco precedente.
RIGHE_SOPRA = 6

# Le formule, e che cosa introducono. L'ordine non conta: si segnala la prima
# che si trova, e il motivo serve solo a farlo capire a chi legge.
FORMULE = (
    (r"cessat[oi] dalla carica",
     "soggetto cessato dalla carica"),
    (r"impresa ausiliaria|avvalimento|ausiliari[ae]\b",
     "impresa ausiliaria"),
    (r"subappaltator|subappalt",
     "subappaltatore"),
    (r"mandante|mandatari[ao]|raggruppament|\br\.?t\.?i\.?\b|consorziat",
     "altro membro del raggruppamento"),
    (r"incorporazione|a seguito di fusione|acquisizione, totale",
     "impresa incorporata o acquisita"),
    (r"nuovo titolare|precedente titolare|subentrante",
     "altra parte della voltura"),
    (r"responsabile dell.impianto|terzo responsabile",
     "responsabile dell'impianto"),
    (r"coniuge|convivente|\berede\b|familiar",
     "familiare"),
    (r"direttore tecnico",
     "direttore tecnico"),
    (r"progettista|direttore dei lavori|collaudator",
     "progettista o direzione lavori"),
    (r"proprietari[oa] dell|committente|amministratore di condominio",
     "proprietario o committente"),
    (r"impresa esecutrice|impresa affidataria",
     "impresa esecutrice"),
)

_COMPILATE = tuple((re.compile(rx, re.I), motivo) for rx, motivo in FORMULE)

# I marcatori che la resa mette al posto dei campi: «12:34» oppure «12:casella»
_MARCATORE = re.compile(r"«(\d+):")


def _motivo(testo: str):
    for rx, motivo in _COMPILATE:
        if rx.search(testo):
            return motivo
    return None


def avvertimenti(mappa: dict, scritte) -> list:
    """Le scritture cadute dove il foglio parla di un altro soggetto.

    `scritte` sono gli identificativi delle ancore su cui si sta per scrivere
    (o su cui si e' scritto). Torna una voce per pagina e motivo:

        [{"pagina": 9, "motivo": "soggetto cessato dalla carica",
          "ancore": ["p9.riempimento.057-234", ...], "riga": "...il testo..."}]

    Vuota non vuol dire che il modulo sia giusto: vuol dire che non si e'
    riconosciuta nessuna delle formule note.
    """
    scritte = set(scritte)
    if not scritte:
        return []
    fuori = {}
    for resa in mappa.get("rese", []):
        righe = resa["testo"].split("\n")
        indirizzi = resa["indirizzi"]
        for numero_riga, riga in enumerate(righe):
            colpite = [indirizzi[n] for n in _MARCATORE.findall(riga)
                       if indirizzi.get(n) in scritte]
            if not colpite:
                continue
            inizio = max(0, numero_riga - RIGHE_SOPRA)
            motivo = _motivo(" ".join(righe[inizio:numero_riga + 1]))
            if not motivo:
                continue
            chiave = (resa["pagina"], motivo)
            voce = fuori.setdefault(chiave, {"pagina": resa["pagina"],
                                             "motivo": motivo,
                                             "ancore": [],
                                             "riga": riga.strip()[:120]})
            voce["ancore"].extend(colpite)
    return [fuori[k] for k in sorted(fuori)]


# Quanto devono somigliarsi due righe per essere due versioni della stessa
# dichiarazione. Misurato sui moduli di gara: le alternative vere condividono
# quasi tutto - cambia il verbo - mentre due dichiarazioni diverse condividono
# al massimo le formule di rito.
SOMIGLIANZA = 0.6
VICINE = 4          # righe di distanza: le alternative stanno in fila


def _parole(riga: str) -> set:
    return set(re.findall(r"[a-zà-ù]{4,}", riga.lower()))


def _soggetti_nominati(riga: str) -> set:
    """Gli enti e le sigle nominate: INPS, INAIL, Cassa Edile, PEC.

    Servono a distinguere due righe **parallele** da due **alternative**. Se
    cambia l'ente di cui si parla sono due cose da dichiarare tutte e due:

        di essere iscritto all'INPS di ___     ]  paralleli:
        di essere iscritto all'INAIL di ___    ]  vanno compilati entrambi

    Se l'ente e' lo stesso e cambia solo il verbo, sono alternative:

        di essere iscritto nell'elenco dei fornitori...        ]  una sola
        di aver presentato domanda... nell'elenco dei fornitori ]  delle due
    """
    # I.N.P.S. e INPS sono lo stesso ente: senza togliere i punti, due righe
    # che nominano enti diversi sembrano parlare della stessa cosa.
    senza_punti = re.sub(r"\b((?:[A-Z]\.){2,}[A-Z]?)", lambda m: m.group(1).replace(".", ""), riga)
    return set(re.findall(r"\b[A-Z]{3,}\b", senza_punti)) | {
        p.lower() for p in re.findall(r"\b[A-Z][a-zà-ù]{3,}\b", senza_punti)}


# Una dichiarazione alternativa e' una dichiarazione: comincia per "dichiara",
# "di essere", "di aver", "di non". Due campi affiancati - "n. di iscrizione" e
# "data di iscrizione" - non lo sono, e senza questo filtro venivano contati.
DICHIARA = re.compile(r"dichiar|di\s+essere|di\s+aver|di\s+non|barrare", re.I)
PAROLE_MINIME = 8


def contraddizioni(mappa: dict, scritte) -> list:
    """Dichiarazioni alternative riempite piu' di una volta.

    Su un modulo di gara le opzioni escludenti stanno in fila e differiscono
    per una parola:

        DICHIARA di essere iscritto nell'elenco dei fornitori...
        DICHIARA di aver presentato la domanda di iscrizione... nell'elenco...
        DICHIARA di non essere iscritto nell'elenco dei fornitori...

    Riempirne due dice due cose incompatibili, e non serve capire di che cosa
    parlino per accorgersene: basta vedere che sono sorelle. E' una difesa che
    non costa una chiamata e che vale su qualunque modulo, perche' guarda la
    forma e non il contenuto.

    Trovata cosi': su due moduli il motore ha dichiarato insieme "sono
    iscritto alla white list" e "ho chiesto l'iscrizione".
    """
    scritte = set(scritte)
    if not scritte:
        return []
    fuori = []
    for resa in mappa.get("rese", []):
        righe = resa["testo"].split("\n")
        indirizzi = resa["indirizzi"]
        toccate = []
        for numero, riga in enumerate(righe):
            colpite = [indirizzi[n] for n in _MARCATORE.findall(riga)
                       if indirizzi.get(n) in scritte]
            if colpite:
                toccate.append((numero, riga, colpite))
        for i, (numero, riga, colpite) in enumerate(toccate):
            for altro_numero, altra, altre in toccate[i + 1:]:
                if altro_numero - numero > VICINE:
                    break
                if not (DICHIARA.search(riga) and DICHIARA.search(altra)):
                    continue
                a, b = _parole(riga), _parole(altra)
                if len(a) < PAROLE_MINIME or len(b) < PAROLE_MINIME:
                    continue
                comune = len(a & b) / min(len(a), len(b))
                # Se le due righe nominano enti diversi sono parallele, non
                # alternative: INPS e INAIL vanno dichiarati tutti e due.
                # Senza questo, su 47 moduli si segnalavano 23 contraddizioni
                # e le prime che ho aperto erano tutte false.
                if _soggetti_nominati(riga) != _soggetti_nominati(altra):
                    continue
                if comune >= SOMIGLIANZA:
                    fuori.append({
                        "pagina": resa["pagina"],
                        "motivo": "due varianti della stessa dichiarazione, "
                                  "riempite tutte e due",
                        "ancore": colpite + altre,
                        "riga": riga.strip()[:110],
                        "altra": altra.strip()[:110]})
    return fuori


# NOTA: qui c'era un controllo che cercava le scritture finite nel blocco del
# destinatario - "Spett.le Comune di...", che sono dati della stazione
# appaltante e non nostri. Ne avevo trovato un caso vero rileggendo a mano un
# collaudo Word: la PEC dell'impresa nell'intestazione di un comune.
#
# L'ho tolto perche' non generalizzava. Con una finestra di righe fisse
# segnalava dodici moduli e undici erano falsi - "Il/La sottoscritto/a" che
# capita in alto non e' il destinatario. Stringendolo, i falsi sparivano e con
# loro anche l'unico caso vero, la cui etichetta era "COMUNE DI ROCCADASPIDE
# AREA TECNICA": per prenderlo avrei dovuto aggiungere "COMUNE DI + nome", cioe'
# tararlo su quel singolo esempio - e rischiare di bocciare "Comune di
# residenza", che e' giusto.
#
# Il caso esiste e va risolto, ma con una misura, non con una regola scritta
# addosso a un modulo.


# Le sezioni che esistono solo in certe configurazioni di gara. Misurato su 48
# bandi e 4553 campi: una domanda sola - partecipi da sola o in raggruppamento?
# - decide 1152 campi, il 25,3%. Cinque domande ne decidono il 30,4%.
#
# Per un'impresa che si presenta da sola quei campi vanno lasciati vuoti, e
# oggi il motore deve indovinarlo uno per uno. Chiederlo costa una domanda e
# toglie di mezzo un quarto del modulo prima ancora di interpellare il modello:
# meno spesa, meno rumore, meno errori.
CONDIZIONI = {
    "raggruppamento": r"raggruppament|\br\.?t\.?i\.?\b|consorz|mandant|mandatari"
                      r"|rete di imprese|aggregazion|\bg\.?e\.?i\.?e\.?\b|cooptat",
    "avvalimento":    r"avvaliment|ausiliari",
    "subappalto":     r"subappalt",
}

_CONDIZIONI = {k: re.compile(v, re.I) for k, v in CONDIZIONI.items()}


def da_saltare(mappa: dict, attive) -> set:
    """Le ancore nelle sezioni che, data la risposta, non si applicano.

    `attive` sono le condizioni che valgono per questa gara: se l'impresa si
    presenta da sola, `attive` e' vuoto e tutte le sezioni condizionali si
    spengono. Non vuota vuol dire "lasciale decidere al modello": qui non si
    indovina niente in piu' di quello che e' stato chiesto.
    """
    # None vuol dire "non lo so ancora", e va tenuto distinto da "nessuna":
    # senza questa riga chi non risponde si vedeva spegnere TUTTE le sezioni
    # condizionali invece di nessuna, cioe' l'opposto. Senza risposta non si
    # decide niente e la palla resta al modello.
    if attive is None:
        return set()
    attive = set(attive)
    spente = [rx for nome, rx in _CONDIZIONI.items() if nome not in attive]
    if not spente:
        return set()
    fuori = set()
    for resa in mappa.get("rese", []):
        righe = resa["testo"].split("\n")
        indirizzi = resa["indirizzi"]
        for numero, riga in enumerate(righe):
            marcatori = _MARCATORE.findall(riga)
            if not marcatori:
                continue
            attorno = " ".join(righe[max(0, numero - RIGHE_SOPRA):numero + 1])
            if any(rx.search(attorno) for rx in spente):
                fuori.update(indirizzi[n] for n in marcatori if n in indirizzi)
    return fuori


def racconta(avvisi: list) -> str:
    """L'avvertimento in italiano, per chi legge il verdetto."""
    if not avvisi:
        return ""
    righe = ["Attenzione: in queste pagine il modulo parla di un soggetto",
             "diverso dall'impresa, oppure la sezione vale solo in certi casi.",
             "Controllale prima di consegnare: qui il motore sbaglia."]
    for a in avvisi:
        righe.append("  pagina %d - %s (%d campi scritti)"
                     % (a["pagina"], a["motivo"], len(a["ancore"])))
    return "\n".join(righe)
