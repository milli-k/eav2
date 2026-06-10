"""Create one per-tenant Omni dashboard with a native FIELD_PICKER control.

Each tenant (customer_id) gets a dashboard on the hub model whose FIELD_PICKER
lists that tenant's dim_subject custom fields. The embed app
(embed-app/) reads the picker + field list from the dashboard and drives it live.

Why per-tenant dashboards: a FIELD_PICKER's options are creator-defined and
static, and each tenant's extension exposes a different field set — so a single
shared dashboard can't list fields that don't exist for every tenant. The hub's
dynamic_shared_extension map_pattern ({{ omni_attributes.customer_id }}) means
the fields resolve at view time when embedded with that customer_id.

Run after generate.py (which creates the extension models). Idempotent: reuses
an existing dashboard with the same name instead of creating a duplicate.
"""

import csv
import os
import random
import string

import requests
from dotenv import load_dotenv
from yaml import safe_load as yaml_load

load_dotenv()
BASE = os.environ["OMNI_BASE_URL"].rstrip("/")
KEY = os.environ["OMNI_API_KEY"]
H = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

CSV_PATH = "dim_subject.csv"
HUB_MODEL_ID = "73a858a3-6778-47b7-8fee-9facd105d30e"
VIEW = "my_db_main__dim_subject"          # how the dim_subject view is referenced
VIEW_FILE = "my_db.main/dim_subject.view"
VIEW_LABEL = "My Db Main Dim Subject"     # viewLabel prefix shown in the picker
COUNT_FIELD = f"{VIEW}.count"
# Raw columns present on the base view — not tenant custom fields.
BASE_COLS = {"dim_bonafide", "dim_subject", "subject_name", "subject_id", "customer_id"}
DASH_SUFFIX = " — Subject Field Explorer"


def api_get(path, **params):
    r = requests.get(f"{BASE}{path}", headers=H, params=params, timeout=90)
    r.raise_for_status()
    return r.json()


def api_post(path, body):
    r = requests.post(f"{BASE}{path}", headers=H, json=body, timeout=120)
    r.raise_for_status()
    return r.json()


def tenant_customer_ids():
    """Distinct, order-preserving customer_id values from the CSV."""
    seen = []
    with open(CSV_PATH, newline="") as f:
        for row in csv.DictReader(f):
            cid = (row.get("customer_id") or "").strip()
            if cid and cid not in seen:
                seen.append(cid)
    return seen


def extension_models():
    """customer_id (model name) -> extension model id, for this hub's extensions."""
    out = {}
    for m in api_get("/api/v1/models")["records"]:
        if m.get("modelKind") == "SHARED_EXTENSION" and m.get("baseModelId") == HUB_MODEL_ID:
            out[m.get("name")] = m.get("id")
    return out


def custom_fields(ext_model_id):
    """[(field_name, label)] for the tenant's dim_subject custom dimensions."""
    files = api_get(f"/api/v1/models/{ext_model_id}/yaml", fileName=VIEW_FILE)["files"]
    view = yaml_load(files[VIEW_FILE])
    fields = []
    for name, meta in (view.get("dimensions") or {}).items():
        if name in BASE_COLS or not isinstance(meta, dict) or "sql" not in meta:
            continue
        fields.append((name, meta.get("label", name)))
    return fields


def existing_dashboard(name):
    """Return identifier of an existing published dashboard with this name, else None."""
    docs = api_get("/api/v1/documents")
    for rec in docs.get("records", []):
        if rec.get("name") == name and rec.get("hasDashboard"):
            return rec.get("identifier")
    return None


def build_document(name, fields):
    field_refs = [f"{VIEW}.{n}" for n, _ in fields]
    picker_id = "".join(random.choices(string.ascii_letters + string.digits, k=8))
    options = [
        {
            "label": label,
            "value": f"{VIEW}.{n}",
            "viewLabel": f"{VIEW_LABEL} • {label}",
            "isDimension": True,
        }
        for n, label in fields
    ]
    return {
        "name": name,
        "modelId": HUB_MODEL_ID,
        "facetFilters": False,
        "filterConfig": {picker_id: {"id": picker_id, "type": "FIELD_PICKER", "options": options}},
        "filterOrder": [picker_id],
        "queryPresentations": [
            {
                "name": "Subjects",
                "topicName": VIEW,
                "fields": field_refs + [COUNT_FIELD],
                "query": {
                    "table": VIEW,
                    "fields": field_refs + [COUNT_FIELD],
                    "sorts": [{"column_name": COUNT_FIELD, "sort_descending": True}],
                    "limit": 1000,
                    "join_paths_from_topic_name": VIEW,
                },
            }
        ],
    }


def main():
    ext = extension_models()
    mapping = {}
    for customer_id in tenant_customer_ids():
        print(f"Tenant {customer_id}:")
        ext_id = ext.get(customer_id)
        if not ext_id:
            print("    No extension model found — run generate.py first. Skipping.")
            continue

        fields = custom_fields(ext_id)
        if not fields:
            print("    No custom fields found. Skipping.")
            continue

        name = f"{customer_id}{DASH_SUFFIX}"
        identifier = existing_dashboard(name)
        if identifier:
            print(f"    Dashboard already exists ({identifier}), reusing.")
        else:
            print(f"    Creating dashboard with {len(fields)} fields: {[n for n, _ in fields]}")
            api_post("/api/v1/documents", build_document(name, fields))
            identifier = existing_dashboard(name)
            print(f"    Created: {identifier}")
        mapping[customer_id] = identifier

    print("\nTENANTS mapping for embed-app/lib/tenants.ts:")
    for cid, ident in mapping.items():
        print(f'  {cid}: {{ dashboardId: "{ident}" }},')


if __name__ == "__main__":
    main()
