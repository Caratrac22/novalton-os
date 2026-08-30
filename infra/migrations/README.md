# Database migrations

Alembic migration history lives here. Run commands from the repository root through the Makefile:
`make db-upgrade` / `make db-current` use the validated development `.env` profile, while
`make test-db-upgrade` / `make test-db-current` use the validated isolated `.env.test` profile.
Both prove the live PostgreSQL identity before Alembic runs. No database credentials are stored in
Alembic configuration or revisions.

The I-004 baseline is intentionally empty: application tables begin with I-005.
