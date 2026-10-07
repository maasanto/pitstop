# Pitstop

Prototype of a bank reconciliation page at `/pitstop` that opens on the pairings Dokos already found:
each unreconciled bank line comes with its best document, a confidence level and the signals behind it.
One click pre-approves a pairing, one more validates every pre-approved pairing.

The scoring lives in the app (`match_scoring.py`, `ranking.py`) and runs on a stock erpnext. It is meant to
move into erpnext's reconciliation page once settled; branch `feat/bank-rec-match-scoring` holds that port.

## Build

```bash
cd frontend
yarn install
yarn build
```

`bench build --app pitstop` runs the same build. `yarn dev` serves the page with hot reload against
the bench's `webserver_port`, or `FRAPPE_WEB_SERVER_PORT` when set.
