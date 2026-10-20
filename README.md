# AI Provider Access Inspector

![Language: Python](https://img.shields.io/badge/Language-Python-3776AB?style=flat-square&logo=python) ![Requests: HTTP GET](https://img.shields.io/badge/Requests-HTTP%20GET-555555?style=flat-square) [![License: MIT](https://img.shields.io/badge/License-MIT-555555?style=flat-square)](LICENSE)

Inspect configured AI-provider access from a single Python CLI: available models, account metadata and balance or usage information when the provider exposes it.

The inspector issues GET requests; it does not submit inference prompts. Provider responses are normalized into access states, so an absent credential, a restricted account and a rate limit do not collapse into the same error.

## Start with the local interface

Python's standard library is sufficient for the CLI and its offline tests:

```console
python key_audit.py --help
python -m unittest discover -s tests -v
```

For your own configured accounts, a bounded operational query is:

```console
python key_audit.py --env-file .env --models-limit 5 --timeout 10 --workers 2 --json --output report.json
```

That command contacts provider endpoints. Use `--provider` with one or more slugs from `--help` to restrict the query. Account reports may contain private account metadata; keep them local.

## Read the result correctly

| State | Meaning |
| --- | --- |
| `missing` | No configured credential was found. |
| `valid` / `partial` | The adapter obtained supported information; coverage can vary by endpoint. |
| `restricted` / `invalid` | The response indicates an access or authentication problem. |
| `rate_limited` / `unavailable` | The query could not complete normally; neither proves an invalid key. |

Model lists are bounded by `--models-limit`; `0` requests the full supported list. A balance is shown only when reported by the provider, not estimated from successful authentication.

[cli.py](keyscope/cli.py) handles bounded concurrency and ordered reporting; [providers.py](keyscope/providers.py) owns provider-specific interpretation; [http.py](keyscope/http.py) owns HTTP behavior. Exception reporting avoids echoing credentials. The offline suite covers controlled responses, not the current permissions of a live account.

**Technology:** Python standard library · HTTP GET · JSON · unittest

Project-authored source: [MIT](LICENSE). Third-party components retain their own notices and terms.
