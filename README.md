# Education Monitor: Hansard feed

Fetches education, schools, skills and FE debates from the official Hansard API twice each weekday and saves them here, so the Education Monitor dashboard can tag and display them.

- `scripts/hansard.py`: the fetcher (standard-library Python).
- `.github/workflows/hansard.yml`: runs it at 05:40 and 15:40 UTC on weekdays, or on demand from the Actions tab.
- `data/index.json`: one line per debate saved (date, house, title, file).
- `data/debates/YYYY/`: one file per debate, with speakers and contribution text.
- `data/state.json`: the last date processed.

To load a date range by hand: Actions → Fetch Hansard → Run workflow, mode `range`, with start and end dates.

Contains Parliamentary information licensed under the Open Parliament Licence v3.0.
