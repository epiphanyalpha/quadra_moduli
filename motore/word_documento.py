"""Adapter between the app's Word contract and addressed OOXML operations.

Candidate whitespace is presented as such, never classified by label dictionaries.
The source and expected paragraph text are checked independently after writing.
"""
import hashlib
import re
from collections import defaultdict
from pathlib import Path

from . import word_inventory as inventory, word_patch as patch


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _table_context(point, roots):
    pos = point.get('posizione_cella')
    if not pos:
        return '', False
    root = roots[point['parte']]
    cell = inventory.antenato(patch.nodo(root, point['percorso_paragrafo']), 'tc')
    row = cell.getparent()
    cells = list(row.findall('w:tc', inventory.NS))
    column = cells.index(cell)
    text = lambda c: ' '.join(inventory.testo_ancore(p)[0].strip()
                             for p in c.iter(inventory.q('p'))
                             if inventory.antenato(p, 'tc') is c).strip()
    left = text(cells[column - 1]) if column else ''
    table = inventory.antenato(cell, 'tbl')
    rows = table.findall('w:tr', inventory.NS)
    headers = rows[0].findall('w:tc', inventory.NS)
    # Grid coordinates, rather than XML indices, preserve context across merged cells.
    header = ''
    grid = 0
    for h in headers:
        span = h.find('w:tcPr/w:gridSpan', inventory.NS)
        width = int(span.get(inventory.q('val'), '1')) if span is not None else 1
        if grid <= pos['colonna_griglia'] < grid + width:
            header = text(h)
        grid += width
    empty_rows = sum(not any(text(c) for c in r.findall('w:tc', inventory.NS)) for r in rows[1:])
    listing = len(headers) > 1 and all(text(c) for c in headers) and empty_rows >= 2 and row is not rows[0]
    return left or (header if row is not rows[0] else ''), listing


def leggi(percorso, cartella_lavoro=None):
    from .word import converti
    source = Path(percorso).resolve()
    usable = converti(source, cartella_lavoro or source.parent / 'convertiti').resolve()
    data = usable.read_bytes()
    physical = inventory.estrai(data)
    _, roots = inventory.apri(data)
    # Plain empty body paragraphs are usually layout. Label-only paragraphs are explicit candidates.
    physical['punti'] = [p for p in physical['punti'] if p['tipo'] != 'paragrafo_vuoto']
    probes = {p['riferimento']: True if p['tipo'].endswith('casella') else
              '2000-01-02' if p.get('sottotipo_sdt') == 'date' else 'VALORE'
              for p in physical['punti'] if p['scrivibile']}
    _, _, ops, rejected = patch.prepara_operazioni(data, physical, probes)
    positions = {o['punto']['riferimento']: (o['inizio'], o['fine']) for o in ops}
    failures = {r['riferimento']: r['motivo'] for r in rejected}
    # Full dry run, audit included, BEFORE asking the model: a point that would
    # fail the audit is manual from the start instead of failing the document
    # after the model has been paid. When everything passes nothing changes.
    _, _, dry_run_failures = patch.scrivi_con_ripiego(
        data, physical, {r: v for r, v in probes.items() if r not in failures})
    failures.update(dry_run_failures)
    blocks = physical['blocchi']
    block_index = {b['id']: i for i, b in enumerate(blocks)}
    anchors = []
    for point in physical['punti']:
        ref = point['riferimento']
        if ref in failures:
            point.update(scrivibile=False, motivo_tecnico=failures[ref])
        start, end = positions.get(ref, (point.get('inizio', 0), point.get('fine', 0)))
        kind = ('casella' if point['tipo'].endswith('casella') else
                'cella' if point['tipo'] == 'cella_vuota' else
                'modulo' if point['tipo'].startswith(('sdt_', 'form_')) else 'riempimento')
        context, listing = _table_context(point, roots)
        pos = point.get('posizione_cella') or {}
        anchors.append(dict(id=ref, tipo=kind, paragrafo=block_index.get(point['paragrafo']),
                            inizio=start, fine=end, capienza=max(end-start, 1) if kind == 'riempimento' else 60,
                            etichetta='', etichette_sdt=point.get('etichette_sdt', {}),
                            tabella=pos.get('tabella'), riga=pos.get('riga'),
                            colonna=pos.get('colonna_griglia'), elenco=listing,
                            contesto_cella=context, parte=point['parte'],
                            scrivibile=point['scrivibile'], motivo=point['motivo_tecnico'],
                            candidato=point.get('candidato', False), tipo_word=point['tipo'],
                            etichetta_implicita=point.get('etichetta_implicita', False)))
    anchors.sort(key=lambda a: (a['paragrafo'] if a['paragrafo'] is not None else -1, a['inizio']))
    by_block = defaultdict(list)
    for a in anchors:
        by_block[a['paragrafo']].append(a)
    for index, group in by_block.items():
        if index is None:
            continue
        text = blocks[index]['testo']; previous = 0
        for a in group:
            label = text[previous:a['inizio']]
            a['etichetta'] = re.sub(r'\s+', ' ', label).strip(' :.-–')[-100:] or a['contesto_cella']
            labels = a.get('etichette_sdt', {})
            a['etichetta'] = labels.get('alias') or labels.get('tag') or a['etichetta']
            previous = max(previous, a['fine'])
    return dict(documento=source.name, formato='word', convertito_da=None if usable == source else source.name,
                ancore=anchors, righe=[(i,b['testo']) for i,b in enumerate(blocks)],
                inventario=physical, originale_docx=str(usable), sorgente_sha256=_sha(source.read_bytes()),
                avvisi_tecnici=physical['avvisi'], copertura_completa_certificata=False)


def rendi(mappa):
    groups = defaultdict(list)
    for a in mappa['ancore']:
        if a.get('scrivibile', True):
            groups[a['paragrafo']].append(a)
    addresses = {}; lines = []; previous_part = None
    blocks = mappa['inventario']['blocchi']
    for index, text in mappa['righe']:
        part = blocks[index]['parte']
        if part != previous_part:
            lines.append('[Parte Word: %s]' % part)
            previous_part = part
        pieces = []; last = 0
        for a in sorted(groups[index], key=lambda x:x['inizio']):
            number = str(len(addresses)+1); addresses[number] = a['id']
            if a['tabella'] is not None and not pieces:
                pieces.append('[Tabella %s; riga %s; colonna %s] ' %
                              (a['tabella'], a['riga'], a['colonna']))
            pieces.append(text[last:a['inizio']])
            if a['contesto_cella']:
                pieces.append('[Etichetta cella: %s] ' % a['contesto_cella'])
            if a.get('etichette_sdt'):
                labels = ' / '.join(dict.fromkeys(v for v in a['etichette_sdt'].values() if v))
                pieces.append('[Etichetta controllo Word: %s] ' % labels)
            # No PDF-style capacity: the Word text flows and placeholder length is not a limit.
            pieces.append('«%s:%s»' % (number, 'casella' if a['tipo']=='casella' else 'testo'))
            if a.get('elenco'):
                pieces.append(' (riga di un elenco di altri soggetti)')
            if a['candidato']:
                pieces.append(' (inserimento facoltativo dopo etichetta: compilare solo se la cella chiede un dato; titoli, testo gia compilato e dichiarazioni non sono campi)'
                              if a.get('etichetta_implicita') else
                              ' (spazio candidato: verificare che chieda un dato)')
            last = a['fine']
        pieces.append(text[last:])
        rendered = re.sub(r'\s+', ' ', ''.join(pieces)).strip()
        if rendered:
            lines.append(rendered)
    return '\n'.join(lines), addresses


def scrivi(percorso, mappa, valori, uscita):
    from .word import _senza_ripetizione
    source = Path(percorso)
    if _sha(source.read_bytes()) != mappa['sorgente_sha256']:
        raise ValueError('Il documento originale e\' cambiato: rileggere il modulo.')
    data = Path(mappa['originale_docx']).read_bytes()
    by_id = {a['id']:a for a in mappa['ancore']}
    chosen = {}; original_values = {}
    for ref,value in valori.items():
        if ref not in by_id:
            raise ValueError('Valore su un campo che non esiste: %s' % ref)
        if value is None or value is False or not str(value).strip():
            continue
        a = by_id[ref]
        original_values[ref] = str(value).strip()
        # Only a complete, explicit printed street prefix may stand for that prefix of the value.
        chosen[ref] = (True if a['tipo']=='casella' else
                       _senza_ripetizione(a['etichetta'], str(value).strip())
                       if a['tipo']=='riempimento' and not a['contesto_cella'] else str(value).strip())
    # A write that fails the audit is dropped and reported, not fatal to the draft.
    output, audit, dropped = patch.scrivi_con_ripiego(data, mappa['inventario'], chosen)
    target = Path(uscita); target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(output)
    writes = []
    for change in audit['modifiche']:
        ref=change['riferimento']; a=by_id[ref]
        writes.append(dict(ancora=ref,tipo=a['tipo'],etichetta=a['etichetta'],
                           valore=change['valore_scritto'].strip(), valore_origine=original_values[ref],
                           paragrafo=a['paragrafo'],tabella=a['tabella'],
                           riga=a['riga'],colonna=a['colonna'],parte=change['parte'],
                           percorso_paragrafo=change['percorso_paragrafo']))
    missed=[dict(ancora=r['riferimento'],valore=original_values.get(r['riferimento'],''),motivo=r['motivo'])
            for r in audit['residui']]
    missed += [dict(ancora=ref, valore=original_values.get(ref, ''), motivo=reason)
               for ref, reason in dropped.items()]
    return dict(bozza=str(target),scritture=writes,mancate=missed,
                originale_docx=mappa['originale_docx'],originale_sha256=_sha(data),piano_audit=audit['piano_audit'])


def verifica(uscita, resoconto):
    from .word import _intorno
    original=Path(resoconto['originale_docx']).read_bytes()
    if _sha(original) != resoconto['originale_sha256']:
        raise ValueError('Originale modificato dopo la scrittura: verifica impossibile.')
    data=Path(uscita).read_bytes()
    check=patch.verifica_collocazione(original,data,resoconto['piano_audit'])
    _,roots=inventory.apri(data)
    verified=[]; missing=[]
    for write in resoconto['scritture']:
        if not check['ok']:
            missing.append(dict(write,motivo='; '.join(check['errori'][:3])))
            continue
        paragraph=patch.nodo(roots[write['parte']],write['percorso_paragrafo'])
        text=inventory.testo_ancore(paragraph)[0]
        verified.append(dict(write,riga=_intorno(text,write['valore'])))
    return dict(verificate=verified,non_trovate=missing,mancate=resoconto.get('mancate',[]),
                verifica_strutturale=check['ok'],verifica_visiva='NON_ESEGUITA')
