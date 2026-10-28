"""Explicit, document-bound sources. A stored practice is not automatically active."""
import math


def contesti(fascicolo):
    result = {}
    if isinstance(fascicolo.get('lavoro_corrente'), dict) and fascicolo['lavoro_corrente']:
        result['lavoro_corrente'] = 'Lavoro corrente'
    scenari = fascicolo.get('scenari')
    for key, value in (scenari if isinstance(scenari, dict) else {}).items():
        if isinstance(value, dict) and value and '.' not in key:
            result['scenari.' + key] = 'Scenario: ' + key.replace('_', ' ')
    return result


def scalare(value):
    return (isinstance(value, (str, bool, int, float)) and
            (not isinstance(value, float) or math.isfinite(value)))


def fonti(fascicolo, contesto=None):
    """Keep legacy profile keys, qualify practice keys and preserve scalar types."""
    result = {k:v for k,v in fascicolo.get('profilo', {}).items() if scalare(v)}
    if contesto is None:
        return result
    if contesto not in contesti(fascicolo):
        raise ValueError('Pratica non disponibile nel fascicolo')
    value = fascicolo
    for key in contesto.split('.'):
        value = value[key]

    def flatten(node, path):
        if isinstance(node, dict):
            for key, child in node.items():
                if not isinstance(key, str) or '.' in key:
                    raise ValueError('Nome di fonte non utilizzabile')
                flatten(child, path + '.' + key)
        elif isinstance(node, list):
            for i, child in enumerate(node):
                flatten(child, path + '.' + str(i))
        elif scalare(node):
            if path in result:
                raise ValueError('Fonti con lo stesso identificativo')
            result[path] = node
    flatten(value, contesto)
    return result


def testo(value):
    if isinstance(value, bool):
        raise ValueError('Un valore si/no non e un testo')
    if not scalare(value) or not str(value).strip():
        raise ValueError('Dato assente o vuoto nel fascicolo')
    return str(value)


def riferimenti(decisione):
    return {k for k in [decisione.get('campo'),
            *((p.get('campo') for p in (decisione.get('parti') or []) if isinstance(p,dict))),
            (decisione.get('confronto') or {}).get('campo')] if isinstance(k,str) and k}
