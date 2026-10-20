# Mock knowledge base for the Oprisa agents

Twelve months of realistic data for three sample businesses, in the shape we
will sync from Tally, plus a month of agent and team work on top, plus a set
of planted situations with the answer each agent should reach. It is the test
bed for building and grading the agents. The design it follows is in the
"Oprisa Agents — Architecture, Knowledge Base & Schema" doc; the tables are in
`docs/agents/schema.sql`.

| Business | Trade, city | Sales (12 months, before tax) | Customers | Invoices | Tally |
|---|---|---|---|---|---|
| Shree Balaji Steels | Steel trading, Pune | ₹191 Cr | 120 | ~1,300 (big, lumpy orders) | TallyPrime, Hinglish |
| Patel Build Mart | Building material, Ahmedabad | ₹93 Cr | 180 | ~4,500 | Tally.ERP 9, English |
| Sai Pharma Distributors | Pharma distribution, Indore | ₹53 Cr | 400 | ~29,000 (many small bills) | TallyPrime, Hinglish |

About 283,000 rows across 37 tables. Today in the data is **19 Oct 2026**, 10:30 am.

## Run it

```bash
python scripts/mock_business/generate.py                 # writes data/mock_business/ (~13 s)
psql "$DB" -f docs/agents/schema.sql                      # needs pgvector and pg_trgm
cd data/mock_business && psql "$DB" -f load.sql           # ~3 s
python scripts/mock_business/verify.py "$DB"             # books reconcile + every scenario found
```

Same `--today`, same data, byte for byte. Python 3.10+, standard library only.

## What's in it

- **Tally mirror (layer A)**: ledgers, stock items, godowns, sales / purchase /
  receipt / payment / credit-note vouchers with lines, bill-wise outstanding with
  allocations, month-end stock by godown. Customers order at their own pace and
  pay by their own habit (grade A pays about on time, D pays late and in parts);
  prices follow each trade's market (steel cycles, pharma creeps up); stock is
  reordered from the supplier with the best price and delivery record.
- **Business facts (B)**, worked out by `facts.py` exactly as the nightly job
  will: customer grades with plain-language reasons, item stock days, every
  price seen, the four-week cash forecast from today's bank balance, daily KPIs.
- **Work state (C)**: the last 30 days of enquiries (English and Hinglish,
  customers' own words for items), quotes and their links, payment promises,
  reminders, supplier rates, purchase orders, today's Inbox, approvals, and
  each owner's agent rules.
- **Memory (D)**: the event timeline and who has processed each event, item
  aliases, remembered preferences and facts (with one superseded fact),
  documents. Embeddings are left empty; the embedding job fills them.
- **Runs (E)**: Tally sync runs every 15 minutes and a week of agent runs with
  token use and cost.

## Planted situations (`scenarios.json`)

Each business has the same 17 checks: 10 situations an agent must spot and act
on, and 7 owner questions with the right answer worked out from the data.

| Situation | Agent | What it should do |
|---|---|---|
| Big quote sent 3 days ago, never opened | Sales | Nudge the customer |
| Quote below the margin floor | Sales | Wait for the owner's approval |
| Payment promise missed 2 days ago | Collections | Put a call at the top of today's list |
| Fastest item has under 12 days of stock, no PO open | Stock | Draft a PO from this morning's best rate |
| A supplier quoted 3% below our last buy | Stock | Use that rate |
| Regular customer stopped ordering 40 days ago | Sales | Win-back call |
| Good payer's recent bills running a month late (B → C) | Score | Propose a lower limit, ask the owner |
| Item with no sale for 9 months | Stock | Offer to past buyers, ask the owner |
| Bulk-buy bill makes week 3 go below zero | Cash | Ask early payers / move the payment |
| Same customer keyed twice in Tally | Collections | Flag it for accounts |
| "Who owes me the most?", "Sales last month?", "What will run out this week?" … | Ask | Give the right figure |

Each entry has the expected result and a `check_sql` that finds it in the
loaded data; `verify.py` runs them all. The agents' own tests compare what the
agent says or does against `expect`.

## Files

| File | What it does |
|---|---|
| `catalog.py` | The three businesses: items, suppliers, team, seasons, enquiry phrasing |
| `simulate.py` | A year of trading, day by day, and where the situations are planted |
| `facts.py` | Layer B, the same logic the real job will use |
| `work.py` | Layers C–E on top of the books |
| `generate.py` | Runs it all; writes CSVs, `load.sql`, `scenarios.json`, `summary.json` and a sample Tally XML export |
| `verify.py` | Checks a loaded database |

`tally_sample_shree_balaji.xml` follows the shape of a TallyPrime XML export
(ENVELOPE / TALLYMESSAGE / LEDGER, STOCKITEM, VOUCHER with inventory and bill
allocations) for the sync parser's tests; it is not a byte-exact Tally file.
