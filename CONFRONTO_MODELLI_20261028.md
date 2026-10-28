# Confronto dei modelli PDF — 28 ottobre 2026

Scelta: Gemini 3.8 Flash via OpenRouter anche per i PDF. Nei due documenti
provati mantiene la copertura attesa e riduce i tempi, con un costo maggiore
autorizzato dall'utente se il confronto risultava favorevole. Il modello dei
Word resta Gemini; il motore di compilazione non cambia.

## Metodo

Stessi due PDF originali e stessa anagrafica, codice del rilascio `38eaf9f`,
quattro processi indipendenti (due documenti per ciascun servizio), due prove
complete per coppia modello/documento: otto compilazioni. Nessun riuso di piani
o correzioni manuali. Inclusi controllo di pertinenza, prima lettura, revisione
AI, scrittura e verifica materiale. Tempi misurati dall'inizio della lavorazione.
Identita dei file e del fascicolo registrate tramite impronte; risposte HTTP,
modelli restituiti, consumi e tempi conservati nelle evidenze private.

Configurazioni operative: DeepSeek diretto, `deepseek-flash`, massimo 393216
token; OpenRouter, `google/gemini-3.8-flash`, massimo 32768 token, come per i
Word. Prompt e codice identici, ragionamento predefinito dei rispettivi servizi.
I limiti diversi rispettano le configurazioni dei modelli: tutte le 72 risposte
terminano con `stop`, nessun troncamento per limite e nessun errore HTTP.

Inventario dei 45 e 61 campi attesi gia esistente prima del confronto. Confronto
dei valori con le bozze precedentemente ispezionate e controllo delle differenze;
il solo numero di scritture non certifica correttezza o completezza universale.

## Risultati

| Documento | Servizio | Campi attesi nelle due prove | Secondi nelle due prove | Media secondi | Costo medio USD |
|---|---|---:|---|---:|---:|
| Istanza | DeepSeek diretto | 45/45, 45/45 | 163,155; 160,457 | 161,806 | 0,03622 |
| Istanza | Gemini / OpenRouter | 45/45, 45/45 | 80,739; 83,618 | 82,179 | 0,10225 |
| Dichiarazioni | DeepSeek diretto | 61/61, 61/61 | 255,453; 242,999 | 249,226 | 0,07326 |
| Dichiarazioni | Gemini / OpenRouter | 61/61, 61/61 | 137,109; 164,383 | 150,746 | 0,20585 |

Gemini riduce i tempi del 49% sull'istanza e del 40% sulle dichiarazioni. Costo
circa 2,8 volte maggiore. I costi Gemini provengono da `usage.cost`; quelli
DeepSeek sono stimati dai token effettivi, distinguendo cache hit/miss, con la
tariffa ufficiale fuori picco applicabile all'ora del test. Non sono preventivi
per ogni documento futuro; la cache del fornitore rimane attiva per entrambi.

Differenze osservate:

- Gemini usa il comune nei campi generici di residenza/sede dove DeepSeek usa
  lo Stato, con il comune ripetuto nella riga dedicata. Dati coerenti con le fonti;
  impaginazione ridondante, non una maggiore copertura. Il modulo non specifica
  esplicitamente Stato in quelle due celle.
- In due residenze societarie Gemini mantiene via/civico e comune, cambiando
  l'ordine e omettendo il CAP, che non e richiesto dall'etichetta. La provincia
  non e esplicita in quelle fonti aggregate e non e riportata da nessuno dei due:
  il conteggio dei campi non va scambiato con una garanzia su ogni componente.
- Un punto finale differisce in un record composto della prima prova Gemini.
- DeepSeek nella prima prova delle dichiarazioni produce una scrittura in piu,
  una categoria documentata in una sezione alternativa della pratica: campo
  fuori inventario e da confermare, non un recupero che porti a 62 campi attesi.
  La seconda prova non la compila. Nessun modello seleziona automaticamente
  caselle dichiarative o firma il documento.

Tutti gli otto PDF renderizzati (48 pagine). Le due prove dell'istanza sono
visivamente identiche per ciascun modello; nelle dichiarazioni cambiano soltanto
la pagina 7 di DeepSeek e la pagina 3 di Gemini, coerentemente con le differenze
sopra. Controllate le pagine compilate e le varianti: nessun nuovo troncamento
o sovrapposizione rilevato. Restano font piccoli nelle righe molto fitte e
l'allegato esplicito per il testo lungo dell'attivita.

## Identita DeepSeek e configurazione scelta

Il catalogo autenticato del servizio restituisce `id=deepseek-flash` con nome
`DeepSeek-V4.1-Flash`, input testo/immagini e ragionamento alto predefinito.
La [documentazione ufficiale](https://api-docs.deepseek.com/quick_start/pricing/)
specifica che questo alias serve **DeepSeek-V4.1-Flash-1017**. Le risposte del
test riportano `deepseek-flash`. Non si sta confrontando una vecchia versione.

La configurazione comune diventa endpoint `https://openrouter.ai/api/v1`,
modello `google/gemini-3.8-flash`, tetto 32768. La credenziale e quella OpenRouter
gia usata dal servizio per i Word, impostata soltanto nelle variabili segrete
di Render. Nessuna chiave, anagrafica o PDF originale pubblicato.

Tariffe e identita verificati sulle fonti ufficiali:
[DeepSeek](https://api-docs.deepseek.com/quick_start/pricing/),
[Gemini su OpenRouter](https://openrouter.ai/google/gemini-3.8-flash),
[catalogo OpenRouter](https://openrouter.ai/api/v1/models).

Evidenze locali private in `esiti/confronto_modelli_20261028/`: risultati delle
otto prove, chiamate con metadati senza segreti, valutazione per campo, PDF e
render. Campione limitato a due moduli: la scelta privilegia la velocita senza
perdere copertura osservata; non dimostra superiorita su ogni famiglia di moduli.
