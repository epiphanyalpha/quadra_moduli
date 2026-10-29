"""La doppia lettura dei PDF: due modelli leggono, il disaccordo si mostra. Nessuna rete."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
import requests
from streamlit.testing.v1 import AppTest

from motore import agente, fascicoli, fonti_pdf, lavori, mappa, piano_pdf, revisione_pdf

ROOT = Path(__file__).resolve().parents[1]
ENV = {'QUADRA_PDF_SECONDA_LETTURA': 'secondo', 'QUADRA_WORD_BASE_URL': 'https://x.invalid/v1',
       'QUADRA_WORD_CHIAVE': 'k', 'QUADRA_WORD_MODELLO': 'primo'}


class DoppiaLettura(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rete = patch.object(agente, '_chiedi', side_effect=AssertionError('Unexpected AI call'))
        self.rete.start()
        self.profilo = dict(profilo=dict(ragione_sociale='Impresa Alfa', nome='Ada Verdi'))
        self.source = self.root/'source.pdf'
        with fitz.open() as d:
            p = d.new_page()
            for i, label in enumerate(('Richiedente', 'Esecutore')):
                y = 80+i*45
                p.insert_text((30, y), label)
                p.draw_rect((140, y-15, 360, y+10))
            d.save(self.source)
        self.ids = [a['id'] for a in mappa.costruisci(self.source)['ancore']]

    def tearDown(self):
        self.rete.stop()
        self.tmp.cleanup()

    def corri(self, prima, seconda, env=ENV):
        chiamate = []

        def decidi(*args, **kwargs):
            config = agente._IN_USO.get()
            chi = config[2] if config else 'primo'
            chiamate.append(chi)
            if chi == 'secondo':
                if isinstance(seconda, Exception):
                    raise seconda
                return seconda
            return prima
        with patch.dict(os.environ, env), patch.object(agente, 'disponibile', return_value=True), \
                patch.object(agente, 'immagini', return_value=[]), \
                patch.object(agente, 'decidi_campi', side_effect=decidi), \
                patch.object(agente, 'rileggi_documento', return_value={}):
            esito = list(piano_pdf.lavora(ROOT, self.source, self.profilo, self.root/'runs',
                                          riusa=False, pertinenza_confermata=True))[-1]
        return esito, chiamate

    def decisione(self, campo):
        return dict(stato='assegna', campo=campo, soggetto='Impresa', motivo='Fonte')

    def test_disaccordo_scritto_e_mostrato_dato_solo_della_seconda_da_confermare(self):
        a, b = self.ids
        prima = {a: self.decisione('nome'), b: dict(stato='dato_assente', campo='', motivo='')}
        seconda = {a: self.decisione('ragione_sociale'), b: self.decisione('nome')}
        esito, chiamate = self.corri(prima, seconda)
        v = esito['verdetto']
        self.assertEqual(sorted(chiamate), ['primo', 'secondo'])
        self.assertEqual([r['valore'] for r in v['verificate']], ['Ada Verdi'])
        self.assertEqual([(r['ancora'], r['scritto'], r['alternativa'], r['sostituibile'])
                          for r in v['letture_discordi']], [(a, 'Ada Verdi', 'Impresa Alfa', True)])
        domanda = next(d for d in v['domande_campi'] if d['ancora'] == b)
        self.assertEqual(domanda['proposta'], 'Ada Verdi')
        self.assertIn('solo la seconda lettura', domanda['motivo'])
        doppia = v['piano']['diagnostica']['doppia_lettura']
        self.assertEqual((doppia['confrontati'], doppia['discordi'], doppia['solo_seconda']), (2, [a], [b]))
        # Scegliere l'altra proposta riscrive senza chiamare nessun modello.
        catalogo = fonti_pdf.fonti(self.profilo, None)
        m = mappa.costruisci(self.source)
        piano = revisione_pdf.rispondi(v['piano'], m, catalogo, a, 'alternativa')
        nuovo = piano_pdf.esegui(self.source, m, piano, self.profilo, lavori.nuova_cartella(self.root/'rifatta'))
        self.assertEqual([r['valore'] for r in nuovo['verdetto']['verificate']], ['Impresa Alfa'])
        self.assertFalse(nuovo['verdetto']['letture_discordi'])

    def test_accordo_non_segnala_niente(self):
        prima = {a: self.decisione('nome') for a in self.ids}
        esito, _ = self.corri(prima, {a: self.decisione('nome') for a in self.ids})
        self.assertFalse(esito['verdetto']['letture_discordi'])
        self.assertEqual(len(esito['verdetto']['verificate']), 2)

    def test_seconda_lettura_guasta_non_cambia_la_prima(self):
        prima = {a: self.decisione('nome') for a in self.ids}
        con_guasto, _ = self.corri(prima, requests.ConnectionError('giu'))
        sola, chiamate = self.corri(prima, None, env={})
        self.assertEqual(chiamate, ['primo'])
        valori = lambda e: [(r['ancora'], r['valore']) for r in e['verdetto']['verificate']]
        self.assertEqual(valori(con_guasto), valori(sola))
        self.assertFalse(con_guasto['verdetto']['letture_discordi'])
        self.assertEqual(con_guasto['verdetto']['piano']['diagnostica']['doppia_lettura']['guasti'][0]['errore'],
                         'ConnectionError')

    def test_app_mostra_il_disaccordo_e_usa_l_altra_proposta(self):
        a, b = self.ids
        esito, _ = self.corri({a: self.decisione('nome'), b: self.decisione('nome')},
                              {a: self.decisione('ragione_sociale'), b: self.decisione('nome')})
        fascicoli.salva(self.root/'fascicoli'/'sintetico.json', self.profilo)
        with patch.dict(os.environ, {'ACCESSO_LIBERO': '1', 'APP_SCADENZA': 'NESSUNA', 'CLIENTI': '',
                                     'QUADRA_DATI': str(self.root)}):
            app = AppTest.from_file(str(ROOT/'app.py'), default_timeout=30).run()
            for k in ('bozza', 'artefatto', 'verdetto'):
                app.session_state[k] = esito[k]
            app.session_state['modulo'] = str(self.source)
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(any('le due letture del modulo non concordano' in w.value for w in app.warning))
            next(x for x in app.button if x.label == 'Usa l’altra').click().run()
            self.assertFalse(app.exception)
            scritti = sorted(r['valore'] for r in app.session_state['verdetto']['verificate'])
            self.assertEqual(scritti, ['Ada Verdi', 'Impresa Alfa'])


if __name__ == '__main__':
    unittest.main()
