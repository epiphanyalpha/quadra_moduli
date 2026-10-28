"""Observe causal stages, including failures erased by clean PDF regeneration."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from requests import Timeout
from motore import agente, piano_pdf, traccia_pdf, fascicoli
from streamlit.testing.v1 import AppTest


class TracciaPDF(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root/'source.pdf'
        with fitz.open() as d:
            p = d.new_page()
            for i in range(3):
                y = 80+i*45
                p.insert_text((30,y), 'Campo '+str(i))
                p.draw_rect((140,y-15,330,y+10))
            d.save(self.source)
        self.profile = {'profilo': {'nome':'Alfa', 'lungo':'W'*5000}}

    def tearDown(self):
        self.tmp.cleanup()

    def run_pipeline(self, decide, review=None):
        with patch.object(agente,'disponibile',return_value=True), \
             patch.object(agente,'immagini',return_value=[]), \
             patch.object(agente,'decidi_campi',side_effect=decide), \
             patch.object(agente,'rileggi_documento',return_value=review or {}):
            return list(piano_pdf.lavora(self.root,self.source,self.profile,
                        self.root/'runs',pertinenza_confermata=True))[-1]

    @staticmethod
    def assigned(campo='nome'):
        return dict(stato='assegna', campo=campo, soggetto='Impresa', motivo='Etichetta')

    def test_original_response_survives_validation(self):
        raw=json.dumps([dict(posto=1,**self.assigned('inventata'))])
        diag={}
        with patch.object(agente,'_chiedi',return_value=raw):
            d=agente.decidi_campi('',{'1':'a'},[],{'nome':'Alfa'},diagnostica=diag)
        self.assertEqual(diag['risposta_originale'],raw)
        self.assertEqual(d['a']['stato'],'dubbio')
        self.assertEqual(diag['ingresso']['chiavi'],['nome'])
        self.assertEqual(diag['ingresso']['fonti']['nome'],'Alfa')
        self.assertEqual(diag['ingresso']['dati_anagrafici'],'fonti_con_valori')

    def test_invalid_json_is_retained(self):
        diag={}
        with patch.object(agente,'_chiedi',return_value='not JSON'):
            with self.assertRaises(agente.RispostaModelloInvalida):
                agente.decidi_campi('',{'1':'a'},[],['nome'],diagnostica=diag)
        self.assertEqual(diag['risposta_originale'],'not JSON')

    def test_stage_attribution_and_immutable_proposals(self):
        anchors=[dict(id=x,pagina=0,etichetta=x,tipo='area',rect=[0,0,10,10]) for x in 'abcde']
        proposed={x:self.assigned() for x in 'abcde'}
        proposed['a']=dict(stato='dubbio',campo='',motivo='Ambiguo')
        current=copy.deepcopy(proposed)
        current['b'].update(stato='dubbio',motivo='Persona diversa')
        before=copy.deepcopy(proposed)
        writes=[dict(ancora=x,scritto=x!='c',motivo='Non entra' if x=='c' else '') for x in 'cde']
        checks=dict(verificate=[dict(ancora='e',motivo='OK')],
                    non_riuscite=[dict(ancora='c',motivo='Non entra')],
                    non_segnalate=[dict(ancora='d',motivo='Fuori campo')])
        t=traccia_pdf.costruisci(dict(ancore=anchors),
            dict(diagnostica=dict(proposte=proposed,rilettura={'b':'Persona diversa'})),current,writes,checks)
        self.assertEqual([r['fase'] for r in t['campi']],
                         ['prima_lettura','rilettura','scrittura','verifica','verifica'])
        self.assertEqual(t['campi'][1]['proposta_iniziale']['stato'],'assegna')
        self.assertEqual(proposed,before)

    def test_failed_appendix_evidence_survives_regeneration(self):
        ids=[]
        def decide(text,addresses,*args,**kwargs):
            if not ids:
                ids.extend(addresses.values())
            return {a:self.assigned('lungo' if a==ids[0] else 'nome') for a in addresses.values()}
        result=self.run_pipeline(decide)
        v=result['verdetto'];t=v['traccia_campi']
        failed=next(r for r in t['campi'] if r['ancora']==ids[0])
        self.assertEqual(failed['fase'],'verifica')
        self.assertTrue(failed['motivo'])
        self.assertEqual(failed['proposta_iniziale']['stato'],'assegna')
        self.assertIn(ids[0],v['scritture_escluse'])
        self.assertNotIn(ids[0],[r['ancora'] for r in v['verificate']])
        self.assertEqual(t['riparazione_scrittura']['campi'], [ids[0]])
        self.assertEqual(len(t['riparazione_scrittura']['pagine']), 1)
        original = next(r for r in t['riparazione_scrittura']['prima_scrittura']['campi'] if r['ancora']==ids[0])
        self.assertEqual(original['esito'], 'verifica_fallita')
        folder=Path(result['artefatto'])
        self.assertEqual(json.loads((folder/'traccia.json').read_text(encoding='utf-8')),t)
        self.assertTrue((folder/'verifica_primo_tentativo.json').is_file())

    def test_review_rejection_keeps_initial_assignment(self):
        m=piano_pdf.mappe.costruisci(self.source);aid=m['ancore'][0]['id']
        def decide(text,addresses,*args,**kwargs):
            return {a:self.assigned() for a in addresses.values()}
        r=self.run_pipeline(decide,{aid:'Dato di altra persona'})
        row=next(r for r in r['verdetto']['traccia_campi']['campi'] if r['ancora']==aid)
        self.assertEqual(row['esito'],'escluso_rilettura')
        self.assertEqual(row['proposta_iniziale']['stato'],'assegna')
        self.assertIsNone(row['scrittura'])

    def test_cache_marks_proposals_as_historical(self):
        def decide(text,addresses,*args,**kwargs):
            return {a:self.assigned() for a in addresses.values()}
        first=self.run_pipeline(decide)
        with patch.object(agente,'decidi_campi',side_effect=AssertionError('No AI on reuse')):
            again=list(piano_pdf.lavora(self.root,self.source,self.profile,self.root/'runs'))[-1]
        t=again['verdetto']['traccia_campi']
        self.assertEqual(t['origine'],'cache')
        self.assertTrue(t['proposta_storica'])
        self.assertEqual([r['proposta_iniziale'] for r in t['campi']],
                         [r['proposta_iniziale'] for r in first['verdetto']['traccia_campi']['campi']])

    def test_service_failure_also_has_report(self):
        result=self.run_pipeline(Timeout())
        self.assertEqual(result['passo'],'rifiuto')
        trace=json.loads(Path(result['traccia']).read_text(encoding='utf-8'))
        self.assertEqual(len(trace['campi']),3)
        attempts=list(Path(result['artefatto']).glob('lettura_pagina_*'))
        self.assertEqual(len(attempts),2)
        self.assertEqual(json.loads(attempts[0].read_text(encoding='utf-8'))['errore']['tipo'],'Timeout')

    def test_old_plan_does_not_claim_an_unrecorded_ai_decision(self):
        m=dict(ancore=[dict(id='a',pagina=0,etichetta='Nome',tipo='area',rect=[0,0,10,10])])
        t=traccia_pdf.costruisci(m,{},dict(a=dict(stato='dubbio',motivo='Vecchia decisione')),
                                origine='cache')
        self.assertEqual(t['campi'][0]['fase'],'non_documentata')
        self.assertIsNone(t['campi'][0]['proposta_iniziale'])

    def test_review_failure_preserves_http_status_in_downloadable_trace(self):
        from requests import HTTPError, Response
        from motore.anagrafe import Anagrafe
        response=Response();response.status_code=503
        failure=HTTPError('Service unavailable',response=response)
        page=dict(pagina=1,testo='Nome',indirizzi={'1':'a'})
        errors=[];diagnostics={}
        with patch.object(agente,'_rileggi_piano_pagina',side_effect=failure):
            rejected=agente.rileggi_documento([page],{'a':'nome'},Anagrafe({'profilo':{'nome':'Alfa'}}),
                piano={'a':self.assigned()},errori=errors,diagnostica=diagnostics)
        self.assertIn('a',rejected)
        self.assertEqual(errors[0]['stato_http'],503)
        self.assertEqual(diagnostics[1]['errore']['errore'],'HTTPError')
        m=dict(ancore=[dict(id='a',pagina=0,etichetta='Nome',tipo='area',rect=[0,0,10,10])])
        trace=traccia_pdf.costruisci(m,dict(diagnostica=dict(guasti_rilettura=errors,
                                   pagine_rilettura=diagnostics)),{'a':self.assigned()})
        self.assertEqual(trace['guasti_rilettura'][0]['pagina'],1)
        self.assertEqual(trace['pagine_rilettura'][1]['errore']['stato_http'],503)

    def test_insufficient_credit_does_not_retry_or_blame_missing_data(self):
        from requests import HTTPError, Response
        response=Response();response.status_code=402
        failure=HTTPError('Payment Required',response=response)
        result=self.run_pipeline(failure)
        self.assertEqual(result['passo'],'rifiuto')
        self.assertIn('Credito',result['testo'])
        self.assertEqual(len(list(Path(result['artefatto']).glob('lettura_pagina_*'))),1)
        with agente.usando(('https://provider.invalid/v1','test-secret','test',1000)), \
             patch('requests.post',side_effect=failure) as post,patch('time.sleep') as sleep:
            with self.assertRaises(HTTPError):agente._chiedi([])
        self.assertEqual(post.call_count,1)
        sleep.assert_not_called()

    def test_user_exclusion_does_not_get_attributed_to_review(self):
        m=dict(ancore=[dict(id='a',pagina=0,etichetta='Nome',tipo='area',rect=[0,0,10,10])])
        t=traccia_pdf.costruisci(m,dict(diagnostica=dict(proposte={'a':self.assigned()},rilettura={'a':'Storico'})),
            dict(a=dict(stato='manuale',origine='utente',motivo='Rimosso')),origine='piano_utente')
        self.assertEqual(t['campi'][0]['fase'],'utente')
        self.assertEqual(t['campi'][0]['motivo'],'Rimosso')

    def test_report_is_visible_in_app_without_a_verified_draft(self):
        def decide(text,addresses,*args,**kwargs):
            return {a:self.assigned() for a in addresses.values()}
        result=self.run_pipeline(decide)
        fascicoli.salva(self.root/'fascicoli'/'profile.json',{'profilo':{'ragione_sociale':'Alfa'}})
        with patch.dict(os.environ,{'ACCESSO_LIBERO':'1','APP_SCADENZA':'NESSUNA',
                                     'CLIENTI':'','QUADRA_DATI':str(self.root)}):
            app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
            app.session_state['artefatto']=result['artefatto']
            app.session_state['verdetto']=None
            app.run()
        self.assertFalse(app.exception)
        self.assertIn('Prima lettura',app.dataframe[0].value.columns)
        self.assertIn('Seconda lettura',app.dataframe[0].value.columns)

        trace_path=Path(result['traccia'])
        trace=json.loads(trace_path.read_text(encoding='utf-8'))
        trace['guasti_rilettura']=[dict(pagina=1,errore='HTTPError',stato_http=402)]
        trace_path.write_text(json.dumps(trace),encoding='utf-8')
        with patch.dict(os.environ,{'ACCESSO_LIBERO':'1','APP_SCADENZA':'NESSUNA',
                                     'CLIENTI':'','QUADRA_DATI':str(self.root)}):
            app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any('Compilazione incompleta' in e.value for e in app.error))
        self.assertTrue(any('Credito' in e.value for e in app.error))


if __name__=='__main__':
    unittest.main()
