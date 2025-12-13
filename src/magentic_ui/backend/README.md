This code has been adapted from AutoGen Studio https://github.com/microsoft/autogen/tree/main/python/packages/autogen-studio

When the backend is pointed at a LangGraph deployment by setting `MAGENTIC_UI_LANGGRAPH_API_URL`,
session routes will proxy directly to the LangGraph API instead of relying on the legacy AutoGen
pipeline or local database state.

## Database configuration

The backend now targets PostgreSQL by default. Provide a PostgreSQL connection string through either
the `MAGENTIC_UI_DATABASE_URI` or `DATABASE_URI` environment variable (the Pydantic settings prefix
means both are accepted). For Supabase, use the full connection string including SSL mode, for
example:

```
MAGENTIC_UI_DATABASE_URI=postgresql+psycopg://postgres:<password>@<project>.supabase.co:5432/postgres?sslmode=require
```

Local development can use any PostgreSQL instance; the default fallback URI is
`postgresql+psycopg://postgres:postgres@localhost:5432/magentic_ui`.
