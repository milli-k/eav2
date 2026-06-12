"""Generate per-tenant dim_subject extension models in Omni.

For each tenant (customer_id) in your subjects CSV, this script:
  1. Parses the packed `dim_subject` column to discover each field and its
     maximum hierarchy depth across all rows for that tenant.
  2. Builds a flat set of Omni dimensions (one per field × hierarchy level)
     with BigQuery-compatible SQL.
  3. Creates a SHARED_EXTENSION model for the tenant in Omni (if it doesn't
     already exist) and writes the dimension YAML to it.
  4. Updates the hub model's `dynamic_shared_extensions` map_pattern so the
     correct extension is loaded per-tenant at query time.

Configuration
-------------
Copy `.env.example` to `.env` and fill in your values before running.

Required environment variables
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
OMNI_API_KEY            Your Omni API key.
OMNI_BASE_URL           Your Omni instance URL, e.g. https://yourorg.omniapp.co

Optional environment variables
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
CSV_PATH                Path to your subjects CSV (default: dim_subject.csv).
                        Required columns: customer_id, dim_subject
MODEL_ID                The UUID of your hub (base) model in Omni.
DIM_SUBJECT_FILE        The view file path inside the model that backs your
                        dim_subject table.
                        Format: <database>.<schema>/<view_name>.view
                        Example: my_project.my_dataset/dim_subject.view
TENANT_ATTRIBUTE        The Omni user attribute used to resolve which extension
                        to load per tenant (default: customer_id).

Usage
-----
  # Dry-run — see what would be generated without touching the API
  python generate.py --dry-run

  # Run for all tenants
  python generate.py

  # Run for a single tenant only
  python generate.py --tenant TENANT_ID

  # Verbose output (prints full YAML written per tenant)
  python generate.py -v
"""
import argparse
import csv
import logging
import os
import re
import sys
from collections import defaultdict
from dotenv import load_dotenv
from omni_python_sdk import OmniAPI
from yaml import safe_load as yaml_load, dump as _yaml_dump


logger = logging.getLogger('dim_subject')


def yaml_dump_wide(data):
    # width=inf prevents PyYAML from line-wrapping long scalars (e.g. dimension
    # SQL). Omni's YAML parser doesn't always fold wrapped plain scalars back
    # into single-line strings, so a wrap inside a regex literal corrupts the
    # pattern and silently returns NULL.
    return _yaml_dump(data, width=float('inf'))


load_dotenv()  # picks up OMNI_BASE_URL and OMNI_API_KEY for OmniAPI

# ---------------------------------------------------------------------------
# Configuration — override any of these via environment variables or .env
# ---------------------------------------------------------------------------

# Path to your subjects CSV.
# Required columns: customer_id, dim_subject
# Optional column:  subject_id (used by embed_app.py for filter targeting)
CSV_PATH = os.environ.get('CSV_PATH', 'dim_subject.csv')

# UUID of your hub (base) model in Omni.
# Find this in the model URL: https://yourorg.omniapp.co/models/<MODEL_ID>
MODEL_ID = os.environ.get('MODEL_ID', 'YOUR_HUB_MODEL_UUID')

# Path to the view file inside the model that backs your dim_subject table.
# Format:  <database>.<schema>/<view_name>.view
# Example: my_project.my_dataset/dim_subject.view
DIM_SUBJECT_FILE = os.environ.get('DIM_SUBJECT_FILE', 'YOUR_PROJECT.YOUR_DATASET/dim_subject.view')

# The Omni user attribute used to select the tenant's extension model at
# query time. This must match the user attribute name configured in Omni
# (Settings → User Attributes) and set on each embedded user's session.
TENANT_ATTRIBUTE = os.environ.get('TENANT_ATTRIBUTE', 'customer_id')

# ---------------------------------------------------------------------------
# Field name normalization
# ---------------------------------------------------------------------------

# Map variant field names to a canonical name when they share the same data.
# Keys and values should be in Title Case (applied after normalization).
# e.g. FIELD_ALIASES = {'Mkt': 'Market'}
# Leave empty if your field names are already consistent across tenants.
FIELD_ALIASES = {}


def normalize_field_name(name):
    """Canonicalize a raw field name so casing/whitespace variants merge.

    Collapses internal runs of whitespace, strips, and Title Cases the name
    (so 'location', ' Location ', and 'LOCATION' all converge), then applies
    FIELD_ALIASES. Used before depth accumulation AND before building the
    regex pattern/label, so a single canonical dimension is produced per field.
    """
    cleaned = re.sub(r'\s+', ' ', name).strip()
    canonical = cleaned.title()
    return FIELD_ALIASES.get(canonical, canonical)


def parse_dim_subject(packed):
    """Parse a packed dim_subject string into [(field_name, [levels]), ...].

    Fields are delimited by ';' or newlines; within a field the form is
    'Name: levelA > levelB > ...'. Trailing empty levels are dropped so depth
    reflects only populated values. Field names are normalized so variants
    merge instead of producing duplicate dimensions.

    Example input:  'Region: EMEA > UK > London; Product: SaaS > Analytics'
    Example output: [('Region', ['EMEA', 'UK', 'London']),
                     ('Product', ['SaaS', 'Analytics'])]
    """
    fields = []
    for segment in re.split(r'[;\n]', packed or ''):
        segment = segment.strip()
        if ':' not in segment:
            continue
        name, _, value = segment.partition(':')
        name = normalize_field_name(name)
        if not name:
            continue
        levels = [lvl.strip() for lvl in value.split('>')]
        while levels and not levels[-1]:
            levels.pop()
        fields.append((name, levels))
    return fields


def slug(name):
    """snake_case a field name into an Omni-safe field identifier."""
    s = re.sub(r'[^0-9a-z]+', '_', name.strip().lower()).strip('_')
    return s or 'field'


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------

def load_tenants(csv_path):
    """Discover, per tenant (customer_id), each field and the max number of
    hierarchy levels it reaches across that tenant's rows.

    Different tenants may carry different fields, which is why each gets its
    own extension model.
    """
    tenants = defaultdict(dict)  # customer_id -> {field_name: max_depth}
    with open(csv_path, newline='') as f:
        for row in csv.DictReader(f):
            customer_id = (row.get('customer_id') or '').strip()
            if not customer_id:
                continue
            for field_name, levels in parse_dim_subject(row.get('dim_subject')):
                current = tenants[customer_id].get(field_name, 0)
                tenants[customer_id][field_name] = max(current, len(levels))
    return tenants


# ---------------------------------------------------------------------------
# Dimension builder — BigQuery SQL
# ---------------------------------------------------------------------------

def build_dim_view(fields):
    """Build one dimension per (field, hierarchy level) using BigQuery SQL.

    Level 1 keeps the field's own name; deeper levels get a numeric suffix
    (e.g. `region_2`, `region_3`). Each dimension's SQL:
      1. Extracts the field's segment from the packed dim_subject column using
         REGEXP_EXTRACT (case-insensitive via (?i) flag).
      2. Splits the extracted value on ' > ' using SPLIT.
      3. Returns the requested level using SAFE_OFFSET (0-based, so level N
         uses index N-1). Returns NULL when the level doesn't exist, rather
         than raising an error.

    Notes on BigQuery compatibility vs Snowflake/DuckDB:
      - REGEXP_EXTRACT replaces regexp_extract(col, pattern, group).
      - SPLIT(...)[SAFE_OFFSET(n)] replaces regexp_split_to_array(...)[n].
      - SAFE_OFFSET returns NULL (not an error) for out-of-range indices.
      - TRIM() works identically.
      - (?i) inline flag is supported by RE2 (BigQuery's regex engine).
    """
    dim_view = {'dimensions': {}}
    for field_name, max_depth in fields.items():
        base = slug(field_name)
        name_pat = re.escape(field_name)
        for level in range(1, max_depth + 1):
            field = base if level == 1 else f'{base}_{level}'
            label = field_name if level == 1 else f'{field_name} {level}'
            logger.info(f"    Adding dimension '{field}' label '{label}'")
            # REGEXP_EXTRACT pulls the field's value from the packed string.
            # (?i) makes the field-name match case-insensitive so the pattern
            # matches mixed-case stored text (e.g. 'region:' or 'Region:').
            extract = (
                f"REGEXP_EXTRACT(${{dim_subject}}, "
                f"r'(?i){name_pat}:\\s*([^;\\n]*)')"
            )
            # SPLIT on ' > ' (with optional surrounding whitespace trimmed
            # by TRIM below). SAFE_OFFSET is 0-based, so level 1 → index 0.
            sql = f"TRIM(SPLIT({extract}, ' > ')[SAFE_OFFSET({level - 1})])"
            dim_view['dimensions'][field] = {'sql': sql, 'label': label}
    return dim_view


# ---------------------------------------------------------------------------
# Per-tenant processing
# ---------------------------------------------------------------------------

def process_tenant(customer_id, fields, api, connection_id, extension_models, dry_run):
    """Create/reuse the tenant's extension model and write its flattened
    dimensions.

    In dry-run mode nothing is created or written — the dimensions and
    resulting YAML are logged instead.
    """
    logger.info(f"Processing tenant: {customer_id}")

    # Build the dimensions first; this is pure and safe in dry-run.
    dim_view = build_dim_view(fields)
    yaml_text = yaml_dump_wide(dim_view)

    if dry_run:
        logger.info(f"    [dry-run] would write {DIM_SUBJECT_FILE}:")
        logger.info("\n" + yaml_text)
        logger.info(f"    [dry-run] done with {customer_id}.\n")
        return

    # Echo the full YAML payload in verbose/debug mode.
    logger.debug("YAML for %s:\n%s", customer_id, yaml_text)

    # Create extension model if it doesn't already exist.
    if customer_id in extension_models:
        logger.info("    Extension model already exists, skipping creation.")
        tenant_model = {'model': extension_models[customer_id]}
    else:
        logger.info("    Creating extension model.")
        tenant_model = api.create_model(
            modelName=customer_id,
            connection_id=connection_id,
            baseModelId=MODEL_ID,
            modelKind='SHARED_EXTENSION',
        )

    # Write the dimension extension to the spoke model.
    logger.info(f"    Writing {DIM_SUBJECT_FILE} ...")
    api.yamlw(tenant_model['model']['id'], {
        'fileName':      DIM_SUBJECT_FILE,
        'yaml':          yaml_text,
        'mode':          'extension',
        'commitMessage': f'Add flattened dim_subject fields for {customer_id}',
    })
    logger.info(f"    Done with {customer_id}.\n")


# ---------------------------------------------------------------------------
# Hub model update
# ---------------------------------------------------------------------------

def update_hub_model(api):
    """Update the hub model so it resolves the correct extension per tenant.

    Sets `dynamic_shared_extensions[0].map_pattern` to the TENANT_ATTRIBUTE
    user attribute. Omni evaluates this at query time to select the matching
    extension model for the logged-in user.
    """
    model_contents = yaml_load(api.yamlr(MODEL_ID, body={'fileName': 'model'})['files']['model'])
    extensions = model_contents.setdefault('dynamic_shared_extensions', [{}])
    if not extensions:
        extensions.append({})
    extensions[0]['map_pattern'] = f'{{{{ omni_attributes.{TENANT_ATTRIBUTE} }}}}'
    extensions[0].pop('mappings', None)
    api.yamlw(MODEL_ID, {
        'fileName':      'model',
        'yaml':          yaml_dump_wide(model_contents),
        'mode':          'combined',
        'commitMessage': 'Set dynamic map_pattern for tenant extensions',
    })
    logger.info("Hub model map_pattern set.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Generate per-tenant dim_subject extension models in Omni.')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print the dimensions/YAML that would be generated '
                             'per tenant and make zero API calls.')
    parser.add_argument('--tenant',
                        help='Process only the given customer_id, leaving other '
                             'tenants untouched.')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable DEBUG logging and echo the full YAML written '
                             'for each tenant.')
    parsed_args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if parsed_args.verbose else logging.INFO,
        format='%(levelname)s %(message)s',
    )

    tenants = load_tenants(CSV_PATH)

    if parsed_args.tenant:
        if parsed_args.tenant not in tenants:
            logger.error("Tenant %s not found in %s", parsed_args.tenant, CSV_PATH)
            sys.exit(1)
        tenants = {parsed_args.tenant: tenants[parsed_args.tenant]}

    api = None
    connection_id = None
    extension_models = {}
    if not parsed_args.dry_run:
        # Initialize the Omni API client.
        # Reads OMNI_BASE_URL and OMNI_API_KEY from .env automatically.
        api = OmniAPI(env_file='.env')

        # Fetch the hub model to get its connectionId.
        all_models = api.list_models(modelKind='SHARED')['records']
        model = next(m for m in all_models if m['id'] == MODEL_ID)
        connection_id = model['connectionId']

        # Fetch existing extension models to avoid creating duplicates.
        extension_models = {
            m['name']: m
            for m in api.list_models(baseModelId=MODEL_ID, modelKind='SHARED_EXTENSION')['records']
        }

    # Process each tenant in isolation: a failure on one tenant is logged and
    # skipped so the rest of the run still completes.
    failures = {}
    for customer_id, fields in tenants.items():
        try:
            process_tenant(customer_id, fields, api, connection_id,
                           extension_models, parsed_args.dry_run)
        except Exception as exc:
            logger.exception("Failed to process tenant %s: %s", customer_id, exc)
            failures[customer_id] = exc

    if not parsed_args.dry_run:
        update_hub_model(api)

    if failures:
        logger.error("Completed with errors. Failed tenants: %s",
                     ', '.join(sorted(failures)))
        sys.exit(1)


if __name__ == '__main__':
    main()
