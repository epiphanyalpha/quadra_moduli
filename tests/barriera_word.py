"""Barriera offline del motore Word: nessuna chiamata AI, nessun dato nel repository.

Per ogni documento: lettura, testo che andrebbe all'AI, scrittura di prova su
TUTTI i campi scrivibili e su meta' di essi, verifica. Per i casi reali
(documento + decisioni salvate + fascicolo, in un JSON privato fuori da git)
rifa' la bozza con le decisioni vere, senza richiamare il modello.

    py -B tests/barriera_word.py fotografia <uscita> [--casi casi.json] <file o cartelle>...
    py -B tests/barriera_word.py confronta <fotografia_prima> <fotografia_dopo>

`fotografia` esce con codice 1 se anche un solo documento si rompe; `confronta`
elenca ogni differenza di testo per l'AI, di bozza o di esito.

Si lavora sempre nella stessa cartella temporanea, qualunque sia <uscita>: un
.doc con il campo "nome del file" nel pie' di pagina, convertito, riporta il
percorso, e due fotografie in cartelle diverse sembrerebbero diverse. Per
questo due fotografie vanno fatte una dopo l'altra, non insieme.
"""
import hashlib
import json
import random
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motore import word  # noqa: E402

ESTENSIONI = ('.doc', '.docx')


def _sha(dati):
    return hashlib.sha256(dati).hexdigest()


def _valore(ancora, date):
    if ancora['tipo'] == 'casella':
        return True
    return '02/01/2000' if ancora['id'] in date else 'Mario Rossi'


def _documenti(argomenti):
    for a in map(Path, argomenti):
        if a.is_dir():
            yield from sorted(p for p in a.iterdir() if p.suffix.lower() in ESTENSIONI)
        elif a.suffix.lower() in ESTENSIONI:
            yield a


def _scrivi(copia, mappa, valori, uscita):
    try:
        res = word.scrivi(copia, mappa, valori, uscita)
        ver = word.verifica(uscita, res)
        return dict(chieste=len(valori), scritte=len(res['scritture']),
                    verificate=len(ver['verificate']), non_trovate=len(ver['non_trovate']),
                    mancate=sorted(m['ancora'] for m in res['mancate']),
                    bozza=_sha(Path(uscita).read_bytes()))
    except Exception as e:  # noqa: BLE001 - e' esattamente quello che si misura
        return dict(chieste=len(valori), errore='%s: %s' % (type(e).__name__, str(e)[:200]))


LAVORO = Path(tempfile.gettempdir()) / 'barriera_word_lavoro'


def _uno(sorgente, uscita, reale=None):
    lavoro = LAVORO / uscita.name
    shutil.rmtree(lavoro, ignore_errors=True)
    lavoro.mkdir(parents=True, exist_ok=True)
    try:
        return _prova(sorgente, lavoro, reale)
    finally:
        uscita.mkdir(parents=True, exist_ok=True)
        for f in ('testo_ai.txt', 'tutte.docx', 'meta.docx', 'reale.docx'):
            if (lavoro / f).exists():
                shutil.copy2(lavoro / f, uscita / f)


def _prova(sorgente, lavoro, reale=None):
    copia = lavoro / sorgente.name
    shutil.copy2(sorgente, copia)
    r = dict(documento=sorgente.name)
    try:
        mappa = word.leggi(copia, lavoro / 'conv')
        testo, indirizzi = word.rendi(mappa)
    except Exception as e:  # noqa: BLE001
        r['errore_lettura'] = '%s: %s' % (type(e).__name__, str(e)[:200])
        r['traccia'] = traceback.format_exc().splitlines()[-3:]
        return r
    (lavoro / 'testo_ai.txt').write_text(testo, encoding='utf-8')
    anc = mappa['ancore']
    date = {p['riferimento'] for p in mappa['inventario']['punti'] if p.get('sottotipo_sdt') == 'date'}
    scrivibili = [a['id'] for a in anc if a.get('scrivibile', True)]
    by = {a['id']: a for a in anc}
    r.update(ancore=len(anc), scrivibili=len(scrivibili), testo_ai=_sha(testo.encode('utf-8')),
             indirizzi=len(indirizzi))
    r['tutte'] = _scrivi(copia, mappa, {i: _valore(by[i], date) for i in scrivibili}, lavoro / 'tutte.docx')
    meta = random.Random(7).sample(scrivibili, len(scrivibili) // 2)
    r['meta'] = _scrivi(copia, mappa, {i: _valore(by[i], date) for i in meta}, lavoro / 'meta.docx')
    if reale:
        decisioni = json.loads(Path(reale['decisioni']).read_text(encoding='utf-8'))
        profilo = json.loads(Path(reale['fascicolo']).read_text(encoding='utf-8'))['profilo']
        valori = {a: profilo[d['finale']] for a, d in decisioni.items()
                  if d.get('finale') and profilo.get(d['finale']) and a in by}
        r['reale'] = _scrivi(copia, mappa, valori, lavoro / 'reale.docx')
    return r


def fotografia(uscita, argomenti, casi=None):
    uscita = Path(uscita)
    reali = {}
    if casi:
        for c in json.loads(Path(casi).read_text(encoding='utf-8')):
            reali[Path(c['documento']).resolve()] = c
    documenti = list(dict.fromkeys(list(_documenti(argomenti)) + list(reali)))
    righe, rotti = [], 0
    for i, doc in enumerate(documenti):
        r = _uno(doc, uscita / ('%03d' % i), reali.get(doc.resolve()))
        guasto = r.get('errore_lettura') or any('errore' in r.get(k, {}) for k in ('tutte', 'meta', 'reale'))
        rotti += bool(guasto)
        righe.append(r)
        print('%-4s %s' % ('ROTTO' if guasto else 'ok', doc.name), flush=True)
    (uscita / 'fotografia.json').write_text(json.dumps(righe, ensure_ascii=False, indent=1), encoding='utf-8')
    print('%d documenti, %d rotti' % (len(righe), rotti))
    return 1 if rotti else 0


def confronta(prima, dopo):
    a = {r['documento']: r for r in json.loads((Path(prima) / 'fotografia.json').read_text(encoding='utf-8'))}
    b = {r['documento']: r for r in json.loads((Path(dopo) / 'fotografia.json').read_text(encoding='utf-8'))}
    diversi = 0
    for nome in sorted(set(a) | set(b)):
        x, y = a.get(nome), b.get(nome)
        if x != y:
            diversi += 1
            print('DIVERSO', nome)
            for k in sorted(set(x or {}) | set(y or {})):
                if (x or {}).get(k) != (y or {}).get(k):
                    print('   %s: %s  ->  %s' % (k, (x or {}).get(k), (y or {}).get(k)))
    print('%d documenti confrontati, %d diversi' % (len(set(a) | set(b)), diversi))
    return 1 if diversi else 0


if __name__ == '__main__':
    comando, resto = sys.argv[1], sys.argv[2:]
    if comando == 'fotografia':
        casi = None
        if '--casi' in resto:
            i = resto.index('--casi'); casi = resto[i + 1]; del resto[i:i + 2]
        sys.exit(fotografia(resto[0], resto[1:], casi))
    sys.exit(confronta(*resto))
