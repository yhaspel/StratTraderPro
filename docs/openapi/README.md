# OpenAPI Schema

`openapi.json` is the source of truth for frontend type generation.

## Regenerate from the live backend

```bash
make schema-export   # writes docs/openapi/openapi.json
make schema-types    # writes frontend/src/app/core/generated/schema.ts
```

`schema-export` runs `python manage.py spectacular --file docs/openapi/openapi.json`
against the dev backend. `schema-types` pipes that file through `openapi-typescript`.

The committed `openapi.json` is a snapshot that may lag the running backend;
CI runs both targets and fails on drift (see `tests/contract/`).
