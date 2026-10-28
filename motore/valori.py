"""Bounded, evidence-backed text projections. No generated code or invented values."""


class ProiezioneInvalida(ValueError):
    pass


def risolvi(decisione, profilo):
    from .fonti_pdf import testo as testo_fonte
    confronto = decisione.get('confronto')
    if confronto is not None:
        if (not isinstance(confronto, dict) or set(confronto) != {'campo', 'uguale_a'}
                or not isinstance(confronto['campo'], str)
                or confronto['campo'] not in profilo):
            raise ProiezioneInvalida('Confronto privo di fonte')
        fonte, atteso = profilo[confronto['campo']], confronto['uguale_a']
        if type(fonte) is not type(atteso) or not isinstance(fonte, (str, bool, int, float)):
            raise ProiezioneInvalida('Confronto di tipi diversi')
        return fonte == atteso
    parti = decisione.get('parti')
    if parti is None:
        campo = decisione.get('campo')
        if not isinstance(campo, str):
            raise ProiezioneInvalida('Chiave della fonte non valida')
        valore = profilo.get(campo)
        if isinstance(valore, bool):
            return valore
        try:
            return testo_fonte(valore)
        except ValueError as exc:
            raise ProiezioneInvalida(str(exc)) from exc
    if not isinstance(parti, list) or not 1 <= len(parti) <= 12:
        raise ProiezioneInvalida('Occorrono da una a dodici fonti')
    sep = decisione.get('separatore', ' ')
    if sep not in (' ', ', ', '; ', '\n', '', ' - '):
        raise ProiezioneInvalida('Separatore non ammesso')
    risultati = []
    for parte in parti:
        if not isinstance(parte, dict) or set(parte)-{'campo','testo'}:
            raise ProiezioneInvalida('Fonte non valida')
        if not isinstance(parte.get('campo'), str):
            raise ProiezioneInvalida('Chiave della fonte non valida')
        fonte = profilo.get(parte.get('campo'))
        try:
            fonte = testo_fonte(fonte)
        except ValueError as exc:
            raise ProiezioneInvalida(str(exc)) from exc
        testo = parte.get('testo', fonte)
        if not isinstance(testo, str) or not testo.strip() or testo not in fonte:
            raise ProiezioneInvalida('Il frammento non compare esattamente nella fonte')
        risultati.append(testo)
    return sep.join(risultati)
