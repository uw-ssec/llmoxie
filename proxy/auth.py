"""
User authentication module for API key validation.

Manages user API keys stored in Azure Table Storage with in-memory caching.
"""

import logging
import os
from typing import Optional, Dict
from datetime import datetime, timedelta
import asyncio

from azure.data.tables import TableServiceClient
from azure.core.exceptions import ResourceNotFoundError
from azure.core.credentials import AzureNamedKeyCredential

logger = logging.getLogger(__name__)
TABLE_NAME = "userkeys"


class UserKeyStore:
    """Manages user API keys with Azure Table Storage backend and in-memory cache."""

    def __init__(self):
        """Initialize the key store and connect to Azure Table Storage."""
        # Reuse blob storage credentials
        account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
        account_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
        
        if not account_name or not account_key:
            raise ValueError(
                "AZURE_STORAGE_ACCOUNT_NAME and AZURE_STORAGE_ACCOUNT_KEY "
                "are required for user authentication"
            )
        
        self.table_name = TABLE_NAME
        
        # Initialize Azure Table Storage client
        account_url = f"https://{account_name}.table.core.windows.net"
        credential = AzureNamedKeyCredential(account_name, account_key)
        self.table_service = TableServiceClient(
            endpoint=account_url,
            credential=credential,
        )
        
        # Get table client
        self.table_client = self.table_service.get_table_client(TABLE_NAME)
        
        # In-memory cache: {api_key: {user_id, user_name, created_at}}
        self.key_cache: Dict[str, Dict[str, str]] = {}
        
        # Cache refresh settings
        self.cache_ttl = timedelta(minutes=5)
        self.last_refresh = None
        
        # Load initial cache
        self._refresh_cache()
        
        logger.info(
            "UserKeyStore initialized with %d keys from table '%s'",
            len(self.key_cache),
            TABLE_NAME
        )
    
    def _refresh_cache(self) -> None:
        """Refresh the in-memory cache from Azure Table Storage."""
        try:
            # Query all entities from the table
            entities = self.table_client.list_entities()
            
            new_cache = {}
            for entity in entities:
                api_key = entity.get("api_key")
                user_id = entity.get("RowKey")  # RowKey is the user_id
                user_name = entity.get("user_name")
                created_at = entity.get("created_at")
                
                if api_key and user_id:
                    new_cache[api_key] = {
                        "user_id": user_id,
                        "user_name": user_name,
                        "created_at": created_at,
                    }
            
            self.key_cache = new_cache
            self.last_refresh = datetime.utcnow()
            
            logger.info("Cache refreshed with %d keys", len(self.key_cache))
            
        except ResourceNotFoundError:
            logger.warning(
                "Table '%s' not found. Creating empty cache. "
                "Please create the table manually.",
                self.table_name
            )
            self.key_cache = {}
            self.last_refresh = datetime.utcnow()
        except Exception as e:
            logger.error("Failed to refresh cache: %s. Using stale cache.", e)
            # Keep using existing cache
    
    def _should_refresh_cache(self) -> bool:
        """Check if cache should be refreshed."""
        if self.last_refresh is None:
            return True
        return datetime.utcnow() - self.last_refresh > self.cache_ttl
    
    def validate_api_key(self, api_key: str) -> Optional[Dict[str, str]]:
        """
        Validate an API key and return user information.
        
        Args:
            api_key: The API key to validate
        
        Returns:
            Dictionary with user_id and user_name if valid, None otherwise
        """
        # Refresh cache if needed
        if self._should_refresh_cache():
            self._refresh_cache()
        
        # Look up in cache
        user_info = self.key_cache.get(api_key)
        
        if user_info:
            logger.debug("Valid API key for user_id: %s", user_info["user_id"])
            return user_info
        
        logger.warning("Invalid API key attempted")
        return None
    
    async def start_background_refresh(self):
        """Start background task to periodically refresh the cache."""
        while True:
            await asyncio.sleep(self.cache_ttl.total_seconds())
            self._refresh_cache()
