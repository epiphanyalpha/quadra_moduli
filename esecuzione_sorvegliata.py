# -*- coding: utf-8 -*-
"""Esegue solo la funzione che sceglie i dati, senza contenitore.

Serve dove un contenitore non si puo' avere: dentro un contenitore, per
esempio. Su Render l'app gira gia' dentro Docker, e Docker dentro Docker
non c'e', quindi con la sola `esecuzione.py` meta' dell'app - tutti i PDF -
sarebbe spenta la' fuori. E i bandi sono quasi tutti in PDF.

L'IDEA, CHE NON E' UN RIPIEGO

Del programma scritto dal modello a noi serve **una funzione sola**:
`valori(fascicolo)`, che restituisce {ancora: valore}. Tutto il resto dello
stampo - aprire il PDF, controllare l'impronta, raddrizzare le pagine,
scrivere, salvare - e' codice nostro, gia' scritto e gia' collaudato, e lo
rifacciamo qui invece di farlo fare a lui.

Quindi non si esegue il suo programma: gli si chiede il dizionario. E' la
divisione che il progetto ha sempre dichiarato - il modello nomina le
chiavi, non tocca la geometria - portata fino in fondo anche
nell'esecuzione.

CHE COSA TIENE, AL POSTO DEL CONTENITORE

Quattro strati, e nessuno dei quattro e' l'unico:

  1. le guardie di `motore/guardie.py`, che gia' oggi rifiutano dentro
     valori() gli import, `open`, `exec`, `eval`, `compile`, `__import__`,
     il documento e la geometria. Girano prima, sull'albero sintattico;
  2. si compila SOLO la definizione di valori(), non il resto del file.
     Quello che il modello avesse scritto altrove non viene nemmeno letto;
  3. si esegue senza builtins, tranne una manciata di nomi innocui. Senza
     `__import__` e senza `open`, da dentro quella funzione non si arriva
     da nessuna parte;
  4. si controlla quello che torna: dev'essere un dizionario, le chiavi
     devono essere ancore che esistono davvero in questo modulo, e i valori
     devono essere testo, numeri o si'/no. Qualunque altra cosa si butta.

Il quarto e' quello che conta di piu', perche' non dipende dall'aver
previsto le mosse di qualcun altro: qualunque cosa succeda la' dentro, di
la' esce un dizionario di stringhe o non esce niente.

RESTA UN GRADINO PIU' BASSO DEL CONTENITORE, e va detto. Il contenitore
tiene anche contro quello che non abbiamo previsto; questo tiene contro
quello che abbiamo previsto. Per questo `esecuzione.py` resta la prima
scelta dove c'e': qui si arriva solo quando l'alternativa e' non compilare
i PDF affatto.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

from motore import guardie

# I nomi che restano raggiungibili dentro valori(). Sono quelli che servono
# a maneggiare dati - unire stringhe, contare, ordinare - e nessuno di loro
# apre file, importa o esegue testo.
BUILTINS_AMMESSI = {
    "True": True, "False": False, "None": None,
    "str": str, "int": int, "float": float, "bool": bool,
    "len": len, "dict": dict, "list": list, "tuple": tuple, "set": set,
    "sorted": sorted, "reversed": reversed, "enumerate": enumerate,
    "zip": zip, "range": range, "sum": sum, "min": min, "max": max,
    "abs": abs, "round": round, "any": any, "all": all,
    "isinstance": isinstance, "repr": repr, "format": format,
}

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

    modulo = ast.Module(body=[definizione], type_ignores=[])
    ast.fix_missing_locations(modulo)
    spazio = {"__builtins__": dict(BUILTINS_AMMESSI)}
    exec(compile(modulo, "<valori>", "exec"), spazio)       # noqa: S102

    try:
        scelte = spazio["valori"](fascicolo)
    except Exception as guaio:                              # noqa: BLE001
        raise ValoriInvalidi("valori() si e' fermata: %s" % guaio) from guaio
    if not isinstance(scelte, dict):
        raise ValoriInvalidi("valori() non ha restituito un dizionario")

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
