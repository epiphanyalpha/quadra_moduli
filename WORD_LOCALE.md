# Correzioni Word locali prima dei documenti del cliente

Base: repository ufficiale `epiphanyalpha/quadra_moduli`, commit
`5668e784dbfd51c3ce9fd9c71273fedf2a713fee`. Questa copia e il suo branch
`codex/word-robustezza` sono locali. Nessun deploy o push eseguito.

## Cosa cambia

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

20 test di primo livello superati, con 14 varianti di modulo da quattro campi
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

## Prossima prova indipendente

I Word del cliente non sono stati ricevuti né usati per queste correzioni.
La versione locale viene fissata con un commit prima di riceverli: andranno
provati prima di qualsiasi ulteriore modifica, distinguendo riconoscimento,
abbinamento AI, scrittura e risultato visivo. I casi che falliscono diventeranno
nuove prove, senza dichiarare superato ciò che non è stato verificato.

Il repository remoto di questa copia punta alla clone locale di riferimento,
non al repository ufficiale. La pubblicazione richiede una richiesta esplicita.
