# -*- coding: utf-8 -*-
"""La lavorazione di un modulo Word, dall'arrivo del file al verdetto.

Stesse fasi del percorso PDF e stessi passi, cosi' la pagina che li racconta e
la barra sono le stesse. Cambia quello che sta sotto, e cambia parecchio: qui
non si misura niente, si sostituisce del testo.

Un passaggio in piu' rispetto al PDF, e obbligatorio: il 77% dei moduli Word
pubblicati dai comuni e' `.doc` del 1997, che nessuna libreria Python apre. Si
converte con LibreOffice prima di tutto il resto.
"""
from __future__ import annotations

import json
from pathlib import Path

from motore import agente, soggetti, word
from motore.anagrafe import Anagrafe

# Quante volte si richiede al modello quando la risposta arriva illeggibile.
# Due, non di piu': in Word non c'e' codice da eseguire e da far fallire, e
# l'unico guasto che si ripaga a ritentare e' quello di passaggio - misurato
# su 02_Demanio_Rimini, una risposta illeggibile e poi la stessa domanda con
# un JSON pulito. Se sbaglia due volte uguale, non e' di passaggio.
TENTATIVI = 2


def _finta_mappa(testo: str, indirizzi: dict) -> dict:
    """La forma che il guardiano si aspetta.

    Il guardiano dei soggetti e' scritto per il PDF, che ha le pagine. Un Word
    e' un flusso unico: si costruisce una pagina sola invece di scriverne un
    altro che poi diverge dal primo.
    """
    return {"rese": [{"pagina": 1, "testo": testo, "indirizzi": indirizzi}]}


def lavora(radice: Path, documento, fascicolo: dict, cartella_lavoro: Path,
           pertinenza_confermata: bool = False, togli=(), condizioni=None,
           scelte_di_prima=None):
    """Genera dizionari {passo, testo, ...}. L'ultimo ha sempre 'verdetto'.

    `scelte_di_prima` e' la decisione gia' presa su questo stesso documento:
    quando c'e', il modello non viene richiamato. Serve a chi toglie un campo
    sbagliato dalla bozza. Senza, rifare la bozza vuol dire rifare la domanda,
    e la risposta e' libera di cambiare: chi ha spuntato una casella si
    ritroverebbe una bozza diversa da quella che ha appena letto.

    Misurato su ModuloDichiarazioneArt.90, due corse indipendenti: 15
    decisioni su 15 identiche. Quindi oggi il rischio e' piccolo - ma e' un
    rischio osservato, non escluso, e qui non serve correrlo: riusare la
    decisione e' anche gratis e immediato, mentre richiamarla si paga.
    """
    documento = Path(documento)
    cartella_lavoro = Path(cartella_lavoro)
    cartella_lavoro.mkdir(parents=True, exist_ok=True)

    yield {"passo": "misura", "testo": "Leggo il modulo Word."}
    try:
        mappa = word.leggi(documento, cartella_lavoro / "convertiti")
    except word.ConversioneAssente as fermata:
        yield {"passo": "rifiuto", "verdetto": None, "testo": str(fermata)}
        return
    if mappa.get("convertito_da"):
        yield {"passo": "misura",
               "testo": "Era un Word vecchio (.doc): convertito per poterlo leggere."}

    # I nomi sono quelli che userebbe chi guarda il foglio, non quelli del
    # codice: chi legge la barra deve riconoscere il modulo che ha in mano.
    NOMI = (("riempimento", "righe da riempire"),
            ("modulo", "campi modulo di Word"),
            ("cella", "celle di tabella"),
            ("casella", "caselle"))
    quanti = {t: sum(1 for a in mappa["ancore"] if a["tipo"] == t) for t, _ in NOMI}
    dettaglio = ", ".join("%d %s" % (quanti[t], nome) for t, nome in NOMI if quanti[t])
    yield {"passo": "mappa", "mappa": mappa,
           "testo": "%d campi%s." % (len(mappa["ancore"]),
                                     ": " + dettaglio if dettaglio else "")}

    testo, indirizzi = word.rendi(mappa)
    if not indirizzi:
        yield {"passo": "verdetto", "verdetto": None,
               "testo": "Non ho trovato nessun campo da riempire in questo "
                        "documento. Se e' un modulo, usa le righe di trattini "
                        "o le celle di tabella."}
        return

    if pertinenza_confermata:
        yield {"passo": "pertinenza_ok",
               "testo": "Mi hai confermato che il modulo e' di questa impresa: vado avanti."}
    else:
        yield {"passo": "pertinenza",
               "testo": "Controllo che il modulo sia di questa impresa."}
        giudizio = agente.pertinenza(testo[:4000], fascicolo)
        if not giudizio.get("pertinente", True):
            yield {"passo": "domanda_bloccante", "verdetto": None,
                   "domanda": giudizio.get("domanda") or giudizio.get("motivo"),
                   "testo": "Mi fermo prima di lavorare: %s" % giudizio.get("motivo", "")}
            return
        yield {"passo": "pertinenza_ok",
               "testo": giudizio.get("motivo", "Modulo pertinente.")}

    # Le sezioni che non si applicano si spengono PRIMA di chiedere al
    # modello: non si paga per farsi dire che cosa mettere in un blocco che
    # deve restare vuoto, e non gli si da' l'occasione di sbagliarci dentro.
    finta = _finta_mappa(testo, indirizzi)
    spente = soggetti.da_saltare(finta, condizioni) if condizioni is not None else set()
    if spente:
        yield {"passo": "valori", "tentativo": 0,
               "testo": "Mi hai detto come partecipa l'impresa: %d campi "
                        "riguardano configurazioni che non sono la sua e "
                        "restano vuoti." % len(spente)}
        # Gli indirizzi NON si tolgono prima di chiedere: il testo mostra
        # ancora quei buchi, il modello risponde su uno di loro e la verifica
        # lo rifiuta come "fuori dal contratto", facendo fallire tutto il
        # modulo. Si lasciano nel contratto e si scartano le risposte dopo.

    anagrafe = Anagrafe(fascicolo)
    profilo = fascicolo.get("profilo", {})
    senza_dato = []

    if scelte_di_prima is not None:
        yield {"passo": "riuso",
               "testo": "Riuso la decisione gia' presa su questo modulo: non "
                        "richiamo il modello, cosi' togliere un campo toglie "
                        "quel campo e non muove gli altri."}
        # `indirizzi` va dal numero del buco all'ancora, quindi le ancore sono
        # i valori. Il filtro serve se la decisione arriva da una lettura
        # diversa del documento: meglio scartarla che scrivere su un campo che
        # in questa lettura non esiste piu'.
        esistenti = set(indirizzi.values())
        chiavi_scelte = {a: c for a, c in scelte_di_prima.items()
                         if a in esistenti and a not in spente}
    else:
        yield {"passo": "valori", "tentativo": 1,
               "testo": "Decido che cosa va in ogni campo."}
        # `scartate` invece dell'eccezione: una sola proposta fuori contratto
        # faceva fallire tutto il modulo, e quella proposta non si poteva
        # scrivere comunque. Misurato su 02_tricase_pitturazione_immobili:
        # modulo intero perso, zero campi, per una riga.
        scartate = []
        chiavi = [v["chiave"] for v in anagrafe.voci]
        # Un secondo tentativo se la risposta non si riesce a leggere. Non e'
        # ostinazione: su 02_Demanio_Rimini la risposta e' arrivata
        # illeggibile una volta e il modulo intero e' andato perso, mentre
        # rifacendo la stessa identica domanda e' tornata un JSON pulito. E'
        # un guasto di passaggio, e costa una chiamata solo quando capita.
        for tentativo in range(1, TENTATIVI + 1):
            try:
                deciso = agente.abbina_pagina(testo, indirizzi, chiavi,
                                              scartate=scartate)
                break
            except agente.RispostaModelloInvalida as storto:
                if tentativo == TENTATIVI:
                    yield {"passo": "verdetto", "verdetto": None,
                           "testo": "Il modello ha risposto in un modo che non "
                                    "riesco a leggere, due volte di fila: %s. "
                                    "Non ho scritto niente." % storto}
                    return
                yield {"passo": "valori", "tentativo": tentativo,
                       "testo": "La risposta e' arrivata illeggibile: "
                                "richiedo la stessa cosa."}
        deciso = {a: c for a, c in deciso.items() if a not in spente}
        if scartate:
            yield {"passo": "valori", "tentativo": 1,
                   "testo": "%d proposte non stavano nel modulo e le ho "
                            "scartate: quei campi restano vuoti." % len(scartate)}

        # Si tengono le CHIAVI, non i valori: la rilettura vuole le chiavi e va
        # a cercarsi il valore da sola nell'anagrafica. Passandole i valori
        # cercava `anagrafe.valore("COSTRUZIONI RIVAMARE S.R.L.")`, trovava
        # None, e bocciava ogni scrittura con "None non e' un valore valido" -
        # buttando via roba giusta senza che niente lo dicesse. Su un modulo ha
        # azzerato tutte e tre le scritture, che erano corrette.
        chiavi_scelte = {}
        for ancora, chiave in deciso.items():
            pulita = str(chiave).split(".")[-1]
            valore = profilo.get(pulita)
            if valore is None or not str(valore).strip():
                senza_dato.append(pulita)
                continue
            chiavi_scelte[ancora] = pulita

        # La rilettura: si guarda il documento COME VERREBBE e si toglie quello
        # che non ha senso, prima di scriverlo. E' una domanda diversa da quella
        # che ha prodotto i valori - non "cosa va qui" ma "questo ha senso qui"
        # - e il valore e' davanti agli occhi invece che da scegliere, come
        # rileggere una frase invece di comporla.
        #
        # Misurata sul percorso PDF: toglie 2 proposte su 45, e fra quelle
        # l'unico errore noto. Mancava qui, e mancava anche nel PDF dentro
        # l'app: stava solo nel banco di prova, quindi i numeri misurati
        # descrivevano il banco e non quello che Bianca ha davanti.
        if chiavi_scelte:
            yield {"passo": "correzione",
                   "testo": "Rileggo quello che verrebbe scritto, prima di scriverlo."}
            # `errori` invece dell'eccezione: se la rilettura non riesce -
            # risposta illeggibile, rete che cade - senza questa lista salta
            # tutto il modulo con un traceback. Con la lista, il meccanismo
            # gia' scritto sospende le assegnazioni di quella pagina: non si
            # scrive quello che non si e' potuto rileggere, e il documento
            # esce comunque, vuoto invece che rotto.
            guasti = []
            bocciati = agente.rileggi_documento(
                _finta_mappa(testo, indirizzi)["rese"], chiavi_scelte, anagrafe,
                errori=guasti)
            for ancora in (bocciati or {}):
                chiavi_scelte.pop(ancora, None)
            if guasti:
                yield {"passo": "correzione",
                       "testo": "Non sono riuscito a rileggere la bozza prima di "
                                "scriverla, e allora non ci scrivo: preferisco "
                                "darti il modulo vuoto che uno di cui non so "
                                "niente."}
            elif bocciati:
                yield {"passo": "correzione",
                       "testo": "Rileggendo ne ho tolti %d che non avevano senso "
                                "dove erano finiti." % len(bocciati)}

    # Si toglie alla fine, cosi' il campo tolto e' tolto e basta: nessun altro
    # passaggio ha piu' l'occasione di rimescolare le carte.
    for ancora in togli:
        chiavi_scelte.pop(ancora, None)

    valori = {a: profilo[c] for a, c in chiavi_scelte.items() if profilo.get(c)}

    yield {"passo": "scrittura", "testo": "Scrivo nel documento."}
    uscita = cartella_lavoro / ("bozza_" + documento.stem + ".docx")
    resoconto = word.scrivi(documento, mappa, valori, uscita)

    yield {"passo": "controllo",
           "testo": "Riapro il documento e verifico ogni scrittura."}
    verdetto = word.verifica(uscita, resoconto)
    finta = _finta_mappa(testo, indirizzi)
    scritte = [s["ancora"] for s in verdetto["verificate"]]
    verdetto["avvisi"] = soggetti.avvertimenti(finta, scritte)
    verdetto["contraddizioni"] = soggetti.contraddizioni(finta, scritte)
    verdetto["campi_totali"] = len(mappa["ancore"])
    verdetto["senza_dato"] = sorted(set(senza_dato))
    verdetto["spenti"] = len(spente)
    verdetto["valori"] = valori
    # La decisione esce col verdetto: chi vorra' togliere un campo la rimanda
    # indietro, e la bozza si rifa' senza ricomprare il giudizio del modello.
    verdetto["scelte"] = dict(chiavi_scelte)
    verdetto["bozza"] = str(uscita)

    yield {"passo": "verdetto", "verdetto": verdetto, "bozza": str(uscita),
           "mappa": mappa, "avvisi": verdetto["avvisi"],
           "testo": racconta(verdetto)}


def racconta(verdetto: dict) -> str:
    righe = ["%d campi scritti e verificati su %d campi del modulo."
             % (len(verdetto["verificate"]), verdetto["campi_totali"])]
    if verdetto["non_trovate"]:
        righe.append("%d scritture non risultano nel documento: da guardare."
                     % len(verdetto["non_trovate"]))
    if verdetto["mancate"]:
        righe.append("%d valori non scritti perche' troppo lunghi per il posto "
                     "che avevano." % len(verdetto["mancate"]))
    if verdetto["contraddizioni"]:
        righe.append("%d dichiarazioni alternative risultano compilate piu' di "
                     "una volta: vanno sistemate, dicono cose incompatibili."
                     % len(verdetto["contraddizioni"]))
    return "\n\n".join(righe)
