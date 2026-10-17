-- Cervello comune di BIG-BOB (Cloudflare D1).
-- Si può rieseguire: crea solo ciò che manca.
-- Nessun dato personale: i giocatori sono codici anonimi (hash di un id casuale generato da BIG-BOB),
-- gli indirizzi IP non vengono salvati (solo un hash giornaliero per i limiti anti-abuso, cancellato dopo 2 giorni).

CREATE TABLE IF NOT EXISTS contributori (
  hash TEXT PRIMARY KEY,
  primo TEXT NOT NULL,
  ultimo TEXT NOT NULL,
  invii INTEGER NOT NULL DEFAULT 0,
  versione TEXT,
  bannato INTEGER NOT NULL DEFAULT 0
);

-- Limiti giornalieri (chiave = hash di ip/contributore + giorno).
CREATE TABLE IF NOT EXISTS limiti (
  chiave TEXT NOT NULL,
  giorno TEXT NOT NULL,
  n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (chiave, giorno)
);

-- Regole: un gruppo per ogni regola "uguale" vista da giocatori diversi.
CREATE TABLE IF NOT EXISTS regole (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  categoria TEXT NOT NULL,
  testo TEXT NOT NULL,
  firma TEXT NOT NULL,
  creata TEXT NOT NULL,
  nascosta INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS regole_categoria ON regole (categoria);

-- Lo stato che ogni giocatore dà a una regola (l'ultimo inviato).
CREATE TABLE IF NOT EXISTS regole_voti (
  regola_id INTEGER NOT NULL,
  contributore TEXT NOT NULL,
  stato TEXT NOT NULL,
  testo TEXT,
  prove TEXT,
  aggiornato TEXT NOT NULL,
  PRIMARY KEY (regola_id, contributore)
);

-- Lezioni (stessa idea delle regole).
CREATE TABLE IF NOT EXISTS lezioni (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tipo TEXT NOT NULL,
  testo TEXT NOT NULL,
  firma TEXT NOT NULL,
  carte TEXT NOT NULL DEFAULT '[]',
  creata TEXT NOT NULL,
  nascosta INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS lezioni_tipo ON lezioni (tipo);

CREATE TABLE IF NOT EXISTS lezioni_voti (
  lezione_id INTEGER NOT NULL,
  contributore TEXT NOT NULL,
  stato TEXT NOT NULL,
  volte INTEGER NOT NULL DEFAULT 1,
  testo TEXT,
  aggiornato TEXT NOT NULL,
  PRIMARY KEY (lezione_id, contributore)
);

-- A quale gruppo corrisponde la regola/lezione locale di un giocatore (così le modifiche successive aggiornano
-- il suo voto invece di crearne uno nuovo).
CREATE TABLE IF NOT EXISTS mappe (
  contributore TEXT NOT NULL,
  tipo TEXT NOT NULL,
  cid TEXT NOT NULL,
  gruppo_id INTEGER NOT NULL,
  PRIMARY KEY (contributore, tipo, cid)
);

-- Testi di carte e location verificati sullo schermo da un giocatore.
CREATE TABLE IF NOT EXISTS carte (
  tipo TEXT NOT NULL,           -- 'carta' | 'location'
  chiave TEXT NOT NULL,         -- slug del nome
  contributore TEXT NOT NULL,
  dati TEXT NOT NULL,           -- JSON: nome, testo, costo, attacco, vita, ...
  aggiornato TEXT NOT NULL,
  PRIMARY KEY (tipo, chiave, contributore)
);

-- Partite: risultato, leggendarie e carte avversarie viste (niente nomi di giocatori).
CREATE TABLE IF NOT EXISTS partite (
  contributore TEXT NOT NULL,
  cid TEXT NOT NULL,
  data TEXT NOT NULL,
  patch TEXT,
  mia_leggendaria TEXT,
  avv_leggendaria TEXT,
  risultato TEXT,
  round INTEGER,
  mie_carte TEXT NOT NULL DEFAULT '[]',
  avv_carte TEXT NOT NULL DEFAULT '[]',
  ricevuta TEXT NOT NULL,
  PRIMARY KEY (contributore, cid)
);
CREATE INDEX IF NOT EXISTS partite_data ON partite (ricevuta);

-- Ultimo riassunto calcolato (lo scaricano tutti i BIG-BOB).
CREATE TABLE IF NOT EXISTS riassunto (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  json TEXT NOT NULL,
  creato TEXT NOT NULL
);

-- Cose nascoste dall'amministratore (carte/location con testo sbagliato, ecc.).
CREATE TABLE IF NOT EXISTS nascosti (
  tipo TEXT NOT NULL,
  chiave TEXT NOT NULL,
  motivo TEXT,
  data TEXT NOT NULL,
  PRIMARY KEY (tipo, chiave)
);
