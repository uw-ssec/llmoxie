"""
Pulumi program to set up Azure Storage infrastructure for LLMaven proxy.

Creates:
- Azure Storage Account in eastus2
- User keys table in Azure Table Storage
"""


import pulumi # type: ignore
import pulumi_azure_native as azure_native # type: ignore

# Configuration
config = pulumi.Config()
location = config.get("location") or "eastus2"
storage_account_name = config.get("storageAccountName") or "llmaven"

# Get the current resource group or create one
resource_group_name = config.get("resourceGroupName") or f"{storage_account_name}-rg"

# Create or use existing resource group
resource_group = azure_native.resources.ResourceGroup(
    "llmaven-proxy-rg",
    resource_group_name=resource_group_name,
    location=location,
)

# Create storage account
storage_account = azure_native.storage.StorageAccount(
    "llmavenStorage",
    account_name=storage_account_name,
    resource_group_name=resource_group.name,
    location=location,
    sku=azure_native.storage.SkuArgs(
        name=azure_native.storage.SkuName.STANDARD_LRS,
    ),
    kind=azure_native.storage.Kind.STORAGE_V2,
    access_tier=azure_native.storage.AccessTier.HOT,
    allow_blob_public_access=False,
    enable_https_traffic_only=True,
    minimum_tls_version=azure_native.storage.MinimumTlsVersion.TLS1_2,
)

# Create the userkeys table
userkeys_table = azure_native.storage.Table(
    "userkeysTable",
    account_name=storage_account.name,
    resource_group_name=resource_group.name,
    table_name="userkeys",
)

llmaven_proxy_logs = azure_native.storage.BlobContainer(
    "proxy-logs",
    account_name=storage_account.name,
    resource_group_name=resource_group.name,
    container_name="proxy-logs",
)

# Get storage account keys
storage_keys = pulumi.Output.all(resource_group.name, storage_account.name).apply(
    lambda args: azure_native.storage.list_storage_account_keys(
        resource_group_name=args[0],
        account_name=args[1],
    )
)

# Export the primary key
primary_key = storage_keys.apply(lambda keys: keys.keys[0].value)

# Export outputs
pulumi.export("resourceGroupName", resource_group.name)
pulumi.export("storageAccountName", storage_account.name)
pulumi.export("storageAccountKey", primary_key)
pulumi.export("tableStorageEndpoint", storage_account.primary_endpoints.apply(lambda e: e.table))
pulumi.export("blobStorageEndpoint", storage_account.primary_endpoints.apply(lambda e: e.blob))

# Export environment variable format
pulumi.export("envVars", pulumi.Output.all(
    storage_account.name,
    primary_key
).apply(lambda args: f"""
export AZURE_STORAGE_ACCOUNT_NAME={args[0]}
export AZURE_STORAGE_ACCOUNT_KEY={args[1]}
""".strip()))
