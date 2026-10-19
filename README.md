# AI Provider Access Inspector

> **Local private review:** publication is paused. See [security review and remaining release conditions](docs/SECURITY_REVIEW.md). Local fixes have not been pushed.


Inspect configured AI provider credentials, visible models and available account metadata from a Python command line interface.

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-standard%20library-blue)](#architecture)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-Douglas%20Silva-0A66C2?logo=linkedin&logoColor=white)](https://www.linkedin.com/in/douglas-silva-data-analyst/)

**Stack:** Python standard library · HTTP GET · JSON · concurrent workers · unittest. No database, frontend or external Python packages.

## Purpose

Compare access across ten provider adapters without sending prompts or running inference. Results distinguish authentication failures, permission restrictions, rate limits and partial responses. A model listing does not establish that inference is permitted or funded.

Implemented adapters: OpenAI, Anthropic, OpenRouter, Groq, Cerebras, Mistral, DeepSeek, Together AI, Hugging Face and Replicate. Availability depends on each provider's current API and credential permissions.

## Quick start

Requires Python 3.10+. Current local validation uses Python 3.14; the configured CI matrix must pass before claiming broader compatibility.

Set credentials in your shell or create a local `.env` using the variable names below. Never commit credentials.

```text
OPENAI_API_KEY=""
ANTHROPIC_API_KEY=""
OPENROUTER_API_KEY=""
GROQ_API_KEY=""
CEREBRAS_API_KEY=""
MISTRAL_API_KEY=""
DEEPSEEK_API_KEY=""
TOGETHER_API_KEY=""
HF_TOKEN=""
REPLICATE_API_TOKEN=""
```

```console
python key_audit.py --help
python key_audit.py --provider deepseek openrouter --summary-only
python key_audit.py --output reports/access.json --summary-only
```

The last two commands contact the selected providers when credentials are configured. Environment values take precedence over `.env`. Use `--models-limit 0` to retain all models returned by a single adapter request; this does not fetch every page.

## Architecture

| Module | Responsibility |
| --- | --- |
| `keyscope/cli.py` | Arguments, concurrent execution, tables, JSON and exit codes |
| `keyscope/env.py` | Local configuration and case-insensitive credential aliases |
| `keyscope/http.py` | GET requests, response limits, error handling and origin checks |
| `keyscope/providers.py` | Provider adapters, normalization and output redaction |

The program keeps no database. Reports are optional local JSON files. Exit codes: `0` for configured providers succeeding, including partial results; `1` for failures; `2` when no credentials are configured. `--strict-missing` also fails if a selected provider has no credential.

## Security and limitations

- Requests use fixed provider endpoints; redirects to a different origin are rejected.
- Credential values are redacted from supported response output; fingerprints are shortened SHA-256 identifiers, not encryption.
- Reports may contain account names, balances and private model identifiers. Keep them private.
- Billing and pricing fields vary by provider. Do not compare raw prices without checking units.
- Offline tests validate simulated responses. They do not verify live credentials, billing, API availability or production readiness.

## Validation

```console
python -m unittest discover -s tests -v
```

Tests use fake clients and temporary environment variables. No real credentials or network requests are needed. A CI template is available in `docs/ci-templates/offline-tests.yml`; it is inactive pending GitHub workflow access. No passing badge is claimed before a remote run.

## Project status

Private review preparation. Source behavior is preserved from the original local project; documentation and CI are being prepared separately. The original provider research is retained in [original notes](docs/original-notes.md) as historical documentation, not as a newly verified API compatibility statement.

Before a public release: review current provider contracts, select a code license, and validate the Python compatibility matrix. No open-source license has been granted by this preparation.

## Author

Douglas de Oliveira Silva · [GitHub](https://github.com/qquante) · [LinkedIn](https://www.linkedin.com/in/douglas-silva-data-analyst/)

Detailed preparation scope: [review notes](docs/REVIEW.md).
