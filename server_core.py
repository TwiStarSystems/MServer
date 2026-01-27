"""
MServerController - Core Server Management Logic

This module contains shared utilities used by both the Central Controller (Master)
and Client nodes (Slave) for distributed deployment communication.

Shared components:
  - PayloadEncryption: Handles encryption/decryption of data between Master and Slave nodes
"""

import json

# Try to import Fernet, but allow it to fail gracefully if not installed
try:
    from cryptography.fernet import Fernet
    FERNET_AVAILABLE = True
except ImportError:
    FERNET_AVAILABLE = False
    Fernet = None


class PayloadEncryption:
    """
    Handles encryption and decryption of payloads for Master-Slave communication.

    Used by:
      - ClientManager (server.py) on the Master/Controller side
      - ClientController (server_client.py) on the Slave/Client side

    Usage:
        encryptor = PayloadEncryption(encryption_key)
        encrypted = encryptor.encrypt(data_dict)
        decrypted = encryptor.decrypt(encrypted_data)
    """

    def __init__(self, encryption_key=None):
        """
        Initialize the encryption handler.

        Args:
            encryption_key: A 32-byte base64-encoded Fernet key, or None to disable encryption
        """
        self.encryption_key = encryption_key
        self.fernet = None

        if encryption_key and FERNET_AVAILABLE:
            try:
                key = encryption_key.encode() if isinstance(encryption_key, str) else encryption_key
                self.fernet = Fernet(key)
            except Exception as e:
                print(f'[PayloadEncryption] Failed to initialize encryption: {e}')
                self.fernet = None

    @property
    def is_enabled(self):
        """Check if encryption is enabled and functional"""
        return self.fernet is not None

    def encrypt(self, data):
        """
        Encrypt payload data if encryption is enabled.

        Args:
            data: Dictionary to encrypt

        Returns:
            If encryption is enabled: {'encrypted': True, 'data': <encrypted_string>}
            If encryption is disabled: Returns original data unchanged
        """
        if not self.fernet:
            return data

        try:
            json_data = json.dumps(data)
            encrypted = self.fernet.encrypt(json_data.encode())
            return {'encrypted': True, 'data': encrypted.decode()}
        except Exception as e:
            print(f"[PayloadEncryption] Encryption error: {e}")
            return data

    def decrypt(self, data):
        """
        Decrypt payload data if encryption is enabled.

        Args:
            data: Dictionary that may contain encrypted data

        Returns:
            Decrypted data dictionary, or original data if not encrypted
        """
        if not self.fernet or not isinstance(data, dict) or not data.get('encrypted'):
            return data

        try:
            encrypted_data = data['data'].encode()
            decrypted = self.fernet.decrypt(encrypted_data)
            return json.loads(decrypted.decode())
        except Exception as e:
            print(f"[PayloadEncryption] Decryption error: {e}")
            return data


print("server_core.py - Core utilities loaded")
