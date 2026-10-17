# Cervello comune di BIG-BOB (Cloudflare Worker + D1)

Il server che mette insieme ciò che imparano tutti i BIG-BOB. Gira sul piano gratuito di Cloudflare.

## Pubblicare o aggiornare
Doppio clic su `pubblica_cervello.bat` (nella cartella di BIG-BOB). La prima volta:
1. installa Node.js se manca (con winget) e lo strumento di Cloudflare (`wrangler`) in `cloud/node_modules`;
2. apre il browser per accedere a Cloudflare (account gratuito);
3. crea il database `bigbob-cervello` e le tabelle (`schema.sql`, si può rieseguire);
4. genera chiave di amministrazione e sale degli hash (in `config.json`: `cervello_admin_key`, `cervello_sale`;
   **non cambiare mai il sale**, cambierebbe il codice anonimo di tutti);
5. pubblica e scrive l'indirizzo in `config.json` (`cervello_url`) e in `cloud/indirizzo.txt`.

Per i BIG-BOB degli altri l'indirizzo va scritto in `origins/cervello.py` (`DEFAULT_URL`) e arriva con l'aggiornamento.

## API
| | |
|---|---|
| `GET /v1/stato` | numeri principali |
| `GET /v1/conoscenza` | conoscenza fusa (ETag, 304 se invariata); ricalcolata ogni ora e dopo i contributi |
| `POST /v1/contributi` | `{install, versione, patch, regole[], lezioni[], carte[], location[], partite[]}` |
| `/v1/admin/*` | `Authorization: Bearer <ADMIN_KEY>` |

Regole di fusione (`src/merge.js`, uguali a `origins/cervello.py`):
- regole uguali scritte in modo diverso si uniscono per somiglianza delle parole (numeri diversi = regole diverse);
  ogni giocatore ha un voto (l'ultimo stato che ha inviato). ✅ confermata con `CONFERMA_GIOCATORI` (2) conferme e più
  conferme che smentite; 🟡 probabile con una sola; ❌ smentita al contrario; ⚠ contestata se pari;
- lezioni: stesso tipo, carte in comune e testo simile; confermate quando 2 giocatori le sostengono;
- testi di carte: vale il valore indicato dal maggior numero di giocatori, "concorde" da 2 in su;
- partite degli ultimi 45 giorni: mazzi avversari (carte con frequenza), winrate per leggendaria e matchup.

Anti-abuso: corpo max 256 KB; 40 invii al giorno per indirizzo, 20 per giocatore, 3 giocatori nuovi al giorno per
indirizzo (contro i voti gonfiati); testi ripuliti da link ed email. Gli IP non vengono salvati: solo un hash giornaliero
per i limiti, cancellato dopo 2 giorni.

## Moderazione
Da BIG-BOB (usa la chiave in `config.json`):
```
python -m origins.cervello admin panoramica
python -m origins.cervello admin regola C12                 # dettagli e voti
python -m origins.cervello admin regola C12 --nascondi
python -m origins.cervello admin regola C12 --testo "testo corretto"
python -m origins.cervello admin regola C12 --unisci-in C3  # stessa regola scritta in modo diverso
python -m origins.cervello admin lezione CL7 --nascondi
python -m origins.cervello admin nascondi carta "Marian" --motivo "testo sbagliato"
python -m origins.cervello admin mostra carta "Marian"
python -m origins.cervello admin banna <hash>                # i suoi dati non contano più
python -m origins.cervello admin ricalcola
```

## Sviluppo
```
cd cloud
npm install
npm test                                   # logica di fusione
cp wrangler.example.toml wrangler.toml     # (database_id qualsiasi per il locale)
npx wrangler d1 execute bigbob-cervello --local --file schema.sql
printf 'ADMIN_KEY=prova\nSALE=prova\n' > .dev.vars
npx wrangler dev
python test/collaudo.py http://127.0.0.1:8787 prova
BIGBOB_CERVELLO_URL=http://127.0.0.1:8787 python ../tests/test_cervello.py
```
