"""Tests for CLI utility functions that don't require certificates."""

import pytest
from datetime import datetime
from email.message import EmailMessage
from amelis_smime_decrypt.cli import (
    get_email_timestamp,
    deduplicate_emails_by_subject,
    parse_email_action,
    get_config_value,
)
from amelis_smime_decrypt.imap import EmailAction


class TestGetEmailTimestamp:
    """Tests for get_email_timestamp function."""

    def test_valid_date_header(self):
        """Test parsing valid Date header."""
        msg = EmailMessage()
        msg["Date"] = "Mon, 24 Feb 2026 10:30:00 +0000"

        timestamp = get_email_timestamp(msg)

        assert isinstance(timestamp, datetime)
        assert timestamp.year == 2026
        assert timestamp.month == 2
        assert timestamp.day == 24

    def test_missing_date_header(self):
        """Test fallback to current time when Date header is missing."""
        msg = EmailMessage()
        # No Date header set

        timestamp = get_email_timestamp(msg)

        assert isinstance(timestamp, datetime)
        # Should be very close to now
        time_diff = abs((datetime.now() - timestamp).total_seconds())
        assert time_diff < 2  # Within 2 seconds

    def test_invalid_date_header(self):
        """Test fallback when Date header is malformed."""
        msg = EmailMessage()
        msg["Date"] = "invalid date string"

        timestamp = get_email_timestamp(msg)

        assert isinstance(timestamp, datetime)
        # Should fallback to current time
        time_diff = abs((datetime.now() - timestamp).total_seconds())
        assert time_diff < 2


class TestDeduplicateEmailsBySubject:
    """Tests for deduplicate_emails_by_subject function."""

    def test_no_duplicates(self):
        """Test with emails having unique subjects."""
        msg1 = EmailMessage()
        msg1["Subject"] = "First Email"
        msg1["Date"] = "Mon, 24 Feb 2026 10:00:00 +0000"

        msg2 = EmailMessage()
        msg2["Subject"] = "Second Email"
        msg2["Date"] = "Mon, 24 Feb 2026 11:00:00 +0000"

        emails = [("1", msg1), ("2", msg2)]

        latest, duplicates = deduplicate_emails_by_subject(emails)

        assert len(latest) == 2
        assert len(duplicates) == 0
        assert ("1", msg1) in latest
        assert ("2", msg2) in latest

    def test_with_duplicates_different_timestamps(self):
        """Test deduplication keeps most recent email."""
        msg1 = EmailMessage()
        msg1["Subject"] = "Duplicate Subject"
        msg1["Date"] = "Mon, 24 Feb 2026 10:00:00 +0000"

        msg2 = EmailMessage()
        msg2["Subject"] = "Duplicate Subject"
        msg2["Date"] = "Mon, 24 Feb 2026 12:00:00 +0000"  # Newer

        msg3 = EmailMessage()
        msg3["Subject"] = "Duplicate Subject"
        msg3["Date"] = "Mon, 24 Feb 2026 11:00:00 +0000"

        emails = [("1", msg1), ("2", msg2), ("3", msg3)]

        latest, duplicates = deduplicate_emails_by_subject(emails)

        assert len(latest) == 1
        assert len(duplicates) == 2
        # msg2 should be kept (most recent)
        assert latest[0][0] == "2"
        # msg1 and msg3 should be duplicates
        assert ("1", msg1) in duplicates
        assert ("3", msg3) in duplicates

    def test_empty_subject_handling(self):
        """Test handling of emails with missing subjects."""
        msg1 = EmailMessage()
        # No subject set
        msg1["Date"] = "Mon, 24 Feb 2026 10:00:00 +0000"

        msg2 = EmailMessage()
        msg2["Subject"] = ""  # Empty subject
        msg2["Date"] = "Mon, 24 Feb 2026 11:00:00 +0000"

        emails = [("1", msg1), ("2", msg2)]

        latest, duplicates = deduplicate_emails_by_subject(emails)

        # Both should be treated as having "(No Subject)" and deduplicated
        assert len(latest) == 1
        assert len(duplicates) == 1

    def test_multiple_subject_groups(self):
        """Test deduplication across multiple subject groups."""
        msg1 = EmailMessage()
        msg1["Subject"] = "Subject A"
        msg1["Date"] = "Mon, 24 Feb 2026 10:00:00 +0000"

        msg2 = EmailMessage()
        msg2["Subject"] = "Subject A"
        msg2["Date"] = "Mon, 24 Feb 2026 11:00:00 +0000"

        msg3 = EmailMessage()
        msg3["Subject"] = "Subject B"
        msg3["Date"] = "Mon, 24 Feb 2026 10:00:00 +0000"

        msg4 = EmailMessage()
        msg4["Subject"] = "Subject B"
        msg4["Date"] = "Mon, 24 Feb 2026 12:00:00 +0000"

        emails = [("1", msg1), ("2", msg2), ("3", msg3), ("4", msg4)]

        latest, duplicates = deduplicate_emails_by_subject(emails)

        assert len(latest) == 2  # One per subject group
        assert len(duplicates) == 2  # One duplicate per group

        # Check correct emails are kept
        latest_ids = [email_id for email_id, _ in latest]
        assert "2" in latest_ids  # Latest of Subject A
        assert "4" in latest_ids  # Latest of Subject B


class TestParseEmailAction:
    """Tests for parse_email_action function."""

    def test_parse_mark_seen(self):
        """Test parsing 'mark_seen' action."""
        action, folder = parse_email_action("mark_seen")
        assert action == EmailAction.MARK_SEEN
        assert folder is None

    def test_parse_mark_seen_case_insensitive(self):
        """Test case-insensitive parsing of mark_seen."""
        action, folder = parse_email_action("MARK_SEEN")
        assert action == EmailAction.MARK_SEEN
        assert folder is None

    def test_parse_delete(self):
        """Test parsing 'delete' action."""
        action, folder = parse_email_action("delete")
        assert action == EmailAction.DELETE
        assert folder is None

    def test_parse_delete_case_insensitive(self):
        """Test case-insensitive parsing of delete."""
        action, folder = parse_email_action("DELETE")
        assert action == EmailAction.DELETE
        assert folder is None

    def test_parse_move_to_folder(self):
        """Test parsing 'move:FolderName' action."""
        action, folder = parse_email_action("move:Archive")
        assert action == EmailAction.MOVE_TO_FOLDER
        assert folder == "archive"  # Note: entire string is lowercased

    def test_parse_move_with_whitespace(self):
        """Test parsing move action with whitespace."""
        action, folder = parse_email_action("move:  My Folder  ")
        assert action == EmailAction.MOVE_TO_FOLDER
        assert folder == "my folder"  # Note: entire string is lowercased

    def test_parse_move_case_insensitive(self):
        """Test case-insensitive parsing of move action."""
        action, folder = parse_email_action("MOVE:Trash")
        assert action == EmailAction.MOVE_TO_FOLDER
        assert folder == "trash"  # Note: entire string is lowercased

    def test_parse_empty_string(self):
        """Test parsing empty string defaults to mark_seen."""
        action, folder = parse_email_action("")
        assert action == EmailAction.MARK_SEEN
        assert folder is None

    def test_parse_none(self):
        """Test parsing None defaults to mark_seen."""
        action, folder = parse_email_action(None)
        assert action == EmailAction.MARK_SEEN
        assert folder is None

    def test_parse_invalid_action(self):
        """Test parsing invalid action defaults to mark_seen."""
        action, folder = parse_email_action("unknown_action")
        assert action == EmailAction.MARK_SEEN
        assert folder is None

    def test_parse_with_leading_trailing_whitespace(self):
        """Test parsing with whitespace around action string."""
        action, folder = parse_email_action("  delete  ")
        assert action == EmailAction.DELETE
        assert folder is None


class TestGetConfigValue:
    """Tests for get_config_value function."""

    def test_cli_value_takes_precedence(self, monkeypatch):
        """Test that CLI value overrides environment variable."""
        monkeypatch.setenv("TEST_VAR", "env_value")

        result = get_config_value("cli_value", "TEST_VAR", "default_value")

        assert result == "cli_value"

    def test_env_value_used_when_no_cli(self, monkeypatch):
        """Test that environment variable is used when CLI value is None."""
        monkeypatch.setenv("TEST_VAR", "env_value")

        result = get_config_value(None, "TEST_VAR", "default_value")

        assert result == "env_value"

    def test_default_value_used_when_no_cli_or_env(self, monkeypatch):
        """Test that default is used when neither CLI nor env is set."""
        monkeypatch.delenv("TEST_VAR", raising=False)

        result = get_config_value(None, "TEST_VAR", "default_value")

        assert result == "default_value"

    def test_none_default_when_not_specified(self, monkeypatch):
        """Test that None is returned when no default is provided."""
        monkeypatch.delenv("TEST_VAR", raising=False)

        result = get_config_value(None, "TEST_VAR")

        assert result is None

    def test_empty_string_cli_value(self, monkeypatch):
        """Test that empty string from CLI is treated as valid value."""
        monkeypatch.setenv("TEST_VAR", "env_value")

        # Empty string should NOT be treated as None
        result = get_config_value("", "TEST_VAR", "default_value")

        # Empty string is still a valid CLI value and should override env
        assert result == ""

    def test_zero_cli_value(self, monkeypatch):
        """Test that zero from CLI is treated as valid value."""
        monkeypatch.setenv("TEST_VAR", "env_value")

        # 0 should NOT be treated as None (but function expects strings)
        result = get_config_value("0", "TEST_VAR", "default_value")

        assert result == "0"
