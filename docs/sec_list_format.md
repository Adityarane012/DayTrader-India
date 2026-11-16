# sec_list.csv: the parsed record contract

NSE's security list (`sec_list.csv`) says which price band each stock has.
This page is the contract two separate programs follow: the trader-exit
skill in this repo (`parse_sec_list` and `band_for` in
`trader-exit/exit.py`) and the user's own screener MCP. The MCP must
implement it independently and must not import this code.

**The shared source of truth is the fixture
`tests/fixtures/trader-exit/sec_list_sample.csv`.** Both test suites parse
that file and must get the same records. It is a hand-made sample (written
2026-11-16), not a download: the names are invented and the malformed rows
are there on purpose. If the contract changes, change this page and the
fixture together.

Unverified: whether NSE's real `sec_list.csv` has exactly the columns
`Symbol, Series, Security Name, Band` (the user's plan names them, but no
real file is checked in). Columns are therefore found by header name, so a
reordered file or extra columns still parse.

## Input

CSV text, UTF-8, with or without a BOM, LF or CRLF line endings.

- The header row is any row whose cells include `Symbol` and `Band`
  (case-insensitive). It sets the column positions for the rows below it. A
  header that repeats later in the file is skipped, and re-sets the
  positions.
- With no header at all, the columns are in the order Symbol, Series,
  Security Name, Band.
- Every cell is trimmed of spaces; a BOM anywhere in the first cell is
  dropped.
- Blank lines (or lines of only commas and spaces) are skipped.

## Record

One record per data row, in file order.

| field | type | meaning |
| --- | --- | --- |
| `symbol` | string | upper-cased, trimmed |
| `series` | string | upper-cased, e.g. `EQ`, `BE`; `""` if the column is missing |
| `name` | string | Security Name as written; `""` if missing |
| `band` | `"percent"`, `"none"` or `"unknown"` | what the row says |
| `band_pct` | number or null | the percent (20.0 for 20, 20 %, " 20 "); null unless `band` is `"percent"` |
| `reason` | string or null | why `band` is `"unknown"`; null otherwise |
| `line` | integer | 1-based line number in the file |

Band cell rules:

- A number, with an optional trailing `%`, greater than 0 and at most 100:
  `percent`.
- `No Band` (any case) or an empty cell: `none`. Not a guess: NSE leaves
  stocks with no band blank or says "No Band".
- Anything else is `unknown` with a reason, never a guess and never an
  exception: text that is not a number (`abc`), zero, a negative number, a
  number over 100, `NaN`.
- A row with a symbol but fewer cells than the Band column needs is
  `unknown`, reason `row has no Band column`.

A row with no symbol is skipped. A parser may report it as
`line N: no symbol`, but it produces no record.

## Duplicates and series

All rows are kept in the parsed list. When one symbol is looked up:

1. Only rows with series `EQ` count (the trader-exit skill trades `-EQ`
   only; a symbol that exists only as `BE`, `SM` etc. is "not found").
2. If `EQ` appears more than once, the **last** row in the file wins, and
   the parser should say so: the trader-exit parser can collect a note per
   extra row ("line 5: ALPHA is in the EQ series again (first at line 2): the
   last row wins"). A `BE` or other-series row of the same symbol is not an
   `EQ` duplicate. An implementation should not fail on duplicates.
3. A trailing `.NS` on the symbol asked for is ignored.

Lookup returns the record (including `unknown` and `none` ones) or nothing.
Nothing and `unknown` both mean "band unknown" to the caller.

## Examples

From the fixture (CRLF lines, BOM on the first):

| row | parsed record |
| --- | --- |
| `ALPHA,EQ,ALPHA SAMPLE NAME,20` | `{symbol: "ALPHA", series: "EQ", name: "ALPHA SAMPLE NAME", band: "percent", band_pct: 20.0, reason: null, line: 2}` |
| `RELIANCE,EQ,RELIANCE SAMPLE NAME,No Band` | `{symbol: "RELIANCE", series: "EQ", name: "RELIANCE SAMPLE NAME", band: "none", band_pct: null, reason: null, line: 6}` |
| `  padded , eq , PADDED CO , 20% ` | `{symbol: "PADDED", series: "EQ", name: "PADDED CO", band: "percent", band_pct: 20.0, reason: null, line: 11}` |
| `BADBAND,EQ,BAD BAND CO,abc` | `{symbol: "BADBAND", series: "EQ", name: "BAD BAND CO", band: "unknown", band_pct: null, reason: "band 'abc' is not a percent between 0 and 100", line: 12}` |
| `SHORTROW,EQ` | `{symbol: "SHORTROW", series: "EQ", name: "", band: "unknown", band_pct: null, reason: "row has no Band column", line: 14}` |

The two `DUPE,EQ,...` rows (bands 5 and 10) both appear in the parsed list;
a lookup of `DUPE` returns the second (10). `BEONLY,BE,...,5` is in the
list but a lookup of `BEONLY` returns nothing.

The `reason` wording is informational; tests should match `band`, `band_pct`
and that a reason is present, not the exact text.

## Band limits (how trader-exit uses a record)

Not part of the parse, but the same maths if the MCP wants it. From the
previous close and a band percent `p`: upper = close x (1 + p/100), rounded
**down** to the NSE tick; lower = close x (1 - p/100), rounded **up** to the
tick, so both limits stay inside the band. The tick goes by the price (Rs
0.01 below 250, 0.05 up to 1,000, 0.10 up to 5,000, 0.50 up to 10,000, 1.00
up to 20,000, 5.00 above). Whether NSE rounds its published limits the same
way is unverified.
