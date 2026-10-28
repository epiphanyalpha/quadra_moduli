"""Identity and storage boundaries for documents and company profiles."""
import hashlib
import json
import uuid
from pathlib import Path


def impronta_dati(dati):
    return hashlib.sha256(json.dumps(dati, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def nuova_cartella(base):
    cartella = Path(base) / uuid.uuid4().hex
    cartella.mkdir(parents=True, exist_ok=False)
    return cartella


def azzera_revisione(stato, word=False):
    prefisso = 'w_togli_' if word else 'togli_'
    nomi = {'w_campo', 'w_dato'} if word else {'pdf_campo', 'pdf_dato'}
    for key in list(stato):
        if (str(key).startswith(prefisso) or key in nomi or
                not word and str(key).startswith('pdf_revisione_')):
            del stato[key]


def sincronizza_fascicolo(stato, percorso, dati):
    identita = (str(Path(percorso).resolve()), impronta_dati(dati))
    if stato.get('_fascicolo_attivo') == identita:
        return
    for key in list(stato):
        if str(key).startswith(('ana_', 'aperto_', 'togli_', 'w_togli_', 'pdf_revisione_', 'pdf_contesto_')):
            del stato[key]
    for key in ('verdetto', 'bozza', 'domanda', 'rifiuto', 'artefatto',
                'w_verdetto', 'w_bozza', 'w_domanda', 'w_rifiuto', 'w_modulo',
                '_lavoro_pdf', '_lavoro_word'):
        stato[key] = None
    stato['passi'], stato['avvisi'], stato['pdf_togli'] = [], [], []
    stato['_fascicolo_attivo'] = identita


def salva_json(percorso, dati):
    """Publish complete JSON in one replace; readers never see half a file."""
    percorso = Path(percorso)
    percorso.parent.mkdir(parents=True, exist_ok=True)
    tmp = percorso.with_name(percorso.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        tmp.write_text(json.dumps(dati, ensure_ascii=False, indent=1), encoding='utf-8')
        tmp.replace(percorso)
    finally:
        tmp.unlink(missing_ok=True)
