from omni_python_sdk import OmniAPI
from yaml import safe_load as yaml_load, dump as yaml_dump
import pyarrow
from dotenv import load_dotenv
load_dotenv()


# Define your query which pulls the unique keys and data types
query = {'query':{
  "sorts": [
    {
      "column_name": "custom_profile_fields.company_id",
      "sort_descending": False
    }
  ],
  "table": "custom_profile_fields",
  "fields": [
    "custom_profile_fields.company_id",
    "custom_profile_fields.field_name",
    "custom_profile_fields.data_type"
  ],
  "pivots": [],
  "dbtMode": False,
  "filters": {},
  "modelId": "4cdba071-e61c-4881-99b0-d9d225fdc770",
  "version": 7,
  "rewriteSql": True,
  "column_limit": 50,
  "dimensionIndex": 3,
  "default_group_by": True,
  "custom_summary_types": {},
  "join_paths_from_topic_name": "custom_profile_fields"
}}


def transform_query_data(query_data:pyarrow.lib.ChunkedArray) -> dict:
    # Transform the query data into a dictionary with company_id as keys
    transformed = {}
    for row in query_data:
        company_id = int(str(row['custom_profile_fields.company_id']))
        field_name = str(row['custom_profile_fields.field_name'])
        data_type = str(row['custom_profile_fields.data_type'])
        
        if company_id not in transformed:
            transformed[company_id] = {}
        
        transformed[company_id].update({
            field_name: {
            'data_type': data_type
            }
        })
    return transformed


# Initialize the API with your credentials
api = OmniAPI(env_file='.env')

# Run the driving metadata query, with the company_id, field_name, and data_type
table = api.run_query_blocking(query)
# Transform the metadata query results into a dictionary
customers = transform_query_data(table[0].to_struct_array())


# Get the core / hub model
model = api.list_models(name='eav', modelKind='SHARED')['records'][0]
modelID, connectionID = model['id'], model['connectionId']
extensionModels = api.list_models(baseModelId=modelID, modelKind='SHARED_EXTENSION')
modelFile = api.yamlr(modelID, body={'fileName': 'model'})
userProfileTopicFile = api.yamlr(modelID, body={'fileName': 'user_profile.topic'})['files']['user_profile.topic']

# Obtain the currently existing extension models (if any)
extensionModels = {
            model['name']:model 
            for model in api.list_models(
                                baseModelId=modelID,
                                modelKind='SHARED_EXTENSION'
                                )['records']
            }
# Define the mapping of data types to SQL expressions for easier field creation
type_map = {
    'boolean': '${boolean_value}',
    'string': '${string_value}',
    'number': '${numeric_value}',
    'datetime': '${date_value}',
}

for customer_id, fields in customers.items():
    print(f"Processing company ID: {customer_id}")
    cid = f'c{customer_id}'
    # Step 1) Create Extension Model if it doesn't exist
    if cid in extensionModels:
        print(f"    Extension model for company {customer_id} already exists, skipping creation.")
        tenantModel = { 'model': extensionModels[cid] }
    else:
        print(f"    Creating extension model for company {customer_id}.")
        tenantModel = api.create_model(
            modelName=cid,
            connection_id=connectionID,
            baseModelId=modelID,
            modelKind='SHARED_EXTENSION',
        )
    # Step 2) Set up the custom fields and flattened custom fields dicts 
    customProfileFields = {'measures':{}}
    flatteningQueryView = {
                        'query':{
                                'fields': {
                                    'custom_profile_fields.user_id': 'user_id'
                                    },
                                'base_view': 'custom_profile_fields', 
                                'filters': {'custom_profile_fields.company_id_str': {'bind': 'user_profile.company_id_str'}}, 
                                'topic': 'custom_profile_fields'
                             },
                            'dimensions': {
                                'user_id': {
                                    'primary_key': True,
                                    'hidden': True
                                },
                                }
                             }
    # Loop over the metadata query, adding each field to the customProfileFields and flatteningQueryView dicts
    for field in fields:
        dataType = fields[field]['data_type']
        print(f"    Adding field {field} with data type {dataType}")
        customProfileFields['measures'][field] = {
            'sql': type_map[dataType],
            'aggregate_type': 'max',
            'filters': {
                'field_name': {
                    'is': field,
                }
            }
        }
        # Add the field to the flattening query view
        flatteningQueryView['query']['fields'][f'custom_profile_fields.{field}'] = field
        flatteningQueryView['dimensions'][field] = {}
    
    # Step 3) write the two YAML files to the extension model
    api.yamlw(tenantModel['model']['id'], 
            {
                'fileName': f'PUBLIC/custom_profile_fields.view',
                'yaml': yaml_dump(customProfileFields),
                'mode': 'extension',
                'commitMessage': f'Add custom field {field} for company {customer_id}',
            }
            )
    
    api.yamlw(tenantModel['model']['id'],
            {
                'fileName': f'tenant_flattened_fields.query.view',
                'yaml': yaml_dump(flatteningQueryView),
                'mode': 'extension',
                'commitMessage': f'Add custom field {field} for company {customer_id}',
            }
            )
    print(f"    Wrote custom extension files.")
    
    # Step 4) Add extension model to the hub mappings
    modelContents = yaml_load(api.yamlr(modelID, body={'fileName': 'model'})['files']['model'])
    modelContents['dynamic_shared_extensions'][0]['mappings'].update({cid:{'values_for_model':[f'{customer_id}']}})
    api.yamlw(modelID, {
        "fileName": f"model",
        "yaml": yaml_dump(modelContents),
        "mode": "combined",
        "commitMessage": f"Add mapping for {customer_id}",
    })
    print(f"    Written to hub model mappings. Finished processing company ID: {customer_id}\n")


