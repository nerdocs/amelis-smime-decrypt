import logging
import os
import imaplib
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

from dotenv import load_dotenv
from M2Crypto import BIO, SMIME, X509, EVP

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
    """Fetch emails that contain a specific keyword in the subject."""
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


def load_smime_keys():
    """Load S/MIME private key and certificate."""
    smime = SMIME.SMIME()
    smime.load_key(PRIVATE_KEY_PATH, CERTIFICATE_PATH)
    return smime


def decrypt_smime(encrypted_data: bytes) -> bytes | None:
    """Decrypt S/MIME encrypted data using M2Crypto."""
    try:
        smime = load_smime_keys()

        logger.debug(f"Encrypted data length: {len(encrypted_data)} bytes")

        # Create a BIO buffer from the encrypted data
        bio = BIO.MemoryBuffer(encrypted_data)

        # Load the PKCS7 object from the encrypted data
        try:
            p7, _data = SMIME.smime_load_pkcs7_bio(bio)
        except SMIME.SMIME_Error as e:
            logger.error(f"SMIME_Error loading PKCS7: {e}")
            return None

        # Decrypt the PKCS7 data
        decrypted_bio = smime.decrypt(p7)

        # Read the decrypted bytes
        decrypted_data = decrypted_bio.read()

        logger.debug(f"Successfully decrypted {len(decrypted_data)} bytes")
        return decrypted_data
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
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

    # Get the encrypted payload
    encrypted_data = encrypted_part.get_payload(decode=True)

    if not encrypted_data:
        logger.error("Failed to get encrypted payload from email")
        return

    # Decrypt the S/MIME data
    decrypted_data = decrypt_smime(encrypted_data)

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


def check_key_and_cert(private_key_path, certificate_path) -> bool:
    """
    Check if the private key and certificate are valid and match.

    :param private_key_path: Path to the private key file
    :param certificate_path: Path to the certificate file
    :return: True if valid, False otherwise
    """
    try:
        # Check if files exist
        if not os.path.exists(private_key_path):
            logger.critical(f"Private key file '{private_key_path}' does not exist.")
            return False
        if not os.path.exists(certificate_path):
            logger.critical(f"Certificate file '{certificate_path}' does not exist.")
            return False

        # Load private key
        pkey = EVP.load_key(private_key_path)
        if not pkey:
            logger.critical("Failed to load private key.")
            return False

        # Load certificate
        cert = X509.load_cert(certificate_path)
        if not cert:
            logger.critical("Failed to load certificate.")
            return False

        # Check if the private key matches the certificate
        cert_pubkey = cert.get_pubkey()
        cert_rsa = cert_pubkey.get_rsa()
        pkey_rsa = pkey.get_rsa()

        if cert_rsa.e != pkey_rsa.e or cert_rsa.n != pkey_rsa.n:
            logger.critical("Private key does not match the certificate.")
            return False

        # Check certificate expiration
        not_before = cert.get_not_before().get_datetime().replace(tzinfo=None)
        not_after = cert.get_not_after().get_datetime().replace(tzinfo=None)
        now = datetime.now()

        if now < not_before:
            logger.critical("Certificate is not yet valid.")
            return False
        if now > not_after:
            logger.critical("Certificate has expired.")
            return False

        return True

    except Exception as e:
        logger.critical(f"Error checking key and certificate: {e}")
        return False


def main():
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not check_key_and_cert(PRIVATE_KEY_PATH, CERTIFICATE_PATH):
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
