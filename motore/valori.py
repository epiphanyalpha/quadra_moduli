"""Bounded, evidence-backed text projections. No generated code or invented values."""


class ProiezioneInvalida(ValueError):
    pass


def risolvi(decisione, profilo):
    parti = decisione.get('parti')
    if parti is None:
        campo = decisione.get('campo')
        if not isinstance(campo, str):
            raise ProiezioneInvalida('Chiave della fonte non valida')
        valore = profilo.get(campo)
        if not isinstance(valore, str) or not valore.strip():
            raise ProiezioneInvalida('Dato assente o vuoto nel fascicolo')
        return valore
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
        if not isinstance(fonte, str) or not fonte.strip():
            raise ProiezioneInvalida('Fonte assente o vuota')
        testo = parte.get('testo', fonte)
        if not isinstance(testo, str) or not testo.strip() or testo not in fonte:
            raise ProiezioneInvalida('Il frammento non compare esattamente nella fonte')
        risultati.append(testo)
    return sep.join(risultati)
