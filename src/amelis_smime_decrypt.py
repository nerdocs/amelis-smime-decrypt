import logging
import os
import imaplib
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

from dotenv import load_dotenv
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.backends import default_backend
from endesive import email as endesive_email

load_dotenv()

logger = logging.getLogger(__file__)

# Email credentials and server details
IMAP_SERVER = os.getenv("IMAP_SERVER")
IMAP_PORT = os.getenv("IMAP_PORT", 993)
EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

SAVE_DIRECTORY = os.getenv("SAVE_DIRECTORY")

# S/MIME decryption keys
PRIVATE_KEY_PATH = os.getenv("PRIVATE_KEY_PATH")
CERTIFICATE_PATH = os.getenv("CERTIFICATE_PATH")
P12_CERTIFICATE_PATH = os.getenv("P12_CERTIFICATE_PATH")
PFX_PASSWORD = os.getenv("PFX_PASSWORD", "")


def connect_to_mailbox() -> imaplib.IMAP4_SSL | None:
    """Connect to the IMAP mailbox and return the connection."""
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        # mail.starttls()
        mail.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
        mail.select("inbox")
        return mail
    except Exception as e:
        logger.critical(f"Error connecting to mailbox: {e}")
        return None


def fetch_unread_mails(
    mail: imaplib.IMAP4, subject_keyword: str, only_unseen: bool = False
) -> list[str]:
    """Fetch emails ids that contain a specific keyword in the subject."""
    try:
        # Search for emails with subject containing the keyword
        if only_unseen:
            status, messages = mail.search(
                None, "UNSEEN", f'SUBJECT "{subject_keyword}"'
            )
        else:
            status, messages = mail.search(None, f'SUBJECT "{subject_keyword}"')

        logger.debug(f"Search status: {status}, keyword: '{subject_keyword}'")

        if status != "OK":
            logger.error(f"IMAP search failed with status: {status}")
            return []

        email_ids = messages[0].decode().split()
        logger.info(
            f"Found {len(email_ids)} email(s) with subject containing '{subject_keyword}'"
        )

        return email_ids
    except Exception as e:
        logger.error(f"Error searching for emails: {e}")
        return []


def load_private_key():
    """Load private key from P12 file."""
    import os

    # Try P12 file first
    if P12_CERTIFICATE_PATH and os.path.exists(P12_CERTIFICATE_PATH):
        p12_path = (
            P12_CERTIFICATE_PATH
            if os.path.isabs(P12_CERTIFICATE_PATH)
            else os.path.abspath(P12_CERTIFICATE_PATH)
        )
        logger.debug(f"Loading P12: {p12_path}")

        try:
            with open(p12_path, "rb") as f:
                p12_data = f.read()

            password = PFX_PASSWORD.encode() if PFX_PASSWORD else b""
            private_key, certificate, additional_certs = (
                pkcs12.load_key_and_certificates(
                    p12_data, password, backend=default_backend()
                )
            )

            logger.debug(f"Loaded private key from P12")
            return private_key

        except Exception as e:
            logger.error(f"Failed to load P12: {e}")
            return None

    logger.error("No P12 certificate file configured or found")
    return None


def decrypt_smime(encrypted_part: EmailMessage) -> bytes | None:
    """
    Decrypt S/MIME encrypted email part using endesive library.

    This handles RSA-OAEP and modern encryption schemes properly.
    """
    try:
        # Load private key from P12
        private_key = load_private_key()
        if not private_key:
            logger.error("Failed to load private key")
            return None

        # Get the entire encrypted message part as string
        # endesive needs the full MIME part
        part_bytes = encrypted_part.as_bytes()
        part_string = part_bytes.decode("utf-8", errors="replace")

        logger.debug(f"Encrypted part length: {len(part_string)} bytes")

        # Decrypt using endesive
        decrypted_data = endesive_email.decrypt(part_string, private_key)

        logger.debug(f"Successfully decrypted {len(decrypted_data)} bytes")
        return decrypted_data

    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        import traceback

        logger.debug(traceback.format_exc())
        return None


def save_attachments_from_email(msg: EmailMessage, subject: str) -> int:
    """Extract and save all PDF attachments from a decrypted email."""
    saved_count = 0

    for part in msg.walk():
        content_type = part.get_content_type()
        filename = part.get_filename()

        # Save PDF attachments
        if content_type == "application/pdf" or (
            filename and filename.lower().endswith(".pdf")
        ):
            if not filename:
                filename = f"attachment_{saved_count + 1}.pdf"

            # Sanitize filename
            safe_filename = "".join(c for c in filename if c.isalnum() or c in "._- ")

            # Create timestamped filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"{timestamp}_{safe_filename}"
            output_path = os.path.join(SAVE_DIRECTORY, output_filename)

            try:
                attachment_data = part.get_payload(decode=True)
                if attachment_data:
                    with open(output_path, "wb") as f:
                        f.write(attachment_data)
                    logger.info(f"Saved attachment: {output_path}")
                    saved_count += 1
            except Exception as e:
                logger.error(f"Failed to save attachment {filename}: {e}")

    return saved_count


def process_email(mail: imaplib.IMAP4_SSL, email_id: str) -> None:
    """Fetch, decrypt, and extract attachments from an email."""

    status, msg_data = mail.fetch(email_id, "(RFC822)")
    if status != "OK":
        logger.error(f"Failed to fetch email {email_id}")
        return

    raw_email: bytes = msg_data[0][1]  # noqa
    msg: EmailMessage = BytesParser(policy=policy.default).parsebytes(raw_email)
    subject = msg.get("Subject", "No Subject")

    logger.info(f"Processing email: {subject}")

    # Find S/MIME encrypted part (could be top-level or nested in multipart)
    encrypted_part = None

    if msg.get_content_type() == "application/pkcs7-mime":
        # Entire message is encrypted
        encrypted_part = msg
    elif msg.is_multipart():
        # Search for encrypted part in multipart message
        for part in msg.walk():
            if part.get_content_type() == "application/pkcs7-mime":
                encrypted_part = part
                break

    if not encrypted_part:
        logger.warning(
            f"No S/MIME encrypted content found (Content-Type: {msg.get_content_type()})"
        )
        # DEBUG: restore "unseen" status to keep email as unread
        mail.store(email_id, "-FLAGS", "\\Seen")
        return

    # Decrypt the S/MIME data (pass the entire part, not just payload)
    decrypted_data = decrypt_smime(encrypted_part)

    if not decrypted_data:
        logger.error(f"Failed to decrypt email: {subject}")
        return

    # Parse the decrypted email
    try:
        decrypted_msg = BytesParser(policy=policy.default).parsebytes(decrypted_data)
        logger.info(f"Successfully decrypted email: {subject}")

        # Extract and save attachments
        saved_count = save_attachments_from_email(decrypted_msg, subject)

        if saved_count > 0:
            logger.info(f"Saved {saved_count} attachment(s) from email: {subject}")
        else:
            logger.warning(f"No PDF attachments found in email: {subject}")

    except Exception as e:
        logger.error(f"Failed to parse decrypted email: {e}")

    # DEBUG: restore "unseen" status to keep email as unread
    mail.store(email_id, "-FLAGS", "\\Seen")


def check_p12_file() -> bool:
    """
    Check if the P12 certificate file exists and can be loaded.

    :return: True if valid, False otherwise
    """
    try:
        if not P12_CERTIFICATE_PATH:
            logger.critical("P12_CERTIFICATE_PATH not configured in .env")
            return False

        p12_path = (
            P12_CERTIFICATE_PATH
            if os.path.isabs(P12_CERTIFICATE_PATH)
            else os.path.abspath(P12_CERTIFICATE_PATH)
        )

        if not os.path.exists(p12_path):
            logger.critical(f"P12 file '{p12_path}' does not exist.")
            return False

        # Try to load it
        with open(p12_path, "rb") as f:
            p12_data = f.read()

        password = PFX_PASSWORD.encode() if PFX_PASSWORD else b""
        private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
            p12_data, password, backend=default_backend()
        )

        if not private_key:
            logger.critical("Failed to load private key from P12.")
            return False

        if not certificate:
            logger.critical("Failed to load certificate from P12.")
            return False

        logger.info(f"P12 certificate loaded successfully: {certificate.subject}")
        return True

    except Exception as e:
        logger.critical(f"Error loading P12 file: {e}")
        return False


def main():
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not check_p12_file():
        return

    if not os.path.exists(SAVE_DIRECTORY):
        os.makedirs(SAVE_DIRECTORY)
        logger.info(f"Created output directory: {SAVE_DIRECTORY}")

    mail = connect_to_mailbox()
    if not mail:
        logger.error("Failed to connect to mailbox")
        return

    email_ids = fetch_unread_mails(mail, os.getenv("SUBJECT_KEYWORD", "Auftrag"))
    if not email_ids:
        logger.info("No emails found matching criteria.")
        return

    for email_id in email_ids:
        process_email(mail, email_id)

    mail.logout()
    logger.info("Processing complete.")


if __name__ == "__main__":
    main()
