# -*- coding: utf-8 -*-
"""Il fascicolo come lo vede Bianca: gruppi e nomi in italiano.

Il fascicolo e' fatto di chiavi tecniche - `via_sede_legale`, `soa_numero` -
perche' e' cosi' che il modello le nomina e cosi' che finiscono nel programma.
Ma ottantatre chiavi in fila alfabetica non sono una scheda anagrafica: sono
un elenco in cui non si trova niente.

I gruppi non stanno scritti da nessuna parte, si **contano**. Le chiavi che
condividono un pezzo di nome parlano della stessa cosa: `via_sede_legale`,
`comune_sede_legale` e `cap_sede_legale` sono la sede legale; `soa_numero` e
`soa_scadenza_finale` sono la SOA. Basta guardare quali pezzi ricorrono.

Cosi' non c'e' una lista da tenere aggiornata: si aggiunge un dato al fascicolo
e finisce nel gruppo giusto da solo. Era la condizione posta dal committente -
niente elenchi su misura che poi divergono dai dati.
"""
from __future__ import annotations

# Le sigle che in italiano si scrivono maiuscole. Non e' una lista su misura
# del fascicolo: e' come si scrivono queste parole, e vale per qualunque dato
# si aggiunga domani.
SIGLE = {"soa", "pec", "cap", "cf", "iva", "inps", "inail", "rea", "ccnl",
         "ateco", "nc", "ci", "dl", "rup", "cig", "cup", "durc", "ue"}

# Sotto questo numero di chiavi un gruppo non e' un gruppo: e' una riga sola
# con un titolo sopra, che occupa spazio e non aiuta a cercare.
MINIMO = 2

ALTRI = "Altri dati"


def etichetta(chiave: str) -> str:
    """`via_sede_legale` diventa `Via sede legale`, `soa_numero` `SOA numero`."""
    parole = [p for p in str(chiave).split("_") if p]
    if not parole:
        return str(chiave)
    fuori = []
    for indice, parola in enumerate(parole):
        if parola.lower() in SIGLE:
            fuori.append(parola.upper())
        elif indice == 0:
            fuori.append(parola.capitalize())
        else:
            fuori.append(parola.lower())
    return " ".join(fuori)


def _candidati(chiave: str):
    """I pezzi di nome che questa chiave potrebbe condividere con altre.

    Sia le code (`via_sede_legale` -> `sede_legale`, `legale`) sia le teste
    (`soa_numero` -> `soa`): un dato o appartiene a un soggetto - la sede, la
    residenza - oppure a una pratica - la SOA, la white list. Le due forme
    coprono i due casi senza doverli distinguere prima.
    """
    parole = [p for p in str(chiave).split("_") if p]
    # La chiave intera e' candidata a nominare il gruppo: `sede_legale` e' il
    # nome della sede legale, e senza questo contava una chiave in meno delle
    # sue e perdeva contro il pezzo piu' corto `legale`.
    for quante in range(len(parole), 0, -1):
        yield "_".join(parole[-quante:])          # la coda
        yield "_".join(parole[:quante])           # la testa


def raggruppa(chiavi) -> dict:
    """{titolo del gruppo: [chiavi]}, ordinato, ricavato contando i pezzi."""
    chiavi = list(chiavi)
    quante = {}
    for chiave in chiavi:
        for pezzo in set(_candidati(chiave)):
            quante[pezzo] = quante.get(pezzo, 0) + 1

    scelto = {}
    for chiave in chiavi:
        migliore = None
        for pezzo in _candidati(chiave):
            if quante.get(pezzo, 0) < MINIMO:
                continue
            # Il piu' condiviso; a parita', il piu' lungo, che dice di piu'.
            peso = (quante[pezzo], len(pezzo.split("_")))
            if migliore is None or peso > migliore[0]:
                migliore = (peso, pezzo)
        scelto[chiave] = migliore[1] if migliore else None

    gruppi = {}
    for chiave, pezzo in scelto.items():
        gruppi.setdefault(pezzo, []).append(chiave)

    fuori = {}
    avanzi = []
    for pezzo, dentro in gruppi.items():
        if pezzo is None or len(dentro) < MINIMO:
            avanzi.extend(dentro)
        else:
            fuori[etichetta(pezzo)] = sorted(dentro)
    if avanzi:
        fuori[ALTRI] = sorted(avanzi)

    # i gruppi piu' pieni per primi, gli avanzi sempre in fondo
    return dict(sorted(fuori.items(),
                       key=lambda kv: (kv[0] == ALTRI, -len(kv[1]), kv[0])))


def mancanti(profilo: dict) -> list:
    """Le chiavi senza valore: sono i campi che resteranno vuoti sulla bozza."""
    return sorted(k for k, v in profilo.items()
                  if v is None or not str(v).strip())
