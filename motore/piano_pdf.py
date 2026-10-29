"""PDF compilation as validated data bindings, independent of generated code."""
import contextvars
import copy
import json
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fitz
from requests import RequestException
from . import agente, controllo, mappa as mappe, soggetti, traccia_pdf
from .anagrafe import Anagrafe
from .lavori import impronta_dati, nuova_cartella, salva_json
from .valori import risolvi, ProiezioneInvalida
from .fonti_pdf import fonti
from . import revisione_pdf
from riusare.strumenti_documento import Ancora, PagineDiritte, firmato, scrivi, impronta

VERSIONE = 3


def _firma_mappa(mappa):
    return impronta_dati(mappa['ancore'])


def _senza_guasti(piano):
    diagnostica = piano.get('diagnostica', {})
    return (not diagnostica.get('guasti_rilettura') and
            not any(d.get('scrittura_fallita') for d in piano.get('decisioni',{}).values()) and
            not any(p.get('errore') or p.get('guasti') for p in
                    (diagnostica.get('riparazione_scrittura') or {}).get('pagine', [])))


def _scrivi(originale, mappa, valori, cartella):
    rows = []
    bozza = cartella / 'bozza.pdf'
    # Un modulo con una firma digitale (di solito dell'ente che l'ha pubblicato)
    # si compila in coda al file, come fa Acrobat: i byte firmati restano
    # identici e la firma resta verificabile sulla sua versione.
    in_coda = firmato(originale)
    if in_coda:
        shutil.copyfile(originale, bozza)
    with fitz.open(bozza if in_coda else originale) as doc:
        with PagineDiritte(doc) as diritto:
            for raw in mappa['ancore']:
                aid = raw['id']
                if aid not in valori:
                    continue
                a = Ancora.da_dict(raw)
                esito = scrivi(diritto[a.pagina], a, valori[aid])
                row = dict(ancora=aid, tipo=a.tipo, etichetta=a.etichetta,
                           valore=valori[aid], scritto=bool(esito.ok), motivo=esito.motivo)
                if (not esito.ok and 'non entra' in esito.motivo and a.tipo in ('area', 'tratto', 'riempimento')
                        and not a.parametri.get('formato_data')):
                    numero = 1+sum('valore_completo' in r for r in rows)
                    riferimento = 'Vedi allegato %d' % numero
                    ripiego = scrivi(diritto[a.pagina], a, riferimento)
                    if ripiego.ok:
                        row.update(valore=riferimento, valore_completo=valori[aid],
                                   allegato=numero,scritto=True,motivo='Valore integrale in allegato richiamato dal campo')
                rows.append(row)
        # Overflow is explicit and lossless: never abbreviate business data silently.
        for row in rows:
            if 'valore_completo' not in row:
                continue
            row['pagina_allegato'] = len(doc)+1
            titolo = 'Allegato %d - pagina %d - %s' % (row['allegato'],
                next(a['pagina']+1 for a in mappa['ancore'] if a['id']==row['ancora']),row['etichetta'])
            testo = row['valore_completo']
            pagina = doc.new_page()
            pagina.insert_textbox(fitz.Rect(40,35,555,105),titolo,fontsize=11)
            # Write by measured lines, continuing on another page when necessary.
            y=120
            for paragrafo in testo.split('\n'):
                linea=''
                for parola in paragrafo.split(' '):
                    candidato=(linea+' '+parola).strip()
                    if fitz.get_text_length(candidato,fontsize=10)>500 and linea:
                        if y>790:
                            pagina=doc.new_page();y=50
                        pagina.insert_text((45,y),linea,fontsize=10);y+=15;linea=parola
                    else:
                        linea=candidato
                if y>790:
                    pagina=doc.new_page();y=50
                pagina.insert_text((45,y),linea,fontsize=10);y+=15
            row['pagina_allegato_fine']=len(doc)
        if in_coda:
            doc.saveIncr()
        else:
            doc.save(bozza)
    return bozza, dict(scritture=rows)


def chiede_conferme():
    """QUADRA_PDF_CONFERME=chiedi lascia vuoti i campi da confermare; per difetto si scrivono."""
    return os.environ.get('QUADRA_PDF_CONFERME', 'scrivi').strip().lower() == 'chiedi'


def esegui(originale, mappa, piano, fascicolo, cartella, togli=(), origine='piano_ricevuto'):
    """Reapply a reviewed plan only to its exact source, profile and map."""
    if (piano.get('versione') != VERSIONE or piano.get('impronta') != impronta(originale)
            or piano.get('fascicolo') != impronta_dati(fascicolo)
            or piano.get('mappa') != _firma_mappa(mappa)):
        raise ValueError('Il modulo o il fascicolo sono cambiati: occorre una nuova verifica.')
    decisions = copy.deepcopy(piano['decisioni'])
    profilo = fascicolo.get('profilo', {})
    catalogo = fonti(fascicolo, piano.get('contesto'))
    chiedi = chiede_conferme()
    if chiedi:
        revisione_pdf.richiedi_conferme(mappa, decisions, piano.get('contesto'))
    else:
        # Compila e basta: quello che chiederebbe conferma si scrive comunque e
        # resta segnato "da controllare", con il motivo, per chi rilegge.
        prova = copy.deepcopy(decisions)
        revisione_pdf.richiedi_conferme(mappa, prova, piano.get('contesto'))
        for aid, d in decisions.items():
            if d.get('origine') == 'utente':
                continue
            if d.get('stato') == 'da_confermare' or (d.get('stato') == 'assegna'
                                                      and prova[aid].get('stato') == 'da_confermare'):
                d.update(stato='assegna', da_controllare=d.get('da_controllare')
                         or prova[aid].get('motivo') or d.get('motivo', ''))
    esclusi = set(togli)
    valori = {}
    by_id = {a['id']: a for a in mappa['ancore']}
    for aid, d in decisions.items():
        if aid not in by_id:
            raise ValueError('Piano con un campo sconosciuto')
        if aid in esclusi:
            d.pop('scrittura_fallita', None)
            d.update(stato='manuale', motivo='Rimosso dall’utente', origine='utente')
        campo = d.get('campo')
        a = by_id[aid]
        if d.get('stato') == 'assegna':
            try:
                if chiedi and revisione_pdf.selezione(a) and d.get('origine') != 'utente':
                    d.update(stato='da_confermare', motivo='Conferma la scelta prima di inserirla')
                    continue
                valori[aid] = revisione_pdf.valore(d, catalogo, a)
            except ProiezioneInvalida as exc:
                d.update(stato='dubbio', motivo=str(exc))
    note = {'punti_aperti': [], 'non_applicabili': [a for a,d in decisions.items() if d.get('stato')=='non_campo']}
    for aid, a in by_id.items():
        if aid not in valori and aid not in note['non_applicabili']:
            d = decisions.get(aid, {})
            campo = d.get('campo', '')
            note['punti_aperti'].append(dict(ancora=aid,
                chiave='profilo.'+campo if campo in profilo and not profilo.get(campo) else '',
                motivo=d.get('motivo') or 'Da verificare manualmente'))
    decisioni_prima_scrittura = copy.deepcopy(decisions)
    bozza, writes = _scrivi(originale, mappa, valori, cartella)
    verdict = controllo.controlla(originale, bozza, mappa, writes, note)
    # Keep the first attempt: the clean regeneration below must not erase why a field failed.
    traccia = traccia_pdf.costruisci(mappa, piano, decisioni_prima_scrittura,
                                    writes['scritture'], verdict, origine)
    salva_json(cartella/'scritture_primo_tentativo.json', writes)
    salva_json(cartella/'verifica_primo_tentativo.json', verdict)
    # A failed material check must not leave a known incorrect write in the draft.
    failed = {r['ancora'] for r in verdict['non_segnalate'] + verdict['non_riuscite']}
    if failed:
        for aid in failed:
            valori.pop(aid, None)
            problema = next(r.get('motivo','') for r in traccia['campi'] if r['ancora']==aid)
            decisions[aid].update(stato='manuale', scrittura_fallita=True,
                motivo='Scrittura non verificata, cambia il dato o completa a mano: '+problema)
            note['punti_aperti'].append(dict(ancora=aid, chiave='', motivo=decisions[aid]['motivo']))
        bozza, writes = _scrivi(originale, mappa, valori, cartella)
        verdict = controllo.controlla(originale, bozza, mappa, writes, note)
    verdict['piano'] = dict(piano, decisioni=decisions)
    verdict['domande_campi'] = revisione_pdf.domande(mappa, verdict['piano'], catalogo)
    verdict['contesto'] = piano.get('contesto')
    verdict['riepilogo_decisioni'] = {s:sum(d.get('stato') == s for d in decisions.values())
        for s in ('assegna', 'da_confermare', 'dubbio', 'dato_assente', 'manuale', 'non_campo')}
    verdict['decisioni_campi'] = decisions
    verdict['scritture_escluse'] = sorted(failed)
    verdict['soggetti_da_controllare'] = soggetti.avvertimenti(mappa, valori)
    verdict['copertura_completa_certificata'] = False
    verdict['avvisi_rilettura'] = piano.get('diagnostica',{}).get('avvisi',[])
    verdict['allegati'] = [s for s in writes['scritture'] if s.get('valore_completo')]
    verdict['firma_preesistente'] = firmato(originale)
    verdict['da_controllare'] = [dict(ancora=aid, pagina=by_id[aid]['pagina']+1,
        etichetta=by_id[aid].get('etichetta') or by_id[aid].get('contesto') or aid,
        scritto=revisione_pdf.descrivi(valori[aid]), motivo=d['da_controllare'])
        for aid, d in decisions.items() if d.get('da_controllare') and aid in valori
        and d.get('origine') != 'utente']
    verdict['letture_discordi'] = [dict(ancora=aid, pagina=by_id[aid]['pagina']+1,
        etichetta=by_id[aid].get('etichetta') or by_id[aid].get('contesto') or aid,
        scritto=revisione_pdf.descrivi(valori[aid]),
        alternativa=revisione_pdf.descrivi(d['seconda_lettura']['valore'])
                    if d['seconda_lettura']['valore'] not in (None, False) else 'lasciarlo vuoto',
        sostituibile=d['seconda_lettura']['valore'] is not None
                     and (d['seconda_lettura'].get('decisione') or {}).get('stato') == 'assegna')
        for aid, d in decisions.items() if d.get('seconda_lettura') and aid in valori
        and d.get('origine') != 'utente']
    verdict['traccia_campi'] = traccia
    salva_json(cartella/'traccia.json', traccia)
    salva_json(cartella/'mappa.json', mappa)
    salva_json(cartella/'piano.json', verdict['piano'])
    salva_json(cartella/'verdetto.json', verdict)
    return dict(passo='verdetto', verdetto=verdict, bozza=str(bozza),
                traccia=str(cartella/'traccia.json'),
                artefatto=str(cartella), avvisi=verdict['soggetti_da_controllare'],
                testo=controllo.racconta(verdict))


def _ripara_scritture(pdf, mappa, piano, evento, fascicolo, catalogo, images, cartella_lavoro):
    """One bounded repair round, at most three pages, never on user answers.

    Preserve every successful binding and the first physical failure evidence.
    The model may only propose new source bindings for failed slots; the usual
    source, semantic and material checks still apply.
    """
    failed = set(evento['verdetto']['scritture_escluse'])
    eligible = {a for a in failed if piano['decisioni'].get(a,{}).get('origine') != 'utente'}
    if not eligible:
        return evento
    plan = copy.deepcopy(evento['verdetto']['piano'])
    report = dict(campi=sorted(eligible), tentativi_massimi=1, pagine_massime=3,
                  prima_scrittura=evento['verdetto']['traccia_campi'], pagine=[])
    by_id = {a['id']:a for a in mappa['ancore']}
    for page in [p for p in mappa['rese'] if eligible.intersection(p['indirizzi'].values())][:3]:
        addresses = {n:a for n,a in page['indirizzi'].items() if a in eligible}
        fields = [dict(posto=n, **{k:by_id[a].get(k) for k in
                    ('etichetta','tipo','rect','contesto','parametri')}) for n,a in addresses.items()]
        errors = [dict(posto=n, decisione=piano['decisioni'][a],
            motivo=next(r['motivo'] for r in report['prima_scrittura']['campi'] if r['ancora']==a))
            for n,a in addresses.items()]
        diagnostic = dict(pagina=page['pagina'])
        report['pagine'].append(diagnostic)
        try:
            proposals = agente.decidi_campi(page['testo'], addresses, fields, catalogo,
                images.get(page['pagina']), diagnostica=diagnostic, _ripara=False, _errori=errors)
            proposals = {a:d for a,d in proposals.items() if a in addresses.values()}
            errors_review, warnings = [], []
            review = agente.rileggi_documento([page],
                {a:d.get('campo','') for a,d in proposals.items() if d.get('stato')=='assegna'},
                Anagrafe({'profilo':catalogo}), images, piano=proposals, mappa=mappa,
                errori=errors_review, avvisi=warnings)
            diagnostic.update(escluse=review, guasti=errors_review, avvisi=warnings)
            for a,d in proposals.items():
                if a in review:
                    d.update(stato='dubbio',motivo=review[a])
                for warning in warnings:
                    if warning['ancora']==a and d.get('stato')=='assegna':
                        d.update(stato='da_confermare',motivo=warning['motivo'])
                plan['decisioni'][a] = d
        except (agente.RispostaModelloInvalida, RequestException) as exc:
            diagnostic['errore'] = dict(tipo=type(exc).__name__,
                stato_http=getattr(getattr(exc,'response',None),'status_code',None))
            # Keep the previous clean draft and its open question if repair failed.
            for a in addresses.values():
                plan['decisioni'][a] = evento['verdetto']['piano']['decisioni'][a]
            if diagnostic['errore']['stato_http'] in (400,401,402,403,404):
                break
    revisione_pdf.richiedi_conferme(mappa, plan['decisioni'], plan.get('contesto'), ambito=eligible)
    plan.setdefault('diagnostica', {})['riparazione_scrittura'] = report
    return esegui(pdf, mappa, plan, fascicolo, nuova_cartella(cartella_lavoro), origine='riparazione_scrittura')


COLLA = {'il', 'a', 'in', 'di', 'del', 'della', 'e', 'nato', 'nata', 'nato/a', '-', '.', 'c.f.', 'cf'}


def confronta_letture(mappa, prima, seconda, catalogo, pagine_guaste=()):
    """Mette a confronto le due letture campo per campo, sul valore che finirebbe scritto.

    Non vota e non sceglie: dove i due modelli non concordano il valore della
    prima resta scritto ma porta con se' l'altra proposta, da mostrare a chi
    compila; dove solo la seconda trova un dato, quel dato diventa una proposta
    da confermare, mai una scrittura. Modifica `prima` sul posto.
    """
    by_id = {a['id']: a for a in mappa['ancore']}
    lette = {aid for p in mappa['rese'] if p['pagina'] not in pagine_guaste
             for aid in p['indirizzi'].values()}

    def scritto(d, a):
        if not d or d.get('stato') != 'assegna':
            return False if revisione_pdf.selezione(a) else None
        try:
            return revisione_pdf.valore(d, catalogo, a)
        except ProiezioneInvalida:
            return False if revisione_pdf.selezione(a) else None

    def uguali(x, y):
        # Lo stesso dato scritto in un altro modo non e' un disaccordo:
        # "Genova il 20/06/1976" e "Genova, 20/06/1976", "IM" accanto al comune.
        if not isinstance(x, str) or not isinstance(y, str):
            return x == y
        parole = lambda v: set(re.findall(r'[\w/@.-]+', v.casefold().replace(',', ' '))) - COLLA
        px, py = parole(x), parole(y)
        return bool(px) and bool(py) and (px <= py or py <= px)
    rapporto = dict(confrontati=0, discordi=[], solo_seconda=[])
    for aid in sorted(lette):
        a, d, altra = by_id.get(aid), prima.get(aid), seconda.get(aid)
        if a is None or d is None or altra is None or not revisione_pdf.scrivibile(a):
            continue
        rapporto['confrontati'] += 1
        va, vb = scritto(d, a), scritto(altra, a)
        if uguali(va, vb):
            continue
        if va is None or va is False:
            prima[aid] = dict(altra, stato='da_confermare', origine='seconda_lettura',
                              seconda_lettura=dict(valore=None, decisione=d),
                              motivo='Lo propone solo la seconda lettura: conferma se è giusto. '
                                     + str(altra.get('motivo', '')))
            rapporto['solo_seconda'].append(aid)
        else:
            d['seconda_lettura'] = dict(valore=vb, decisione=altra)
            rapporto['discordi'].append(aid)
    return rapporto


PAGINE_REVISIONE = 6


def _decisione_uguale(nuova, vecchia):
    chiave = lambda d: (d.get('stato'), d.get('campo', ''), json.dumps(d.get('parti'), sort_keys=True),
                        d.get('separatore', ' '), json.dumps(d.get('confronto'), sort_keys=True))
    return chiave(nuova) == chiave(vecchia)


def _revisione_visiva(pdf, mappa, evento, fascicolo, catalogo, cartella_lavoro):
    """Un giro di revisione guardando la pagina COMPILATA, non l'originale.

    La rilettura di prima giudica le associazioni sul modulo vuoto. Qui il
    modello vede il PDF finito con i valori dentro: e' li' che si vedono un dato
    nella riga sbagliata, una parola stampata ripetuta, un posto lasciato vuoto
    che le fonti potevano riempire. La letteratura sull'autocorrezione (CRITIC e
    seguenti) dice che correggere funziona con un riscontro esterno e pochi giri:
    il riscontro e' la pagina resa, il giro e' uno, e ogni correzione ripassa
    dagli stessi controlli di fonte, formato e verifica materiale.
    Non tocca le decisioni dell'utente ne' le scelte da confermare.
    """
    verdetto = evento['verdetto']
    piano = verdetto['piano']
    decisioni = piano['decisioni']
    scritte = {r['ancora']: r.get('valore') for r in verdetto['verificate']}
    by_id = {a['id']: a for a in mappa['ancore']}
    modificabili = lambda a: (decisioni.get(a, {}).get('origine') != 'utente'
                              and decisioni.get(a, {}).get('stato') != 'da_confermare'
                              and not revisione_pdf.selezione(by_id[a]))
    pagine = [p for p in mappa['rese']
              if any(modificabili(a) for a in p['indirizzi'].values())][:PAGINE_REVISIONE]
    if not pagine:
        return evento
    immagini = agente.immagini_per_pagina(evento['bozza'], [p['pagina'] for p in pagine])
    rapporto = dict(pagine=[], cambiate={})
    nuove = {}
    for page in pagine:
        indirizzi = {n: a for n, a in page['indirizzi'].items() if modificabili(a)}
        campi = [dict(posto=n, **{k: by_id[a].get(k) for k in ('etichetta', 'tipo', 'rect', 'contesto', 'parametri')})
                 for n, a in indirizzi.items()]
        attuali = [dict(posto=n, decisione={k: decisioni.get(a, {}).get(k) for k in
                                            ('stato', 'campo', 'parti', 'separatore', 'soggetto', 'motivo')},
                        valore_scritto=scritte.get(a, '')) for n, a in indirizzi.items()]
        diagnostica = dict(pagina=page['pagina'])
        rapporto['pagine'].append(diagnostica)
        try:
            proposte = agente.decidi_campi(page['testo'], indirizzi, campi, catalogo,
                                           immagini.get(page['pagina']), diagnostica=diagnostica,
                                           _ripara=False, _errori=attuali, revisione=True)
        except (agente.RispostaModelloInvalida, RequestException) as exc:
            diagnostica['errore'] = type(exc).__name__
            continue
        for aid, d in proposte.items():
            vecchia = decisioni.get(aid, {})
            if aid not in indirizzi.values() or _decisione_uguale(d, vecchia):
                continue
            if d.get('motivo') == 'Il modello non ha restituito una decisione':
                continue
            d = dict(d, origine='revisione_visiva')
            nuove[aid] = d
            rapporto['cambiate'][aid] = dict(prima=vecchia, dopo=d)
    if not nuove:
        piano.setdefault('diagnostica', {})['revisione_visiva'] = rapporto
        return evento
    nuovo_piano = copy.deepcopy(piano)
    nuovo_piano['decisioni'].update(nuove)
    nuovo_piano.setdefault('diagnostica', {})['revisione_visiva'] = rapporto
    return esegui(pdf, mappa, nuovo_piano, fascicolo, nuova_cartella(cartella_lavoro),
                  origine='revisione_visiva')


def lavora(radice, pdf, fascicolo, cartella_lavoro, riusa=True,
           pertinenza_confermata=False, piano_di_prima=None, togli=(), contesto=None):
    """Il modello dei PDF (QUADRA_PDF_MODELLO) vale per tutto il lavoro, se c'e'."""
    with agente.usando(agente.config_pdf()):
        yield from _lavora(radice, pdf, fascicolo, cartella_lavoro, riusa,
                           pertinenza_confermata, piano_di_prima, togli, contesto)


def _lavora(radice, pdf, fascicolo, cartella_lavoro, riusa=True,
            pertinenza_confermata=False, piano_di_prima=None, togli=(), contesto=None):
    pdf = Path(pdf)
    if firmato(pdf):
        yield dict(passo='misura', testo='Il modulo porta una firma digitale: la lascio intatta e aggiungo i dati in coda al file.')
    work = nuova_cartella(cartella_lavoro)
    if piano_di_prima is not None:
        contesto = piano_di_prima.get('contesto')
    catalogo = fonti(fascicolo, contesto)
    yield dict(passo='misura', testo='Leggo testo, tabelle e spazi del modulo.')
    m = mappe.costruisci(pdf)
    yield dict(passo='mappa', mappa=m, testo=f"{len(m['ancore'])} spazi individuati: verifico il significato di ciascuno.")
    if not m['ancore']:
        yield dict(passo='rifiuto', testo='Non ho individuato spazi utilizzabili. Il modulo non e compilato.')
        return
    identity = dict(versione=VERSIONE, impronta=m['impronta'],
                    fascicolo=impronta_dati(fascicolo), mappa=_firma_mappa(m))
    if contesto is not None:
        identity['contesto'] = contesto
    cache = Path(cartella_lavoro)/'piani'/ (impronta_dati(identity)+'.json')
    override_file = cache.with_suffix('.utente.json')
    overrides = {}
    if override_file.is_file():
        try:
            saved = json.loads(override_file.read_text(encoding='utf-8'))
            if all(saved.get(k) == v for k,v in identity.items()):
                overrides = saved.get('decisioni', {})
        except (ValueError, OSError):
            pass
    piano = piano_di_prima
    if piano is None and riusa and cache.is_file():
        try:
            cached = json.loads(cache.read_text(encoding='utf-8'))
            if all(cached.get(k) == v for k, v in identity.items()):
                piano = cached
        except (ValueError, OSError):
            pass
    if piano is not None:
        piano = copy.deepcopy(piano)
        if piano_di_prima is None:
            piano['decisioni'].update(overrides)
        yield dict(passo='riuso', testo='Riuso le decisioni verificate per questo modulo e questa anagrafica.')
        event = esegui(pdf, m, piano, fascicolo, work, togli,
                       origine='piano_utente' if piano_di_prima is not None else 'cache')
        if piano_di_prima is not None:
            decisions = event['verdetto']['piano']['decisioni']
            salva_json(override_file, dict(identity, decisioni={a:d for a,d in decisions.items()
                                                              if d.get('origine') == 'utente'}))
            if (not event['verdetto']['scritture_escluse'] and not event['verdetto']['non_segnalate']
                    and not any(d.get('stato') == 'dubbio' for d in decisions.values())
                    and _senza_guasti(event['verdetto']['piano'])):
                salva_json(cache, event['verdetto']['piano'])
            else:
                cache.unlink(missing_ok=True)
        yield event
        return
    if not agente.disponibile():
        raise agente.ModelloAssente('Il servizio di lettura non e configurato.')
    if not pertinenza_confermata:
        yield dict(passo='pertinenza', testo='Controllo che il modulo riguardi questa impresa.')
        judgment = agente.pertinenza(agente.testo_prima_pagina(pdf), fascicolo,
                                     agente.immagini(pdf, pagine={0}))
        if judgment.get('pertinente') is not True:
            yield dict(passo='domanda_bloccante', domanda=judgment.get('domanda') or judgment.get('motivo'),
                       testo='Conferma la pertinenza del modulo prima di compilare.')
            return
    yield dict(passo='valori', testo='Associo i dati ai campi, distinguendo soggetti e sezioni.')
    images = {i+1: image for i, image in enumerate(agente.immagini(pdf))}
    decisions, guasti, dettagli_guasti = {}, [], []
    seconda = agente.config_seconda_lettura()
    def decide(page, prefisso='lettura'):
        fields = [dict(posto=n, **{k: a.get(k) for k in ('etichetta', 'tipo', 'rect', 'contesto')})
                  for n, aid in page['indirizzi'].items() for a in m['ancore'] if a['id'] == aid]
        for f in fields:
            a = next(a for a in m['ancore'] if a['id']==page['indirizzi'][f['posto']])
            f['parametri'] = a.get('parametri',{})
        for attempt in range(2):
            diagnostica = dict(pagina=page['pagina'], tentativo=attempt+1)
            try:
                return agente.decidi_campi(page['testo'], page['indirizzi'], fields,
                                           catalogo, images.get(page['pagina']),
                                           diagnostica=diagnostica)
            except (agente.RispostaModelloInvalida, RequestException) as exc:
                status = getattr(getattr(exc, 'response', None), 'status_code', None)
                diagnostica['errore'] = dict(tipo=type(exc).__name__, stato_http=status)
                if attempt or status in (400, 401, 402, 403, 404):
                    raise
            except Exception as exc:
                diagnostica['errore'] = dict(tipo=type(exc).__name__)
                raise
            finally:
                salva_json(work/f'{prefisso}_pagina_{page["pagina"]}_tentativo_{attempt+1}.json', diagnostica)
    def decide_secondo(page):
        with agente.usando(seconda):
            return decide(page, 'seconda_lettura')
    seconde, guasti_secondi = {}, []
    with ThreadPoolExecutor(max_workers=6 if seconda else 3) as pool:
        # Il modello in uso deve seguire il lavoro nei thread: un contesto per pagina.
        jobs = [(p, pool.submit(contextvars.copy_context().run, decide, p)) for p in m['rese']]
        # La seconda lettura corre insieme alla prima: non allunga l'attesa.
        jobs_secondi = [(p, pool.submit(contextvars.copy_context().run, decide_secondo, p))
                        for p in m['rese']] if seconda else []
        for page, job in jobs_secondi:
            try:
                seconde.update(job.result())
            except Exception as exc:  # noqa: BLE001 - la seconda lettura non ferma mai la prima
                guasti_secondi.append(dict(pagina=page['pagina'], errore=type(exc).__name__))
        for page, job in jobs:
            try:
                decisions.update(job.result())
            except (agente.RispostaModelloInvalida, RequestException) as exc:
                guasti.append(page['pagina'])
                dettagli_guasti.append(dict(pagina=page['pagina'], errore=type(exc).__name__,
                    stato_http=getattr(getattr(exc, 'response', None), 'status_code', None)))
                decisions.update({aid: dict(stato='dubbio', campo='', soggetto='',
                    motivo='Lettura del servizio non disponibile: da verificare') for aid in page['indirizzi'].values()})
    proposte = copy.deepcopy(decisions)
    letture_originali = {p.name:json.loads(p.read_text(encoding='utf-8'))
                        for p in work.glob('lettura_pagina_*_tentativo_*.json')}
    salva_json(work/'proposte_iniziali.json', proposte)
    doppia = None
    if seconda:
        salva_json(work/'proposte_seconda_lettura.json', seconde)
        doppia = confronta_letture(m, decisions, seconde, catalogo,
                                   set(guasti) | {g['pagina'] for g in guasti_secondi})
        doppia.update(modello=seconda[2], guasti=guasti_secondi)
        salva_json(work/'doppia_lettura.json', doppia)
    decisions.update(overrides)
    choices = {a: d['campo'] for a, d in decisions.items() if d.get('stato') == 'assegna'}
    if guasti and not choices:
        salva_json(work/'errori_servizio.json', dettagli_guasti)
        traccia = traccia_pdf.costruisci(m, dict(diagnostica=dict(proposte=proposte,
                                        letture_originali=letture_originali)), decisions)
        salva_json(work/'traccia.json', traccia)
        codes = {g['stato_http'] for g in dettagli_guasti}
        message = ('Credito del servizio AI insufficiente: avvisa chi gestisce il servizio prima di riprovare.'
                   if 402 in codes else
                   'Il servizio AI non autorizza la richiesta: occorre verificare la credenziale configurata.'
                   if codes & {401, 403} else
                   'Il servizio di lettura non ha completato la richiesta. Riprova piu tardi.')
        yield dict(passo='rifiuto', testo=message+' Nessun dato e stato scritto.',
                   artefatto=str(work), traccia=str(work/'traccia.json'),
                   guasti_lettura=guasti, dettaglio_guasti_lettura=dettagli_guasti)
        return
    yield dict(passo='correzione', testo='Rileggo le associazioni prima di scrivere i dati.')
    errors, warnings, review_details = [], [], {}
    review = {a:c for a,c in choices.items() if decisions[a].get('origine') != 'utente'}
    rejected = agente.rileggi_documento(m['rese'], review, Anagrafe({'profilo':catalogo}), images,
                                       errori=errors, piano=decisions, avvisi=warnings,
                                       mappa=m, diagnostica=review_details)
    salva_json(work/'rilettura.json', dict(assegnazioni_esaminate=review, escluse=rejected,
                                        errori=errors,avvisi=warnings,pagine=review_details))
    for aid, reason in rejected.items():
        decisions[aid].update(stato='dubbio', motivo=reason)
    # Doubts, choices, role risks and practice bindings become answerable questions.
    revisione_pdf.richiedi_conferme(m, decisions, contesto, warnings)
    piano = dict(identity, decisioni=decisions,
                 diagnostica=dict(proposte=proposte, rilettura=rejected, avvisi=warnings,
                                  letture_originali=letture_originali,
                                  guasti_rilettura=errors, pagine_rilettura=review_details))
    if doppia is not None:
        piano['diagnostica']['doppia_lettura'] = doppia
    yield dict(passo='scrittura', testo='Scrivo soltanto i dati con associazioni verificate.')
    event = esegui(pdf, m, piano, fascicolo, work, togli, origine='nuova_lettura')
    if event['verdetto']['scritture_escluse']:
        yield dict(passo='correzione', testo='Correggo una volta i soli campi con scrittura fallita, conservando quelli riusciti.')
        event = _ripara_scritture(pdf, m, piano, event, fascicolo, catalogo, images, cartella_lavoro)
        piano = event['verdetto']['piano']
        decisions = piano['decisioni']
    if os.environ.get('QUADRA_PDF_REVISIONE', '').strip().lower() in ('1', 'si', 'sì', 'true'):
        yield dict(passo='correzione', testo='Riguardo le pagine compilate e correggo quello che non va.')
        event = _revisione_visiva(pdf, m, event, fascicolo, catalogo, cartella_lavoro)
        piano = event['verdetto']['piano']
        decisions = piano['decisioni']
    # Cache only a completely processed decision/review, never a failed attempt.
    if (not guasti and not errors and event['verdetto']['verificate']
            and not any(d.get('stato') == 'dubbio' for d in decisions.values())
            and _senza_guasti(piano)
            and not event['verdetto']['non_segnalate'] and not event['verdetto']['scritture_escluse']):
        salva_json(cache, piano)
    event['verdetto']['guasti_lettura'] = guasti
    event['verdetto']['guasti_rilettura'] = errors
    event['verdetto']['dettaglio_guasti_lettura'] = dettagli_guasti
    salva_json(Path(event['artefatto'])/'verdetto.json', event['verdetto'])
    yield event
