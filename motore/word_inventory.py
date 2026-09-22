"""Punti scrivibili OOXML, senza interpretazione delle etichette.

Gli indirizzi sono validi solo per l'impronta dell'originale. Un candidato
fisico non è necessariamente un campo: è l'inventario AI a distinguerli.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import io
import re
import zipfile

from lxml import etree as ET

VERSIONE = 1
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
W14 = 'http://schemas.microsoft.com/office/word/2010/wordml'
NS = {'w': W, 'w14': W14}
VUOTO = re.compile(r'[_.…·]{2,}|[-–—]{3,}|[\u2002\u2003]{3,}|\(\s*\)')
CASELLA = re.compile(r'[□☐❑☒☑\uf06f\uf0a8\uf071\uf0fe\uf0fc]|\[ *\]')
SPUNTATI = set('☒☑\uf0fe\uf0fc')


def q(nome):
    return '{' + W + '}' + nome


def apri(dati):
    with zipfile.ZipFile(io.BytesIO(dati)) as z:
        contenuti = {i.filename: z.read(i) for i in z.infolist()}
    if 'word/document.xml' not in contenuti:
        raise ValueError('Serve un DOCX; convertire separatamente gli originali DOC')
    parser = ET.XMLParser(resolve_entities=False, no_network=True)
    parti = {n: ET.fromstring(b, parser) for n, b in contenuti.items()
             if re.fullmatch(r'word/(document|header\d+|footer\d+|footnotes|endnotes)\.xml', n)}
    return contenuti, parti


def salva(dati, parti):
    """Conserva byte e metadati ZIP delle parti non modificate."""
    memoria = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(dati)) as z, zipfile.ZipFile(memoria, 'w') as out:
        out.comment = z.comment
        for info in z.infolist():
            contenuto = parti.get(info.filename, z.read(info))
            out.writestr(info, contenuto)
    return memoria.getvalue()


def serializza(root):
    return ET.tostring(root, encoding='UTF-8', xml_declaration=True, standalone=True)


def antenato(el, tag):
    return next((a for a in el.iterancestors() if a.tag == q(tag)), None)


def testo_ancore(p):
    """Non conta due volte il testo nelle caselle di testo annidate."""
    testo, ancore = [], []
    for el in p.iter():
        if antenato(el, 'p') is not p or antenato(el, 'r') is None:
            continue
        valore = ''
        if el.tag == q('t'):
            valore = el.text or ''
        elif el.tag == q('sym'):
            try:
                valore = chr(int(el.get(q('char'), ''), 16))
            except (ValueError, OverflowError):
                valore = '\ufffd'
        elif el.tag in {q('tab'), q('br'), q('cr')}:
            valore = '\t' if el.tag == q('tab') else '\n'
        testo.append(valore)
        ancore.extend((el, i) for i in range(len(valore)))
    return ''.join(testo), ancore


def numerazioni(contenuti):
    if 'word/numbering.xml' not in contenuti:
        return {}, {}
    root = ET.fromstring(contenuti['word/numbering.xml'])
    astratti = {a.get(q('abstractNumId')): a for a in root.findall('w:abstractNum', NS)}
    numeri = {}
    for n in root.findall('w:num', NS):
        a = n.find('w:abstractNumId', NS)
        if a is None:
            continue
        livelli = {}
        astratto = astratti.get(a.get(q('val')))
        if astratto is not None:
            livelli.update({l.get(q('ilvl')): l for l in astratto.findall('w:lvl', NS)})
        for o in n.findall('w:lvlOverride', NS):
            l = o.find('w:lvl', NS)
            if l is not None:
                livelli[o.get(q('ilvl'))] = l
        numeri[n.get(q('numId'))] = livelli
    return numeri, astratti


def estrai(dati):
    contenuti, parti = apri(dati)
    numeri, _ = numerazioni(contenuti)
    stili = {}
    if 'word/styles.xml' in contenuti:
        stili = {s.get(q('styleId')): s for s in ET.fromstring(contenuti['word/styles.xml']).findall('w:style', NS)}
    risultato = dict(versione=VERSIONE, docx_sha256=hashlib.sha256(dati).hexdigest(),
                     punti=[], blocchi=[], avvisi=[])
    for parte, root in sorted(parti.items(), key=lambda x: (x[0] != 'word/document.xml', x[0])):
        albero = root.getroottree()
        percorso = albero.getelementpath
        paragrafi = list(root.iter(q('p')))
        indici = {p: i for i, p in enumerate(paragrafi)}
        prefisso = '' if parte == 'word/document.xml' else parte[5:-4] + '_'
        contatori = Counter()
        occupati = set()

        def aggiungi(tipo, el, p, **extra):
            base = prefisso + f'p{indici[p]:04d}' if p is not None else prefisso + 'struttura'
            contatori[base, tipo] += 1
            ref = f'{base}_{tipo}{contatori[base, tipo]:02d}'
            testo = testo_ancore(p)[0] if p is not None else ''
            tc = el if el.tag == q('tc') else antenato(el, 'tc')
            posizione = None
            if tc is not None:
                tr = tc.getparent(); tb = antenato(tc, 'tbl')
                celle = list(tr.findall('w:tc', NS))
                def ampiezza(c):
                    span = c.find('w:tcPr/w:gridSpan', NS)
                    return int(span.get(q('val'), '1')) if span is not None else 1
                prima = tr.find('w:trPr/w:gridBefore', NS)
                colonna = int(prima.get(q('val'), '0')) if prima is not None else 0
                colonna += sum(ampiezza(c) for c in celle[:celle.index(tc)])
                posizione = {'tabella': percorso(tb), 'riga': list(tb.findall('w:tr', NS)).index(tr)
                             if tr in tb.findall('w:tr', NS) else None,
                             'colonna_xml': celle.index(tc), 'colonna_griglia': colonna,
                             'ampiezza_griglia': ampiezza(tc)}
            voce = dict(riferimento=ref, tipo=tipo, parte=parte, percorso=percorso(el),
                        paragrafo=base, percorso_paragrafo=percorso(p) if p is not None else None,
                        testo_originale=testo, posizione_cella=posizione,
                        scrivibile=True, motivo_tecnico='', **extra)
            if any(a.tag in {q('del'), q('ins'), q('moveFrom'), q('moveTo')} for a in el.iterancestors()):
                voce.update(scrivibile=False, motivo_tecnico='Revisioni Word da risolvere')
            if any(ET.QName(a).localname in {'AlternateContent', 'Fallback', 'Choice'} for a in el.iterancestors()):
                voce.update(scrivibile=False, motivo_tecnico='Rappresentazioni Word alternative da verificare')
            risultato['punti'].append(voce)
            return voce

        # I controlli possiedono il loro risultato: il glifo/placeholder interno
        # non diventa un secondo campo indipendente.
        for sdt in root.iter(q('sdt')):
            pr = sdt.find('w:sdtPr', NS); corpo = sdt.find('w:sdtContent', NS)
            if pr is None or corpo is None:
                continue
            cb = pr.find('w14:checkbox', NS)
            testuale = any(pr.find('w:' + nome, NS) is not None for nome in ('text', 'date', 'dropDownList', 'comboBox'))
            p = antenato(sdt, 'p')
            if p is None:
                p = next(corpo.iter(q('p')), None)
            tipo_sdt = 'sdt_casella' if cb is not None else 'sdt_testo' if testuale else 'sdt_rich_text'
            v = aggiungi(tipo_sdt, sdt, p)
            if (list(corpo.iter(q('sdt'))) or any(corpo.find('.//' + q(tag)) is not None
                                                for tag in ('tbl', 'drawing', 'pict', 'object', 'fldChar', 'fldSimple'))):
                v.update(scrivibile=False, motivo_tecnico='Controllo Word strutturato: scrittura da verificare')
            v['testo_controllo'] = ''.join(corpo.itertext())
            strutturati = [nome for nome in ('date', 'dropDownList', 'comboBox') if pr.find('w:' + nome, NS) is not None]
            if strutturati:
                v['sottotipo_sdt'] = strutturati[0]
                v['opzioni_sdt'] = [e.get(q('displayText'), e.get(q('value'), ''))
                                    for e in pr.iter(q('listItem'))]
                v.update(scrivibile=False, motivo_tecnico='Controllo data/elenco: stato Word da aggiornare manualmente')
            if cb is not None:
                checked = cb.find('w14:checked', NS)
                v['spuntata'] = checked is not None and checked.get('{' + W14 + '}val', '0') not in {'0', 'false', 'off'}
            if pr.find('w:dataBinding', NS) is not None or pr.find('w:lock', NS) is not None or len(list(corpo.iter(q('p')))) > 1:
                v.update(scrivibile=False, motivo_tecnico='Controllo collegato, protetto o su più paragrafi')
            for outer in sdt.iterancestors(q('sdt')):
                outer_pr = outer.find('w:sdtPr', NS)
                if outer_pr is not None and any(outer_pr.find('w:' + tag, NS) is not None for tag in ('lock', 'dataBinding')):
                    v.update(scrivibile=False, motivo_tecnico='Controllo dentro un contenitore protetto o collegato')
            if not list(corpo.iter(q('sdt'))):
                occupati.update(corpo.iter())

        for campo in root.iter(q('fldSimple')):
            istruzione = campo.get(q('instr'), '').strip().upper()
            if istruzione.startswith('FORMTEXT'):
                v = aggiungi('form_semplice_testo', campo, antenato(campo, 'p'))
                occupati.update(campo.iter())
                v.update(scrivibile=False, motivo_tecnico='Campo semplice inventariato; scrittura da implementare')

        for p in paragrafi:
            testo, ancore = testo_ancore(p)
            base = prefisso + f'p{indici[p]:04d}'
            risultato['blocchi'].append(dict(id=base, parte=parte, percorso=percorso(p), testo=testo))
            # Campi Word complessi, con delimitatori effettivamente abbinati.
            pila = []
            for el in p.iter():
                if antenato(el, 'p') is not p:
                    continue
                if el.tag == q('fldChar'):
                    tipo = el.get(q('fldCharType'))
                    if tipo == 'begin':
                        pila.append(dict(inizio=el, istruzione='', separatore=None, nodi=[]))
                    elif tipo == 'separate' and pila:
                        pila[-1]['separatore'] = el
                    elif tipo == 'end' and pila:
                        campo = pila.pop(); ff = campo['inizio'].find('w:ffData', NS)
                        cb = ff.find('w:checkBox', NS) if ff is not None else None
                        tx = ff.find('w:textInput', NS) if ff is not None else None
                        if cb is not None or tx is not None or 'FORMTEXT' in campo['istruzione']:
                            v = aggiungi('form_casella' if cb is not None else 'form_testo', campo['inizio'], p,
                                         fine_campo=percorso(el), separatore=percorso(campo['separatore']) if campo['separatore'] is not None else None)
                            if cb is not None:
                                chk = cb.find('w:checked', NS)
                                if chk is None:
                                    chk = cb.find('w:default', NS)
                                v['spuntata'] = chk is not None and chk.get(q('val'), '1') not in {'0', 'false', 'off'}
                            if campo['separatore'] is None or pila:
                                v.update(scrivibile=False, motivo_tecnico='Campo Word senza risultato semplice')
                            occupati.update(campo['nodi'])
                        elif campo['istruzione'].strip():
                            risultato['avvisi'].append(dict(paragrafo=base, motivo='Campo Word calcolato conservato', tipo='campo_calcolato'))
                if pila:
                    pila[-1]['nodi'].append(el)
                    if el.tag == q('instrText'):
                        pila[-1]['istruzione'] += el.text or ''
            if pila:
                risultato['avvisi'].append(dict(paragrafo=base, motivo='Campo Word non chiuso nel paragrafo', tipo='campo_incompleto'))
                for campo in pila:
                    occupati.update(campo['nodi'])

            # Ereditarietà degli stili e override del livello, senza cambiare i rientri.
            num = p.find('w:pPr/w:numPr', NS)
            if num is None:
                stile = p.find('w:pPr/w:pStyle', NS); visitati = set()
                sid = stile.get(q('val')) if stile is not None else None
                while sid in stili and sid not in visitati:
                    visitati.add(sid); st = stili[sid]; num = st.find('w:pPr/w:numPr', NS)
                    if num is not None:
                        break
                    padre = st.find('w:basedOn', NS); sid = padre.get(q('val')) if padre is not None else None
            if num is not None and p not in occupati:
                nid = num.find('w:numId', NS); il = num.find('w:ilvl', NS)
                livello = il.get(q('val')) if il is not None else '0'
                n = nid.get(q('val')) if nid is not None else None
                lvl = numeri.get(n, {}).get(livello)
                glifo = lvl.find('w:lvlText', NS) if lvl is not None else None
                if glifo is not None and CASELLA.fullmatch(glifo.get(q('val'), '')):
                    aggiungi('elenco_casella', p, p, num_id=n, livello=livello,
                             spuntata=glifo.get(q('val')) in SPUNTATI)
            coperti = set()
            for numero, m in enumerate(VUOTO.finditer(testo), 1):
                # Keep ordinary ellipsis in prose out; mixed fillers remain one slot.
                segni = m.group()
                if set(segni) <= set('_.…·') and sum({'_': 2, '…': 3}.get(c, 1) for c in segni) < 5:
                    continue
                if any(e in occupati for e, _ in ancore[m.start():m.end()]):
                    continue
                v = aggiungi('testo', p, p, inizio=m.start(), fine=m.end(), originale=m.group())
                v['riferimento'] = f'{base}_v{numero:02d}'
                coperti.update(range(m.start(), m.end()))
            for m in CASELLA.finditer(testo):
                if any(e in occupati for e, _ in ancore[m.start():m.end()]):
                    continue
                aggiungi('glifo_casella', p, p, inizio=m.start(), fine=m.end(), originale=m.group(), spuntata=m.group() in SPUNTATI)
                coperti.update(range(m.start(), m.end()))
            for m in re.finditer(r'\[[^\[\]\r\n]+\]', testo):
                if any(i in coperti for i in range(m.start(), m.end())) or any(e in occupati for e, _ in ancore[m.start():m.end()]):
                    continue
                aggiungi('segnaposto_testuale', p, p, inizio=m.start(), fine=m.end(), originale=m.group(), candidato=True)
                coperti.update(range(m.start(), m.end()))
            # Evidenza fisica soltanto: spazi ripetuti, tab e spazio finale
            # preservato. Il modello può classificarli come non_campo.
            ordine_xml = {el: i for i, el in enumerate(p.iter())}
            delimitatori = [ordine_xml[el] for el in p.iter(q('fldChar'))]
            for m in re.finditer(r'[ \t]{2,}|\t', testo):
                if not testo.strip() or any(i in coperti for i in range(m.start(), m.end())):
                    continue
                # Whitespace touching an explicit placeholder is padding, not
                # another question. Preserve it in the document, not the map.
                if m.start()-1 in coperti or m.end() in coperti:
                    continue
                # Leading indentation has no label and is not an input field.
                if not testo[:m.start()].strip():
                    continue
                if any(e in occupati for e, _ in ancore[m.start():m.end()]):
                    continue
                # Due spazi ai lati di un campo vuoto non sono un terzo campo.
                primo = ordine_xml[ancore[m.start()][0]]
                ultimo = ordine_xml[ancore[m.end() - 1][0]]
                if any(primo <= i <= ultimo for i in delimitatori):
                    continue
                start = m.start()
                # Keep label spacing in its own run: do not inherit the label font
                # when the blank is a separately underlined/formatted run.
                first_node = ancore[start][0]
                if testo[:start].strip() and first_node.tag == q('t'):
                    prefix = (first_node.text or '')[:ancore[start][1]]
                    if prefix.strip():
                        while start < m.end() and ancore[start][0] is first_node:
                            start += 1
                        if start == m.end():
                            start = m.start()
                aggiungi('spazio_implicito', p, p, inizio=start, fine=m.end(), originale=testo[start:m.end()], candidato=True)

            # A full-width table cell may consist solely of a printed label,
            # without punctuation or any explicit blank. Expose an OPTIONAL
            # insertion point, never assume that a title/declaration is a field.
            # Paired label/value cells keep their existing blank-cell target.
            tc = antenato(p, 'tc')
            plain_cell = (tc is not None
                          and len(tc.getparent().findall('w:tc', NS)) == 1
                          and len(list(tc.iter(q('p')))) == 1
                          and re.fullmatch(r'[^:\n\t]{2,100}', testo.strip())
                          and not any(tc.find('.//' + q(t)) is not None for t in
                                      ('tbl', 'drawing', 'pict', 'object', 'fldChar', 'fldSimple', 'sdt'))
                          and not any(tc.find('w:tcPr/w:' + t, NS) is not None
                                      for t in ('vMerge', 'hMerge')))
            # A labelled line/cell can ask for a value without a drawn placeholder.
            if ((re.fullmatch(r'[^:\n]{2,100}:\s*', testo) or plain_cell)
                    and not any(v['paragrafo'] == base for v in risultato['punti'])
                    and not any(e in occupati for e in p.iter())):
                aggiungi('inserimento_testo', p, p, inizio=len(testo), fine=len(testo),
                         originale='', candidato=True, etichetta_implicita=bool(plain_cell))

        for tc in root.iter(q('tc')):
            if any(e in occupati for e in tc.iter()):
                continue
            ps = [p for p in tc.iter(q('p')) if antenato(p, 'tc') is tc]
            if not ps or any(testo_ancore(p)[0].strip() for p in ps):
                continue
            if any(tc.find('.//' + q(t)) is not None for t in ('tbl', 'drawing', 'pict', 'object', 'fldChar', 'sym')):
                continue
            v = aggiungi('cella_vuota', tc, ps[0], candidato=True)
            for direzione in ('vMerge', 'hMerge'):
                merge = tc.find('w:tcPr/w:' + direzione, NS)
                if merge is not None and merge.get(q('val')) != 'restart':
                    v.update(scrivibile=False, motivo_tecnico='Continuazione di cella unita')
        for p in paragrafi:
            if p in occupati or antenato(p, 'tc') is not None or testo_ancore(p)[0].strip():
                continue
            if any(p.find('.//' + q(t)) is not None for t in ('drawing', 'pict', 'object', 'fldChar', 'fldSimple', 'sdt', 'sectPr')):
                continue
            aggiungi('paragrafo_vuoto', p, p, candidato=True)
        for tag in ('altChunk', 'object', 'drawing', 'pict', 'fldSimple'):
            for el in root.iter(q(tag)):
                risultato['avvisi'].append(dict(parte=parte, percorso=percorso(el), tipo=tag,
                                                motivo='Oggetto da verificare; il testo accessibile è inventariato separatamente'))
    risultato['conteggi'] = dict(Counter(p['tipo'] for p in risultato['punti']))
    risultato['copertura_completa_certificata'] = False
    return risultato
