# ContextOS

Local-first business context layer bridging **Pre-Sales** (discovery notes, SOWs, commercial terms) and **Delivery** (engineering, DevOps, project management).

ContextOS pairs structured canonical records in SQLite (WAL mode, foreign keys, append-only `audit_events`) with Git-tracked Markdown documents and portable `SKILL.md` playbooks indexed via SQLite FTS5. A YAML policy engine enforces role-based field redaction and write gates across every read, write, MCP tool call, and REST request.

## Architecture

```text
                    +-------------------------------------------+
                    |         AI Agents & Delivery Tools        |
                    |  Cursor / Claude (MCP) | REST API | CLI   |
                    +---------------------+---------------------+
                                          |
                    +---------------------v---------------------+
                    |      FastMCP Server  &  FastAPI REST      |
                    +---------------------+---------------------+
                                          |
                    +---------------------v---------------------+
                    |     Governance Engine (YAML Policies)     |
                    |  Role Redaction  |  Write Gates  | Audit  |
                    +----------+--------------------+-----------+
                               |                    |
              +----------------v------+      +------v------------------+
              |  SQLite (WAL + FKs)   |      |   context_store/ (Git)  |
              |  Client -> Project -> |<---->|   clients/*/sow_v1.md   |
              |  Scope / Guardrail /  | FTS5 |   clients/*/discovery   |
              |  CR / audit_events    |      |   skills/*/SKILL.md     |
              +-----------------------+      +-------------------------+
                                          |
                    +---------------------v---------------------+
                    |     Swappable LLMProvider Interface       |
                    |      Groq (default)  |  Gemini (.env)     |
                    +-------------------------------------------+
```

## Role Governance Model

Policies live in `context_store/governance_policies.yaml`:

| Role | Read Scope | Redacted Fields | Write / Approval Rules |
|---|---|---|---|
| `presales_sa` | Full | None | Read/write on `Client`, `Project`, `ScopeItem`, `Guardrail` |
| `pm` | Full | None | Read/write on `Project` and `ChangeRequest` (including `approve`); read-only `Guardrail` |
| `delivery_dev` | Technical context | `contract_value_usd`, `margin_notes` | Read-only `Project`/`ScopeItem`/`Guardrail`; can submit draft CRs, blocked from `approve` |

Every read, write, search, and denied action is recorded in `audit_events`, protected by SQLite `BEFORE UPDATE` and `BEFORE DELETE` triggers.

## Quickstart

```bash
git clone https://github.com/Osamarasheed147/contextOS.git
cd contextOS

uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

cp .env.example .env
# Add your GROQ_API_KEY to .env (https://console.groq.com/keys)

python examples/run_demo_scenarios.py
```

To run the three demo scenarios offline without an API key:

```bash
python examples/run_demo_scenarios.py --mock
```

### Switching from Groq to Gemini

Install the optional Gemini dependency and update `.env`:

```bash
uv pip install -e ".[gemini]"
```

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_key
GEMINI_MODEL=gemini-2.5-flash
```

## REST API & Tests

```bash
pytest -v

# Seed sample FinBridge UK data and start FastAPI (OpenAPI docs at http://localhost:8000/docs)
python examples/seed_demo.py
uvicorn contextos.api:app --reload
```

## MCP Server Setup (Cursor / Claude Desktop)

Seed the local SQLite database once (`python examples/seed_demo.py`), then register ContextOS in `.cursor/mcp.json` or `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "contextos": {
      "command": "/absolute/path/to/contextOS/.venv/bin/python",
      "args": ["-m", "contextos.mcp_server"],
      "env": {
        "CONTEXTOS_DB_PATH": "/absolute/path/to/contextOS/contextos.db"
      }
    }
  }
}
```

### Exposed MCP Tools
- `get_project_context(project_id, role)` - Governed project, scope items, and guardrails with role-based redaction.
- `search_client_docs(client_id, query, role)` - SQLite FTS5 search over client SOWs and discovery notes.
- `load_skill(skill_name)` - Returns raw `SKILL.md` rubrics (`scope_creep_check`, `cloud_guardrail_check`).
- `submit_change_request(project_id, requested_by, description, role)` - Logs a pending Change Request.
- `get_audit_log(project_id, limit=20)` - Returns recent immutable audit events.

## License

MIT - see [LICENSE](LICENSE).
