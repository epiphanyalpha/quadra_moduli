"""General data provenance and layout families; synthetic sources only."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from motore import agente, geometria, mappa, piano_pdf, lavori
from motore.valori import risolvi, ProiezioneInvalida
from motore.anagrafe import Anagrafe


class CoperturaPDF(unittest.TestCase):
    def test_exact_parts_and_composition_with_source_provenance(self):
        p={'strada':'Via Esempio','numero':'12/B','persone':'Ada Verdi - direttrice; Leo Blu - socio'}
        d=dict(parti=[{'campo':'strada'},{'campo':'numero'}])
        self.assertEqual(risolvi(d,p),'Via Esempio 12/B')
        self.assertEqual(risolvi(dict(parti=[dict(campo='persone',testo='Leo Blu')]),p),'Leo Blu')
        self.assertEqual(risolvi(dict(parti=[dict(campo='persone',testo='socio')]),p),'socio')

    def test_unproven_or_arbitrary_expressions_are_rejected(self):
        p={'fonte':'Ada Verdi - 10/02/1980'}
        for d in (dict(parti=[dict(campo='fonte',testo='Ada Bianchi')]),
                  dict(parti=[dict(campo='ignota')]),dict(parti=[]),
                  dict(parti=[dict(campo=['fonte'])]),
                  dict(parti=[dict(campo='fonte',codice='eval(1)')]),
                  dict(parti=[dict(campo='fonte')],separatore=' testo aggiunto ')):
            with self.subTest(d=d),self.assertRaises(ProiezioneInvalida):risolvi(d,p)

    def test_first_reader_accepts_grounded_parts_and_rejects_invention(self):
        raw=[dict(posto=i,campo='',stato='assegna',soggetto='Persona',motivo='Fonte',
                  parti=[dict(campo='testo',testo=t)]) for i,t in enumerate(('Ada','Gianni'),1)]
        with patch.object(agente,'_chiedi',return_value=json.dumps(raw)):
            d=agente.decidi_campi('',{'1':'a','2':'b'},[],{'testo':'Ada Verdi'})
        self.assertEqual(d['a']['stato'],'assegna')
        self.assertEqual(d['b']['stato'],'dubbio')

    def test_open_tables_with_one_divider_and_repeated_labels(self):
        for scale in (.6,1,1.6):
            for dx,dy in ((0,0),(37,61)):
                with self.subTest(scale=scale,offset=(dx,dy)),fitz.open() as d:
                    p=d.new_page()
                    xs=[dx+scale*x for x in (30,160,310)]
                    ys=[dy+scale*y for y in (40,70,100,130)]
                    p.draw_line((xs[1],ys[0]),(xs[1],ys[-1]))
                    for y in ys[1:-1]:p.draw_line((xs[0],y),(xs[-1],y))
                    # At least three crossbars support outer-span inference.
                    p.draw_line((xs[0],ys[-1]),(xs[-1],ys[-1]))
                    for i,t in enumerate(('Campo Alfa','Campo Beta','Campo Gamma')):
                        p.insert_text((xs[0]+2,ys[i]+scale*18),t,fontsize=scale*9)
                    g=geometria.leggi(p,0)
                    self.assertEqual(len([c for c in g.celle if c.riquadro.x0>=xs[1]-1]),3)

    def test_empty_ruling_does_not_become_a_table(self):
        v=[geometria.Segmento(100,40,130)]
        h=[geometria.Segmento(y,30,310) for y in (40,70,100,130)]
        _,_,inferred=geometria.completa_griglie(v,h,[])
        self.assertFalse(inferred)

    def test_date_mask_is_one_full_width_field(self):
        with tempfile.TemporaryDirectory() as tmp,fitz.open() as d:
            p=d.new_page();p.insert_text((40,90),'Scadenza: __/__/____',fontsize=11)
            path=Path(tmp)/'date.pdf';d.save(path)
            anchors=mappa.costruisci(path)['ancore']
            dates=[a for a in anchors if a['parametri'].get('formato_data')]
            self.assertEqual(len(dates),1)
            self.assertGreater(dates[0]['rect'][2]-dates[0]['rect'][0],40)

    def test_column_headers_propagate_through_empty_rows(self):
        with tempfile.TemporaryDirectory() as tmp,fitz.open() as d:
            p=d.new_page()
            for x in (30,160,290):p.draw_line((x,40),(x,160))
            for y in (40,70,100,130,160):p.draw_line((30,y),(290,y))
            p.insert_text((35,60),'Nome');p.insert_text((165,60),'Cognome')
            path=Path(tmp)/'rows.pdf';d.save(path)
            a=[a for a in mappa.costruisci(path)['ancore'] if a['tipo']=='area']
            self.assertEqual([x['etichetta'] for x in a],['Nome','Cognome']*3)

    def test_review_distinguishes_format_preference_from_contradiction(self):
        page=dict(pagina=1,testo='Codice; Residenza del delegato',indirizzi={'1':'a','2':'b'})
        plan={a:dict(campo='dato',stato='assegna',soggetto='Impresa',motivo='Fonte') for a in 'ab'}
        response=[dict(posto=1,esito='dubbio',tipo='formato',evidenza='Codice',perche='Preferirei un elemento'),
                  dict(posto=2,esito='errore',tipo='soggetto',evidenza='Residenza del delegato',perche='Dato del firmatario')]
        with patch.object(agente,'_chiedi',return_value=json.dumps(response)):
            fatal,warnings=agente._rileggi_piano_pagina(page,plan,{'dato':'A; B'},None)
        self.assertEqual(set(fatal),{'b'})
        self.assertEqual([r['ancora'] for r in warnings],['a'])

    def test_veto_without_page_evidence_is_a_visible_warning(self):
        page=dict(pagina=1,testo='Codice',indirizzi={'1':'a'})
        plan={'a':dict(campo='dato',stato='assegna')}
        response=[dict(posto=1,esito='errore',tipo='significato',evidenza='Non presente',perche='Dubbio')]
        with patch.object(agente,'_chiedi',return_value=json.dumps(response)):
            fatal,warnings=agente._rileggi_piano_pagina(page,plan,{'dato':'A; B'},None)
        self.assertFalse(fatal);self.assertEqual(len(warnings),1)

    def test_review_cannot_assign_another_columns_label_to_a_field(self):
        page=dict(pagina=1,testo='Nome e cognome; Codice fiscale',indirizzi={'1':'a'})
        plan={'a':dict(campo='nome',stato='assegna')}
        raw=[dict(posto=1,esito='errore',tipo='significato',evidenza='Codice fiscale',perche='Qui serve un CF')]
        geom={'a':dict(etichetta='Nome e cognome',rect=[100,100,250,120])}
        with patch.object(agente,'_chiedi',return_value=json.dumps(raw)):
            fatal,warnings=agente._rileggi_piano_pagina(page,plan,{'nome':'Ada Verdi'},None,geom)
        self.assertFalse(fatal);self.assertEqual(len(warnings),1)
        geom['a']['etichetta']='Codice fiscale'
        with patch.object(agente,'_chiedi',return_value=json.dumps(raw)):
            fatal,warnings=agente._rileggi_piano_pagina(page,plan,{'nome':'Ada Verdi'},None,geom)
        self.assertEqual(set(fatal),{'a'});self.assertFalse(warnings)

    def test_composed_plan_writes_values_and_is_bound_to_full_profile(self):
        with tempfile.TemporaryDirectory() as tmp,fitz.open() as d:
            root=Path(tmp);p=d.new_page();p.draw_rect((150,60,380,90));p.insert_text((30,80),'Indirizzo')
            source=root/'source.pdf';d.save(source)
            m=mappa.costruisci(source);aid=m['ancore'][0]['id'];profile={'profilo':{'via':'Via Esempio','civico':'8'}}
            decision=dict(stato='assegna',campo='',parti=[dict(campo='via'),dict(campo='civico')],soggetto='Impresa',motivo='Fonti')
            plan=dict(versione=piano_pdf.VERSIONE,impronta=m['impronta'],mappa=piano_pdf._firma_mappa(m),
                      fascicolo=lavori.impronta_dati(profile),decisioni={aid:decision})
            r=piano_pdf.esegui(source,m,plan,profile,lavori.nuova_cartella(root/'runs'))
            self.assertEqual([v['valore'] for v in r['verdetto']['verificate']],['Via Esempio 8'])
            changed=copy.deepcopy(profile);changed['profilo']['civico']='9'
            with self.assertRaises(ValueError):piano_pdf.esegui(source,m,plan,changed,root)

    def test_overflow_keeps_full_data_and_verifies_the_appendix(self):
        from motore import controllo
        with tempfile.TemporaryDirectory() as tmp,fitz.open() as d:
            root=Path(tmp);p=d.new_page();p.draw_rect((150,60,280,80));p.insert_text((30,75),'Attivita')
            source=root/'source.pdf';d.save(source)
            m=mappa.costruisci(source);aid=m['ancore'][0]['id']
            full='Costruzione e manutenzione; trasporto e recupero materiali. '*30
            profile={'profilo':{'attivita':full}}
            plan=dict(versione=piano_pdf.VERSIONE,impronta=m['impronta'],mappa=piano_pdf._firma_mappa(m),
                fascicolo=lavori.impronta_dati(profile),decisioni={aid:dict(stato='assegna',campo='attivita')})
            out=lavori.nuova_cartella(root/'runs');r=piano_pdf.esegui(source,m,plan,profile,out)
            self.assertEqual(len(r['verdetto']['verificate']),1)
            self.assertEqual(r['verdetto']['allegati'][0]['valore_completo'],full)
            with fitz.open(r['bozza']) as generated:
                self.assertGreater(len(generated),1)
            # A reference alone must fail if the independently checked appendix is missing.
            forged=dict(scritture=[dict(ancora=aid,tipo='area',etichetta='Attivita',
                valore='Vedi allegato 1',scritto=True,valore_completo=full,
                pagina_allegato=100,pagina_allegato_fine=100)])
            check=controllo.controlla(source,r['bozza'],m,forged)
            self.assertTrue(check['non_segnalate'])

    def test_numbered_open_list_has_one_slot_per_row(self):
        with tempfile.TemporaryDirectory() as tmp,fitz.open() as d:
            p=d.new_page();p.draw_line((65,50),(65,150))
            for y in (75,100,125):p.draw_line((40,y),(350,y))
            for i in range(4):p.insert_text((43,67+i*25),str(i+1)+')  ',fontsize=10)
            path=Path(tmp)/'list.pdf';d.save(path)
            a=[a for a in mappa.costruisci(path)['ancore'] if a['tipo']=='area' and a['rect'][0]>60]
            self.assertEqual(len(a),4)


if __name__=='__main__':unittest.main()
