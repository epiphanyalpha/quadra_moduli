"""Scrittura OOXML indirizzata e audit della collocazione sull'originale.

Non interpreta etichette. Conservare struttura e stile non dimostra la fedeltà
visiva: il riflusso dei valori lunghi va verificato separatamente in Word/PDF.
"""
from collections import defaultdict
from copy import deepcopy
import hashlib
import re

from lxml import etree as ET

from .word_inventory import (W14, NS, q, apri, salva, serializza,
                                testo_ancore, numerazioni, antenato)


def nodo(root, percorso):
    trovato = root.find(percorso)
    if trovato is None:
        raise ValueError('Posizione Word non univoca')
    return trovato


def _testo(el, valore):
    el.text = valore
    el.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')


def _run(p, valore, modello_run=None):
    r = ET.Element(q('r'))
    modello = modello_run.find('w:rPr', NS) if modello_run is not None else p.find('w:r/w:rPr', NS)
    if modello is not None:
        r.append(deepcopy(modello))
    _testo(ET.SubElement(r, q('t')), valore)
    return r


def _font_simbolo(run, nome):
    pr = run.find('w:rPr', NS)
    if pr is None: pr = ET.Element(q('rPr')); run.insert(0, pr)
    font = pr.find('w:rFonts', NS)
    if font is None: font = ET.Element(q('rFonts')); pr.insert(0, font)
    for k in ('asciiTheme', 'hAnsiTheme', 'eastAsiaTheme', 'cstheme'):
        font.attrib.pop(q(k), None)
    for k in ('ascii', 'hAnsi', 'eastAsia', 'cs'): font.set(q(k), nome)


def _intervallo(p, inizio, fine, valore):
    _, ancore = testo_ancore(p)
    porzione = ancore[inizio:fine]
    if not porzione:
        raise ValueError('Intervallo Word vuoto')
    if any(el.tag not in {q('t'), q('tab'), q('sym')} for el, _ in porzione):
        raise ValueError('Intervallo con interruzioni Word')
    primo, offset = porzione[0]; ultimo, ultimo_offset = porzione[-1]
    if primo.tag == q('sym') and primo is ultimo:
        if valore not in {'☒', '☐', '\uf0fe', '\uf06f'}:
            raise ValueError('Il simbolo Word richiede una casella')
        primo.set(q('font'), 'Wingdings'); primo.set(q('char'), 'F0FE' if valore in {'☒', '\uf0fe'} else 'F06F')
        return
    if primo.tag == q('tab'):
        sostituto = ET.Element(q('t')); _testo(sostituto, valore)
        primo.getparent().replace(primo, sostituto)
    else:
        if primo.tag != q('t'):
            raise ValueError('Ancoraggio testuale non supportato')
        dopo = (primo.text or '')[ultimo_offset + 1:] if primo is ultimo else ''
        _testo(primo, (primo.text or '')[:offset] + valore + dopo)
    visti = {primo}
    for el, _ in porzione:
        if el in visti:
            continue
        visti.add(el)
        if el.tag == q('t'):
            _testo(el, (el.text or '')[ultimo_offset + 1:] if el is ultimo else '')
        else:
            el.getparent().remove(el)


def _risultato_form(root, punto):
    inizio = nodo(root, punto['percorso']); fine = nodo(root, punto['fine_campo'])
    sep = nodo(root, punto['separatore'])
    p = antenato(inizio, 'p')
    rsep, rfine = sep.getparent(), fine.getparent()
    if rsep.getparent() is not p or rfine.getparent() is not p:
        raise ValueError('Campo Word con contenitori annidati')
    figli = list(p); a, b = figli.index(rsep), figli.index(rfine)
    if a >= b or len(rsep.findall('w:fldChar', NS)) != 1 or len(rfine.findall('w:fldChar', NS)) != 1:
        raise ValueError('Delimitatori Word non separati')
    # Non cancellare segnalibri o markup legale assieme al risultato.
    risultato = figli[a + 1:b]
    if any(r.tag != q('r') or any(e.tag not in {q('r'), q('rPr'), q('t'), q('sym'), q('tab')}
                                      for e in r if e.tag != q('rPr')) for r in risultato):
        raise ValueError('Risultato Word contiene struttura da preservare')
    return inizio, p, rsep, rfine, risultato


def _intervallo_nodi(p, elementi):
    _, ancore = testo_ancore(p)
    insieme = {e for el in elementi for e in el.iter()}
    pos = [i for i, (e, _) in enumerate(ancore) if e in insieme]
    if pos:
        return min(pos), max(pos) + 1
    # Per un campo privo di risultato l'inserimento precede il delimitatore finale.
    ordine = list(p.iter()); indice = ordine.index(elementi[-1]) if elementi else len(ordine)
    prima = set(ordine[:indice])
    at = sum(e in prima for e, _ in ancore)
    return at, at


def prepara_operazioni(dati, fisico, valori):
    """Congela ancore e testo atteso PRIMA di modificare l'albero."""
    contenuti, parti = apri(dati)
    per_rif = {p['riferimento']: p for p in fisico['punti']}
    operazioni, residui = [], []
    for ref, valore in valori.items():
        punto = per_rif[ref]; root = parti[punto['parte']]
        if not punto['scrivibile']:
            residui.append(dict(riferimento=ref, motivo=punto['motivo_tecnico'])); continue
        try:
            el = nodo(root, punto['percorso']); p = nodo(root, punto['percorso_paragrafo'])
            tipo = punto['tipo']; a = punto.get('inizio'); b = punto.get('fine')
            testo = testo_ancore(p)[0]
            scritto = str(valore)
            extra = {}
            if tipo.endswith('casella'):
                if type(valore) is not bool:
                    raise ValueError('La casella richiede una scelta sì/no esplicita')
                scritto = '☒' if valore else '☐'
            if tipo == 'glifo_casella':
                _, ancore = testo_ancore(p)
                if ancore[a][0].tag == q('sym') or any('\uf000' <= c <= '\uf0ff' for c in punto['originale']):
                    scritto = '\uf0fe' if valore else '\uf06f'
            elif tipo in {'cella_vuota', 'paragrafo_vuoto'}:
                a, b = 0, len(testo)
                extra['aggiungi_run'] = True
            elif tipo == 'inserimento_testo':
                if testo and not testo[-1].isspace():
                    scritto = ' ' + scritto
            elif tipo.startswith('sdt_'):
                corpo = el.find('w:sdtContent', NS)
                a, b = _intervallo_nodi(p, [corpo])
                ts = list(corpo.iter(q('t')))
                if any(corpo.iter(q('sym'))) or any(corpo.iter(q('br'))) or any(corpo.iter(q('tab'))):
                    raise ValueError('Controllo Word con risultato non testuale semplice')
                if tipo == 'sdt_casella' and len(ts) != 1:
                    raise ValueError('Casella Word senza risultato testuale singolo')
                extra['testi_sdt'] = ts
                extra['corpo_sdt'] = corpo
                if punto.get('sottotipo_sdt') == 'date':
                    from .word_date import converti as converti_data
                    scritto, extra['data_iso'] = converti_data(valore, punto['formato_data'], punto['calendario_data'])
                if tipo == 'sdt_casella':
                    cb = el.find('w:sdtPr/w14:checkbox', NS)
                    stato = cb.find('w14:checkedState' if valore else 'w14:uncheckedState', NS)
                    if stato is not None:
                        scritto = chr(int(stato.get('{' + W14 + '}val'), 16))
                    extra['cb'] = cb
                    extra['font_casella'] = (stato.get('{' + W14 + '}font') if stato is not None else None) or ('Wingdings' if '\uf000' <= scritto <= '\uf0ff' else 'Segoe UI Symbol')
            elif tipo.startswith('form_'):
                begin, p, rsep, rfine, risultati = _risultato_form(root, punto)
                a, b = _intervallo_nodi(p, risultati if risultati else [rfine])
                if not risultati:
                    b = a
                extra.update(begin=begin, rsep=rsep, rfine=rfine, risultati=risultati)
                if tipo == 'form_casella':
                    extra['indice_controllo'] = list(p.iter(q('checkBox'))).index(begin.find('w:ffData/w:checkBox', NS))
                    _, ancore = testo_ancore(p)
                    if b > a and (ancore[a][0].tag == q('sym') or any('\uf000' <= ch <= '\uf0ff' for ch in testo[a:b])):
                        scritto = '\uf0fe' if valore else '\uf06f'
            elif tipo == 'elenco_casella':
                a = b = 0
                scritto = ''  # Il glifo appartiene alla numerazione, non al testo.
            if a is None or b is None:
                raise ValueError('Posizione di scrittura assente')
            if b > a and tipo not in {'sdt_casella', 'sdt_testo', 'sdt_rich_text', 'elenco_casella'}:
                _, ancore = testo_ancore(p)
                if any(e.tag not in {q('t'), q('tab'), q('sym')} for e, _ in ancore[a:b]):
                    raise ValueError('Intervallo con interruzioni Word: da compilare manualmente')
            if tipo in {'testo', 'spazio_implicito', 'segnaposto_testuale'}:
                # Mantiene parentesi e separazione tipografica senza correggere il dato.
                if testo[a:b].startswith('(') and testo[a:b].endswith(')'):
                    scritto = '(' + scritto + ')'
                if a and (testo[a - 1].isalnum() or testo[a - 1] in ':;') and scritto and scritto[0].isalnum(): scritto = ' ' + scritto
                if b < len(testo) and testo[b].isalnum() and scritto and scritto[-1].isalnum(): scritto += ' '
            operazioni.append(dict(punto=punto, el=el, p=p, inizio=a, fine=b,
                                    valore=valore, scritto=scritto, **extra))
        except (ValueError, KeyError, TypeError) as exc:
            residui.append(dict(riferimento=ref, motivo=str(exc)))
    return contenuti, parti, operazioni, residui


def _marca_elenco(op, contenuti, parti_modificate):
    """Override privato del livello: conserva numPr, tabulazioni e rientri."""
    dati = parti_modificate.get('word/numbering.xml', contenuti['word/numbering.xml'])
    root = ET.fromstring(dati)
    numeri, _ = numerazioni({'word/numbering.xml': dati})
    punto = op['punto']; vecchio = punto['num_id']; livello = punto['livello']
    originale = next(n for n in root.findall('w:num', NS) if n.get(q('numId')) == vecchio)
    nuovo = deepcopy(originale)
    nuovo_id = str(max(int(n.get(q('numId'))) for n in root.findall('w:num', NS)) + 1)
    nuovo.set(q('numId'), nuovo_id)
    override = next((o for o in nuovo.findall('w:lvlOverride', NS) if o.get(q('ilvl')) == livello), None)
    if override is None:
        override = ET.SubElement(nuovo, q('lvlOverride')); override.set(q('ilvl'), livello)
    for vec in list(override.findall('w:lvl', NS)):
        override.remove(vec)
    lvl = deepcopy(numeri[vecchio][livello]); override.append(lvl)
    lvl.find('w:lvlText', NS).set(q('val'), '\uf0fe' if op['valore'] else '\uf06f')
    pr = lvl.find('w:rPr', NS)
    if pr is None: pr = ET.SubElement(lvl, q('rPr'))
    font = pr.find('w:rFonts', NS)
    if font is None: font = ET.SubElement(pr, q('rFonts'))
    for k in ('ascii', 'hAnsi', 'eastAsia', 'cs'): font.set(q(k), 'Wingdings')
    root.append(nuovo)
    ppr = op['p'].find('w:pPr', NS)
    if ppr is None: ppr = ET.Element(q('pPr')); op['p'].insert(0, ppr)
    numpr = ppr.find('w:numPr', NS)
    if numpr is None: numpr = ET.SubElement(ppr, q('numPr'))
    for nome, val in (('ilvl', livello), ('numId', nuovo_id)):
        e = numpr.find('w:' + nome, NS)
        if e is None: e = ET.SubElement(numpr, q(nome))
        e.set(q('val'), val)
    parti_modificate['word/numbering.xml'] = serializza(root)


def scrivi(dati, fisico, valori):
    if fisico['docx_sha256'] != hashlib.sha256(dati).hexdigest():
        raise ValueError('Le posizioni appartengono a un altro originale')
    contenuti, parti, ops, residui = prepara_operazioni(dati, fisico, valori)
    attesi = {}; gruppi = defaultdict(list)
    for op in ops:
        pt = op['punto']; gruppi[pt['parte'], pt['percorso_paragrafo']].append(op)
    # Il controllo atteso è una proiezione testuale per posizione dell'originale,
    # non una fotografia del documento già modificato.
    esclusi = set()
    for chiave, gruppo in gruppi.items():
        ordinati = sorted(gruppo, key=lambda o: (o['inizio'], o['fine']))
        intervalli = [o for o in ordinati if o['punto']['tipo'] != 'elenco_casella']
        for prima, dopo in zip(intervalli, intervalli[1:]):
            if dopo['inizio'] < prima['fine'] or dopo['inizio'] == prima['inizio']:
                esclusi.update(id(o) for o in gruppo)
        if any(id(o) in esclusi for o in gruppo):
            residui.extend(dict(riferimento=o['punto']['riferimento'], motivo='Punti scrivibili sovrapposti') for o in gruppo)
            continue
        testo = testo_ancore(gruppo[0]['p'])[0]
        for op in reversed(ordinati):
            testo = testo[:op['inizio']] + op['scritto'] + testo[op['fine']:]
        attesi[chiave] = testo
    modifiche, parti_modificate = [], {}
    for op in sorted(ops, key=lambda o: (o['punto']['parte'], o['punto']['percorso_paragrafo'], o['inizio']), reverse=True):
        if id(op) in esclusi: continue
        punto = op['punto']; tipo = punto['tipo']; el = op['el']; p = op['p']
        if tipo == 'elenco_casella':
            _marca_elenco(op, contenuti, parti_modificate)
        elif tipo.startswith('sdt_'):
            ts = op['testi_sdt']
            if ts:
                _testo(ts[0], op['scritto'])
                for t in ts[1:]:
                    _testo(t, '')
            else:
                container = next(op['corpo_sdt'].iter(q('p')), op['corpo_sdt'])
                container.append(_run(p, op['scritto']))
            if tipo == 'sdt_casella':
                cb = op['cb']; chk = cb.find('w14:checked', NS)
                if chk is None: chk = ET.SubElement(cb, '{' + W14 + '}checked')
                chk.set('{' + W14 + '}val', '1' if op['valore'] else '0')
                _font_simbolo(antenato(ts[0], 'r'), op['font_casella'])
            pr = el.find('w:sdtPr', NS); placeholder = pr.find('w:showingPlcHdr', NS)
            if placeholder is not None: pr.remove(placeholder)
            if op.get('data_iso'):
                pr.find('w:date', NS).set(q('fullDate'), op['data_iso'])
        elif tipo.startswith('form_'):
            if op['fine'] > op['inizio']:
                _intervallo(p, op['inizio'], op['fine'], op['scritto'])
            else:
                modello = op['risultati'][0] if op['risultati'] else op['begin'].getparent()
                nuovo_run = _run(p, op['scritto'], modello)
                if tipo == 'form_casella': _font_simbolo(nuovo_run, 'Segoe UI Symbol')
                p.insert(list(p).index(op['rfine']), nuovo_run)
            if tipo == 'form_casella':
                cb = op['begin'].find('w:ffData/w:checkBox', NS); chk = cb.find('w:checked', NS)
                if chk is None: chk = ET.SubElement(cb, q('checked'))
                chk.set(q('val'), '1' if op['valore'] else '0')
        elif tipo in {'cella_vuota', 'paragrafo_vuoto', 'inserimento_testo'}:
            if tipo == 'inserimento_testo':
                p.append(_run(p, op['scritto']))
            elif op['fine']:
                _intervallo(p, 0, op['fine'], op['scritto'])
            else:
                p.append(_run(p, op['scritto']))
        else:
            valore = op['scritto']
            _intervallo(p, op['inizio'], op['fine'], valore)
        modifiche.append(dict(riferimento=punto['riferimento'], tipo=tipo, parte=punto['parte'],
                              percorso_paragrafo=punto['percorso_paragrafo'], percorso_controllo=punto['percorso'],
                              indice_controllo=op.get('indice_controllo'), data_iso=op.get('data_iso'),
                              valore=op['valore'], valore_scritto=op['scritto']))
    for parte in {m['parte'] for m in modifiche}:
        parti_modificate[parte] = serializza(parti[parte])
    risultato = salva(dati, parti_modificate) if modifiche else dati
    piano_audit = dict(paragrafi_attesi=[dict(parte=k[0], percorso=k[1], testo=v) for k,v in attesi.items()],
                      parti_modificate=list(parti_modificate), modifiche=modifiche)
    verifica = verifica_collocazione(dati, risultato, piano_audit)
    if not verifica['ok']:
        raise ValueError('Audit di collocazione fallito: ' + '; '.join(verifica['errori'][:3]))
    return risultato, dict(modifiche=modifiche, residui=residui, piano_audit=piano_audit, verifica=verifica)


def verifica_collocazione(originale, compilato, piano):
    prima, roots = apri(originale); dopo, finali = apri(compilato)
    errori = []
    attesi = {(v['parte'], v['percorso']): v['testo'] for v in piano['paragrafi_attesi']}
    if set(prima) != set(dopo): errori.append('Parti del documento aggiunte o rimosse')
    for parte, dati in prima.items():
        if parte not in piano['parti_modificate'] and dopo.get(parte) != dati:
            errori.append('Parte non autorizzata modificata: ' + parte)
    for parte, root in roots.items():
        final = finali.get(parte)
        if final is None: continue
        def struttura(el):
            cp = deepcopy(el)
            # Block-level SDTs keep properties outside paragraphs. Normalize only
            # the explicitly authorized date state, verified separately below.
            for change in piano['modifiche']:
                if change['parte'] != parte or not change.get('data_iso'):
                    continue
                control = nodo(cp, change['percorso_controllo'])
                props = control.find('w:sdtPr', NS)
                date = props.find('w:date', NS)
                date.attrib.pop(q('fullDate'), None)
                for marker in props.findall('w:showingPlcHdr', NS):
                    props.remove(marker)
            # Il testo dei paragrafi e le loro proprietà hanno verifiche
            # dedicate; qui restano tabelle, celle, sezioni e contenitori.
            for p in reversed(list(cp.iter(q('p')))):
                for figlio in list(p): p.remove(figlio)
            return ET.tostring(cp, method='c14n', exclusive=True)
        if struttura(root) != struttura(final):
            errori.append('Struttura esterna ai paragrafi modificata: ' + parte)
        ps = list(root.iter(q('p'))); pf = list(final.iter(q('p')))
        if len(ps) != len(pf): errori.append('Struttura paragrafi cambiata: ' + parte); continue
        for p in ps:
            path = root.getroottree().getelementpath(p)
            try:
                letto = testo_ancore(nodo(final, path))[0]
                atteso = attesi.get((parte, path), testo_ancore(p)[0])
                if letto != atteso: errori.append('Testo nella posizione errata: ' + parte + ':' + path)
                # Le proprietà del paragrafo restano identiche, salvo il riferimento
                # alla numerazione privata quando si marca una casella elenco.
                pp = p.find('w:pPr', NS); fp = nodo(final, path).find('w:pPr', NS)
                def proprieta(el):
                    cp = deepcopy(el) if el is not None else ET.Element(q('pPr'))
                    for n in list(cp.findall('w:numPr', NS)): cp.remove(n)
                    return ET.tostring(cp, method='c14n', exclusive=True)
                if proprieta(pp) != proprieta(fp): errori.append('Proprietà paragrafo alterate: ' + path)
            except ValueError:
                errori.append('Paragrafo spostato: ' + path)
    # Gli stati Word sono verificati separatamente dal testo visibile.
    numeri, _ = numerazioni(dopo)
    for m in piano['modifiche']:
        tipo = m['tipo']
        if m.get('data_iso'):
            try:
                sdt = nodo(finali[m['parte']], m['percorso_controllo'])
                date = sdt.find('w:sdtPr/w:date', NS)
                if date is None or date.get(q('fullDate')) != m['data_iso']:
                    errori.append('Stato data Word errato')
                if sdt.find('w:sdtPr/w:showingPlcHdr', NS) is not None:
                    errori.append('Data Word ancora marcata come segnaposto')
            except (ValueError, AttributeError):
                errori.append('Stato data Word non rileggibile')
        if not tipo.endswith('casella'): continue
        try:
            p = nodo(finali[m['parte']], m['percorso_paragrafo'])
            if tipo == 'elenco_casella':
                num = p.find('w:pPr/w:numPr', NS)
                nid = num.find('w:numId', NS).get(q('val')); il = num.find('w:ilvl', NS).get(q('val'))
                glifo = numeri[nid][il].find('w:lvlText', NS).get(q('val'))
                if glifo != ('\uf0fe' if m['valore'] else '\uf06f'): errori.append('Stato elenco errato')
            elif tipo == 'form_casella':
                cb = list(p.iter(q('checkBox')))[m['indice_controllo']]
                chk = cb.find('w:checked', NS)
                if chk is None or chk.get(q('val')) != ('1' if m['valore'] else '0'): errori.append('Stato campo modulo errato')
            elif tipo == 'sdt_casella':
                sdt = nodo(finali[m['parte']], m['percorso_controllo'])
                chk = sdt.find('w:sdtPr/w14:checkbox/w14:checked', NS)
                if chk is None or chk.get('{' + W14 + '}val') != ('1' if m['valore'] else '0'): errori.append('Stato content control errato')
        except (ValueError, AttributeError, KeyError, IndexError):
            errori.append('Stato casella non rileggibile')
    return dict(ok=not errori, errori=errori, verifica_visiva='NON_ESEGUITA', pronto_per_firma=False)
