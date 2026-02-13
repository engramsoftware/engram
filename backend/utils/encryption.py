"""
Encryption utilities for secure API key storage.
Uses Fernet symmetric encryption.
"""

import logging
import base64
import hashlib
from typing import Optional
from cryptography.fernet import Fernet

from config import get_settings

logger = logging.getLogger(__name__)


def _get_fernet() -> Fernet:
    """
    Get Fernet instance using encryption key from settings.
    Derives a valid Fernet key from the configured encryption key.
    """
    settings = get_settings()
    
    # Derive a 32-byte key from the configured key
    # This allows using any string as the encryption key
    key_bytes = hashlib.sha256(
        settings.encryption_key.encode()
    ).digest()
    
    # Fernet requires base64-encoded 32-byte key
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    
    return Fernet(fernet_key)


def encrypt_api_key(api_key: str) -> str:
    """
    Encrypt an API key for secure storage.
    
    Args:
        api_key: Plain text API key
        
    Returns:
        Encrypted API key as base64 string
    """
    if not api_key:
        return ""
    
    try:
        fernet = _get_fernet()
        encrypted = fernet.encrypt(api_key.encode())
        return encrypted.decode()
    except Exception as e:
        logger.error(f"Failed to encrypt API key: {e}")
        raise ValueError("Encryption failed")


def decrypt_api_key(encrypted_key: str) -> str:
    """
    Decrypt an encrypted API key.
    
    Args:
        encrypted_key: Encrypted API key string
        
    Returns:
        Decrypted plain text API key
    """
    if not encrypted_key:
        return ""
    
    try:
        fernet = _get_fernet()
        decrypted = fernet.decrypt(encrypted_key.encode())
        return decrypted.decode()
    except Exception as e:
        logger.error(f"Failed to decrypt API key: {e}")
        raise ValueError("Decryption failed - key may be corrupted")


def mask_api_key(api_key: str, visible_chars: int = 4) -> str:
    """
    Mask an API key for display, showing only last few characters.
    
    Args:
        api_key: API key to mask
        visible_chars: Number of characters to show at end
        
    Returns:
        Masked API key like "sk-...abc123"
    """
    if not api_key:
        return ""
    
    if len(api_key) <= visible_chars:
        return "*" * len(api_key)
    
    prefix = api_key[:3] if api_key.startswith(("sk-", "key")) else ""
    suffix = api_key[-visible_chars:]
    
    return f"{prefix}...{suffix}"
