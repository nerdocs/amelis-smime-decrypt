"""Command-line interface for amelis-smime-decrypt."""

import argparse
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from typing import List, Tuple, Optional
from dotenv import load_dotenv

from amelis_smime_decrypt.certificate import SMIMECertificate
from amelis_smime_decrypt.imap import MailboxClient, EmailAction
from amelis_smime_decrypt.smime import decrypt_email
from amelis_smime_decrypt.attachment import extract_attachments
from amelis_smime_decrypt.pdf_parser import rename_pdf

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
    emails: List[Tuple[str, EmailMessage]],
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
    Parse email action string.

    Formats:
        - "mark_seen" -> (EmailAction.MARK_SEEN, None)
        - "delete" -> (EmailAction.DELETE, None)
        - "move:Archive" -> (EmailAction.MOVE_TO_FOLDER, "Archive")

    Args:
        action_str: Action string from environment or CLI

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


def parse_arguments() -> argparse.Namespace:
    """
    Parse command-line arguments.

    CLI arguments override .env configuration values.
    """
    parser = argparse.ArgumentParser(
        prog="amelis-smime-decrypt",
        description="Fetch and decrypt S/MIME encrypted emails, extract PDF attachments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Use .env configuration
  amelis-smime-decrypt

  # Override specific settings
  amelis-smime-decrypt --subject "Invoice" --output ./invoices

  # Full CLI configuration (no .env needed)
  amelis-smime-decrypt \\
    --imap-server imap.example.com \\
    --imap-user user@example.com \\
    --imap-pass secret \\
    --cert certificate.p12 \\
    --password pfx_pass \\
    --subject "Order" \\
    --output ./orders \\
    --email-action delete \\
    --duplicate-action "move:Duplicates"

Action formats:
  mark_seen              - Mark email as read (default)
  delete                 - Delete email from mailbox
  move:FolderName        - Move email to specified IMAP folder
        """,
    )

    # IMAP connection settings
    imap_group = parser.add_argument_group("IMAP Configuration")
    imap_group.add_argument(
        "--imap-server",
        dest="imap_server",
        help="IMAP server hostname (default: from .env IMAP_SERVER)",
    )
    imap_group.add_argument(
        "--imap-port",
        dest="imap_port",
        type=int,
        help="IMAP server port (default: from .env IMAP_PORT or 993)",
    )
    imap_group.add_argument(
        "--imap-user",
        dest="imap_user",
        help="IMAP username/email account (default: from .env EMAIL_ACCOUNT)",
    )
    imap_group.add_argument(
        "--imap-pass",
        dest="imap_pass",
        help="IMAP password (default: from .env EMAIL_PASSWORD)",
    )

    # Certificate settings
    cert_group = parser.add_argument_group("S/MIME Certificate")
    cert_group.add_argument(
        "--cert",
        dest="cert_path",
        help="Path to P12/PFX certificate file (default: from .env P12_CERTIFICATE_PATH)",
    )
    cert_group.add_argument(
        "--password",
        dest="cert_password",
        help="Certificate password (default: from .env PFX_PASSWORD)",
    )

    # Processing settings
    process_group = parser.add_argument_group("Email Processing")
    process_group.add_argument(
        "--subject",
        dest="subject_keyword",
        help='Subject keyword to filter emails (default: from .env SUBJECT_KEYWORD or "Auftrag")',
    )
    process_group.add_argument(
        "--output",
        dest="output_dir",
        help="Output directory for PDF attachments (default: from .env SAVE_DIRECTORY or ./output)",
    )
    process_group.add_argument(
        "--email-action",
        dest="email_action",
        help='Action for successfully processed emails: mark_seen|delete|move:Folder (default: from .env EMAIL_ACTION or "mark_seen")',
    )
    process_group.add_argument(
        "--duplicate-action",
        dest="duplicate_action",
        help='Action for older duplicate emails (same subject): mark_seen|delete|move:Folder (default: from .env DUPLICATE_ACTION or "mark_seen")',
    )
    process_group.add_argument(
        "--rename",
        dest="rename_pattern",
        help="Rename PDFs using pattern with variables: {last_name}, {first_name}, {birth_date}, {barcode_number}, {samplecollectiondate}, {receiptdate}, {finalreport}, {samplecollectiondate_yyyymmdd}, {receiptdate_yyyymmdd}, {finalreport_yyyymmdd} (default: from .env RENAME_PATTERN)",
    )

    # General options
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose/debug logging"
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.2.0")

    return parser.parse_args()


def get_config_value(
    cli_value: Optional[str], env_key: str, default: str = None
) -> Optional[str]:
    """
    Get configuration value with priority: CLI arg > .env > default.

    Args:
        cli_value: Value from command-line argument (None if not provided)
        env_key: Environment variable key to check
        default: Default value if neither CLI nor env is set

    Returns:
        Configuration value
    """
    if cli_value is not None:
        return cli_value
    return os.getenv(env_key, default)


def main():
    """CLI entry point for amelis-smime-decrypt."""

    # Parse command-line arguments
    args = parse_arguments()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Load configuration: CLI args override .env values
    imap_server = get_config_value(args.imap_server, "IMAP_SERVER")
    imap_port = (
        args.imap_port
        if args.imap_port is not None
        else int(os.getenv("IMAP_PORT", 993))
    )
    email_account = get_config_value(args.imap_user, "EMAIL_ACCOUNT")
    email_password = get_config_value(args.imap_pass, "EMAIL_PASSWORD")
    p12_cert_path = get_config_value(args.cert_path, "P12_CERTIFICATE_PATH")
    pfx_password = get_config_value(args.cert_password, "PFX_PASSWORD", "")
    save_directory = get_config_value(args.output_dir, "SAVE_DIRECTORY", "./output")
    subject_keyword = get_config_value(
        args.subject_keyword, "SUBJECT_KEYWORD", "Auftrag"
    )
    email_action_str = get_config_value(args.email_action, "EMAIL_ACTION", "mark_seen")
    duplicate_action_str = get_config_value(
        args.duplicate_action, "DUPLICATE_ACTION", "mark_seen"
    )
    rename_pattern = get_config_value(args.rename_pattern, "RENAME_PATTERN")

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

    # Log rename configuration
    if rename_pattern:
        logger.info(f"PDF rename pattern: {rename_pattern}")
    else:
        logger.info("PDF renaming disabled (no pattern specified)")

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

            logger.info(
                f"Processing {len(emails)} unique email(s) after deduplication..."
            )

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

                        # Rename PDFs if pattern is specified
                        if rename_pattern:
                            for pdf_path in saved_files:
                                try:
                                    new_path = rename_pdf(pdf_path, rename_pattern)
                                    if new_path:
                                        logger.debug(
                                            f"Renamed PDF: {pdf_path} -> {new_path}"
                                        )
                                except Exception as e:
                                    logger.error(
                                        f"Failed to rename PDF {pdf_path}: {e}"
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
