# Bank Matching

Prototype of a bank reconciliation page at `/bank-matching` that opens on the pairings Dokos already found:
each unreconciled bank line comes with its best document, a confidence level and the signals behind it.
One click pre-approves a pairing, one more validates every pre-approved pairing.

The scoring is erpnext's (`erpnext/accounts/page/bank_reconciliation/match_scoring.py`), so the app needs an
erpnext that ships it: branch `feat/bank-rec-match-scoring` until it is merged.

## Build

```bash
cd frontend
yarn install
yarn build
```

`bench build --app bank_matching` runs the same build. `yarn dev` serves the page with hot reload against
the bench's `webserver_port`, or `FRAPPE_WEB_SERVER_PORT` when set.
