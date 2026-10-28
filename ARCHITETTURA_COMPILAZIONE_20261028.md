# Compilazione assistita verificabile — 28 ottobre 2026

## Decisione

Quadra deve diventare un sistema di compilazione assistita con fonti e decisioni
esplicite. Un OCR e un LLM più potenti possono migliorare una fase, ma non
risolvono campi mai individuati, dati non passati al modello, ruoli confusi,
scelte non documentate e scritture materialmente illeggibili.

La precedente riforma aveva introdotto regressioni reali. Questo incremento ne
corregge il percorso funzionale; non certifica la compilazione universale dei PDF.

## Cosa dicono le fonti tecniche

- [FormGym, EACL 2026](https://aclanthology.org/2026.eacl-long.175/) studia proprio
  la compilazione completa di moduli documentali. Individua nella localizzazione
  dei campi un limite importante dei modelli visuali e valuta uno strumento
  dedicato per migliorarla. Non basta valutare OCR o estrazione separatamente.
- [Microsoft Document Intelligence](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/concept/accuracy-confidence?view=doc-intel-4.0.0)
  distingue la confidenza della lettura da quella dell'associazione chiave/valore
  e raccomanda revisione umana nei flussi che lo richiedono. La confidenza del
  riconoscimento non prova che un indirizzo appartenga al soggetto richiesto.
- [Amazon Textract: best practices](https://docs.aws.amazon.com/textract/latest/dg/textract-best-practices.html)
  documenta difficoltà con celle unite e tabelle irregolari e la necessità di
  scegliere soglie e revisione in base all'uso concreto.
- [Amazon Textract: selezioni](https://docs.aws.amazon.com/textract/latest/dg/how-it-works-selectables.html)
  rappresenta separatamente geometria, stato della casella e collegamento al
  campo o alla cella. Rilevare una casella non equivale a decidere se selezionarla.
- La [documentazione AWS della revisione umana](https://docs.aws.amazon.com/sagemaker/latest/dg/a2i-json-humantaskactivationconditions-textract-example.html)
  descrive condizioni per campi mancanti, inferenze dubbie e campionamento dei
  risultati. È un riferimento di progettazione, non una proposta di acquistare
  A2I, che non accetta nuovi clienti.

La scelta architetturale di Quadra è una nostra applicazione di questi principi.
Non abbiamo acquistato servizi OCR nuovi né trasferito documenti a nuovi fornitori.
Non usiamo percentuali di sicurezza auto-dichiarate dal modello come misure calibrate.

## Percorso e responsabilità

1. **Rilevare gli spazi:** testo, widget, linee, celle e posizione sulla pagina.
2. **Scegliere le fonti:** anagrafica stabile più una sola pratica esplicitamente
   scelta. Nessuna attivazione automatica di tutti gli scenari salvati.
3. **Proporre associazioni:** ogni campo ha stato, soggetto dichiarato, fonte,
   eventuali frammenti letterali e motivo. L'AI non fornisce codice da eseguire.
4. **Risolvere le decisioni:** dubbi, rischi di soggetto, scelte e associazioni
   della pratica diventano domande nell'app. Le risposte sono legate a PDF,
   fascicolo completo, mappa e contesto.
5. **Scrivere e controllare:** scrittura deterministica e controllo indipendente
   sul PDF riaperto. Le scritture fallite vengono rimosse dalla bozza.
6. **Correggere solo ciò che fallisce:** un giro AI aggiuntivo, massimo tre pagine,
   soltanto sui campi falliti. Restano immutate le associazioni riuscite. Le
   proposte riparate passano ancora per fonte, rilettura e controllo materiale.

Le modifiche confermate dall'utente si applicano senza nuove chiamate AI. Non
si rigenera tutto per correggere un campo. Gli errori 402 non vengono ritentati.

## Implementato

- Catalogo delle fonti condiviso da prima lettura, rilettura e scrittura:
  mantiene testo, numeri e valori sì/no; include `lavoro_corrente` oppure uno
  scenario scelto. Chiavi qualificate per evitare omonimie.
- Scelta della pratica prima di Compila, con elenco dei dati effettivamente usati.
- «Completiamo il modulo»: ritaglio del campo, soggetto, fonte, proposta;
  conferma singola o in gruppo, scelta di un'altra fonte, risposta esplicita,
  non applicabile, compilazione manuale. Le risposte di pratica non modificano
  l'anagrafica dell'impresa.
- Caselle disegnate e widget CheckBox gestiti con valori booleani. Anche le
  pagine composte soltanto da caselle vengono esaminate. Le scelte richiedono
  una risposta esplicita; firme e widget non supportati non vengono simulati.
- Bordi puntinati ricostruiti da sequenze regolari di piccoli rettangoli. Nessun
  nome di Comune, file o coordinata di un modulo nel rilevatore. I bordi delle
  celle non diventano ulteriori righe da compilare.
- Riparazione limitata dopo un errore materiale e conservazione dell'evidenza
  del primo fallimento. Un guasto della riparazione non diventa una cache valida.
- Testi lunghi su righe e aree: eventuale richiamo esplicito all'allegato integrale
  quando entra e risulta verificabile; nessun troncamento silenzioso.
- Separazione nel rapporto tra scrittura verificata materialmente, decisione in
  attesa, dato assente, campo manuale e spazio non applicabile. Una scrittura
  nota come fallita non può essere sbloccata con una semplice conferma.
  Anche una risposta utente non scrivibile resta nella coda fino a correzione
  oppure esclusione esplicita.

## Collaudo reale circoscritto

110 test automatici superati anche nella copia esatta destinata alla
pubblicazione; inoltre 24 controlli Word e 17 controlli del motore PDF superati.

Cinque PDF, stesso fascicolo di prova reale, Gemini tramite OpenRouter, cache
disabilitata. Costo API misurato: **0,95385825 USD**. Alla fine è stata riapplicata
senza AI la politica deterministica definitiva delle conferme; questa operazione
è registrata separatamente e non viene presentata come una nuova lettura.

| Caso | Scritture verificate | Proposte applicabili con conferma |
|---|---:|---:|
| Istanza originale | 44 | 1 |
| Dichiarazioni originali | 61 | 0 |
| Istanza Difesa | 38 | 1 |
| Domanda Genova | 48 | 7 |
| Occupazione suolo, contesto scelto | 18 | 10 |

Queste colonne non sono percentuali di accuratezza e non contano tutti i campi
ancora aperti. Le proposte non sono già scritte né tutte semanticamente corrette.

Su Genova sono ora presenti e compilati i cinque campi iniziali che mancavano
anche nel vecchio rilevatore. Le alternative della natura giuridica vengono
proposte con un solo sì e cinque no, da confermare. Su occupazione suolo non si
copia più l'impresa in entrambi i ruoli e sono disponibili otto associazioni di
dati della pratica, oltre a due del committente, da verificare.

In questa prova una di queste ultime associazioni usa il Comune dell'immobile
come Comune della sede del committente: **la fonte non prova quella relazione**.
È una proposta da correggere/rifiutare e resta fuori dalla bozza fino a risposta.
Il contesto del fascicolo non certifica inoltre che questa sia una pratica reale
del Comune del modulo usato per il test. Non abbiamo inventato una conferma umana.

Sul caso Difesa resta una scrittura non verificabile materialmente dopo la
correzione; viene rimossa e resta una domanda. Questo incremento non la dichiara
risolta. Gli originali restano invariati. Le bozze sono state renderizzate per
la verifica visiva; ciò non sostituisce un'annotazione semantica completa.

Il rilevatore preesistente di rischi di soggetto resta conservativo: può chiedere
conferma anche per un dato corretto, come la classifica SOA nell'istanza. Questa
è una ragione per passare a soggetti e relazioni espliciti, descritti sotto.

La revisione indipendente con Astra ha trovato e fatto correggere la scomparsa
dalla coda di una risposta utente non scrivibile. Cinque verifiche mirate passate;
nessun finding materiale aperto nel perimetro esaminato. Non è una certificazione
di correttezza semantica dell'intero corpus.

## Lavoro strutturale successivo ancora necessario

- **Soggetti come entità distinte:** impresa, persona, committente, immobile,
  conto e delegato, con ruoli e relazioni espliciti. Il campo libero `soggetto`
  e i nomi delle fonti non costituiscono ancora un'ontologia verificata.
  La conferma riduce l'automazione dove queste relazioni non sono dimostrate.
- **Inventario indipendente della completezza:** confrontare richieste visibili
  e spazi rilevati, anche nelle scansioni. La tabella delle decisioni vede solo
  ciò che il rilevatore ha trovato. Nessuna certificazione del 100%.
- **Famiglie di moduli e correzioni riusabili:** separare struttura del modello
  e valori della pratica, con versioni e controlli della geometria. Oggi il riuso
  è legato all'esatto PDF, fascicolo e mappa, non a ogni modulo somigliante.
- **Corpus annotato:** valutare campi compilabili, soggetto, dato corretto,
  alternative e casi non applicabili; impedire il rilascio su regressioni.
  I conteggi di scritture non sostituiscono questa valutazione.
- **Persistenza del lavoro:** il server gratuito ha ancora disco volatile.
  Anagrafiche e conferme non sopravvivono garantitamente a sospensioni/riavvii.
- **PDF già firmati:** il rifiuto preesistente resta. Serve un flusso esplicito
  di copia di lavoro; non rimuoviamo firme né presentiamo modifiche come firmate.

Obiettivo realistico: automatizzare i dati dimostrati e riusare le decisioni
verificate, facendo rispondere soltanto dove serve. L'autonomia totale su ogni
PDF arbitrario non è un risultato dimostrato, né una promessa di questo rilascio.
