"""PDF attachment extraction from decrypted emails."""

import logging
import os
from datetime import datetime
from typing import List, Optional
from email.message import EmailMessage

logger = logging.getLogger(__name__)


def extract_attachments(
    msg: EmailMessage,
    output_dir: str,
    filename_prefix: Optional[str] = None,
    add_timestamp: bool = True,
) -> List[str]:
    """
    Extract PDF attachments from an email message.

    Args:
        msg: Email message to extract attachments from
        output_dir: Directory to save extracted PDFs
        filename_prefix: Optional prefix for saved filenames
        add_timestamp: If True, add timestamp to filename (default: True)

    Returns:
        List of saved file paths

    Raises:
        ValueError: If output directory doesn't exist or isn't writable
    """
    # Validate output directory
    if not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir)
            logger.info(f"Created output directory: {output_dir}")
        except Exception as e:
            raise ValueError(f"Cannot create output directory: {e}") from e

    if not os.path.isdir(output_dir):
        raise ValueError(f"Output path is not a directory: {output_dir}")

    if not os.access(output_dir, os.W_OK):
        raise ValueError(f"Output directory is not writable: {output_dir}")

    saved_files = []
    attachment_count = 0

    for part in msg.walk():
        content_type = part.get_content_type()
        filename = part.get_filename()

        # Identify PDF attachments
        if content_type == "application/pdf" or (
            filename and filename.lower().endswith(".pdf")
        ):
            attachment_count += 1

            # Generate filename
            if not filename:
                filename = f"attachment_{attachment_count}.pdf"

            # Sanitize filename (remove unsafe characters)
            safe_filename = "".join(c for c in filename if c.isalnum() or c in "._- ")

            # Add optional prefix and timestamp
            output_filename = safe_filename
            if filename_prefix:
                output_filename = f"{filename_prefix}_{output_filename}"
            if add_timestamp:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_filename = f"{timestamp}_{output_filename}"

            output_path = os.path.join(output_dir, output_filename)

            try:
                attachment_data = part.get_payload(decode=True)
                if attachment_data:
                    with open(output_path, "wb") as f:
                        f.write(attachment_data)
                    logger.info(f"Saved attachment: {output_path}")
                    saved_files.append(output_path)
                else:
                    logger.warning(f"Empty attachment data for: {filename}")

            except Exception as e:
                logger.error(f"Failed to save attachment {filename}: {e}")

    if not saved_files:
        logger.debug("No PDF attachments found in email")

    return saved_files
