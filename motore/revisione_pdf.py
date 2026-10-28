"""Review state and typed answers shared by the engine and the UI. No AI calls."""
import copy

from .valori import risolvi, ProiezioneInvalida
from .fonti_pdf import riferimenti


def selezione(ancora):
    return (ancora['tipo'] == 'casella' or
            ancora['tipo'] == 'widget' and ancora.get('parametri', {}).get('genere') == 'CheckBox')


def scrivibile(ancora):
    return ancora['tipo'] != 'widget' or ancora.get('parametri', {}).get('genere') in ('Text', 'CheckBox')


def descrivi(valore):
    return ('Casella selezionata' if valore else 'Casella vuota') if isinstance(valore, bool) else str(valore)


def richiedi_conferme(mappa, decisioni, contesto=None, avvisi=(), ambito=None):
    from . import soggetti
    by_id = {a['id']:a for a in mappa['ancore']}
    attive = {a for a,d in decisioni.items() if d.get('stato')=='assegna'
              and d.get('origine')!='utente' and (ambito is None or a in ambito)}
    motivi = {a['ancora']:a['motivo'] for a in avvisi}
    for alert in soggetti.avvertimenti(mappa, attive):
        for aid in alert['ancore']:
            motivi.setdefault(aid, 'Verifica il soggetto: '+alert['motivo'])
    for aid in attive:
        d = decisioni[aid]
        motivo = motivi.get(aid)
        if not motivo and selezione(by_id[aid]):
            motivo = 'Conferma la scelta proposta: '+d.get('motivo','')
        if not motivo and contesto and any(k.startswith(contesto+'.') for k in riferimenti(d)):
            motivo = 'Dato della pratica: conferma l’associazione a questo campo. '+d.get('motivo','')
        if motivo:
            d.update(stato='da_confermare', motivo=motivo)


def valore(decisione, fonti, ancora):
    if not scrivibile(ancora):
        raise ProiezioneInvalida('Tipo di campo non supportato')
    if 'valore_utente' in decisione:
        if decisione.get('origine') != 'utente':
            raise ProiezioneInvalida('Solo una risposta esplicita puo contenere un valore libero')
        result = decisione['valore_utente']
        if selezione(ancora):
            if not isinstance(result, bool):
                raise ProiezioneInvalida('La scelta richiede si o no')
        elif not isinstance(result, str) or not result.strip():
            raise ProiezioneInvalida('Risposta vuota')
        return result
    result = risolvi(decisione, fonti)
    if selezione(ancora) != isinstance(result, bool):
        raise ProiezioneInvalida('Il tipo del dato non corrisponde al campo')
    return result


def domande(mappa, piano, fonti):
    result = []
    for a in mappa['ancore']:
        d = piano['decisioni'].get(a['id'], {})
        if not scrivibile(a) or d.get('stato') == 'non_campo':
            continue
        if (d.get('origine') == 'utente' and d.get('stato') == 'manuale'
                and not d.get('scrittura_fallita')):
            continue
        if d.get('stato') == 'assegna':
            continue
        proposta = None
        try:
            proposta = valore(d, fonti, a)
        except ProiezioneInvalida:
            pass
        result.append(dict(ancora=a['id'], pagina=a['pagina']+1,
            etichetta=a.get('etichetta') or a.get('contesto') or a['id'],
            motivo=d.get('motivo', ''), soggetto=d.get('soggetto', ''),
            proposta=proposta, fonte=d.get('campo') or d.get('parti') or '',
            selezione=selezione(a), confermabile=proposta is not None and not d.get('scrittura_fallita')))
    return result


def rispondi(piano, mappa, fonti, aid, azione, *, campo=None, testo=None):
    """A response changes only one slot of the already bound plan."""
    a = next((a for a in mappa['ancore'] if a['id'] == aid), None)
    if a is None or not scrivibile(a):
        raise ValueError('Campo non disponibile')
    result = copy.deepcopy(piano)
    d = copy.deepcopy(result['decisioni'].get(aid, {}))
    if azione == 'conferma':
        if d.get('scrittura_fallita'):
            raise ProiezioneInvalida('La scrittura e fallita: occorre correggere il dato o completare a mano')
        valore(d, fonti, a)
        d.update(stato='assegna', origine='utente', motivo='Proposta confermata dall’utente')
    elif azione == 'fonte':
        d = dict(stato='assegna', origine='utente', campo=campo,
                 soggetto='Scelto dall’utente', motivo='Fonte scelta dall’utente')
        valore(d, fonti, a)
    elif azione in ('si', 'no', 'testo'):
        d = dict(stato='assegna', origine='utente', campo='',
                 valore_utente=(azione == 'si') if azione != 'testo' else testo,
                 soggetto='Scelto dall’utente', motivo='Risposta esplicita per questo modulo')
        valore(d, fonti, a)
    elif azione in ('non_applicabile', 'manuale'):
        d = dict(stato='non_campo' if azione == 'non_applicabile' else 'manuale',
                 origine='utente', campo='', soggetto='Scelto dall’utente',
                 motivo='Non applicabile, confermato dall’utente' if azione == 'non_applicabile'
                        else 'Lasciato alla compilazione manuale dall’utente')
    else:
        raise ValueError('Risposta non riconosciuta')
    result['decisioni'][aid] = d
    return result
