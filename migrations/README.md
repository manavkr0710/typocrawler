# Migrations

Alembic, targeting `typocrawler.db.models.metadata`.

```bash
alembic upgrade head                      # apply
alembic revision --autogenerate -m "..."  # scaffold a new migration
alembic downgrade -1                       # roll back one
```

Override the target DB with `TYPOCRAWLER_DB=sqlite:///some.db`.

`init-db` / `typocrawler.db.init_db()` use `metadata.create_all` for quick local setup; Alembic
is the source of truth for schema evolution.
