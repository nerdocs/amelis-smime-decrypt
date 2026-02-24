"""S/MIME email decryption functionality."""

import logging
from typing import Optional
from email.message import EmailMessage
from email.parser import BytesParser
from email import policy

from endesive import email as endesive_email

from amelis_smime_decrypt.certificate import SMIMECertificate

logger = logging.getLogger(__name__)


def find_encrypted_part(msg: EmailMessage) -> Optional[EmailMessage]:
    """
    Find the S/MIME encrypted part in an email message.

    Args:
        msg: Email message to search

    Returns:
        Encrypted EmailMessage part, or None if not found
    """
    # Check if entire message is encrypted
    if msg.get_content_type() == "application/pkcs7-mime":
        return msg

    # Search for encrypted part in multipart message
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "application/pkcs7-mime":
                return part

    return None


def decrypt_email(
    msg: EmailMessage, certificate: SMIMECertificate
) -> Optional[EmailMessage]:
    """
    Decrypt an S/MIME encrypted email message.

    Args:
        msg: Email message containing S/MIME encrypted content
        certificate: SMIMECertificate with private key for decryption

    Returns:
        Decrypted EmailMessage, or None if decryption fails

    Raises:
        ValueError: If no encrypted content is found in the message
    """
    # Find encrypted part
    encrypted_part = find_encrypted_part(msg)
    if not encrypted_part:
        raise ValueError(
            f"No S/MIME encrypted content found (Content-Type: {msg.get_content_type()})"
        )

    logger.debug(f"Found encrypted part: {encrypted_part.get_content_type()}")

    try:
        # Get the entire encrypted message part as bytes
        part_bytes = encrypted_part.as_bytes()
        part_string = part_bytes.decode("utf-8", errors="replace")

        logger.debug(f"Encrypted part length: {len(part_string)} bytes")

        # Decrypt using endesive with private key
        decrypted_data = endesive_email.decrypt(part_string, certificate.private_key)

        logger.debug(f"Successfully decrypted {len(decrypted_data)} bytes")

        # Parse decrypted content as email message
        decrypted_msg = BytesParser(policy=policy.default).parsebytes(decrypted_data)
        logger.info("Email decrypted successfully")

        return decrypted_msg

    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        import traceback

        logger.debug(traceback.format_exc())
        return None
