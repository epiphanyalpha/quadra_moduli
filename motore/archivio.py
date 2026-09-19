# -*- coding: utf-8 -*-
"""L'archivio del corpus: moduli, campi trovati, esiti delle scritture.

Con due moduli le domande si rispondono a occhio. Con cento no, e rispondere a
occhio e' come si finisce a ritoccare una regola finche' un campione viene bene.

Qui dentro ogni campo di ogni modulo diventa una riga. Da quel momento
'i trattini corti sono un principio o sono rumore?' non e' piu' un'opinione:

    SELECT quanti, COUNT(*) FROM ancore WHERE tipo='riempimento' GROUP BY quanti

L'archivio non decide niente e non sa niente di enti o clienti: registra.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
ARCHIVIO = RADICE / "corpus" / "corpus.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS moduli (
    id           INTEGER PRIMARY KEY,
    file         TEXT UNIQUE NOT NULL,
    url          TEXT,
    sha256       TEXT UNIQUE NOT NULL,
    byte         INTEGER,
    pagine       INTEGER,
    caratteri    INTEGER,
    scansione    INTEGER DEFAULT 0,
    scaricato_il TEXT
);

CREATE TABLE IF NOT EXISTS misure (
    id            INTEGER PRIMARY KEY,
    modulo        INTEGER NOT NULL REFERENCES moduli(id) ON DELETE CASCADE,
    misurato_il   TEXT,
    campi         INTEGER,
    tentate       INTEGER,
    verificate    INTEGER,
    non_riuscite  INTEGER,
    non_segnalate INTEGER,
    secondi       REAL,
    guaio         TEXT
);

CREATE TABLE IF NOT EXISTS ancore (
    id         INTEGER PRIMARY KEY,
    modulo     INTEGER NOT NULL REFERENCES moduli(id) ON DELETE CASCADE,
    ancora     TEXT,
    tipo       TEXT,
    pagina     INTEGER,
    larghezza  REAL,
    altezza    REAL,
    corpo      REAL,
    quanti     INTEGER,      -- celle di una fila, o riempitivi di una corsa
    riempitivo TEXT,
    lato       REAL,         -- il quadrato misurato di una casella
    etichetta  TEXT
);

CREATE TABLE IF NOT EXISTS esiti (
    id      INTEGER PRIMARY KEY,
    modulo  INTEGER NOT NULL REFERENCES moduli(id) ON DELETE CASCADE,
    ancora  TEXT,
    tipo    TEXT,
    stato   TEXT,            -- verificata | non_riuscita | non_segnalata
    motivo  TEXT
);

CREATE INDEX IF NOT EXISTS i_ancore_tipo ON ancore(tipo);
CREATE INDEX IF NOT EXISTS i_esiti_stato ON esiti(stato);
"""


def apri(percorso=None) -> sqlite3.Connection:
    percorso = Path(percorso or ARCHIVIO)
    percorso.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(percorso, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Raccolta e misura girano insieme: senza queste due righe il secondo che
    # scrive trova il database occupato e muore a meta' lavoro.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 20000")
    conn.executescript(SCHEMA)
    return conn


def registra_modulo(conn, voce: dict) -> int:
    """Inserisce un modulo scaricato. Se c'e' gia' (stessa impronta) lo ritrova."""
    trovato = conn.execute("SELECT id FROM moduli WHERE sha256 = ?",
                           (voce["sha256"],)).fetchone()
    if trovato:
        return trovato["id"]
    cur = conn.execute(
        "INSERT INTO moduli (file, url, sha256, byte, pagine, caratteri,"
        " scansione, scaricato_il) VALUES (?,?,?,?,?,?,?,?)",
        (voce["file"], voce.get("url"), voce["sha256"], voce.get("byte"),
         voce.get("pagine"), voce.get("caratteri"),
         1 if voce.get("scansione") else 0,
         voce.get("scaricato_il") or time.strftime("%Y-%m-%d")))
    conn.commit()
    return cur.lastrowid


def id_di(conn, sha256: str):
    riga = conn.execute("SELECT id FROM moduli WHERE sha256 = ?", (sha256,)).fetchone()
    return riga["id"] if riga else None


def registra_ancore(conn, modulo: int, mappa: dict, secondi: float = None):
    """Solo la struttura: quali campi ha il modulo, senza scrivere niente.

    Per capire com'e' fatto un modulo non serve compilarlo: serve sapere quali
    campi chiede. E' molto piu' veloce, e su un corpus grande e' la differenza
    fra una domanda che si puo' fare e una che non si fa."""
    conn.execute("DELETE FROM ancore WHERE modulo = ?", (modulo,))
    conn.execute("DELETE FROM misure WHERE modulo = ?", (modulo,))
    conn.execute("INSERT INTO misure (modulo, misurato_il, campi, secondi)"
                 " VALUES (?,?,?,?)",
                 (modulo, time.strftime("%Y-%m-%d"), len(mappa["ancore"]),
                  round(secondi, 2) if secondi else None))
    _inserisci_ancore(conn, modulo, mappa)
    conn.commit()


def _inserisci_ancore(conn, modulo: int, mappa: dict):
    for a in mappa["ancore"]:
        p = a.get("parametri", {})
        conn.execute(
            "INSERT INTO ancore (modulo, ancora, tipo, pagina, larghezza, altezza,"
            " corpo, quanti, riempitivo, lato, etichetta) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (modulo, a["id"], a["tipo"], a["pagina"] + 1,
             round(a["rect"][2] - a["rect"][0], 2),
             round(a["rect"][3] - a["rect"][1], 2),
             p.get("dimensione"), p.get("quante") or p.get("quanti"),
             p.get("riempitivo"), p.get("lato"), (a.get("etichetta") or "")[:120]))


def registra_misura(conn, modulo: int, mappa: dict, verdetto: dict,
                    secondi: float, guaio: str = None):
    """Sostituisce la misura precedente: di un modulo interessa l'ultima."""
    conn.execute("DELETE FROM misure WHERE modulo = ?", (modulo,))
    conn.execute("DELETE FROM ancore WHERE modulo = ?", (modulo,))
    conn.execute("DELETE FROM esiti WHERE modulo = ?", (modulo,))
    if guaio is not None:
        conn.execute("INSERT INTO misure (modulo, misurato_il, guaio) VALUES (?,?,?)",
                     (modulo, time.strftime("%Y-%m-%d"), guaio[:400]))
        conn.commit()
        return
    conn.execute(
        "INSERT INTO misure (modulo, misurato_il, campi, tentate, verificate,"
        " non_riuscite, non_segnalate, secondi) VALUES (?,?,?,?,?,?,?,?)",
        (modulo, time.strftime("%Y-%m-%d"), len(mappa["ancore"]),
         len(verdetto["verificate"]) + len(verdetto["non_riuscite"])
         + len(verdetto["non_segnalate"]),
         len(verdetto["verificate"]), len(verdetto["non_riuscite"]),
         len(verdetto["non_segnalate"]), round(secondi, 2)))
    _inserisci_ancore(conn, modulo, mappa)
    for stato, elenco in (("verificata", verdetto["verificate"]),
                          ("non_riuscita", verdetto["non_riuscite"]),
                          ("non_segnalata", verdetto["non_segnalate"])):
        for r in elenco:
            conn.execute(
                "INSERT INTO esiti (modulo, ancora, tipo, stato, motivo)"
                " VALUES (?,?,?,?,?)",
                (modulo, r["ancora"], r["tipo"], stato, (r.get("motivo") or "")[:200]))
    conn.commit()


# ------------------------------------------------------------- le domande

DOMANDE = {
    "moduli": "SELECT COUNT(*) AS moduli, SUM(pagine) AS pagine,"
              " SUM(scansione) AS scansioni FROM moduli",
    "coperta": "SELECT COUNT(*) AS misurati, SUM(campi) AS campi,"
               " SUM(verificate) AS verificate, SUM(non_riuscite) AS non_riuscite,"
               " SUM(non_segnalate) AS silenzio FROM misure WHERE guaio IS NULL",
    "tipi": "SELECT tipo, COUNT(*) AS campi, COUNT(DISTINCT modulo) AS moduli"
            " FROM ancore GROUP BY tipo ORDER BY campi DESC",
    "corse": "SELECT quanti, COUNT(*) AS campi, COUNT(DISTINCT modulo) AS moduli"
             " FROM ancore WHERE tipo='riempimento' AND quanti IS NOT NULL"
             " GROUP BY quanti ORDER BY quanti",
    "celle": "SELECT quanti, COUNT(*) AS file, COUNT(DISTINCT modulo) AS moduli"
             " FROM ancore WHERE tipo='celle' GROUP BY quanti ORDER BY quanti",
    "caselle": "SELECT ROUND(lato,1) AS lato, COUNT(*) AS caselle,"
               " COUNT(DISTINCT modulo) AS moduli FROM ancore WHERE tipo='casella'"
               " GROUP BY ROUND(lato,1) ORDER BY lato",
    "guai": "SELECT tipo, stato, SUBSTR(motivo,1,52) AS motivo, COUNT(*) AS quanti,"
            " COUNT(DISTINCT modulo) AS moduli FROM esiti WHERE stato<>'verificata'"
            " GROUP BY tipo, stato, SUBSTR(motivo,1,52) ORDER BY quanti DESC",
    "silenzio": "SELECT m.file, e.ancora, e.tipo, e.motivo FROM esiti e"
                " JOIN moduli m ON m.id=e.modulo WHERE e.stato='non_segnalata'"
                " ORDER BY m.file",
    "vuoti": "SELECT m.file, m.pagine, m.scansione FROM moduli m"
             " LEFT JOIN ancore a ON a.modulo=m.id WHERE a.id IS NULL",
}


def chiedi(conn, nome: str):
    return [dict(r) for r in conn.execute(DOMANDE[nome]).fetchall()]


def tabella(righe) -> str:
    if not righe:
        return "   (niente)"
    colonne = list(righe[0])
    larghezze = {c: max(len(str(c)), max(len(str(r[c])) for r in righe))
                 for c in colonne}
    fuori = ["   " + "  ".join(str(c).ljust(larghezze[c]) for c in colonne)]
    for r in righe:
        fuori.append("   " + "  ".join(str(r[c]).ljust(larghezze[c]) for c in colonne))
    return "\n".join(fuori)


def racconta(conn) -> str:
    pezzi = []
    for nome in ("moduli", "coperta", "tipi", "corse", "celle", "caselle", "guai"):
        pezzi.append("--- %s" % nome)
        pezzi.append(tabella(chiedi(conn, nome)))
        pezzi.append("")
    return "\n".join(pezzi)


if __name__ == "__main__":
    import sys
    conn = apri()
    if len(sys.argv) > 1 and sys.argv[1] in DOMANDE:
        print(tabella(chiedi(conn, sys.argv[1])))
    elif len(sys.argv) > 1:
        print(tabella([dict(r) for r in conn.execute(sys.argv[1]).fetchall()]))
    else:
        print(racconta(conn))
    conn.close()
