"""Tests for IMAP module components that don't require server connection."""

import pytest
from amelis_smime_decrypt.imap import EmailAction


class TestEmailAction:
    """Tests for EmailAction enum."""

    def test_mark_seen_value(self):
        """Test MARK_SEEN enum value."""
        assert EmailAction.MARK_SEEN.value == "mark_seen"

    def test_delete_value(self):
        """Test DELETE enum value."""
        assert EmailAction.DELETE.value == "delete"

    def test_move_to_folder_value(self):
        """Test MOVE_TO_FOLDER enum value."""
        assert EmailAction.MOVE_TO_FOLDER.value == "move_to_folder"

    def test_enum_members(self):
        """Test that all expected enum members exist."""
        members = [action.name for action in EmailAction]
        assert "MARK_SEEN" in members
        assert "DELETE" in members
        assert "MOVE_TO_FOLDER" in members

    def test_enum_comparison(self):
        """Test enum member comparison."""
        assert EmailAction.MARK_SEEN == EmailAction.MARK_SEEN
        assert EmailAction.DELETE != EmailAction.MARK_SEEN
        assert EmailAction.MOVE_TO_FOLDER != EmailAction.DELETE

    def test_enum_from_value(self):
        """Test creating enum from value string."""
        assert EmailAction("mark_seen") == EmailAction.MARK_SEEN
        assert EmailAction("delete") == EmailAction.DELETE
        assert EmailAction("move_to_folder") == EmailAction.MOVE_TO_FOLDER

    def test_invalid_enum_value_raises(self):
        """Test that invalid value raises ValueError."""
        with pytest.raises(ValueError):
            EmailAction("invalid_action")
