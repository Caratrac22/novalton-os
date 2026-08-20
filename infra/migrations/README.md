# Database migrations

Alembic migration history lives here. Commands run from the repository root through the
Makefile and load `DATABASE_URL` from the process environment (normally the ignored `.env`).
No database credentials are stored in Alembic configuration or revisions.

The I-004 baseline is intentionally empty: application tables begin with I-005.
