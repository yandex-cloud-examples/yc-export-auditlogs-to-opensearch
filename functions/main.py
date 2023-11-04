import requests
import json
import os
import boto3
import time
import base64


# Function - Get token
def get_token():
    response = requests.get('http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token', headers={"Metadata-Flavor":"Google"})
    return response.json().get('access_token')

# Function - Decrypt data with KMS key
def decrypt_secret_kms(secret):
    token = get_token()
    request_suffix = f"{kms_key_id}:decrypt"
    request_json_data = {'ciphertext': secret}
    response = requests.post('https://kms.yandex/kms/v1/keys/'+request_suffix, data=json.dumps(request_json_data), headers={"Accept":"application/json", "Authorization": "Bearer "+token})
    b64_data = response.json().get('plaintext')
    return base64.b64decode(b64_data).decode()

# # Configuration - Get ElasticSearch CA.pem
# def get_elastic_cert():
#     file = '/app/include/CA.pem'
#     if os.path.isfile(file):
#         return file
#     else:
#         url = 'https://storage.yandexcloud.net/cloud-certs/CA.pem'
#         response = requests.get(url)
#         with open('/app/include/CA.pem', 'wb') as f:
#             f.write(response.content)
#         return file


# Configuration - Keys
kms_key_id              = os.environ['KMS_KEY_ID']
elastic_auth_pw_encr    = os.environ['ELK_PASS_ENCR']
s3_key_encr             = os.environ['S3_KEY_ENCR']
s3_secret_encr          = os.environ['S3_SECRET_ENCR']

# Configuration - Setting up variables for ElasticSearch
elastic_server          = os.environ['ELASTIC_SERVER']
elastic_auth_user       = os.environ['ELASTIC_AUTH_USER']
elastic_auth_pw         = decrypt_secret_kms(elastic_auth_pw_encr)
elastic_index_name      = f"{os.environ['ELASTIC_INDEX_NAME']}-000001"
elastic_index_alias     = "audit-trails-index"
elastic_index_template  = "audit-trails-template"
elastic_index_ilm       = "audit-trails-ilm"
elastic_index_pipeline  = "audit-trails-pipeline"
kibana_server           = os.environ['KIBANA_SERVER']
fals = False #tls validation disable (please enable it when you use valid certificate)
#elastic_cert            = get_elastic_cert()

# Configuration - Setting up variables for S3
s3_key                  = decrypt_secret_kms(s3_key_encr)
s3_secret               = decrypt_secret_kms(s3_secret_encr)
s3_bucket               = os.environ['S3_BUCKET']
s3_folder               = os.environ['S3_FOLDER']
s3_local                = '/tmp/s3'

# Configuration - Sleep time
if(os.getenv('SLEEP_TIME') is not None):
    sleep_time = int(os.environ['SLEEP_TIME'])
else:
    sleep_time = 240


# State - Setting up S3 client
s3 = boto3.resource('s3',
    endpoint_url            = 'https://storage.yandexcloud.net',
    aws_access_key_id       = s3_key,
    aws_secret_access_key   = s3_secret 
)

# Create tenant
def create_tenant():
    request_suffix  = "/_plugins/_security/api/tenants/at-tenant"
    request_json    = """{
        "description": "A tenant for the yandex cloud audit trails events."
    }"""
    response = requests.put(elastic_server+request_suffix, data=request_json, verify=fals, auth=(elastic_auth_user, elastic_auth_pw), headers={"Content-Type":"application/json"})
    if(response.status_code == 200):
        print('Tenant -- CREATED')
    print(f"{response.status_code} - {response.text}")

# Function - Create config index in ElasticSearch
def create_config_index():
    request_suffix  = f"/.state-{elastic_index_alias}"
    response        = requests.get(elastic_server+request_suffix, verify=fals, auth=(elastic_auth_user, elastic_auth_pw))
    if(response.status_code == 404):
        request_suffix  = f"/.state-{elastic_index_alias}/_doc/1"
        request_json    = """{
            "is_configured": true
        }"""
        response = requests.post(elastic_server+request_suffix, data=request_json, verify=fals, auth=(elastic_auth_user, elastic_auth_pw), headers={"Content-Type":"application/json"})
        print('Config index -- CREATED')
    else:
        print('Config index -- EXISTS')
    print(f"{response.status_code} - {response.text}")


# Function - Get config index state
def get_config_index_state():
    request_suffix  = f"/.state-{elastic_index_alias}/_doc/1"
    response        = requests.get(elastic_server+request_suffix, verify=fals, auth=(elastic_auth_user, elastic_auth_pw))
    if(response.status_code != 200):
        return False
    print(f"{response.status_code} - {response.text}")
    return True
    


# Function - Create ingest pipeline
def create_ingest_pipeline():
    request_suffix  = f"/_ingest/pipeline/{elastic_index_pipeline}"
    data_file       = open('/app/include/audit-trail/pipeline.json')
    data_json       = json.load(data_file)
    data_file.close()
    response        = requests.put(elastic_server+request_suffix, json=data_json, verify=fals, auth=(elastic_auth_user, elastic_auth_pw), headers={"securitytenant":"at-tenant"})
    if(response.status_code == 200):
        print('Ingest pipeline -- CREATED')
    print(f"{response.status_code} - {response.text}")




# Function - Create an index lifecycle policy
def create_lifecycle_policy():
    request_suffix  = f"/_plugins/_ism/policies/{elastic_index_ilm}"
    data_file       = open('/app/include/audit-trail/ism-policy.json')
    data_json       = json.load(data_file)
    data_file.close()

    response = requests.put(elastic_server+request_suffix, json=data_json, verify=fals, auth=(elastic_auth_user, elastic_auth_pw), headers={"Content-Type":"application/json", "securitytenant":"at-tenant"})
    if(response.status_code == 200):
        print('Index lifecycle policy -- CREATED')
    print(f"{response.status_code} - {response.text}")



# Function - Create an index template
def create_index_template():
    request_suffix  = f"/_index_template/{elastic_index_template}"
    data_file       = open('/app/include/audit-trail/index-template.json')
    data_json       = json.load(data_file)
    data_file.close()
    response        = requests.put(elastic_server+request_suffix, json=data_json, verify=fals, auth=(elastic_auth_user, elastic_auth_pw), headers={"Content-Type":"application/json", "securitytenant":"at-tenant"})
    if(response.status_code == 200):
        print('Index template -- CREATED')
    print(f"{response.status_code} - {response.text}")


# Function - Create an index
def create_first_index():
    request_suffix  = f"/{elastic_index_name}"
    response        = requests.put(elastic_server+request_suffix, verify=fals, auth=(elastic_auth_user, elastic_auth_pw), headers={"securitytenant":"at-tenant"})
    if(response.status_code == 200):
        print(f"Index {elastic_index_name} -- CREATED")
    print(f"{response.status_code} - {response.text}")


# Function - Create an index alias
def create_index_alias():
    request_suffix  = f"/_aliases"
    request_json    = """{
        "actions" : [
            { "add" : { "index" : "%s", "alias" : "%s" } }
        ]
    }""" % (elastic_index_name, elastic_index_alias)
    response = requests.post(elastic_server+request_suffix, data=request_json, verify=fals, auth=(elastic_auth_user, elastic_auth_pw), headers={"Content-Type":"application/json", "securitytenant":"at-tenant"})
    if(response.status_code == 200):
        print('Index alias -- CREATED')
    print(f"{response.status_code} - {response.text}")


# Function - Refresh index
def refresh_index():
    request_suffix  = f"/{elastic_index_alias}/_refresh"
    response        = requests.post(elastic_server+request_suffix, verify=fals, auth=(elastic_auth_user, elastic_auth_pw), headers={"securitytenant":"at-tenant"})
    if(response.status_code == 200):
        print('Index -- REFRESHED')
    print(f"{response.status_code} - {response.text}")



#----
# Function - Preconfigure Kibana
def configure_kibana():
    #Index pattern
    data_file = {
        'file': open('/app/include/audit-trail/index-pattern.ndjson', 'rb')
    }
    request_suffix = '/api/saved_objects/_import'
    response = requests.post(kibana_server+request_suffix, files=data_file, verify=fals, auth=(elastic_auth_user, elastic_auth_pw), headers={"osd-xsrf":"true", "securitytenant":"at-tenant"})
    if(response.status_code == 200):
        print('Index patterns -- IMPORTED')
    print(f"{response.status_code} - {response.text}")

# Filters
    data_file = {
        'file': open('/app/include/audit-trail/filters.ndjson', 'rb')
    }
    request_suffix = '/api/saved_objects/_import'
    response = requests.post(kibana_server+request_suffix, files=data_file, verify=fals, auth=(elastic_auth_user, elastic_auth_pw), headers={"osd-xsrf":"true", "securitytenant":"at-tenant"})
    if(response.status_code == 200):
        print('Filters -- IMPORTED')
    print(f"{response.status_code} - {response.text}")

# Search
    data_file = {
        'file': open('/app/include/audit-trail/search.ndjson', 'rb')
    }
    request_suffix = '/api/saved_objects/_import'
    response = requests.post(kibana_server+request_suffix, files=data_file, verify=fals, auth=(elastic_auth_user, elastic_auth_pw), headers={"osd-xsrf":"true", "securitytenant":"at-tenant"})
    if(response.status_code == 200):
        print('Searches -- IMPORTED')
    print(f"{response.status_code} - {response.text}")

#Detections Alerts monitors
    request_suffix  = "/_plugins/_alerting/monitors"
    data_file       = open('/app/include/audit-trail/alert.json')
    data_json       = json.load(data_file)
    data_file.close()

    response = requests.post(elastic_server+request_suffix, json=data_json, verify=fals, auth=(elastic_auth_user, elastic_auth_pw), headers={"Content-Type":"application/json", "securitytenant":"at-tenant"})
    if(response.status_code == 200):
        print('Alert monitor uploaded -- CREATED')
    print(f"{response.status_code} - {response.text}")

#Dashboard
    data_file = {
        'file': open('/app/include/audit-trail/dashboard.ndjson', 'rb')
    }
    request_suffix = '/api/saved_objects/_import?overwrite=true'
    response = requests.post(kibana_server+request_suffix, files=data_file, verify=fals, auth=(elastic_auth_user, elastic_auth_pw), headers={"osd-xsrf":"true", "securitytenant":"at-tenant"})
    if(response.status_code == 200):
        print('Dashboard -- IMPORTED')
    print(f"{response.status_code} - {response.text}")


# Function - Download JSON logs to local folder
def download_s3_folder(s3_bucket, s3_folder, local_folder=None):
    print('JSON download -- STARTED')
    bucket = s3.Bucket(s3_bucket)
    if not os.path.exists(local_folder):
            os.makedirs(local_folder)
    for obj in bucket.objects.filter(Prefix=s3_folder):
        target = obj.key if local_folder is None \
            else os.path.join(local_folder, os.path.relpath(obj.key, s3_folder))
        if not os.path.exists(local_folder):
            os.makedirs(local_folder)
        if obj.key[-1] == '/':
            continue
        # Downloading JSON logs in a flat-structured way
        bucket.download_file(obj.key, local_folder+'/'+target.rsplit('/')[-1])
    print('JSON download -- COMPLETE')


# Function - Clean up S3 folder
def delete_objects_s3(s3_bucket, s3_folder):
    bucket = s3.Bucket(s3_bucket)
    for obj in bucket.objects.filter(Prefix=s3_folder):
        if(obj.key != s3_folder+'/'):
            bucket.delete_objects(
                Delete={
                    'Objects': [
                        {
                            'Key': obj.key
                        },
                    ]
                }
            )
    print('S3 bucket -- EMPTIED')

# Function - Upload logs to ElasticSearch
def upload_docs_bulk(s3_bucket, s3_folder):
    print('JSON upload -- STARTED')
    request_suffix = f"/{elastic_index_alias}/_bulk?pipeline={elastic_index_pipeline}"
    error_count = 0

    for f in os.listdir(s3_local):
        if f.endswith(".json"):
            with open(f"{s3_local}/{f}", "r") as read_file:
                data = json.load(read_file)
            result = [json.dumps(record) for record in data]
            with open(f"{s3_local}/nd-temp.json", 'w') as obj:
                for i in result:
                    obj.write('{"index":{}}\n')
                    obj.write(i+'\n')
            
            data_file = open(f"{s3_local}/nd-temp.json", 'rb').read()
            response = requests.post(elastic_server+request_suffix, data=data_file, verify=fals, auth=(elastic_auth_user, elastic_auth_pw), headers={"Content-Type":"application/x-ndjson"})
            os.remove(s3_local+"/"+f)
            if(response.status_code != 200):
                error_count += 1
                print(response.text)
            print(f"{response.status_code} - {response.text}")
    if(os.path.exists(f"{s3_local}/nd-temp.json")):
        os.remove(f"{s3_local}/nd-temp.json")
    print(f"JSON upload -- COMPLETE -- {error_count} ERRORS")
    if(error_count == 0):
        delete_objects_s3(s3_bucket, s3_folder)
    refresh_index()


# Process - Upload data
def upload_logs():
    if(get_config_index_state()):
        print("Config index -- EXISTS")
        download_s3_folder(s3_bucket, s3_folder, s3_local)
        upload_docs_bulk(s3_bucket, s3_folder)
    else:
        create_tenant()
        create_lifecycle_policy()
        create_index_template()
        create_first_index()
        create_index_alias()
        create_ingest_pipeline()
        configure_kibana()
        create_config_index()
        download_s3_folder(s3_bucket, s3_folder, s3_local)
        upload_docs_bulk(s3_bucket, s3_folder)


### MAIN CONTROL PANEL
upload_logs()
print("Sleep -- STARTED")
time.sleep(sleep_time)