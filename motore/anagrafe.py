# -*- coding: utf-8 -*-
"""Abbina un campo del modulo a un dato dell'anagrafica. Deterministico.

L'obiettivo non e' piu' compilare tutto: e' compilare **bene** la parte che il
fascicolo gia' conosce, e dire chiaramente che il resto non lo tocchiamo.

Questo strato non chiama nessun modello e non indovina mai. Tre esiti soli:

    (chiave, "")        so quale dato va qui
    (None, "ambiguo")   l'etichetta porta a piu' dati: decide il modello
    (None, "ignoto")    non e' anagrafica: resta a chi compila

L'ambiguita' non e' un difetto da nascondere. 'Via' puo' essere quella della
sede o quella di residenza, e sbagliarla e' peggio che lasciarla vuota: chi
guarda una bozza vede il campo vuoto, non vede un indirizzo giusto al posto
sbagliato.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

# una parola che compare in troppe chiavi non distingue niente: 'data' sta in
# dieci chiavi diverse e farebbe corrispondere 'data di scadenza' alla nascita
MASSIME_CHIAVI = 3
# oltre queste parole significative non e' piu' il nome di un campo ma
# un pezzo di frase: li' il deterministico si ferma e passa al modello
PAROLE_DA_ETICHETTA = 3
VUOTE = {"il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "di", "del",
         "della", "dello", "dei", "degli", "delle", "da", "dal", "dalla", "in",
         "nel", "nella", "con", "su", "per", "tra", "fra", "e", "ed", "o",
         "che", "chi", "al", "allo", "alla", "ai", "agli", "alle", "a", "n",
         "sottoscritto", "sottoscritta", "dichiara", "dichiaro", "presso",
         "seguente", "seguenti", "cui", "come", "anche", "non", "si", "se",
         "ovvero", "oppure", "quale", "qualita", "num", "numero"}

# come i moduli scrivono le stesse cose. Non e' un elenco di casi: e' il
# vocabolario dell'anagrafica visto dalla parte di chi stampa il modulo.
SINONIMI = {
    "cf": "fiscale", "c f": "codice fiscale", "p iva": "partita iva",
    "piva": "partita iva", "p i": "partita iva", "cap": "cap",
    "prov": "provincia", "tel": "telefono", "e mail": "email",
    "mail": "email", "pec": "pec", "rea": "rea", "denominazione": "ragione",
    "ditta": "ragione", "societa": "ragione", "impresa": "ragione",
    "residenza": "residenza", "domicilio": "residenza", "nato": "nascita",
    "nata": "nascita", "luogo": "luogo", "via": "via", "civico": "civico",
}


def semplice(testo: str) -> str:
    testo = unicodedata.normalize("NFKD", testo or "")
    testo = "".join(c for c in testo if not unicodedata.combining(c))
    testo = re.sub(r"[^\w\s]+", " ", testo.lower())
    return re.sub(r"\s+", " ", testo).strip()


def parole(testo: str):
    piano = semplice(testo)
    for corta, lunga in SINONIMI.items():
        piano = re.sub(r"\b%s\b" % re.escape(corta), lunga, piano)
    return [p for p in piano.split() if p not in VUOTE and len(p) > 2]


class Anagrafe:
    """Il fascicolo visto come vocabolario: chiave -> parole, chiave -> valore."""

    def __init__(self, fascicolo: dict, sezione: str = "profilo"):
        self.fascicolo = fascicolo
        self.sezione = sezione
        self.voci = []
        for chiave, valore in (fascicolo.get(sezione) or {}).items():
            if not isinstance(valore, str) or not valore.strip():
                continue
            ps = tuple(p for p in parole(chiave.replace("_", " ")))
            if ps:
                self.voci.append({"chiave": chiave, "parole": ps, "valore": valore})
        conta = Counter()
        for v in self.voci:
            for p in set(v["parole"]):
                conta[p] += 1
        self.distintive = conta
        # tutte le parole che l'anagrafica usa: serve a riconoscere quando
        # un'etichetta ne contiene una che parla di un dato diverso
        self.vocabolario = set(conta)

    @staticmethod
    def da_file(percorso, sezione: str = "profilo") -> "Anagrafe":
        return Anagrafe(json.loads(Path(percorso).read_text(encoding="utf-8")), sezione)

    def abbina(self, etichetta: str, contesto: str = ""):
        """Quale dato dell'anagrafica va in questo campo. Nessuna ipotesi.

        Il deterministico decide **solo quando l'etichetta e' un nome di
        campo**: poche parole, come 'Cognome', 'P.IVA', 'C.A.P.'. Misurato su
        dodici moduli, il 24% degli abbinamenti nasceva invece da frammenti di
        frase lunghi, ed e' li' che stavano tutti gli errori di senso -
        'infiltrazione mafiosa (c.d. White List)' finiva sulla prefettura della
        white list. Un frammento di dichiarazione non e' l'etichetta di un
        campo: va letto nel suo contesto, e quello sa farlo solo il modello.
        """
        insieme = set(parole(etichetta))
        if not insieme:
            return None, "senza etichetta"
        if len(insieme) > PAROLE_DA_ETICHETTA:
            return None, "frase, non etichetta"
        candidate = []
        for v in self.voci:
            comuni = insieme & set(v["parole"])
            forti = [p for p in comuni if self.distintive.get(p, 99) <= MASSIME_CHIAVI]
            if forti:
                candidate.append((len(comuni), len(forti), v))
        if not candidate:
            return None, "ignoto"
        # se una chiave combacia meglio di tutte le altre, e' quella
        candidate.sort(key=lambda x: (-x[0], -x[1], len(x[2]["parole"])))
        migliore = candidate[0]
        pari = [c for c in candidate if (c[0], c[1]) == (migliore[0], migliore[1])]
        if len(pari) > 1:
            nomi = ", ".join(sorted(c[2]["chiave"] for c in pari)[:3])
            return None, "ambiguo (%s)" % nomi

        # L'etichetta deve parlare di quel dato e basta. Se contiene un'altra
        # parola del vocabolario dell'anagrafica, che al dato scelto non
        # appartiene, allora sta dicendo due cose e non si decide.
        #
        # Misurato: 'luogo e data' finiva su luogo_nascita venticinque volte
        # nel corpus. E' la riga della firma in fondo al modulo - dove e quando
        # si firma - non il luogo di nascita. Decideva su 'luogo' e buttava via
        # 'data', che era la parola che distingueva i due casi.
        fuori = (insieme - set(migliore[2]["parole"])) & self.vocabolario
        if fuori:
            return None, "ambiguo (l'etichetta dice anche: %s)" % ", ".join(sorted(fuori))
        return migliore[2]["chiave"], ""

    def somiglia(self, etichetta: str, contesto: str = "") -> bool:
        """Vale la pena chiedere al modello che cosa va in questo campo?

        Se ne' l'etichetta ne' la frase intorno contengono una sola parola del
        vocabolario dell'anagrafica, non e' anagrafica e non si paga per
        chiederlo. Serve a mandare al modello qualche decina di campi per
        modulo, non tutti."""
        parole_note = set()
        for v in self.voci:
            parole_note.update(v["parole"])
        vicine = set(parole(etichetta)) | set(parole(contesto))
        return bool(vicine & parole_note)

    def valore(self, chiave: str):
        return (self.fascicolo.get(self.sezione) or {}).get(chiave)


def accetta_testo(ancora) -> bool:
    """Il profilo testuale non risponde a scelte, firme o pulsanti PDF."""
    return (ancora.tipo != "casella" and
            (ancora.tipo != "widget" or ancora.parametri.get("genere") == "Text"))


def riempi(ancore, anagrafe: Anagrafe):
    """Per ogni ancora dice **quale chiave** del fascicolo va scritta, o perche' no.

    Ritorna (chiavi, motivi): `chiavi` e' {ancora: nome del campo}, non il
    valore. E' la differenza che tiene: lo script nomina la chiave e copia il
    valore dal fascicolo al momento di scrivere, cosi' in una dichiarazione
    sostitutiva non finisce mai una trascrizione, e se il fascicolo cambia il
    modulo si rifa' da solo.

    `motivi` dice per ogni ancora perche' e' rimasta vuota: un campo vuoto con
    il motivo scritto e' un esito legittimo, un campo riempito a caso no.
    """
    chiavi, motivi, incerti = {}, {}, []
    for a in ancore:
        if not accetta_testo(a):
            motivi[a.id] = "scelta, non anagrafica"
            continue
        chiave, perche = anagrafe.abbina(a.etichetta, a.contesto)
        if chiave is None:
            motivi[a.id] = perche
            # un campo senza etichetta e senza contesto non ha niente da
            # leggere: al modello si manderebbe una pagina bianca
            muto = not (a.etichetta or "").strip() and not (a.contesto or "").strip()
            if not muto and (perche != "ignoto"
                             or anagrafe.somiglia(a.etichetta, a.contesto)):
                incerti.append(a)
            continue
        if not anagrafe.valore(chiave):
            motivi[a.id] = "il fascicolo non ha %s" % chiave
            continue
        chiavi[a.id] = chiave
        motivi[a.id] = chiave
    togli_colonne_ripetute(chiavi, motivi, ancore)
    return chiavi, motivi, incerti


def togli_colonne_ripetute(chiavi: dict, motivi: dict, ancore):
    """Una colonna di tabella che si ripete su piu' righe non si compila.

    Sotto l'intestazione COGNOME ci sono tre celle, e sono per tre persone
    diverse: il fascicolo ne conosce una sola, e scriverla in tutte e tre e' un
    documento falso, non un documento incompleto. Si riconosce dalla geometria -
    stessa colonna, stessa larghezza, righe diverse - senza sapere che cosa
    contenga la tabella.

    Non se ne compila nemmeno una: la prima riga sarebbe un'ipotesi su chi viene
    per primo, e qui non si fanno ipotesi.
    """
    per_id = {a.id: a for a in ancore}
    colonne = {}
    for identificativo, chiave in chiavi.items():
        a = per_id.get(identificativo)
        if a is None:
            continue
        colonne.setdefault((a.pagina, chiave, round(a.rect[0], 0), round(a.rect[2], 0)),
                           []).append(a)
    for (_, chiave, _, _), gruppo in colonne.items():
        if len(gruppo) < 2:
            continue
        if len({round(a.rect[1], 0) for a in gruppo}) < 2:
            continue                       # stessa riga: non e' una colonna
        for a in gruppo:
            chiavi.pop(a.id, None)
            motivi[a.id] = ("colonna di tabella ripetuta su %d righe: la "
                            "compila chi sa chi sono" % len(gruppo))
