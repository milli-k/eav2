# Omni Hierarchical Filter Demo

Two scripts that together implement a multi-tenant hierarchical filter for an [Omni](https://omni.co/) embedded dashboard.

- **`generate.py`** — reads a subjects CSV, generates per-tenant [extension models](https://docs.omni.co/docs/modeling/model-extensions) in Omni with flattened `dim_subject` dimensions, and wires up `dynamic_shared_extensions` on the hub model for tenant-scoped routing.
- **`embed_app.py`** — reads the same CSV, builds a hierarchy tree per tenant, signs an Omni SSO embed URL, and outputs a self-contained `embed_demo.html` with a filter UI that drives the embedded dashboard via `postMessage`.

## How it works

Each row in your CSV has a packed `dim_subject` column like:

```
Region: EMEA > UK > London; Product: SaaS > Analytics
```

`generate.py` parses this to discover each tenant's fields and hierarchy depth, then generates one Omni dimension per (field × level) — e.g. `region`, `region_2`, `region_3` — using BigQuery SQL. Each tenant gets its own [shared extension model](https://docs.omni.co/docs/modeling/model-extensions); the hub model's `dynamic_shared_extensions` map_pattern routes to the correct extension at query time based on the `customer_id` user attribute.

`embed_app.py` builds a browser-side node tree from the same CSV. The HTML it generates lets a user pick hierarchy nodes across axes; selections are intersected (AND) and pushed into the embedded dashboard as an Omni filter via `postMessage` — no page reload required.

## Setup

### 1. Configure your environment

```bash
cp .env.example .env
```

Open `.env` and fill in your values. See the comments in `.env.example` for descriptions of each variable. At minimum you need:

| Variable | Description |
|---|---|
| `OMNI_BASE_URL` | Your Omni instance URL |
| `OMNI_API_KEY` | Your Omni API key (Settings → API Keys) |
| `MODEL_ID` | UUID of your hub model |
| `OMNI_EMBED_SECRET` | Your embed secret (Settings → Embed) |
| `OMNI_VANITY_DOMAIN` | Your embed vanity domain |
| `OMNI_DASHBOARD_PATH` | Path to the dashboard to embed |

### 2. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Prepare your CSV

The scripts expect a CSV at the path set by `CSV_PATH` (default: `dim_subject.csv`) with these columns:

| Column | Required | Description |
|---|---|---|
| `customer_id` | ✅ | Tenant identifier |
| `dim_subject` | ✅ | Packed hierarchy string (see format above) |
| `subject_id` | For `embed_app.py` | ID used as the dashboard filter value |

## Usage

### `generate.py` — build extension models in Omni

```bash
# Dry-run: preview what would be generated, no API calls
python generate.py --dry-run

# Run for all tenants
python generate.py

# Run for a single tenant only
python generate.py --tenant TENANT_ID

# Verbose: print full YAML written per tenant
python generate.py -v
```

### `embed_app.py` — generate the filter demo HTML

```bash
# Generate embed_demo.html (all tenants, iframe scoped to first tenant)
python embed_app.py

# Scope the iframe to a specific tenant
python embed_app.py --customer TENANT_ID

# Export hierarchy JSON only (no signing, for use with a custom front-end)
python embed_app.py --emit-json hierarchy.json
```

Open the output `embed_demo.html` in a browser. Use the dropdowns to select hierarchy nodes, then click **Apply filter** to push the selection into the embedded dashboard.

> **Note:** The iframe is signed for one tenant at a time. The customer selector in the UI re-targets the filter but does not re-scope server-side row-level security. Re-run with `--customer` or set `OMNI_DEMO_CUSTOMER_ID` in `.env` to sign for a different tenant.

## Field name normalization

If the same hierarchy concept appears under different names across tenants (e.g. `market` vs `Market`), add an alias in the `FIELD_ALIASES` dict near the top of each script:

```python
FIELD_ALIASES = {
    'Mkt': 'Market',
}
```

Only alias fields that truly share the same data — merging fields with different paths produces nodes that don't resolve at query time.

## Relevant Omni docs

- [Embed overview](https://docs.omni.co/docs/embed/overview)
- [SSO embed URL signing](https://docs.omni.co/docs/embed/sso-embed)
- [Model extensions](https://docs.omni.co/docs/modeling/model-extensions)
- [User attributes](https://docs.omni.co/docs/access-and-security/user-attributes)
- [postMessage API](https://docs.omni.co/docs/embed/post-message)
