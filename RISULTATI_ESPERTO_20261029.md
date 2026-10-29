# Compilazione "esperta" dei Word — risultati del 29/10/2026

Ramo `claude/compila-come-esperto` (cartella `E:\python\Quadra_Moduli_esperto`),
partito da GitHub `main` 3ee041b, la versione in uso. Non pubblicato.

## Cosa cambia

`motore/compilatore_esperto.py`, acceso da `QUADRA_WORD_MODO=esperto` (gia' nel
`render.yaml` del ramo), modello `anthropic/claude-sonnet-5.5` via OpenRouter.
Segue le prescrizioni della letteratura (FormGym e FormFactory 2025, CRITIC):

- il codice trova e scrive i posti, il modello decide solo il contenuto;
- il modello vede i VALORI dell'anagrafica e puo' comporli ("nata a Imperia il
  ..., c.f. ..."), indicando le voci usate; il codice verifica che ogni parola
  venga da quelle voci e che il formato torni col testo stampato (codice
  fiscale, IBAN con cifra di controllo, CAP, PEC, partita IVA, telefono);
- righe senza spazio segnato ("Banca", "IBAN") compilabili indicando il
  paragrafo, accettato solo se e' una riga-etichetta breve;
- dopo la scrittura il modello rilegge il modulo COMPILATO con le segnalazioni
  dei controlli e propone correzioni: al massimo due giri;
- sezioni per operatori transfrontalieri escluse nel codice;
- memoria per modulo: cio' che chi compila toglie o conferma resta legato
  all'impronta del modulo e la volta dopo vale come indicazione;
- se il servizio non risponde, si torna da soli al percorso di prima.

## Misure (anagrafica finta, una corsa per modulo)

6 moduli di Bianca: esperto 7-31 s a modulo, 25 centesimi in tutto. MOD 4 da
7 a 10 campi (Banca, Filiale, IBAN, delegati al conto); classifica SOA nel
MOD 1; "sottoscritta Carla Ferrante nata a ..." nel MOD 3.

20 moduli di gara, contro il percorso attuale (Gemini):

| | esperto (Sonnet 5.5) | attuale (Gemini) |
|---|---:|---:|
| campi scritti | 430 | 380 |
| tempo mediano a modulo | 35 s | 58 s |
| costo | $2,18 (~11 cent. a modulo) | ~2-5 cent. a modulo |

Differenze rilette una per una. Meglio l'esperto: nome e qualifica del
sottoscritto (l'attuale li salta in 6 moduli), niente "via Via", SOA, ATECO,
certificazioni, numero dipendenti, elenchi soggetti per persona, CCNL col
codice; non scrive l'IBAN dell'impresa dove si chiede il conto della stazione
appaltante e non compila il CCNL nelle dichiarazioni alternative (l'attuale
si'). Peggio o mancante: Prefettura della white list saltata in 4 moduli,
Camera di Commercio in 1, una data a meta' in 1; due compilazioni in sezioni
per transfrontalieri, ora bloccate nel codice.

Test: 116 + 6 nuovi, tutti passati. Il motore di lettura/scrittura Word non
e' toccato.

## Per pubblicare

    cd E:\python\Quadra_Moduli_esperto
    git push https://github.com/epiphanyalpha/quadra_moduli.git claude/compila-come-esperto:main

Render e' gestito dal `render.yaml`: le due variabili nuove si applicano da
sole, la chiave `QUADRA_WORD_CHIAVE` e' gia' impostata. Per tornare indietro
basta mettere `QUADRA_WORD_MODO=classico` su Render. In produzione i dati veri
di Bianca andrebbero ad Anthropic tramite OpenRouter.

## PDF: provato, nessun guadagno misurato, lasciato spento

Aggiunti (spenti per difetto): `QUADRA_PDF_MODELLO` per far decidere un altro
modello sui PDF, e `QUADRA_PDF_REVISIONE=1` per un giro di revisione guardando
le pagine GIA' COMPILATE (max 6 pagine), con le correzioni che ripassano dagli
stessi controlli. Misurato su 5 PDF (istanza e dichiarazioni di gara,
cessazione, istanza Provincia di Savona, sospensione), anagrafica finta:

| PDF | Sonnet + revisione | Gemini (attuale) |
|---|---:|---:|
| istanza | 44 | 44 |
| dichiarazioni | 60 | 61 |
| cessazione | 16 | 20 |
| Provincia SV | 15 | 15 |
| sospensione | 15 | 15 |

La revisione ha confermato tutte le decisioni su 16 pagine. Le poche
differenze vanno nei due sensi (Gemini meglio sulla cessazione: telefono,
email, CCIAA "Imperia"; Sonnet evita una data in una riga di casella).
Conclusione: sui PDF il giudizio del modello non e' il collo di bottiglia; lo
sono, secondo letteratura e note di Codex, la mappa dei campi (campi mancanti),
la geometria delle righe fitte e le caselle. Prossimo passo: i PDF che Bianca
ha dovuto correggere, e la prova di un rilevatore di campi dedicato
(CommonForms/FFDNet) se entra nella memoria del piano Render.
Costo della prova PDF: circa $2.

## Pubblicazione Word (29/10, sera)

`claude/compila-come-esperto` 1ac298d spinto su GitHub `main` su richiesta di
Francesco. Render pubblica da solo; i Word ora passano da Sonnet 5.5.

## PDF: doppia lettura (Gemini + Sonnet), misurata

Codice: `QUADRA_PDF_SECONDA_LETTURA=<modello>` (spenta per difetto). Le due
letture corrono in parallelo; si confronta il valore che finirebbe scritto, e
lo stesso dato scritto in un altro modo ("Genova il 20/06/1976" / "Genova,
20/06/1976") non conta come disaccordo. Disaccordo: resta scritta la prima, e
l'app la mostra con l'altra proposta e il bottone "Usa l'altra". Dato trovato
solo dalla seconda: proposta da confermare, mai scritta da sola.

Misura con riferimento vero: il modulo di gara che Bianca ha compilato a mano
(`_Lotto_1_04_Dichiaraz-OE`, 49 campi di testo e 17 caselle), rifatto
dall'app sul modulo vuoto con l'anagrafica finta e confrontato voce per voce.
Le due letture concordano su tutto. 38 campi scritti e 5 proposte, tutti
giusti tranne ATECO (scritto l'elenco intero invece del codice prevalente).
Mancano soprattutto 15 caselle su 17 e i dati che l'anagrafica non ha
(oggetto, Agenzia Entrate, Ispettorato, categorie white list). Sono errori
che i due modelli fanno insieme, quindi la doppia lettura non li vede.

Altri 4 PDF: Desio 13 scritti e 0 segnalazioni, VT_1 17 e 0, Taggia 0 e 0,
Sanluri 46 scritti e 4 proposte in piu' dalla seconda lettura (qualifica del
firmatario tre volte, organismo SOA), probabilmente giuste. Sui 5 PDF di prima:
un errore vero preso (la scadenza SOA nella riga della data di rilascio) su
circa 6 segnalazioni.

Costo: la lettura Sonnet costa da 5 a 10 volte quella Gemini (0,04-0,65 $ a
PDF contro 0,02-0,08 $). Conclusione: funziona come previsto, ma segnala poco
perche' gli errori veri sono comuni ai due modelli. Lasciata spenta.

## PDF firmati dall'ente: ora si compilano

22 moduli dell'archivio su 340, fra cui quelli di gara di Bianca (Lotto 1/2),
portano la firma digitale di chi li ha pubblicati, e l'app li rifiutava come
"gia' firmati". Bianca infatti li ha compilati a mano. Ora si scrive in coda al
file, come fa Acrobat: i byte firmati restano identici (provato su tutti i 22;
sul Lotto 1 vero 38 campi, gli stessi del modulo senza firma). L'app avvisa che
il modulo va poi firmato da chi compila. Commit 02167ef, non ancora pubblicato.
