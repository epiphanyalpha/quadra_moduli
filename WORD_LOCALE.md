# Correzioni Word locali e prima regressione reale

Base: repository ufficiale `epiphanyalpha/quadra_moduli`, commit
`5668e784dbfd51c3ce9fd9c71273fedf2a713fee`. Questa copia e il suo branch
`codex/word-robustezza` sono locali. Nessun deploy o push eseguito.

## Cosa cambia

Aggiornamento successivo autorizzato: anche in A rimosso il questionario
preliminare sulla partecipazione, comprese le checkbox dipendenti. La UI
passa condizioni=None: nessuna esclusione da risposte preselezionate o
vecchio stato sessione. Motore A e revisione/Togli invariati. Il checkpoint
precedente 98f0144, tag word-a-20260922 e relativo bundle restano recuperabili.

- L'API `word.leggi/rendi/scrivi/verifica` resta invariata per l'app.
- Il lettore conserva l'ordine XML di paragrafi e tabelle, incluse tabelle
  annidate, intestazioni/piè di pagina e testo accessibile delle caselle di testo.
- Riconosce campi FORMTEXT, controlli testuali SDT anche con risultati su più run,
  underscore/puntini/trattini, celle vuote e righe con etichetta seguita da due punti.
- Spazi ripetuti e tabulazioni sono candidati presentati al modello: non si
  presume che qualsiasi spazio di impaginazione richieda un dato.
- I controlli protetti, collegati o strutturati non gestibili restano segnalati;
  non vengono convertiti silenziosamente in testo ordinario.
- La lunghezza del segnaposto non rifiuta più un dato correttamente assegnato.
- Disattivata la rimozione generica delle frasi ripetute. Resta solo la
  ricomposizione di un tipo di strada esplicitamente stampato come etichetta
  autonoma, ad esempio `Via ___` con valore `Via Roma`.
- L'audit confronta il testo previsto nella posizione XML, le parti originali
  non autorizzate e gli stati delle caselle; non si limita alla presenza del valore.
- La UI mantiene schede, controlli e disposizione. Cambiano messaggi e colore
  dell'esito Word quando nullo/incompleto, e il titolo del dettaglio dei rifiuti.
- Motore PDF, modello e configurazione delle chiamate AI non modificati.

Gli strati `word_inventory.py` e `word_patch.py` derivano da
`inventario_docx_gara.py` e `scrittura_docx_gara.py` del workspace DeducibilitaAI,
adattati qui senza creare dipendenze verso il workspace esterno.

## Verifiche

Eseguire dalla radice di questa copia:

```powershell
py -B -m unittest discover -s tests -p "test_word*.py" -v
```

22 test di primo livello superati, con 14 varianti di modulo da quattro campi
e 24 controlli storici eseguiti come sottocasi. Include scrittura/rilettura,
conservazione di indirizzi e ragioni sociali, cambio originale, scambio di valori,
alterazione di parti non autorizzate, campi SDT bloccati/vuoti/rich text semplice,
ordine delle tabelle, formattazione degli spazi sottolineati e avvio UI Streamlit.

Le prove storiche sono state recuperate dalla copia locale Quadra_Moduli.
Una aspettativa è stata corretta intenzionalmente: la frase già comparsa altrove
nel documento NON autorizza più a troncare il dato da inserire. Il test non è
stato semplicemente escluso: ora richiede la conservazione del valore completo.

Tutte le chiamate al modello sono simulate o bloccate nella suite. Le prove
dimostrano lettura, scrittura e controlli, non l'accuratezza semantica dell'AI.
Tre bozze sintetiche (spazi sottolineati, tab leader, SDT) sono state convertite
con il percorso di anteprima dell'app e ispezionate: una pagina per documento,
quattro valori visibili, nessun taglio osservato. Questo non certifica il layout
di documenti diversi o lunghi. I test non certificano tutti i vecchi `.doc`.

## Prima prova indipendente e seconda correzione

Questa versione A viene congelata prima della sperimentazione strutturale B.
Limite noto emerso nel confronto con il report Grok: nell'ultima prova il
campo CCNL alternativo e' stato compilato nonostante il codice gia' stampato
corrisponda al fascicolo. L'audit di scrittura non certifica la correttezza
semantica e la rilettura AI non ha segnalato questa scelta. Versione di riserva
funzionante sul difetto delle tre celle, non certificazione senza riserve.

Il checkpoint `da1c787` precede il documento reale. Il primo test utente ha
mostrato tre celle con sola etichetta senza due punti ancora escluse dai punti
scrivibili. Corretto il riconoscimento di celle a riga intera con breve testo
semplice (massimo 100 caratteri, un paragrafo, senza campi/oggetti/unioni
verticali): sono candidati facoltativi, non assegnamenti automatici. Aggiunti
contesto tabella/riga/colonna e regressioni sintetiche senza nomi cliente.
Questa estensione non certifica tutte le celle composite o multiparagrafo.

Una singola elaborazione AI autorizzata il 22 settembre ha scritto e verificato
le tre celle prima omesse, assegnando nome completo e codice fiscale alla
persona e ragione sociale all'impresa. Totale: 8 scritture verificate su 27
candidati strutturali, non 27 campi anagrafici obbligatori. Rilettura senza
rifiuti/guasti. Le 3 pagine dell'anteprima prodotta dall'app sono state ispezionate:
nessun taglio osservato. Non e' una certificazione di completezza delle
dichiarazioni, scelte, firme o qualificazioni; esito applicativo da_verificare.

Tempi misurati della singola corsa: lettura/conversione 4,7 s, pertinenza 3,8 s,
abbinamento 71,8 s, rilettura 54,0 s, scrittura e verifica circa 0,6 s,
anteprima 2,2 s. Totale circa 137 s: nessun miglioramento di velocita dimostrato.
Il generatore registra ora tempi locali per fase senza testo o dati personali
in `esiti/.../diagnostica_word_<id>.json`. Esclude l'attesa della UI fra eventi;
la generazione anteprima e' esterna ed e' stata misurata nel banco reale.

Prossimo incremento strutturale proposto, NON ancora implementato: decisione
esplicita per ogni candidato (dato assegnato, non campo, dato assente, dubbio),
prompt e schema specifici Word, misurazione token/retry e prova comparativa
prima di ridurre la rilettura. Nessun cambio di modello o PDF.
Risultati e documento cliente restano nella cartella ignorata
`esiti/prova_reale_celle_22set`; l'uscita precedente in `esiti/chat_word` e'
conservata. La suite resta interamente offline; la corsa reale e' separata.

Il repository remoto di questa copia punta alla clone locale di riferimento,
non al repository ufficiale. La pubblicazione richiede una richiesta esplicita.
