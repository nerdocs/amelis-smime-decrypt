"""Certificate and private key management for S/MIME decryption."""

import logging
import os
from typing import Optional

from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.x509 import Certificate

logger = logging.getLogger(__name__)


class SMIMECertificate:
    """
    Manages S/MIME certificate and private key loading.

    Supports P12/PFX format certificates with optional password protection.
    """

    def __init__(
        self,
        private_key: RSAPrivateKey,
        certificate: Certificate,
        additional_certs: Optional[list] = None,
    ):
        """
        Initialize with loaded cryptographic materials.

        Args:
            private_key: RSA private key for decryption
            certificate: X.509 certificate
            additional_certs: Optional list of additional CA certificates
        """
        self.private_key = private_key
        self.certificate = certificate
        self.additional_certs = additional_certs or []

    @classmethod
    def from_p12(
        cls, p12_path: str, password: Optional[str] = None
    ) -> "SMIMECertificate":
        """
        Load certificate and private key from P12/PFX file.

        Args:
            p12_path: Path to P12/PFX certificate file (absolute or relative)
            password: Optional password for encrypted P12 file

        Returns:
            SMIMECertificate instance

        Raises:
            FileNotFoundError: If P12 file doesn't exist
            ValueError: If P12 file is invalid or password is incorrect
        """
        # Resolve absolute path
        if not os.path.isabs(p12_path):
            p12_path = os.path.abspath(p12_path)

        if not os.path.exists(p12_path):
            raise FileNotFoundError(f"P12 certificate file not found: {p12_path}")

        logger.debug(f"Loading P12 certificate from: {p12_path}")

        try:
            with open(p12_path, "rb") as f:
                p12_data = f.read()

            password_bytes = password.encode() if password else b""
            private_key, certificate, additional_certs = (
                pkcs12.load_key_and_certificates(
                    p12_data, password_bytes, backend=default_backend()
                )
            )

            if not private_key:
                raise ValueError("No private key found in P12 file")

            if not certificate:
                raise ValueError("No certificate found in P12 file")

            logger.info(f"Successfully loaded P12 certificate: {certificate.subject}")
            return cls(private_key, certificate, additional_certs)

        except Exception as e:
            logger.error(f"Failed to load P12 file: {e}")
            raise ValueError(f"Invalid P12 file or incorrect password: {e}") from e

    def validate(self) -> bool:
        """
        Validate that the certificate and private key are properly loaded.

        Returns:
            True if valid, False otherwise
        """
        try:
            if not self.private_key:
                logger.error("Private key is missing")
                return False

            if not self.certificate:
                logger.error("Certificate is missing")
                return False

            logger.info(f"Certificate is valid: {self.certificate.subject}")
            return True

        except Exception as e:
            logger.error(f"Certificate validation failed: {e}")
            return False
