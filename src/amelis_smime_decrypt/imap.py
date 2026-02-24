"""IMAP mailbox operations for fetching and managing emails."""

import logging
import imaplib
from enum import Enum
from typing import Optional, List, Tuple
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

logger = logging.getLogger(__name__)


class EmailAction(Enum):
    """Post-processing actions for emails after successful decryption."""

    MARK_SEEN = "mark_seen"
    DELETE = "delete"
    MOVE_TO_FOLDER = "move_to_folder"


class MailboxClient:
    """
    IMAP mailbox client for fetching and managing emails.

    Supports context manager protocol for automatic connection cleanup.

    Example:
        with MailboxClient("imap.example.com", 993, "user", "pass") as client:
            emails = client.fetch_emails(subject="Order")
            for email_id, msg in emails:
                # Process email
                client.handle_email(email_id, EmailAction.MARK_SEEN)
    """

    def __init__(
        self,
        host: str,
        port: int = 993,
        username: str = None,
        password: str = None,
        mailbox: str = "INBOX",
    ):
        """
        Initialize IMAP client configuration.

        Args:
            host: IMAP server hostname
            port: IMAP server port (default: 993 for SSL)
            username: Email account username
            password: Email account password
            mailbox: Mailbox/folder to select (default: "INBOX")
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.mailbox = mailbox
        self._connection: Optional[imaplib.IMAP4_SSL] = None

    def connect(self) -> "MailboxClient":
        """
        Establish connection to IMAP server.

        Returns:
            Self for chaining

        Raises:
            ConnectionError: If connection or authentication fails
        """
        try:
            logger.debug(f"Connecting to {self.host}:{self.port}")
            self._connection = imaplib.IMAP4_SSL(self.host, self.port)
            self._connection.login(self.username, self.password)
            self._connection.select(self.mailbox)
            logger.info(f"Connected to mailbox: {self.mailbox}")
            return self
        except Exception as e:
            logger.error(f"Failed to connect to mailbox: {e}")
            raise ConnectionError(f"IMAP connection failed: {e}") from e

    def disconnect(self):
        """Close IMAP connection gracefully."""
        if self._connection:
            try:
                self._connection.logout()
                logger.info("Disconnected from mailbox")
            except Exception as e:
                logger.warning(f"Error during logout: {e}")
            finally:
                self._connection = None

    def __enter__(self):
        """Context manager entry."""
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()

    def fetch_emails(
        self, subject: Optional[str] = None, unseen: bool = False
    ) -> List[Tuple[str, EmailMessage]]:
        """
        Fetch emails matching specified criteria.

        Args:
            subject: Optional subject keyword to filter by
            unseen: If True, only fetch unread emails (default: False)

        Returns:
            List of (email_id, EmailMessage) tuples

        Raises:
            RuntimeError: If not connected to mailbox
        """
        if not self._connection:
            raise RuntimeError("Not connected to mailbox. Call connect() first.")

        try:
            # Build search criteria
            search_criteria = []
            if unseen:
                search_criteria.append("UNSEEN")
            if subject:
                search_criteria.append(f'SUBJECT "{subject}"')

            search_query = " ".join(search_criteria) if search_criteria else "ALL"

            logger.debug(f"Searching for emails: {search_query}")
            status, messages = self._connection.search(None, *search_criteria)

            if status != "OK":
                logger.error(f"IMAP search failed with status: {status}")
                return []

            email_ids = messages[0].decode().split()
            logger.info(f"Found {len(email_ids)} email(s)")

            # Fetch email messages
            results = []
            for email_id in email_ids:
                status, msg_data = self._connection.fetch(email_id, "(RFC822)")
                if status == "OK":
                    raw_email: bytes = msg_data[0][1]
                    msg: EmailMessage = BytesParser(policy=policy.default).parsebytes(
                        raw_email
                    )
                    results.append((email_id, msg))
                else:
                    logger.warning(f"Failed to fetch email {email_id}")

            return results

        except Exception as e:
            logger.error(f"Error fetching emails: {e}")
            return []

    def handle_email(
        self, email_id: str, action: EmailAction, folder: Optional[str] = None
    ):
        """
        Perform post-processing action on an email.

        Args:
            email_id: Email ID to process
            action: EmailAction to perform (MARK_SEEN, DELETE, MOVE_TO_FOLDER)
            folder: Target folder for MOVE_TO_FOLDER action

        Raises:
            RuntimeError: If not connected to mailbox
            ValueError: If MOVE_TO_FOLDER is used without folder parameter
        """
        if not self._connection:
            raise RuntimeError("Not connected to mailbox. Call connect() first.")

        try:
            if action == EmailAction.MARK_SEEN:
                self._connection.store(email_id, "+FLAGS", "\\Seen")
                logger.debug(f"Marked email {email_id} as seen")

            elif action == EmailAction.DELETE:
                self._connection.store(email_id, "+FLAGS", "\\Deleted")
                self._connection.expunge()
                logger.info(f"Deleted email {email_id}")

            elif action == EmailAction.MOVE_TO_FOLDER:
                if not folder:
                    raise ValueError(
                        "folder parameter required for MOVE_TO_FOLDER action"
                    )
                # Copy to target folder then delete from current
                self._connection.copy(email_id, folder)
                self._connection.store(email_id, "+FLAGS", "\\Deleted")
                self._connection.expunge()
                logger.info(f"Moved email {email_id} to folder: {folder}")

        except Exception as e:
            logger.error(f"Failed to handle email {email_id} with action {action}: {e}")
            raise

    def mark_as_seen(self, email_id: str):
        """Mark email as read/seen."""
        self.handle_email(email_id, EmailAction.MARK_SEEN)

    def delete(self, email_id: str):
        """Delete email from mailbox."""
        self.handle_email(email_id, EmailAction.DELETE)

    def move_to_folder(self, email_id: str, folder: str):
        """Move email to specified folder."""
        self.handle_email(email_id, EmailAction.MOVE_TO_FOLDER, folder)
