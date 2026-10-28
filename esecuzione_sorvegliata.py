# -*- coding: utf-8 -*-
"""Compatibilita con i compilatori storici mediante proiezioni di dati.

Il nuovo percorso applicativo PDF usa piani JSON e scrittura deterministica.
Qui i vecchi corpi valori() vengono interpretati da motore.espressioni:
nessuna esecuzione di Python generato, attributo arbitrario o accesso a file.
I costrutti non supportati sono rifiutati; gli artefatti originali restano
conservati e possono essere rigenerati come piani dichiarativi.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

from motore import guardie

# Che cosa puo' esserci in un campo. Un'ancora vuole un testo, un numero o
# una spunta: qualunque altra cosa - una funzione, un oggetto, una lista -
# e' un errore del modello e non si scrive.
TIPI_AMMESSI = (str, int, float, bool)

VALORE_MASSIMO = 2000        # un campo di modulo non contiene un romanzo


class ValoriInvalidi(RuntimeError):
    """La funzione del modello non ha restituito quello che doveva."""


def _definizione_di_valori(codice: str) -> ast.FunctionDef:
    """Solo il `def valori(...)`, staccato dal resto del file."""
    for nodo in ast.parse(codice).body:
        if isinstance(nodo, ast.FunctionDef) and nodo.name == "valori":
            return nodo
    raise ValoriInvalidi("il programma non contiene una funzione valori()")


def _senza_cicli_infiniti(definizione):
    """Niente `while` dentro valori().

    Una funzione che sceglie dei dati non ha bisogno di girare in tondo, e
    senza contenitore non c'e' nessuno che la fermi se lo fa. Vietarlo costa
    niente e toglie l'unico modo semplice di bloccare il server.
    """
    for nodo in ast.walk(definizione):
        if isinstance(nodo, ast.While):
            raise ValoriInvalidi("valori() contiene un ciclo while: non serve "
                                 "a scegliere dei dati e qui non si esegue")


def scegli_valori(codice: str, fascicolo: dict, ancore: dict) -> dict:
    """Il dizionario {ancora: valore}, ripulito di tutto quello che non torna."""
    definizione = _definizione_di_valori(codice)
    _senza_cicli_infiniti(definizione)

    try:
        from motore.espressioni import proietta
        scelte = proietta(definizione, fascicolo)
    except Exception as guaio:                              # noqa: BLE001
        raise ValoriInvalidi("valori() si e' fermata: %s" % guaio) from guaio
    if not isinstance(scelte, dict):
        raise ValoriInvalidi("valori() non ha restituito un dizionario")
    # Old exclusion wrappers are data, never a second function to execute.
    for nodo in ast.parse(codice).body:
        if isinstance(nodo, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_TOLTE' for t in nodo.targets):
            try:
                tolte = ast.literal_eval(nodo.value)
                if not isinstance(tolte, list) or not all(isinstance(a, str) for a in tolte):
                    raise ValueError('Filtro non valido')
                scelte = {a: v for a, v in scelte.items() if a not in tolte}
            except (ValueError, TypeError) as exc:
                raise ValoriInvalidi('Filtro di esclusione non interpretabile') from exc

    # Il filtro finale: qui non si giudica il senso, si giudica la forma.
    # Un'ancora che non esiste non ha un posto dove andare, e un valore che
    # non e' un testo non e' una cosa che si scrive su un foglio.
    pulite, scartate = {}, []
    for chiave, valore in scelte.items():
        if chiave not in ancore:
            scartate.append((chiave, "questa ancora non esiste nel modulo"))
            continue
        if valore is None or valore is False or valore == "":
            continue
        if not isinstance(valore, TIPI_AMMESSI):
            scartate.append((chiave, "non e' un testo: %s" % type(valore).__name__))
            continue
        testo = valore if isinstance(valore, bool) else str(valore)
        if not isinstance(testo, bool) and len(testo) > VALORE_MASSIMO:
            scartate.append((chiave, "lungo %d caratteri" % len(testo)))
            continue
        pulite[chiave] = testo
    return pulite, scartate


def esegui(codice: str, originale, cartella, fascicolo: dict) -> dict:
    """Stessa firma e stesso resoconto di `esecuzione.esegui`.

    Cosi' chi chiama non deve sapere quale delle due strade e' stata presa:
    cambia dove gira la funzione del modello, non che cosa succede al PDF.
    """
    import fitz
    from riusare.strumenti_documento import (Ancora, PagineDiritte, firmato,
                                             impronta, scrivi)

    originale, cartella = Path(originale), Path(cartella)
    uscita = cartella / "uscita"
    uscita.mkdir(parents=True, exist_ok=True)

    def fallita(perche):
        return {"codice_uscita": 1, "stdout": "", "stderr": perche,
                "uscita": str(uscita), "bozza": None, "scritture": None,
                "riuscita": False}

    if firmato(originale):
        return fallita("Questo PDF ha gia' una firma digitale applicata: "
                       "scriverci dentro la renderebbe non valida.")

    # Le guardie prima di tutto: se parlano, non si esegue niente.
    guasti = guardie.controlla_programma(codice)
    if guasti:
        return fallita("Le guardie hanno fermato il programma:\n%s"
                       % "\n".join(guasti))

    ancore = json.loads(_blocco_ancore(codice))
    attesa = _impronta_attesa(codice)
    trovata = impronta(originale)
    if attesa and trovata != attesa:
        return fallita("Questo compilatore e' stato misurato su un'altra "
                       "edizione del modulo:\n  attesa:  %s\n  trovata: %s"
                       % (attesa, trovata))

    try:
        scelte, scartate = scegli_valori(codice, fascicolo, ancore)
    except ValoriInvalidi as guaio:
        return fallita(str(guaio))

    documento = fitz.open(str(originale))
    scritture = []
    with PagineDiritte(documento) as diritto:
        for identificativo, valore in scelte.items():
            ancora = Ancora.da_dict(ancore[identificativo])
            esito = scrivi(diritto[ancora.pagina], ancora, valore)
            scritture.append({"ancora": identificativo, "tipo": ancora.tipo,
                              "etichetta": ancora.etichetta, "valore": valore,
                              "scritto": bool(esito.ok), "motivo": esito.motivo})
    bozza = uscita / "bozza.pdf"
    documento.save(str(bozza))
    documento.close()

    dove = uscita / "scritture.json"
    dove.write_text(json.dumps({"impronta": attesa, "scritture": scritture},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    riuscite = sum(1 for s in scritture if s["scritto"])
    racconto = ["scritture riuscite: %d su %d" % (riuscite, len(scritture))]
    for chiave, perche in scartate:
        racconto.append("  scartata %s: %s" % (chiave, perche))
    return {"codice_uscita": 0, "stdout": "\n".join(racconto), "stderr": "",
            "uscita": str(uscita), "bozza": str(bozza),
            "scritture": str(dove), "riuscita": True}


def _blocco_ancore(codice: str) -> str:
    """La geometria congelata nello stampo, presa senza eseguire il file."""
    for nodo in ast.parse(codice).body:
        if (isinstance(nodo, ast.Assign)
                and any(getattr(b, "id", "") == "ANCORE" for b in nodo.targets)):
            # ANCORE = json.loads(r\"\"\"...\"\"\")
            for dentro in ast.walk(nodo.value):
                if isinstance(dentro, ast.Constant) and isinstance(dentro.value, str):
                    return dentro.value
    raise ValoriInvalidi("il programma non contiene le ancore misurate")


def _impronta_attesa(codice: str) -> str:
    for nodo in ast.parse(codice).body:
        if (isinstance(nodo, ast.Assign)
                and any(getattr(b, "id", "") == "IMPRONTA" for b in nodo.targets)
                and isinstance(nodo.value, ast.Constant)):
            return str(nodo.value.value)
    return ""
