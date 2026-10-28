"""Private, per-field evidence. Observes the pipeline without changing decisions."""
import copy
from collections import Counter


def costruisci(mappa, piano, decisioni, scritture=(), verifica=None, origine='nuova_lettura'):
    storia = piano.get('diagnostica', {})
    proposte = storia.get('proposte', {})
    bocciati = storia.get('rilettura', {})
    avvisi = {a['ancora']:a for a in storia.get('avvisi',[])}
    writes = {s['ancora']: s for s in scritture}
    checks = {}
    for gruppo, esito in (('verificate', 'verificata'), ('non_riuscite', 'scrittura_fallita'),
                          ('non_segnalate', 'verifica_fallita')):
        for r in (verifica or {}).get(gruppo, []):
            checks[r['ancora']] = dict(esito=esito, motivo=r.get('motivo', ''))
    righe = []
    for a in mappa['ancore']:
        aid = a['id']
        proposta = proposte.get(aid)
        d = decisioni.get(aid, {})
        scrittura = writes.get(aid)
        controllo = checks.get(aid)
        umana = d.get('origine') == 'utente'
        if scrittura is not None:
            if not scrittura.get('scritto'):
                fase, esito = 'scrittura', 'scrittura_fallita'
                motivo = scrittura.get('motivo', '')
            elif controllo and controllo['esito'] == 'verificata':
                fase, esito, motivo = 'verifica', 'scritto_verificato', controllo['motivo']
            else:
                fase, esito = 'verifica', 'verifica_fallita'
                motivo = (controllo or {}).get('motivo', 'Scrittura non verificata')
        elif umana and d.get('stato') != 'assegna':
            fase, esito, motivo = 'utente', 'escluso_utente', d.get('motivo', '')
        elif not umana and aid in bocciati:
            fase, esito, motivo = 'rilettura', 'escluso_rilettura', bocciati[aid]
        elif d.get('stato') == 'assegna':
            fase, esito, motivo = 'preparazione', 'dato_non_utilizzabile', 'Dato assente, vuoto o tipo non scrivibile'
        else:
            fase = ('regola' if d.get('origine') == 'regola' else
                    'prima_lettura' if proposta is not None else 'non_documentata')
            esito, motivo = d.get('stato') or 'non_documentato', d.get('motivo', '')
        righe.append(dict(ancora=aid, pagina=a['pagina']+1, etichetta=a.get('etichetta', ''),
                          tipo=a['tipo'], rect=list(a['rect']), proposta_iniziale=copy.deepcopy(proposta),
                          decisione_prima_scrittura=copy.deepcopy(d),
                          rilettura=(dict(esito='esclusa', motivo=bocciati[aid]) if aid in bocciati else
                                     dict(esito='approvata') if proposta and proposta.get('stato') == 'assegna' else None),
                          scrittura=copy.deepcopy(scrittura), verifica=controllo,
                          avviso_rilettura=avvisi.get(aid),
                          fase=fase, esito=esito, motivo=motivo,
                          chiave=d.get('campo', '')))
    return dict(versione=2, origine=origine, ingresso_ai='fonti_con_valori',
                guasti_rilettura=copy.deepcopy(storia.get('guasti_rilettura',[])),
                pagine_rilettura=copy.deepcopy(storia.get('pagine_rilettura',{})),
                proposta_storica=origine != 'nuova_lettura',
                copertura_completa_certificata=False,
                riepilogo=dict(Counter(r['esito'] for r in righe)), campi=righe)
