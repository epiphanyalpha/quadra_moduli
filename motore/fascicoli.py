# -*- coding: utf-8 -*-
"""Il fascicolo dell'impresa: leggerlo, e riempirne i buchi.

Quando Bianca risponde a un punto aperto il dato entra qui, non dentro un
programma. Poi si riesegue l'artefatto: zero chiamate al modello, zero costo,
e la risposta resta buona anche per il prossimo modulo che chiede la stessa cosa.
"""
from __future__ import annotations

import json
from pathlib import Path


def elenco(radice: Path):
    return sorted((radice / "fascicoli").glob("*.json"))


def carica(percorso) -> dict:
    return json.loads(Path(percorso).read_text(encoding="utf-8"))


def e_di_prova(fascicolo: dict) -> bool:
    """Se questo fascicolo contiene dati inventati.

    Il marchio sta DENTRO il file, non nel nome. Un elenco di nomi da
    escludere lascia passare in silenzio il file rinominato, ed e' lo stesso
    errore gia' fatto una volta col .gitignore. Qui la posta in gioco e'
    peggio: una bozza consegnata con dentro il nome di un'impresa che non
    esiste.

    Un fascicolo senza marchio si considera vero. E' il verso giusto: chi
    aggiunge un fascicolo di prova deve dirlo, e se se ne dimentica se ne
    accorge subito perche' l'app non lo segnala; se fosse al contrario, il
    fascicolo vero senza marchio verrebbe trattato come finto e nessuno se
    ne accorgerebbe fino alla consegna.
    """
    return bool(fascicolo.get("prova"))


def veri(radice: Path):
    """Solo i fascicoli con dati veri."""
    return [p for p in elenco(radice) if not e_di_prova(carica(p))]


def salva(percorso, fascicolo: dict):
    Path(percorso).write_text(json.dumps(fascicolo, ensure_ascii=False, indent=1),
                              encoding="utf-8")


def imposta(fascicolo: dict, chiave: str, valore):
    """Scrive un valore su una chiave puntata ('profilo.orario_inizio')."""
    pezzi = [p for p in str(chiave).split(".") if p]
    if not pezzi:
        raise ValueError("chiave vuota")
    dove = fascicolo
    for pezzo in pezzi[:-1]:
        if not isinstance(dove.get(pezzo), dict):
            dove[pezzo] = {}
        dove = dove[pezzo]
    dove[pezzi[-1]] = valore
    return fascicolo


# I nomi sotto cui puo' arrivare l'anagrafica. Il motore legge `profilo`, ma
# chi esporta i dati da un'altra parte la chiama come gli pare, e un fascicolo
# con la sezione sbagliata non da' errore: compila zero campi e sembra colpa
# del modulo. Meglio riconoscerlo qui, una volta.
SEZIONI = ("profilo", "profilo_app", "anagrafica", "dati", "impresa")

CANONICA = "profilo"


def _scalare(valore) -> bool:
    return valore is None or isinstance(valore, (str, int, float, bool))


def importa(dati: dict):
    """Porta un'anagrafica qualunque nella forma che il motore legge.

    Torna (fascicolo, resoconto). Il resoconto dice che cosa e' stato trovato e
    che cosa e' stato lasciato fuori, perche' un'importazione muta e' peggio di
    una che fallisce: i dati mancanti si scoprono a bozza consegnata.
    """
    if not isinstance(dati, dict):
        raise ValueError("un'anagrafica e' un oggetto JSON, non %s"
                         % type(dati).__name__)

    trovata = None
    for nome in SEZIONI:
        sezione = dati.get(nome)
        if isinstance(sezione, dict) and any(_scalare(v) for v in sezione.values()):
            trovata = nome
            break

    if trovata is None:
        # nessuna sezione nota: se il livello piu' alto e' gia' fatto di dati,
        # e' lui l'anagrafica
        if any(_scalare(v) for v in dati.values()):
            grezzo, resto = dict(dati), {}
        else:
            raise ValueError(
                "Non trovo l'anagrafica. Cerco una sezione fra %s, oppure i "
                "dati direttamente al primo livello." % ", ".join(SEZIONI))
    else:
        grezzo = dict(dati[trovata])
        resto = {k: v for k, v in dati.items() if k != trovata}

    profilo, scartate = {}, []
    for chiave, valore in grezzo.items():
        if not _scalare(valore):
            scartate.append(chiave)                # elenchi e sotto-oggetti
            continue
        profilo[chiave] = "" if valore is None else str(valore)

    fascicolo = dict(resto)
    fascicolo[CANONICA] = profilo
    resoconto = {
        "sezione": trovata or "(primo livello)",
        "rinominata": bool(trovata and trovata != CANONICA),
        "dati": len(profilo),
        "vuoti": sorted(k for k, v in profilo.items() if not v.strip()),
        "scartate": sorted(scartate),
        "altre_sezioni": sorted(resto),
    }
    return fascicolo, resoconto


def racconta_importazione(r: dict) -> str:
    righe = ["Trovati %d dati nella sezione «%s»." % (r["dati"], r["sezione"])]
    if r["rinominata"]:
        righe.append("La sezione si chiamava «%s»: l'ho messa sotto «%s», che "
                     "e' quella che il compilatore legge." % (r["sezione"], CANONICA))
    if r["vuoti"]:
        righe.append("%d dati sono senza valore: %s."
                     % (len(r["vuoti"]), ", ".join(r["vuoti"][:6])
                        + (" e altri" if len(r["vuoti"]) > 6 else "")))
    if r["scartate"]:
        righe.append("Non sono dati singoli e restano fuori dalla scheda: %s."
                     % ", ".join(r["scartate"]))
    return "\n\n".join(righe)


def leggi(fascicolo: dict, chiave: str):
    dove = fascicolo
    for pezzo in str(chiave).split("."):
        if not isinstance(dove, dict) or pezzo not in dove:
            return None
        dove = dove[pezzo]
    return dove
