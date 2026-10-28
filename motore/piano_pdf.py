"""PDF compilation as validated data bindings, independent of generated code."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fitz
from requests import RequestException
from . import agente, controllo, mappa as mappe, soggetti
from .anagrafe import Anagrafe
from .lavori import impronta_dati, nuova_cartella, salva_json
from riusare.strumenti_documento import Ancora, PagineDiritte, firmato, scrivi, impronta

VERSIONE = 1


def _firma_mappa(mappa):
    return impronta_dati(mappa['ancore'])


def _scrivi(originale, mappa, valori, cartella):
    rows = []
    with fitz.open(originale) as doc:
        with PagineDiritte(doc) as diritto:
            for raw in mappa['ancore']:
                aid = raw['id']
                if aid not in valori:
                    continue
                a = Ancora.da_dict(raw)
                esito = scrivi(diritto[a.pagina], a, valori[aid])
                rows.append(dict(ancora=aid, tipo=a.tipo, etichetta=a.etichetta,
                                 valore=valori[aid], scritto=bool(esito.ok), motivo=esito.motivo))
        bozza = cartella / 'bozza.pdf'
        doc.save(bozza)
    return bozza, dict(scritture=rows)


def esegui(originale, mappa, piano, fascicolo, cartella, togli=()):
    """Reapply a reviewed plan only to its exact source, profile and map."""
    if (piano.get('versione') != VERSIONE or piano.get('impronta') != impronta(originale)
            or piano.get('fascicolo') != impronta_dati(fascicolo)
            or piano.get('mappa') != _firma_mappa(mappa)):
        raise ValueError('Il modulo o il fascicolo sono cambiati: occorre una nuova verifica.')
    decisions = copy.deepcopy(piano['decisioni'])
    profilo = fascicolo.get('profilo', {})
    esclusi = set(togli)
    valori = {}
    by_id = {a['id']: a for a in mappa['ancore']}
    for aid, d in decisions.items():
        if aid not in by_id:
            raise ValueError('Piano con un campo sconosciuto')
        if aid in esclusi:
            d.update(stato='manuale', motivo='Rimosso dall’utente', origine='utente')
        campo = d.get('campo')
        a = by_id[aid]
        if (d.get('stato') == 'assegna' and a['tipo'] != 'casella'
                and (a['tipo'] != 'widget' or a.get('parametri', {}).get('genere') == 'Text')
                and isinstance(profilo.get(campo), str) and profilo[campo].strip()):
            valori[aid] = profilo[campo]
    note = {'punti_aperti': []}
    for aid, a in by_id.items():
        if aid not in valori:
            d = decisions.get(aid, {})
            campo = d.get('campo', '')
            note['punti_aperti'].append(dict(ancora=aid,
                chiave='profilo.'+campo if campo in profilo and not profilo.get(campo) else '',
                motivo=d.get('motivo') or 'Da verificare manualmente'))
    bozza, writes = _scrivi(originale, mappa, valori, cartella)
    verdict = controllo.controlla(originale, bozza, mappa, writes, note)
    # A failed material check must not leave a known incorrect write in the draft.
    failed = {r['ancora'] for r in verdict['non_segnalate'] + verdict['non_riuscite']}
    if failed:
        for aid in failed:
            valori.pop(aid, None)
            decisions[aid].update(stato='manuale', motivo='Scrittura non verificata: lasciato vuoto')
            note['punti_aperti'].append(dict(ancora=aid, chiave='', motivo=decisions[aid]['motivo']))
        bozza, writes = _scrivi(originale, mappa, valori, cartella)
        verdict = controllo.controlla(originale, bozza, mappa, writes, note)
    verdict['piano'] = dict(piano, decisioni=decisions)
    verdict['decisioni_campi'] = decisions
    verdict['scritture_escluse'] = sorted(failed)
    verdict['soggetti_da_controllare'] = soggetti.avvertimenti(mappa, valori)
    verdict['copertura_completa_certificata'] = False
    salva_json(cartella/'mappa.json', mappa)
    salva_json(cartella/'piano.json', verdict['piano'])
    salva_json(cartella/'verdetto.json', verdict)
    return dict(passo='verdetto', verdetto=verdict, bozza=str(bozza),
                artefatto=str(cartella), avvisi=verdict['soggetti_da_controllare'],
                testo=controllo.racconta(verdict))


def lavora(radice, pdf, fascicolo, cartella_lavoro, riusa=True,
           pertinenza_confermata=False, piano_di_prima=None, togli=()):
    pdf = Path(pdf)
    if firmato(pdf):
        yield dict(passo='rifiuto', testo='Il PDF e gia firmato: usa il modulo originale non firmato.')
        return
    work = nuova_cartella(cartella_lavoro)
    yield dict(passo='misura', testo='Leggo testo, tabelle e spazi del modulo.')
    m = mappe.costruisci(pdf)
    yield dict(passo='mappa', mappa=m, testo=f"{len(m['ancore'])} spazi individuati: verifico il significato di ciascuno.")
    if not m['ancore']:
        yield dict(passo='rifiuto', testo='Non ho individuato spazi utilizzabili. Il modulo non e compilato.')
        return
    identity = dict(versione=VERSIONE, impronta=m['impronta'],
                    fascicolo=impronta_dati(fascicolo), mappa=_firma_mappa(m))
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
        event = esegui(pdf, m, piano, fascicolo, work, togli)
        if piano_di_prima is not None:
            decisions = event['verdetto']['piano']['decisioni']
            salva_json(override_file, dict(identity, decisioni={a:d for a,d in decisions.items()
                                                              if d.get('origine') == 'utente'}))
            if (not event['verdetto']['scritture_escluse'] and not event['verdetto']['non_segnalate']
                    and not any(d.get('stato') == 'dubbio' for d in decisions.values())):
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
    def decide(page):
        fields = [dict(posto=n, **{k: a.get(k) for k in ('etichetta', 'tipo', 'rect', 'contesto')})
                  for n, aid in page['indirizzi'].items() for a in m['ancore'] if a['id'] == aid]
        if fields and all(f['tipo'] == 'casella' for f in fields):
            return {aid: dict(stato='manuale', campo='', soggetto='',
                             motivo='Scelta o dichiarazione da confermare manualmente')
                    for aid in page['indirizzi'].values()}
        for attempt in range(2):
            try:
                return agente.decidi_campi(page['testo'], page['indirizzi'], fields,
                                           fascicolo.get('profilo', {}), images.get(page['pagina']))
            except (agente.RispostaModelloInvalida, RequestException) as exc:
                status = getattr(getattr(exc, 'response', None), 'status_code', None)
                if attempt or status in (400, 401, 403, 404):
                    raise
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [(p, pool.submit(decide, p)) for p in m['rese']]
        for page, job in jobs:
            try:
                decisions.update(job.result())
            except (agente.RispostaModelloInvalida, RequestException) as exc:
                guasti.append(page['pagina'])
                dettagli_guasti.append(dict(pagina=page['pagina'], errore=type(exc).__name__,
                    stato_http=getattr(getattr(exc, 'response', None), 'status_code', None)))
                decisions.update({aid: dict(stato='dubbio', campo='', soggetto='',
                    motivo='Lettura del servizio non disponibile: da verificare') for aid in page['indirizzi'].values()})
    decisions.update(overrides)
    choices = {a: d['campo'] for a, d in decisions.items() if d.get('stato') == 'assegna'}
    if guasti and not choices:
        salva_json(work/'errori_servizio.json', dettagli_guasti)
        codes = {g['stato_http'] for g in dettagli_guasti}
        message = ('Il servizio AI non autorizza la richiesta: occorre verificare la credenziale configurata.'
                   if codes & {401, 403} else
                   'Il servizio di lettura non ha completato la richiesta. Riprova piu tardi.')
        yield dict(passo='rifiuto', testo=message+' Nessun dato e stato scritto.',
                   guasti_lettura=guasti, dettaglio_guasti_lettura=dettagli_guasti)
        return
    yield dict(passo='correzione', testo='Rileggo le associazioni prima di scrivere i dati.')
    errors = []
    review = {a:c for a,c in choices.items() if decisions[a].get('origine') != 'utente'}
    rejected = agente.rileggi_documento(m['rese'], review, Anagrafe(fascicolo), images, errori=errors)
    for aid, reason in rejected.items():
        decisions[aid].update(stato='dubbio', motivo=reason)
    piano = dict(identity, decisioni=decisions)
    yield dict(passo='scrittura', testo='Scrivo soltanto i dati con associazioni verificate.')
    event = esegui(pdf, m, piano, fascicolo, work, togli)
    # Cache only a completely processed decision/review, never a failed attempt.
    if (not guasti and not errors and event['verdetto']['verificate']
            and not any(d.get('stato') == 'dubbio' for d in decisions.values())
            and not event['verdetto']['non_segnalate'] and not event['verdetto']['scritture_escluse']):
        salva_json(cache, piano)
    event['verdetto']['guasti_lettura'] = guasti
    event['verdetto']['guasti_rilettura'] = errors
    event['verdetto']['dettaglio_guasti_lettura'] = dettagli_guasti
    salva_json(work/'verdetto.json', event['verdetto'])
    yield event
