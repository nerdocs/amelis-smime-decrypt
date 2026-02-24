"""Command-line interface for amelis-smime-decrypt."""

import logging
import os
from collections import defaultdict
from datetime import datetime
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from typing import List, Tuple
from dotenv import load_dotenv

from amelis_smime_decrypt.certificate import SMIMECertificate
from amelis_smime_decrypt.imap import MailboxClient, EmailAction
from amelis_smime_decrypt.smime import decrypt_email
from amelis_smime_decrypt.attachment import extract_attachments

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


def get_email_timestamp(msg: EmailMessage) -> datetime:
    """
    Extract timestamp from email message.

    Tries Date header first, falls back to current time if missing/invalid.

    Args:
        msg: Email message

    Returns:
        datetime object representing email timestamp
    """
    try:
        date_header = msg.get("Date")
        if date_header:
            return parsedate_to_datetime(date_header)
    except Exception as e:
        logger.debug(f"Failed to parse Date header: {e}")

    # Fall back to current time if Date header is missing/invalid
    logger.warning("Email has invalid/missing Date header, using current time")
    return datetime.now()


def deduplicate_emails_by_subject(
    emails: List[Tuple[str, EmailMessage]]
) -> Tuple[List[Tuple[str, EmailMessage]], List[Tuple[str, EmailMessage]]]:
    """
    Group emails by subject and return only the latest email per subject.

    When multiple emails have the exact same subject, only the most recent
    email (by Date header timestamp) is kept for processing.

    Args:
        emails: List of (email_id, EmailMessage) tuples

    Returns:
        Tuple of:
            - List of latest emails (one per unique subject)
            - List of older duplicate emails to handle
    """
    # Group emails by subject
    subject_groups = defaultdict(list)

    for email_id, msg in emails:
        subject = msg.get("Subject", "").strip()
        if not subject:
            subject = "(No Subject)"

        timestamp = get_email_timestamp(msg)
        subject_groups[subject].append((email_id, msg, timestamp))

    latest_emails = []
    duplicate_emails = []

    # For each subject group, find the latest email
    for subject, group in subject_groups.items():
        if len(group) == 1:
            # No duplicates, keep the single email
            email_id, msg, _ = group[0]
            latest_emails.append((email_id, msg))
        else:
            # Sort by timestamp descending (most recent first)
            group.sort(key=lambda x: x[2], reverse=True)

            # Keep the latest email
            latest_id, latest_msg, latest_timestamp = group[0]
            latest_emails.append((latest_id, latest_msg))

            logger.info(
                f"Found {len(group)} emails with subject '{subject}', "
                f"using latest from {latest_timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
            )

            # Mark older emails as duplicates
            for email_id, msg, timestamp in group[1:]:
                duplicate_emails.append((email_id, msg))
                logger.debug(
                    f"  - Duplicate (older): {timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
                )

    return latest_emails, duplicate_emails


def parse_email_action(action_str: str) -> tuple[EmailAction, str | None]:
    """
    Parse EMAIL_ACTION environment variable.

    Formats:
        - "mark_seen" -> (EmailAction.MARK_SEEN, None)
        - "delete" -> (EmailAction.DELETE, None)
        - "move:Archive" -> (EmailAction.MOVE_TO_FOLDER, "Archive")

    Args:
        action_str: Action string from environment

    Returns:
        Tuple of (EmailAction, folder_name)
    """
    if not action_str:
        return EmailAction.MARK_SEEN, None

    action_str = action_str.strip().lower()

    if action_str == "delete":
        return EmailAction.DELETE, None
    elif action_str.startswith("move:"):
        folder = action_str.split(":", 1)[1].strip()
        return EmailAction.MOVE_TO_FOLDER, folder
    else:
        # Default to mark_seen
        return EmailAction.MARK_SEEN, None


def main():
    """CLI entry point for amelis-smime-decrypt."""

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Load configuration from environment
    imap_server = os.getenv("IMAP_SERVER")
    imap_port = int(os.getenv("IMAP_PORT", 993))
    email_account = os.getenv("EMAIL_ACCOUNT")
    email_password = os.getenv("EMAIL_PASSWORD")
    p12_cert_path = os.getenv("P12_CERTIFICATE_PATH")
    pfx_password = os.getenv("PFX_PASSWORD", "")
    save_directory = os.getenv("SAVE_DIRECTORY", "./output")
    subject_keyword = os.getenv("SUBJECT_KEYWORD", "Auftrag")
    email_action_str = os.getenv("EMAIL_ACTION", "mark_seen")
    duplicate_action_str = os.getenv("DUPLICATE_ACTION", "mark_seen")

    # Validate required configuration
    if not all([imap_server, email_account, email_password, p12_cert_path]):
        logger.critical(
            "Missing required configuration. Please check your .env file for: "
            "IMAP_SERVER, EMAIL_ACCOUNT, EMAIL_PASSWORD, P12_CERTIFICATE_PATH"
        )
        return 1

    # Parse email actions
    email_action, target_folder = parse_email_action(email_action_str)
    logger.info(f"Email post-processing action: {email_action.value}")
    if target_folder:
        logger.info(f"Target folder: {target_folder}")

    duplicate_action, duplicate_folder = parse_email_action(duplicate_action_str)
    logger.info(f"Duplicate email action: {duplicate_action.value}")
    if duplicate_folder:
        logger.info(f"Duplicate target folder: {duplicate_folder}")

    # Load S/MIME certificate
    try:
        certificate = SMIMECertificate.from_p12(p12_cert_path, pfx_password)
        if not certificate.validate():
            logger.critical("Certificate validation failed")
            return 1
    except Exception as e:
        logger.critical(f"Failed to load certificate: {e}")
        return 1

    # Ensure output directory exists
    if not os.path.exists(save_directory):
        os.makedirs(save_directory)
        logger.info(f"Created output directory: {save_directory}")

    # Connect to mailbox and process emails
    try:
        with MailboxClient(
            imap_server, imap_port, email_account, email_password
        ) as mailbox:

            # Fetch emails matching criteria
            all_emails = mailbox.fetch_emails(subject=subject_keyword, unseen=False)

            if not all_emails:
                logger.info("No emails found matching criteria.")
                return 0

            logger.info(f"Fetched {len(all_emails)} email(s) matching criteria")

            # Deduplicate emails by subject (keep only latest per subject)
            emails, duplicates = deduplicate_emails_by_subject(all_emails)

            logger.info(f"Processing {len(emails)} unique email(s) after deduplication...")

            # Handle duplicate emails first
            if duplicates:
                logger.info(
                    f"Handling {len(duplicates)} older duplicate email(s) "
                    f"with action: {duplicate_action.value}"
                )
                for dup_id, dup_msg in duplicates:
                    try:
                        mailbox.handle_email(dup_id, duplicate_action, duplicate_folder)
                    except Exception as e:
                        logger.error(f"Error handling duplicate email {dup_id}: {e}")

            # Process unique emails (latest per subject)
            for email_id, msg in emails:
                subject = msg.get("Subject", "No Subject")
                logger.info(f"Processing: {subject}")

                try:
                    # Decrypt email
                    decrypted_msg = decrypt_email(msg, certificate)

                    if not decrypted_msg:
                        logger.error(f"Decryption failed for: {subject}")
                        continue

                    # Extract PDF attachments
                    saved_files = extract_attachments(decrypted_msg, save_directory)

                    if saved_files:
                        logger.info(
                            f"Saved {len(saved_files)} attachment(s) from: {subject}"
                        )
                    else:
                        logger.warning(f"No PDF attachments found in: {subject}")

                    # Handle email post-processing
                    mailbox.handle_email(email_id, email_action, target_folder)

                except ValueError as e:
                    logger.warning(f"Skipping email (not encrypted): {subject}")
                    # Restore unseen status for non-encrypted emails
                    mailbox._connection.store(email_id, "-FLAGS", "\\Seen")

                except Exception as e:
                    logger.error(f"Error processing email '{subject}': {e}")

            logger.info("Processing complete.")
            return 0

    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
