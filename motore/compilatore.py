# -*- coding: utf-8 -*-
"""Genera l'artefatto: il modulo tradotto in un programma, una volta sola.

Lo script non viene scritto liberamente dal modello. Nasce da **uno stampo
solo**, uguale per tutti i moduli, in cui si innestano due cose:

  ANCORE   i dati misurati dal classificatore, congelati in numeri letterali;
  valori() l'unica funzione che il modello scrive, e che tocca solo dati.

E' qui che 'niente toppe su misura' smette di essere una buona intenzione e
diventa una proprieta' della struttura: nello stampo non c'e' un posto dove
scrivere una correzione per un modulo, e dentro valori() la geometria non e'
raggiungibile. Se un campo viene male, o e' sbagliata la misura - e si corregge
il classificatore, per tutti - o e' sbagliato il valore - e si corregge il
fascicolo. Non esiste la terza strada.

L'artefatto porta l'impronta del PDF da cui e' nato: su un'altra edizione del
modulo si rifiuta di girare invece di scrivere su coordinate vecchie.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from string import Template

from motore import guardie

STAMPO = Template('''# -*- coding: utf-8 -*-
"""Compilatore di $nome.

Generato il $data dalla mappa misurata del modulo. Da qui in avanti questo
modulo si compila rieseguendo questo file: nessuna chiamata al modello, nessun
costo, stesso risultato. Se il fascicolo si arricchisce, si riesegue e basta.

    python programma.py [originale.pdf] [fascicolo.json] [cartella_uscita]
"""
import json
import sys
from pathlib import Path

import fitz
from strumenti_documento import (Ancora, PagineDiritte, firmato, impronta,
                                 scrivi)

IMPRONTA = "$impronta"

# Geometria misurata sul modulo, non stimata. Non si tocca a mano: si rigenera.
ANCORE = json.loads(r"""$ancore""")


$valori


# ---- da qui in giu' e' lo stampo, uguale per ogni modulo -------------------

def principale(argomenti):
    originale = Path(argomenti[0] if len(argomenti) > 0 else "/work/originale.pdf")
    percorso_fascicolo = Path(argomenti[1] if len(argomenti) > 1 else "/work/fascicolo.json")
    uscita = Path(argomenti[2] if len(argomenti) > 2 else "/work/uscita")
    uscita.mkdir(parents=True, exist_ok=True)

    if firmato(originale):
        print("Questo PDF ha gia' una firma digitale applicata.")
        print("Scriverci dentro la renderebbe non valida: si compila prima e si")
        print("firma dopo. Non scrivo niente.")
        return 4

    trovata = impronta(originale)
    if trovata != IMPRONTA:
        print("Questo compilatore e' stato misurato su un'altra edizione del modulo.")
        print("  attesa:  %s" % IMPRONTA)
        print("  trovata: %s" % trovata)
        print("Non scrivo niente: le coordinate non varrebbero piu'.")
        return 2

    fascicolo = json.loads(percorso_fascicolo.read_text(encoding="utf-8"))
    scelte = valori(fascicolo)
    ignote = [i for i in scelte if i not in ANCORE]
    if ignote:
        print("Valori su ancore inesistenti: %s" % ignote)
        return 3

    documento = fitz.open(originale)
    scritture = []
    with PagineDiritte(documento) as diritto:
        for identificativo, valore in scelte.items():
            if valore is None or valore is False or valore == "":
                continue
            ancora = Ancora.da_dict(ANCORE[identificativo])
            esito = scrivi(diritto[ancora.pagina], ancora, valore)
            scritture.append({"ancora": identificativo, "tipo": ancora.tipo,
                              "etichetta": ancora.etichetta,
                              "valore": valore if not isinstance(valore, bool) else bool(valore),
                              "scritto": bool(esito.ok), "motivo": esito.motivo})
    # Il contesto ripristina le rotazioni: salvare prima le perderebbe nel file.
    documento.save(uscita / "bozza.pdf")
    documento.close()

    (uscita / "scritture.json").write_text(
        json.dumps({"impronta": IMPRONTA, "scritture": scritture},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    riuscite = sum(1 for s in scritture if s["scritto"])
    print("scritture riuscite: %d su %d" % (riuscite, len(scritture)))
    for s in scritture:
        if not s["scritto"]:
            print("  non riuscita %s (%s): %s" % (s["ancora"], s["etichetta"], s["motivo"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(principale(sys.argv[1:]))
''')

VALORI_VUOTA = '''def valori(fascicolo):
    """Restituisce {ancora: valore}. E' l'unica parte scritta dal modello.

    Qui si maneggiano solo dati del fascicolo: la geometria e' gia' misurata e
    non e' raggiungibile. Un'ancora che non si sa compilare si lascia fuori, o
    si mette a None: restera' un punto aperto, che e' una risposta legittima.
    """
    return {}
'''


def cartella(radice: Path, mappa: dict) -> Path:
    """Un artefatto per edizione di modulo: l'impronta sta nel nome."""
    nome = Path(mappa["documento"]).stem
    return radice / "compilatori" / ("%s_%s" % (nome, mappa["impronta"][:8]))


SEGNAPOSTO = "# ---- da qui in giu'"

FILTRO = '''
# ---- tolto da chi compila -------------------------------------------------
# Un campo sbagliato su cinquanta faceva buttare tutta la bozza. Qui si toglie
# quello e basta: il programma e' lo stesso, la geometria e' la stessa, cambia
# solo che queste ancore non vengono scritte. Nessuna chiamata al modello.
_valori_prima_del_filtro = valori
_TOLTE = %s


def valori(fascicolo):
    scelte = _valori_prima_del_filtro(fascicolo)
    for _ancora in _TOLTE:
        scelte.pop(_ancora, None)
    return scelte


'''


def senza(codice: str, ancore) -> str:
    """Lo stesso programma, ma senza scrivere le ancore indicate.

    Si innesta subito prima dello stampo, cosi' funziona anche sugli artefatti
    gia' fatti: sono un centinaio e non vanno rigenerati per questo. Il filtro
    ridefinisce `valori` dopo l'originale, e Python risolve i nomi globali al
    momento della chiamata: quando il programma parte, trova questa.
    """
    ancore = [a for a in dict.fromkeys(ancore) if a]
    if not ancore:
        return codice
    if SEGNAPOSTO not in codice:
        raise ValueError("programma senza segnaposto: non so dove innestare il filtro")
    return codice.replace(SEGNAPOSTO, FILTRO % repr(ancore) + SEGNAPOSTO, 1)


def componi(mappa: dict, valori: str = VALORI_VUOTA) -> str:
    ancore = {a["id"]: a for a in mappa["ancore"]}
    return STAMPO.substitute(
        nome=mappa["documento"],
        data=date.today().isoformat(),
        impronta=mappa["impronta"],
        ancore=json.dumps(ancore, ensure_ascii=False, indent=1),
        valori=valori.strip("\n"))


def salva(radice: Path, mappa: dict, valori: str, note: dict = None,
          destinazione: Path = None) -> Path:
    """Scrive l'artefatto dopo le guardie. Se una guardia parla, non si salva.

    `destinazione` serve alle prove: gli artefatti in compilatori/ sono l'asset
    che si accumula, e una prova non ci scrive dentro.
    """
    codice = componi(mappa, valori)
    guardie.imponi(radice, codice)
    destinazione = Path(destinazione) if destinazione else cartella(radice, mappa)
    destinazione.mkdir(parents=True, exist_ok=True)
    (destinazione / "programma.py").write_text(codice, encoding="utf-8")
    (destinazione / "mappa.json").write_text(
        json.dumps(mappa, ensure_ascii=False, indent=1), encoding="utf-8")
    (destinazione / "note.json").write_text(
        json.dumps(note or {}, ensure_ascii=False, indent=1), encoding="utf-8")
    return destinazione
