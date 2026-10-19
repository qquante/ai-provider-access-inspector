# AI Provider Access Inspector

Python CLI for inspecting configured AI provider access, model catalogs and account metadata.

## Features

- Inspect credentials across ten provider adapters without sending inference prompts.
- Distinguish authentication failures, rate limits and partial responses.
- Export account and model observations as structured JSON.

## Stack

Python standard library · HTTP GET · JSON · unittest

No database or external Python package is required. Account outputs may contain sensitive metadata.

## Getting started

Requires Python 3.10+. Configure provider credentials locally using .env.example, then inspect the CLI help before querying an account. Run python -m unittest discover -s tests -v for offline checks.

## How it works

```text
Local credential configuration → provider HTTP adapter → normalized observation → JSON output
```

## Current limitations

Model listing does not establish inference access. Account metadata availability varies by provider.

## Tests

```console
python -m unittest discover -s tests -v
```

These checks use offline fixtures or controlled backends.

## License

No open-source license has been granted. Redistribution terms remain to be defined.

## CLI help

```console
python key_audit.py --help
```

Provider requests require your own locally configured credentials. Help and the offline unit tests do not query provider accounts.
