# Database migration strategy

This internal MVP uses SQLAlchemy models as the source of truth for schema design.

For production, use Supabase Postgres and a migration tool such as Alembic.

Recommended steps:
1. Keep local dev on SQLite.
2. Create a Postgres schema in Supabase.
3. Apply model-based migrations in a controlled release pipeline.
4. Validate all approval and audit tables before production usage.
