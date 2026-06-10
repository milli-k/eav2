import csv
import re
from collections import defaultdict
from dotenv import load_dotenv
from omni_python_sdk import OmniAPI
from yaml import safe_load as yaml_load, dump as _yaml_dump


def yaml_dump_wide(data):
    # width=inf prevents PyYAML from line-wrapping long scalars (e.g. dimension
    # SQL). Omni's YAML parser doesn't always fold wrapped plain scalars back
    # into single-line strings, so a wrap inside a regex literal corrupts the
    # pattern and silently returns NULL.
    return _yaml_dump(data, width=float('inf'))


load_dotenv()  # picks up Omni host / api key for OmniAPI

# Local CSV holding the subjects. Tenants are the distinct customer_id values;
# the packed `dim_subject` column holds the custom fields we flatten into
# one column per hierarchy level (see dim_subject_abc_flat.csv for the target).
CSV_PATH = 'dim_subject.csv'

MODEL_ID = '73a858a3-6778-47b7-8fee-9facd105d30e'

# Hub view file backing the warehouse `dim_subject` table. Each tenant
# extension adds parsed-out dimensions to this view. The SQL references the
# raw column via ${dim_subject}, which assumes the hub view exposes the
# dim_subject column as a dimension of that name.
DIM_SUBJECT_FILE = 'my_db.main/dim_subject.view'

# Omni user attribute that resolves which extension to load per tenant.
TENANT_ATTRIBUTE = 'customer_id'


def parse_dim_subject(packed):
    """Parse a packed dim_subject string into [(field_name, [levels]), ...].

    Fields are delimited by ';' or newlines; within a field the form is
    'Name: levelA > levelB > ...'. Trailing empty levels (e.g. a dangling
    '> ') are dropped so depth reflects only populated levels.
    """
    fields = []
    for segment in re.split(r'[;\n]', packed or ''):
        segment = segment.strip()
        if ':' not in segment:
            continue
        name, _, value = segment.partition(':')
        name = name.strip()
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


# Discover, per tenant (customer_id), each field and the max number of
# hierarchy levels it reaches across that tenant's rows. Different tenants
# carry different fields, which is exactly why each gets its own extension.
tenants = defaultdict(dict)  # customer_id -> {field_name: max_depth}
with open(CSV_PATH, newline='') as f:
    for row in csv.DictReader(f):
        customer_id = (row.get('customer_id') or '').strip()
        if not customer_id:
            continue
        for field_name, levels in parse_dim_subject(row.get('dim_subject')):
            current = tenants[customer_id].get(field_name, 0)
            tenants[customer_id][field_name] = max(current, len(levels))


# Initialize the API with your credentials
api = OmniAPI(env_file='.env')

# Fetch the hub model (to get connectionId)
all_models = api.list_models(modelKind='SHARED')['records']
model = next(m for m in all_models if m['id'] == MODEL_ID)
connectionID = model['connectionId']

# Obtain the currently existing extension models
extensionModels = {
    m['name']: m
    for m in api.list_models(baseModelId=MODEL_ID, modelKind='SHARED_EXTENSION')['records']
}


for customer_id, fields in tenants.items():
    print(f"Processing tenant: {customer_id}")

    # Step 1) Create extension model if it doesn't exist
    if customer_id in extensionModels:
        print("    Extension model already exists, skipping creation.")
        tenantModel = {'model': extensionModels[customer_id]}
    else:
        print("    Creating extension model.")
        tenantModel = api.create_model(
            modelName=customer_id,
            connection_id=connectionID,
            baseModelId=MODEL_ID,
            modelKind='SHARED_EXTENSION',
        )

    # Step 2) Build one dimension per (field, hierarchy level). Level 1 keeps
    # the field's own name; deeper levels get a generic 'Name N' suffix. Each
    # dimension's SQL pulls the field's segment out of the packed dim_subject
    # column (up to the next ';' or newline), splits it on '>', and trims the
    # requested level. list index is 1-based; out-of-range yields NULL.
    # regexp_split_to_array on '\s*>\s*' trims whitespace around each level
    # during the split; the regex literals avoid PyYAML line-wrap corruption.
    dimView = {'dimensions': {}}
    for field_name, max_depth in fields.items():
        base = slug(field_name)
        name_pat = re.escape(field_name)
        for level in range(1, max_depth + 1):
            field = base if level == 1 else f'{base}_{level}'
            label = field_name if level == 1 else f'{field_name} {level}'
            print(f"    Adding dimension '{field}' label '{label}'")
            value = f"regexp_extract(${{dim_subject}}, '{name_pat}:\\s*([^;\\n]*)', 1)"
            sql = f"trim(regexp_split_to_array({value}, '\\s*>\\s*')[{level}])"
            dimView['dimensions'][field] = {'sql': sql, 'label': label}

    # Step 3) Write the dimension extension to the spoke
    print(f"    Writing {DIM_SUBJECT_FILE} ...")
    api.yamlw(tenantModel['model']['id'], {
        'fileName':      DIM_SUBJECT_FILE,
        'yaml':          yaml_dump_wide(dimView),
        'mode':          'extension',
        'commitMessage': f'Add flattened dim_subject fields for {customer_id}',
    })
    print(f"    Done with {customer_id}.\n")


# Step 4) Ensure the hub model resolves the extension per tenant via customer_id
modelContents = yaml_load(api.yamlr(MODEL_ID, body={'fileName': 'model'})['files']['model'])
extensions = modelContents.setdefault('dynamic_shared_extensions', [{}])
if not extensions:
    extensions.append({})
extensions[0]['map_pattern'] = f'{{{{ omni_attributes.{TENANT_ATTRIBUTE} }}}}'
extensions[0].pop('mappings', None)
api.yamlw(MODEL_ID, {
    'fileName':      'model',
    'yaml':          yaml_dump_wide(modelContents),
    'mode':          'combined',
    'commitMessage': 'Set dynamic map_pattern for tenant extensions',
})
print("Hub model map_pattern set.")
