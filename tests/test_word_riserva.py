"""Un modello per i Word con quello di sempre come riserva: nessuna rete."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from motore import agente, lavorazione_word
from word_fixtures import paragraphs

WORD = {'QUADRA_WORD_BASE_URL': 'https://word.example.invalid/v1',
        'QUADRA_WORD_CHIAVE': 'chiave-word', 'QUADRA_WORD_MODELLO': 'modello-word'}
FASCICOLO = {'profilo': {'ragione_sociale': 'Aurora Servizi S.r.l.'}}


class RiservaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        doc = Document(); paragraphs(doc, '_' * 25)
        self.src = self.root / 'm.docx'; doc.save(self.src)
        self.rete = patch.object(agente, '_chiedi', side_effect=AssertionError('nessuna rete nei test'))
        self.rete.start()

    def tearDown(self):
        self.rete.stop()
        self.temp.cleanup()

    def corri(self, abbina, env=None, rileggi=None):
        visti = []

        def spia_abbina(testo, indirizzi, chiavi, **kw):
            visti.append(('abbina', agente._IN_USO.get()))
            return abbina(len(visti), indirizzi)

        def spia_rileggi(rese, scelte, anagrafe, errori=None, **kw):
            visti.append(('rileggi', agente._IN_USO.get()))
            return rileggi(len(visti), errori) if rileggi else {}
        with patch.dict(os.environ, env or {}, clear=False), \
                patch.object(agente, 'abbina_pagina', side_effect=spia_abbina), \
                patch.object(agente, 'rileggi_documento', side_effect=spia_rileggi):
            for k in WORD:
                if not env:
                    os.environ.pop(k, None)
            passi = list(lavorazione_word.lavora(self.root, self.src, FASCICOLO, self.root / 'lavoro',
                                                 pertinenza_confermata=True))
        return passi, visti

    @staticmethod
    def prima(indirizzi):
        return {next(iter(indirizzi.values())): 'ragione_sociale'}

    def test_senza_configurazione_non_cambia_niente(self):
        passi, visti = self.corri(lambda n, ind: self.prima(ind))
        self.assertEqual([c for _, c in visti], [None, None])
        self.assertEqual(len(passi[-1]['verdetto']['verificate']), 1)

    def test_il_word_usa_il_suo_modello(self):
        passi, visti = self.corri(lambda n, ind: self.prima(ind), env=WORD)
        self.assertEqual({c[2] for _, c in visti}, {'modello-word'})
        self.assertEqual(visti[0][1][3], 32768)
        self.assertEqual(len(passi[-1]['verdetto']['verificate']), 1)

    def test_due_risposte_illeggibili_passano_alla_riserva(self):
        def abbina(n, ind):
            if agente._IN_USO.get() is not None:
                raise agente.RispostaModelloInvalida('illeggibile')
            return self.prima(ind)
        passi, visti = self.corri(abbina, env=WORD)
        self.assertEqual([c is None for p, c in visti if p == 'abbina'], [False, False, True])
        self.assertIn('modello di riserva', ' '.join(p['testo'] for p in passi))
        self.assertEqual(len(passi[-1]['verdetto']['verificate']), 1)

    def test_senza_riserva_restano_due_tentativi(self):
        def abbina(n, ind):
            raise agente.RispostaModelloInvalida('illeggibile')
        passi, visti = self.corri(abbina)
        self.assertEqual(len(visti), 2)
        self.assertIn('due volte di fila', passi[-1]['testo'])

    def test_rilettura_fallita_si_rifa_con_la_riserva(self):
        def rileggi(n, errori):
            if agente._IN_USO.get() is not None:
                errori.append({'fase': 'rilettura', 'pagina': 1, 'errore': 'X'})
                return {}
            return {}
        passi, visti = self.corri(lambda n, ind: self.prima(ind), env=WORD, rileggi=rileggi)
        self.assertEqual([c is None for p, c in visti if p == 'rileggi'], [False, True])
        v = passi[-1]['verdetto']
        self.assertFalse(v['guasti'])
        self.assertEqual(len(v['verificate']), 1)

    def test_la_richiesta_va_al_modello_in_uso(self):
        self.rete.stop()
        chiamate = []

        class Risposta:
            def raise_for_status(self): pass
            def json(self): return {'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}]}

        def post(url, headers=None, json=None, timeout=None):
            chiamate.append((url, headers['Authorization'], json['model'], json['max_tokens']))
            return Risposta()
        try:
            with patch('requests.post', side_effect=post), patch.dict(os.environ, WORD):
                with agente.usando(agente.config_word()):
                    agente._chiedi([{'role': 'user', 'content': 'x'}])
        finally:
            self.rete.start()
        self.assertEqual(chiamate, [('https://word.example.invalid/v1/chat/completions',
                                     'Bearer chiave-word', 'modello-word', 32768)])

    def test_la_rilettura_nei_thread_usa_il_modello_in_uso(self):
        visti = []

        def pagina(testo, indirizzi, immagine=None):
            visti.append(agente._IN_USO.get())
            return {}
        rese = [{'pagina': i, 'testo': '«1:testo»', 'indirizzi': {'1': 'a%d' % i}} for i in range(4)]
        with patch.object(agente, 'rileggi_pagina', side_effect=pagina), \
                patch.object(agente, 'con_i_valori', return_value='=[ x ]'):
            with agente.usando(('b', 'c', 'm', 1)):
                agente.rileggi_documento(rese, {'a0': 'k'}, None)
        self.assertEqual(visti, [('b', 'c', 'm', 1)] * 4)


if __name__ == '__main__':
    unittest.main()
