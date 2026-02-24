"""
amelis-smime-decrypt - A library for fetching and decrypting S/MIME encrypted emails.

This library provides tools to:
- Load S/MIME certificates and private keys
- Connect to IMAP mailboxes
- Fetch and decrypt S/MIME encrypted emails
- Extract PDF attachments
- Manage email post-processing (mark as seen, delete, move)
"""

from amelis_smime_decrypt.certificate import SMIMECertificate
from amelis_smime_decrypt.imap import MailboxClient, EmailAction
from amelis_smime_decrypt.smime import decrypt_email
from amelis_smime_decrypt.attachment import extract_attachments

__version__ = "0.2.0"

__all__ = [
    "SMIMECertificate",
    "MailboxClient",
    "EmailAction",
    "decrypt_email",
    "extract_attachments",
]
