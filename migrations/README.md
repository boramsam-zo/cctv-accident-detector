# Database migrations

`env.py` loads SQLAlchemy models and reads `DATABASE_URL` from the process environment. `versions/` contains the PostgreSQL schema history.

```bash
uv run --locked alembic upgrade head
uv run --locked alembic current
```

Apply migrations before starting the API with PostgreSQL. SQLite tests still create isolated tables directly.
