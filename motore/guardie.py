# -*- coding: utf-8 -*-
"""Le guardie che fanno fallire il salvataggio invece di produrre un avviso.

Un avviso si ignora. Queste tre regole tengono in piedi la tesi del progetto e
quindi non sono consigli:

  V1  un'operazione entra nella libreria comune solo dopo essersi ripetuta in
      tre script indipendenti. Qui la si misura e la si dice; e' l'unica delle
      tre che resta un giudizio, perche' 'ripetersi' si vede leggendo.
  V2  nessuno script importa un altro script: solo la libreria comune.
  V3  la libreria comune non sa niente di moduli, enti o clienti.

V3 non si difende con un elenco scritto a mano di parole proibite - sarebbe la
stessa toppa su misura di cui e' fatta la malattia. Il vocabolario vietato si
ricava dai dati: i nomi dei moduli in cartella e i nomi propri dei fascicoli.
Aggiungere un cliente aggiorna la guardia da sola.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

IMPORT_AMMESSI = {"json", "sys", "re", "math", "datetime", "pathlib", "fitz",
                  "strumenti_documento"}

# dentro valori() il modello maneggia solo dati: niente documento, niente
# geometria, niente file. E' questo che toglie alla toppa il posto dove stare.
VIETATI_NEI_VALORI = {"fitz", "Ancora", "ANCORE", "scrivi", "verifica", "open",
                      "exec", "eval", "compile", "__import__", "globals", "locals"}

MINIMA_PAROLA = 5


class Violazione(Exception):
    """Una guardia ha fermato il salvataggio."""


def _nomi_usati(nodo) -> set:
    usati = set()
    for n in ast.walk(nodo):
        if isinstance(n, ast.Name):
            usati.add(n.id)
        elif isinstance(n, ast.Attribute):
            usati.add(n.attr)
    return usati


def controlla_programma(codice: str) -> list:
    """V2 piu' la separazione fra dati e geometria dentro lo script generato."""
    guai = []
    try:
        albero = ast.parse(codice)
    except SyntaxError as e:
        return ["il programma non si compila: %s" % e]

    for n in ast.walk(albero):
        if isinstance(n, ast.Import):
            nomi = [a.name.split(".")[0] for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            nomi = [(n.module or "").split(".")[0]]
        else:
            continue
        for nome in nomi:
            if nome not in IMPORT_AMMESSI:
                guai.append("V2: importa %r; uno script puo' importare solo la "
                            "libreria comune e la libreria standard" % nome)

    for n in albero.body:
        if isinstance(n, ast.FunctionDef) and n.name == "valori":
            intrusi = _nomi_usati(n) & VIETATI_NEI_VALORI
            if intrusi:
                guai.append("valori() tocca %s: li' dentro si calcolano dati, "
                            "la geometria e' gia' misurata" % sorted(intrusi))
            break
    else:
        guai.append("manca la funzione valori(fascicolo): e' l'unica parte che "
                    "il modello scrive")
    return guai


_PAROLA = re.compile(r"[A-Za-zÀ-ÿ]{%d,}" % MINIMA_PAROLA)
_FINE_FRASE = re.compile(r"[.;:!?\n]\s*$")


def _nomi_propri(testi) -> set:
    """Un nome proprio compare maiuscolo *dentro* una frase e non compare mai
    minuscolo altrove: cosi' 'Imperia' entra e 'Comune' resta fuori, senza che
    nessuno debba scrivere a mano l'elenco delle parole comuni."""
    forti, minuscole = set(), set()
    for testo in testi:
        for trovata in _PAROLA.finditer(testo):
            parola = trovata.group(0)
            if parola[0].islower():
                minuscole.add(parola.lower())
                continue
            if not parola[1:].islower():
                continue                       # SIGLE e ACRONIMI: non sono nomi
            prima = testo[:trovata.start()]
            if prima.strip() and not _FINE_FRASE.search(prima):
                forti.add(parola.lower())
    return forti - minuscole


_vocabolario_in_cache = {}


def _vocabolario_dei_moduli(radice: Path) -> set:
    """Le parole che i moduli pubblici stampano: sono lingua comune.

    Serve a non scambiare per nome proprio una parola come 'Legge', che nei
    fascicoli compare solo maiuscola ma sui moduli e' stampata ovunque. Anche
    questo esce dai dati: nessun elenco di eccezioni scritto a mano.
    """
    if str(radice) in _vocabolario_in_cache:
        return _vocabolario_in_cache[str(radice)]
    parole = set()
    try:
        import fitz
    except ImportError:
        return parole
    for pdf in (radice / "moduli").glob("*.pdf"):
        try:
            doc = fitz.open(pdf)
        except Exception:                                  # noqa: BLE001
            continue
        for pagina in doc:
            parole.update(p.lower() for p in _PAROLA.findall(pagina.get_text("text")))
        doc.close()
    _vocabolario_in_cache[str(radice)] = parole
    return parole


def _parole_dai_dati(radice: Path) -> set:
    """Il vocabolario che la libreria comune non puo' contenere, ricavato dai
    moduli in cartella e dai nomi propri dei fascicoli."""
    dai_nomi = set()
    for pdf in (radice / "moduli").glob("*.pdf"):
        for pezzo in re.split(r"[^a-zA-Z]+", pdf.stem):
            if len(pezzo) >= MINIMA_PAROLA:
                dai_nomi.add(pezzo.lower())
    testi = []
    for fascicolo in (radice / "fascicoli").glob("*.json"):
        try:
            dati = json.loads(fascicolo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        testi.extend(_stringhe(dati))
    propri = _nomi_propri(testi) - _vocabolario_dei_moduli(radice)
    return dai_nomi | propri


def _stringhe(dati):
    if isinstance(dati, str):
        yield dati
    elif isinstance(dati, dict):
        for k, v in dati.items():
            yield str(k)
            yield from _stringhe(v)
    elif isinstance(dati, list):
        for v in dati:
            yield from _stringhe(v)


def controlla_libreria(radice: Path) -> list:
    """V3: la libreria comune non nomina moduli, enti o clienti."""
    sorgente = (radice / "riusare" / "strumenti_documento.py").read_text(encoding="utf-8")
    parole_sorgente = set(re.findall(r"[a-zà-ù]{%d,}" % MINIMA_PAROLA, sorgente.lower()))
    intruse = sorted(parole_sorgente & _parole_dai_dati(radice))
    if intruse:
        return ["V3: la libreria comune nomina %s" % ", ".join(intruse)]
    return []


def verifica_tutto(radice: Path, codice: str = None) -> list:
    guai = controlla_libreria(radice)
    if codice is not None:
        guai += controlla_programma(codice)
    return guai


def imponi(radice: Path, codice: str = None):
    """Non avvisa: ferma."""
    guai = verifica_tutto(radice, codice)
    if guai:
        raise Violazione("\n".join(guai))
