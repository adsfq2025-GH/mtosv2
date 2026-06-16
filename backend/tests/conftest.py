import os

from cryptography.fernet import Fernet

os.environ.setdefault("JWT_SECRET", "unit-test-jwt-secret")
os.environ.setdefault("INTEGRATION_ENCRYPTION_KEY", Fernet.generate_key().decode())

