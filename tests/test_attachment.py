"""Tests for attachment extraction functionality."""

import pytest
import os
import tempfile
import shutil
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.mime.text import MIMEText
from amelis_smime_decrypt.attachment import extract_attachments


class TestExtractAttachments:
    """Tests for extract_attachments function."""

    @pytest.fixture
    def temp_output_dir(self):
        """Create a temporary directory for test outputs."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        # Cleanup after test
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extract_single_pdf_attachment(self, temp_output_dir):
        """Test extracting a single PDF attachment."""
        # Create email with PDF attachment
        msg = MIMEMultipart()
        msg["Subject"] = "Test Email"

        # Add text body
        body = MIMEText("This is the email body", "plain")
        msg.attach(body)

        # Add PDF attachment
        pdf_content = b"%PDF-1.4 fake pdf content"
        pdf = MIMEApplication(pdf_content, _subtype="pdf")
        pdf.add_header("Content-Disposition", "attachment", filename="test.pdf")
        msg.attach(pdf)

        # Extract attachments
        saved_files = extract_attachments(msg, temp_output_dir, add_timestamp=False)

        assert len(saved_files) == 1
        assert os.path.exists(saved_files[0])
        assert saved_files[0].endswith("test.pdf")

        # Verify content
        with open(saved_files[0], "rb") as f:
            assert f.read() == pdf_content

    def test_extract_multiple_pdf_attachments(self, temp_output_dir):
        """Test extracting multiple PDF attachments."""
        msg = MIMEMultipart()

        # Add two PDF attachments
        for i in range(2):
            pdf_content = f"%PDF-1.4 content {i}".encode()
            pdf = MIMEApplication(pdf_content, _subtype="pdf")
            pdf.add_header(
                "Content-Disposition", "attachment", filename=f"document{i}.pdf"
            )
            msg.attach(pdf)

        saved_files = extract_attachments(msg, temp_output_dir, add_timestamp=False)

        assert len(saved_files) == 2
        for file_path in saved_files:
            assert os.path.exists(file_path)
            assert file_path.endswith(".pdf")

    def test_no_attachments(self, temp_output_dir):
        """Test email with no attachments returns empty list."""
        msg = MIMEMultipart()
        body = MIMEText("Just text, no attachments", "plain")
        msg.attach(body)

        saved_files = extract_attachments(msg, temp_output_dir)

        assert len(saved_files) == 0

    def test_non_pdf_attachments_ignored(self, temp_output_dir):
        """Test that non-PDF attachments are ignored."""
        msg = MIMEMultipart()

        # Add a text file attachment
        txt = MIMEApplication(b"Text content", _subtype="txt")
        txt.add_header("Content-Disposition", "attachment", filename="document.txt")
        msg.attach(txt)

        # Add a PDF
        pdf = MIMEApplication(b"%PDF content", _subtype="pdf")
        pdf.add_header("Content-Disposition", "attachment", filename="document.pdf")
        msg.attach(pdf)

        saved_files = extract_attachments(msg, temp_output_dir, add_timestamp=False)

        # Only PDF should be extracted
        assert len(saved_files) == 1
        assert saved_files[0].endswith(".pdf")

    def test_create_output_directory_if_missing(self):
        """Test that output directory is created if it doesn't exist."""
        temp_base = tempfile.mkdtemp()
        try:
            output_dir = os.path.join(temp_base, "new_subdir")
            assert not os.path.exists(output_dir)

            msg = MIMEMultipart()
            pdf = MIMEApplication(b"%PDF content", _subtype="pdf")
            pdf.add_header("Content-Disposition", "attachment", filename="test.pdf")
            msg.attach(pdf)

            saved_files = extract_attachments(msg, output_dir, add_timestamp=False)

            assert os.path.exists(output_dir)
            assert len(saved_files) == 1
        finally:
            shutil.rmtree(temp_base, ignore_errors=True)

    def test_output_path_not_directory_raises_error(self, temp_output_dir):
        """Test that ValueError is raised if output path is a file."""
        # Create a file instead of directory
        file_path = os.path.join(temp_output_dir, "not_a_directory")
        with open(file_path, "w") as f:
            f.write("test")

        msg = MIMEMultipart()
        pdf = MIMEApplication(b"%PDF content", _subtype="pdf")
        pdf.add_header("Content-Disposition", "attachment", filename="test.pdf")
        msg.attach(pdf)

        with pytest.raises(ValueError, match="not a directory"):
            extract_attachments(msg, file_path)

    def test_sanitize_filename(self, temp_output_dir):
        """Test that unsafe characters are removed from filenames."""
        msg = MIMEMultipart()

        # Filename with unsafe characters
        pdf = MIMEApplication(b"%PDF content", _subtype="pdf")
        pdf.add_header(
            "Content-Disposition", "attachment", filename="bad/file:name*.pdf"
        )
        msg.attach(pdf)

        saved_files = extract_attachments(msg, temp_output_dir, add_timestamp=False)

        assert len(saved_files) == 1
        # Verify unsafe characters are removed
        filename = os.path.basename(saved_files[0])
        assert "/" not in filename
        assert ":" not in filename
        assert "*" not in filename

    def test_filename_prefix(self, temp_output_dir):
        """Test adding prefix to saved filenames."""
        msg = MIMEMultipart()
        pdf = MIMEApplication(b"%PDF content", _subtype="pdf")
        pdf.add_header("Content-Disposition", "attachment", filename="document.pdf")
        msg.attach(pdf)

        saved_files = extract_attachments(
            msg, temp_output_dir, filename_prefix="PREFIX", add_timestamp=False
        )

        assert len(saved_files) == 1
        filename = os.path.basename(saved_files[0])
        assert filename.startswith("PREFIX_")

    def test_add_timestamp(self, temp_output_dir):
        """Test adding timestamp to saved filenames."""
        msg = MIMEMultipart()
        pdf = MIMEApplication(b"%PDF content", _subtype="pdf")
        pdf.add_header("Content-Disposition", "attachment", filename="document.pdf")
        msg.attach(pdf)

        saved_files = extract_attachments(msg, temp_output_dir, add_timestamp=True)

        assert len(saved_files) == 1
        filename = os.path.basename(saved_files[0])
        # Should have format: YYYYMMDD_HHMMSS_document.pdf
        parts = filename.split("_")
        assert len(parts) >= 3
        # First part should be date (8 digits)
        assert len(parts[0]) == 8
        assert parts[0].isdigit()

    def test_no_filename_generates_default(self, temp_output_dir):
        """Test that default filename is generated when attachment has no filename."""
        msg = MIMEMultipart()
        pdf = MIMEApplication(b"%PDF content", _subtype="pdf")
        # Don't set filename header
        msg.attach(pdf)

        saved_files = extract_attachments(msg, temp_output_dir, add_timestamp=False)

        assert len(saved_files) == 1
        filename = os.path.basename(saved_files[0])
        assert "attachment_" in filename
        assert filename.endswith(".pdf")

    def test_pdf_by_extension_only(self, temp_output_dir):
        """Test that files with .pdf extension are extracted even without pdf mime type."""
        msg = MIMEMultipart()

        # Create attachment with wrong content type but .pdf extension
        pdf = MIMEApplication(b"%PDF content", _subtype="octet-stream")
        pdf.add_header("Content-Disposition", "attachment", filename="document.pdf")
        msg.attach(pdf)

        saved_files = extract_attachments(msg, temp_output_dir, add_timestamp=False)

        assert len(saved_files) == 1
        assert saved_files[0].endswith(".pdf")

    def test_empty_attachment_data_skipped(self, temp_output_dir):
        """Test that attachments with empty data are skipped."""
        msg = MIMEMultipart()

        # Create attachment with no payload
        pdf = MIMEApplication(b"", _subtype="pdf")
        pdf.add_header("Content-Disposition", "attachment", filename="empty.pdf")
        msg.attach(pdf)

        saved_files = extract_attachments(msg, temp_output_dir, add_timestamp=False)

        # Empty attachments should be skipped
        assert len(saved_files) == 0

    def test_combined_prefix_and_timestamp(self, temp_output_dir):
        """Test using both prefix and timestamp together."""
        msg = MIMEMultipart()
        pdf = MIMEApplication(b"%PDF content", _subtype="pdf")
        pdf.add_header("Content-Disposition", "attachment", filename="doc.pdf")
        msg.attach(pdf)

        saved_files = extract_attachments(
            msg, temp_output_dir, filename_prefix="ORDER", add_timestamp=True
        )

        assert len(saved_files) == 1
        filename = os.path.basename(saved_files[0])
        # Format: YYYYMMDD_HHMMSS_ORDER_doc.pdf
        assert "ORDER_" in filename
        parts = filename.split("_")
        assert parts[0].isdigit()  # timestamp date part
