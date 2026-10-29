"""Compatibility and human review invariants; synthetic sources, no paid API."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from streamlit.testing.v1 import AppTest

from motore import agente, fascicoli, fonti_pdf, geometria, lavori, mappa, piano_pdf, revisione_pdf
from motore.valori import risolvi, ProiezioneInvalida

ROOT = Path(__file__).resolve().parents[1]


class PraticaRevisionePDF(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.network = patch.object(agente, '_chiedi', side_effect=AssertionError('Unexpected AI call'))
        self.network.start()
        # Questi controlli riguardano la modalita' che chiede conferma prima di scrivere.
        self.conferme = patch.dict(os.environ, {'QUADRA_PDF_CONFERME': 'chiedi'})
        self.conferme.start()
        self.addCleanup(self.conferme.stop)
        self.profile = dict(profilo=dict(ragione_sociale='Impresa Alfa', nome='Ada Verdi'),
            lavoro_corrente=dict(proprietario='Committente Beta', superficie=18, autorizzato=False),
            scenari=dict(altro=dict(proprietario='Committente Gamma')))

    def tearDown(self):
        self.network.stop()
        self.tmp.cleanup()

    def document(self, checkbox=False):
        path = self.root/'source.pdf'
        with fitz.open() as d:
            p = d.new_page()
            for i, label in enumerate(('Richiedente', 'Esecutore')):
                y = 80+i*45
                p.insert_text((30,y), label)
                p.draw_rect((140,y-15,360,y+10))
            if checkbox:
                p.insert_text((60,180),'Autorizzazione')
                p.draw_rect((35,170,44,179),width=0.4)
            d.save(path)
        return path, mappa.costruisci(path)

    def plan(self, mapping, decisions, context=None):
        return dict(versione=piano_pdf.VERSIONE, impronta=mapping['impronta'],
            fascicolo=lavori.impronta_dati(self.profile), mappa=piano_pdf._firma_mappa(mapping),
            contesto=context, decisioni=decisions)

    def test_catalog_excludes_unselected_practices_and_keeps_typed_sources(self):
        self.assertEqual(fonti_pdf.fonti(self.profile), self.profile['profilo'])
        active = fonti_pdf.fonti(self.profile, 'lavoro_corrente')
        self.assertEqual(active['lavoro_corrente.superficie'], 18)
        self.assertIs(active['lavoro_corrente.autorizzato'], False)
        self.assertNotIn('scenari.altro.proprietario', active)
        alternate = fonti_pdf.fonti(self.profile, 'scenari.altro')
        self.assertNotIn('lavoro_corrente.proprietario', alternate)
        self.assertEqual(alternate['scenari.altro.proprietario'], 'Committente Gamma')
        with self.assertRaises(ValueError): fonti_pdf.fonti(self.profile, 'profilo')
        with self.assertRaises(ValueError): fonti_pdf.fonti(self.profile, 'scenari.assente')

    def test_scalars_and_predicates_are_typed_and_source_backed(self):
        sources = dict(numero=0, vero=True, falso=False, forma='Srl')
        self.assertEqual(risolvi(dict(campo='numero'), sources), '0')
        self.assertIs(risolvi(dict(campo='falso'), sources), False)
        self.assertIs(risolvi(dict(confronto=dict(campo='forma',uguale_a='Srl')), sources), True)
        for d in (dict(confronto=dict(campo='vero',uguale_a=1)),
                  dict(confronto=dict(campo='assente',uguale_a='x')),
                  dict(parti=[dict(campo='vero')]),dict(campo='assente')):
            with self.assertRaises(ProiezioneInvalida): risolvi(d, sources)

    def test_selected_practice_reaches_both_readers_and_writer(self):
        source, mapping = self.document()
        observed = []
        def decide(text, addresses, fields, sources, *args, **kwargs):
            observed.append(sources)
            ids = list(addresses.values())
            return {ids[0]:dict(stato='assegna', campo='lavoro_corrente.proprietario', soggetto='Committente', motivo='Ruolo'),
                    ids[1]:dict(stato='assegna', campo='ragione_sociale', soggetto='Esecutore', motivo='Ruolo')}
        def review(rese, choices, anagrafe, *args, **kwargs):
            self.assertEqual(anagrafe.fascicolo['profilo'], observed[0])
            return {}
        with patch.object(agente,'disponibile',return_value=True), patch.object(agente,'immagini',return_value=[]), \
             patch.object(agente,'decidi_campi',side_effect=decide), patch.object(agente,'rileggi_documento',side_effect=review):
            result = list(piano_pdf.lavora(ROOT,source,self.profile,self.root/'runs',
                contesto='lavoro_corrente',pertinenza_confermata=True))[-1]
        self.assertEqual({s['valore'] for s in result['verdetto']['verificate']}, {'Impresa Alfa'})
        question=result['verdetto']['domande_campi'][0]
        self.assertEqual(question['proposta'],'Committente Beta')
        plan=revisione_pdf.rispondi(result['verdetto']['piano'],mapping,observed[0],question['ancora'],'conferma')
        approved=piano_pdf.esegui(source,mapping,plan,self.profile,lavori.nuova_cartella(self.root/'runs'))
        self.assertEqual({s['valore'] for s in approved['verdetto']['verificate']},{'Committente Beta','Impresa Alfa'})
        self.assertEqual(result['verdetto']['contesto'], 'lavoro_corrente')
        with self.assertRaises(ValueError):
            changed = copy.deepcopy(self.profile)
            changed['lavoro_corrente']['proprietario'] = 'Delta'
            piano_pdf.esegui(source,mapping,result['verdetto']['piano'],changed,self.root)

    def test_checkbox_proposal_requires_real_confirmation_then_reuses_without_ai(self):
        source, mapping = self.document(checkbox=True)
        a = next(a for a in mapping['ancore'] if a['tipo']=='casella')
        plan = self.plan(mapping,{a['id']:dict(stato='assegna',campo='lavoro_corrente.autorizzato',motivo='Dato')},'lavoro_corrente')
        first = piano_pdf.esegui(source,mapping,plan,self.profile,lavori.nuova_cartella(self.root/'runs'))
        v = first['verdetto']
        question = next(d for d in v['domande_campi'] if d['ancora']==a['id'])
        self.assertTrue(question['confermabile'])
        self.assertIs(question['proposta'],False)
        self.assertFalse(v['verificate'])
        corrected = revisione_pdf.rispondi(v['piano'],mapping,fonti_pdf.fonti(self.profile,'lavoro_corrente'),a['id'],'conferma')
        second = list(piano_pdf.lavora(ROOT,source,self.profile,self.root/'runs',piano_di_prima=corrected))[-1]
        self.assertEqual(len(second['verdetto']['verificate']),1)
        self.assertIs(second['verdetto']['verificate'][0]['valore'],False)
        self.assertNotIn(a['id'],[q['ancora'] for q in second['verdetto']['domande_campi']])
        self.assertEqual(second['verdetto']['contesto'],'lavoro_corrente')

    def test_page_with_only_checkboxes_is_read_instead_of_forced_manual(self):
        source, mapping = self.document(checkbox=True)
        a = next(a for a in mapping['ancore'] if a['tipo']=='casella')
        mapping['ancore'] = [a]
        mapping['rese'] = [dict(pagina=1,testo='Autorizzazione «1:casella»',indirizzi={'1':a['id']})]
        decision = {a['id']:dict(stato='assegna',campo='',confronto=dict(campo='nome',uguale_a='Ada Verdi'),soggetto='Impresa',motivo='Fonte')}
        with patch.object(piano_pdf.mappe,'costruisci',return_value=mapping), \
             patch.object(agente,'disponibile',return_value=True),patch.object(agente,'immagini',return_value=[]), \
             patch.object(agente,'decidi_campi',return_value=decision) as reader,patch.object(agente,'rileggi_documento',return_value={}):
            result=list(piano_pdf.lavora(ROOT,source,self.profile,self.root/'runs',pertinenza_confermata=True))[-1]
        self.assertEqual(reader.call_count,1)
        self.assertEqual(result['verdetto']['domande_campi'][0]['proposta'], True)
        question=result['verdetto']['domande_campi'][0]
        # A boolean proposal must expose both its reference and comparison value.
        self.assertEqual(question['fonte'],dict(campo='nome',uguale_a='Ada Verdi'))
        display=revisione_pdf.descrivi_fonte(question['fonte'])
        self.assertIn('nome',display)
        self.assertIn('Ada Verdi',display)
        self.assertNotIn('{',display)

    def test_explicit_answers_do_not_change_profile_or_other_slots(self):
        source, mapping = self.document(checkbox=True)
        a,b = [a for a in mapping['ancore'] if a['tipo']=='area']
        plan = self.plan(mapping,{a['id']:dict(stato='dubbio'),b['id']:dict(stato='assegna',campo='nome')})
        original = copy.deepcopy(self.profile)
        changed = revisione_pdf.rispondi(plan,mapping,fonti_pdf.fonti(self.profile),a['id'],'testo',testo='Dato di questa pratica')
        self.assertEqual(changed['decisioni'][b['id']],plan['decisioni'][b['id']])
        result = piano_pdf.esegui(source,mapping,changed,self.profile,lavori.nuova_cartella(self.root/'runs'))
        self.assertEqual(self.profile,original)
        self.assertEqual({r['valore'] for r in result['verdetto']['verificate']},{'Dato di questa pratica','Ada Verdi'})
        changed['decisioni'][a['id']]['origine']='modello'
        self.assertRaises(ProiezioneInvalida,revisione_pdf.valore,changed['decisioni'][a['id']],fonti_pdf.fonti(self.profile),a)
        self.assertRaises(ValueError,revisione_pdf.rispondi,plan,mapping,{},'inventato','manuale')

    def test_non_applicable_answer_leaves_queue_and_not_missing_data(self):
        source, mapping = self.document()
        ids = [a['id'] for a in mapping['ancore']]
        plan = self.plan(mapping,{a:dict(stato='dubbio') for a in ids})
        for aid in ids:
            plan = revisione_pdf.rispondi(plan,mapping,{},aid,'non_applicabile')
        result = piano_pdf.esegui(source,mapping,plan,self.profile,lavori.nuova_cartella(self.root/'runs'))
        self.assertFalse(result['verdetto']['domande_campi'])
        self.assertFalse(result['verdetto']['punti_aperti'])
        self.assertNotEqual(result['verdetto']['stato'],'completo') # no write is not a completed form

    def test_review_uncertainty_becomes_answerable_not_silently_written(self):
        source, mapping = self.document()
        ids = [a['id'] for a in mapping['ancore']]
        decisions = {a:dict(stato='assegna',campo='nome',soggetto='Richiedente',motivo='Fonte') for a in ids}
        def review(*args,**kwargs):
            kwargs['avvisi'].append(dict(ancora=ids[0],pagina=1,motivo='Conferma il richiedente'))
            return {}
        with patch.object(agente,'disponibile',return_value=True),patch.object(agente,'immagini',return_value=[]), \
             patch.object(agente,'decidi_campi',return_value=decisions),patch.object(agente,'rileggi_documento',side_effect=review):
            result = list(piano_pdf.lavora(ROOT,source,self.profile,self.root/'runs',pertinenza_confermata=True))[-1]
        self.assertEqual(len(result['verdetto']['verificate']),1)
        self.assertEqual(result['verdetto']['domande_campi'][0]['proposta'],'Ada Verdi')

    def test_real_ui_confirmation_updates_pdf_without_ai(self):
        source, mapping = self.document()
        ids = [a['id'] for a in mapping['ancore']]
        plan = self.plan(mapping,{a:dict(stato='da_confermare',campo='nome',motivo='Conferma il richiedente',soggetto='Richiedente') for a in ids})
        first = piano_pdf.esegui(source,mapping,plan,self.profile,lavori.nuova_cartella(self.root/'runs'))
        fascicoli.salva(self.root/'fascicoli'/'sintetico.json',self.profile)
        with patch.dict(os.environ,{'ACCESSO_LIBERO':'1','APP_SCADENZA':'NESSUNA','CLIENTI':'','QUADRA_DATI':str(self.root)}):
            app = AppTest.from_file(str(ROOT/'app.py'),default_timeout=30).run()
            for k in ('bozza','artefatto','verdetto'): app.session_state[k] = first[k]
            app.session_state['modulo'] = str(source)
            app.run()
            self.assertFalse(app.exception)
            next(b for b in app.button if b.label=='Applica la risposta e aggiorna la bozza').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.session_state['verdetto']['verificate']),1)
            self.assertEqual(len(app.session_state['verdetto']['domande_campi']),1)
            with fitz.open(app.session_state['bozza']) as d:
                self.assertIn('Ada Verdi',d[0].get_text())

    def test_dotted_borders_are_reconstructed_across_scales_and_translations(self):
        for scale in (0.6,1,2):
            for dx,dy in ((0,0),(43,57)):
                with self.subTest(scale=scale, translation=(dx,dy)), fitz.open() as d:
                    p = d.new_page()
                    def dotted(x0,y0,x1,y1):
                        n = round(max(abs(x1-x0),abs(y1-y0)))
                        for i in range(n):
                            x = dx+scale*(x0+(x1-x0)*i/n)
                            y = dy+scale*(y0+(y1-y0)*i/n)
                            p.draw_rect((x,y,x+scale*.45,y+scale*.45),color=None,fill=(0,0,0))
                    for x in (30,120,240): dotted(x,50,x,150)
                    for y in (50,75,100,125,150): dotted(30,y,240,y)
                    for i in range(4): p.insert_text((dx+scale*34,dy+scale*(67+i*25)),'Campo '+str(i),fontsize=8*scale)
                    path = self.root/'dotted.pdf';d.save(path)
                    fields = [a for a in mappa.costruisci(path)['ancore'] if a['tipo']=='area']
                    self.assertEqual(len(fields),4, [(a['tipo'],a['etichetta'],a['rect']) for a in mappa.costruisci(path)['ancore']])

    def test_isolated_dots_and_separated_runs_are_not_joined(self):
        dots = [dict(riquadro=fitz.Rect(x,10,x+.5,10.5),pieno=True) for x in (1,3,20,22,40,42)]
        self.assertEqual(geometria._bordi_puntinati(dots),([],[]))

    def test_material_repair_targets_only_failures_and_preserves_history(self):
        source, mapping = self.document()
        self.profile['profilo']['aggregato'] = 'W'*5000+' Ada Verdi'
        ids = [a['id'] for a in mapping['ancore']]
        calls = []
        def decide(text, addresses, *args, **kwargs):
            calls.append(set(addresses.values()))
            if len(calls)==1:
                return {a:dict(stato='assegna',campo='aggregato' if a==ids[0] else 'ragione_sociale',
                    soggetto='Richiedente',motivo='Fonte') for a in addresses.values()}
            # A malicious/out-of-scope suggestion for the successful slot is ignored.
            return {ids[0]:dict(stato='assegna',campo='',parti=[dict(campo='aggregato',testo='Ada Verdi')],
                              soggetto='Richiedente',motivo='Solo il nominativo richiesto'),
                    ids[1]:dict(stato='assegna',campo='nome',soggetto='Richiedente',motivo='Fuori ambito')}
        with patch.object(agente,'disponibile',return_value=True),patch.object(agente,'immagini',return_value=[]), \
             patch.object(agente,'decidi_campi',side_effect=decide),patch.object(agente,'rileggi_documento',return_value={}):
            result = list(piano_pdf.lavora(ROOT,source,self.profile,self.root/'runs',pertinenza_confermata=True))[-1]
        self.assertEqual(calls,[set(ids),{ids[0]}])
        v = result['verdetto']
        self.assertEqual({r['valore'] for r in v['verificate']},{'Ada Verdi','Impresa Alfa'})
        self.assertFalse(v['scritture_escluse'])
        self.assertEqual(v['piano']['decisioni'][ids[1]]['campo'],'ragione_sociale')
        before = v['traccia_campi']['riparazione_scrittura']['prima_scrittura']
        self.assertEqual(next(r for r in before['campi'] if r['ancora']==ids[0])['esito'],'verifica_fallita')

    def test_starting_another_document_clears_unsent_answers(self):
        state = dict(pdf_revisione_testo_a='Vecchia risposta',pdf_revisione_azione_a='testo',
                     pdf_contesto_a='lavoro_corrente',w_campo='Word')
        lavori.azzera_revisione(state)
        self.assertFalse(any(k.startswith('pdf_revisione_') for k in state))
        self.assertEqual(state['pdf_contesto_a'],'lavoro_corrente')
        self.assertEqual(state['w_campo'],'Word')

    def test_checkbox_widget_is_written_and_reopened_after_user_answer(self):
        source = self.root/'widget.pdf'
        with fitz.open() as d:
            p=d.new_page();w=fitz.Widget();w.field_name='scelta';w.field_type=fitz.PDF_WIDGET_TYPE_CHECKBOX
            w.rect=fitz.Rect(50,50,65,65);p.add_widget(w);d.save(source)
        mapping=mappa.costruisci(source)
        aid=mapping['ancore'][0]['id']
        plan=self.plan(mapping,{aid:dict(stato='manuale',campo='',motivo='Scelta')})
        plan=revisione_pdf.rispondi(plan,mapping,{},aid,'si')
        r=piano_pdf.esegui(source,mapping,plan,self.profile,lavori.nuova_cartella(self.root/'runs'))
        self.assertEqual(len(r['verdetto']['verificate']),1)
        with fitz.open(r['bozza']) as d:
            page=d[0];w=next(page.widgets());self.assertEqual(w.field_value,w.on_state())
        plan=revisione_pdf.rispondi(plan,mapping,{},aid,'no')
        r=piano_pdf.esegui(source,mapping,plan,self.profile,lavori.nuova_cartella(self.root/'runs'))
        with fitz.open(r['bozza']) as d:
            page=d[0];self.assertEqual(next(page.widgets()).field_value,'Off')

    def test_repair_credit_failure_is_bounded_and_cannot_be_cached(self):
        from requests import HTTPError, Response
        source,mapping=self.document()
        self.profile['profilo']['lungo']='W'*5000
        ids=[a['id'] for a in mapping['ancore']]
        response=Response();response.status_code=402
        failure=HTTPError('Payment Required',response=response)
        decisions={a:dict(stato='assegna',campo='lungo' if a==ids[0] else 'nome',soggetto='Richiedente',motivo='Fonte') for a in ids}
        with patch.object(agente,'disponibile',return_value=True),patch.object(agente,'immagini',return_value=[]), \
             patch.object(agente,'decidi_campi',side_effect=[decisions,failure]) as reader,patch.object(agente,'rileggi_documento',return_value={}):
            r=list(piano_pdf.lavora(ROOT,source,self.profile,self.root/'runs',pertinenza_confermata=True))[-1]
        self.assertEqual(reader.call_count,2)
        report=r['verdetto']['traccia_campi']['riparazione_scrittura']
        self.assertEqual(report['pagine'][0]['errore']['stato_http'],402)
        self.assertEqual(len(r['verdetto']['verificate']),1)
        self.assertIn(ids[0],[q['ancora'] for q in r['verdetto']['domande_campi']])
        self.assertFalse(next(q for q in r['verdetto']['domande_campi'] if q['ancora']==ids[0])['confermabile'])
        self.assertFalse(list((self.root/'runs'/'piani').glob('*.json')))

    def test_failed_user_answer_remains_visible_until_explicitly_left_manual(self):
        source,mapping=self.document()
        aid=mapping['ancore'][0]['id']
        plan=self.plan(mapping,{aid:dict(stato='manuale',campo='')})
        plan=revisione_pdf.rispondi(plan,mapping,{},aid,'testo',testo='W'*5000)
        first=piano_pdf.esegui(source,mapping,plan,self.profile,lavori.nuova_cartella(self.root/'runs'))
        v=first['verdetto']
        question=next(q for q in v['domande_campi'] if q['ancora']==aid)
        self.assertFalse(question['confermabile'])
        self.assertTrue(v['piano']['decisioni'][aid]['scrittura_fallita'])
        self.assertRaises(ProiezioneInvalida,revisione_pdf.rispondi,v['piano'],mapping,{},aid,'conferma')
        manual=revisione_pdf.rispondi(v['piano'],mapping,{},aid,'manuale')
        second=piano_pdf.esegui(source,mapping,manual,self.profile,lavori.nuova_cartella(self.root/'runs'))
        self.assertNotIn(aid,[q['ancora'] for q in second['verdetto']['domande_campi']])
        excluded=piano_pdf.esegui(source,mapping,v['piano'],self.profile,lavori.nuova_cartella(self.root/'runs'),togli=[aid])
        self.assertNotIn(aid,[q['ancora'] for q in excluded['verdetto']['domande_campi']])


if __name__ == '__main__': unittest.main()
