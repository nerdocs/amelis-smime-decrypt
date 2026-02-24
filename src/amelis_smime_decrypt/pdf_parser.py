"""PDF parsing and renaming functionality for lab reports."""

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

logger = logging.getLogger(__name__)


class PDFData:
    """Container for extracted PDF data."""

    def __init__(self):
        self.last_name: Optional[str] = None
        self.first_name: Optional[str] = None
        self.birth_date: Optional[str] = None
        self.barcode_number: Optional[str] = None
        self.samplecollectiondate: Optional[str] = None
        self.receiptdate: Optional[str] = None
        self.finalreport: Optional[str] = None

    def to_dict(self) -> Dict[str, Optional[str]]:
        """Convert to dictionary for template formatting."""
        return {
            "last_name": self.last_name or "",
            "first_name": self.first_name or "",
            "birth_date": self.birth_date or "",
            "barcode_number": self.barcode_number or "",
            "samplecollectiondate": self.samplecollectiondate or "",
            "receiptdate": self.receiptdate or "",
            "finalreport": self.finalreport or "",
        }

    def __repr__(self):
        return (
            f"PDFData(last_name={self.last_name}, first_name={self.first_name}, "
            f"birth_date={self.birth_date}, barcode_number={self.barcode_number}, "
            f"samplecollectiondate={self.samplecollectiondate}, receiptdate={self.receiptdate}, finalreport={self.finalreport})"
        )


def extract_pdf_data(pdf_path: str) -> Optional[PDFData]:
    """
    Extract structured data from lab report PDF.

    Extracts:
    - Last name (from "Name" field)
    - First name (from "Name" field)
    - Birth date (from "geb. am" field)
    - Barcode number (from "Barcodenummer" field)
    - Entnahme (sample collection date)
    - Eingang (receipt date)
    - Endbefund (final report date)

    Args:
        pdf_path: Path to PDF file

    Returns:
        PDFData object with extracted fields, or None if extraction fails
    """
    if PdfReader is None:
        logger.error("pypdf library not installed. Install with: uv add pypdf")
        return None

    try:
        reader = PdfReader(pdf_path)
        if not reader.pages:
            logger.warning(f"PDF has no pages: {pdf_path}")
            return None

        # Extract text from first page
        text = reader.pages[0].extract_text()

        data = PDFData()

        # Extract Name (format: "LASTNAME, FIRSTNAME")
        name_match = re.search(
            r"Name\s+([A-ZÄÖÜ]+),\s*([A-ZÄÖÜ]+)", text, re.IGNORECASE
        )
        if name_match:
            data.last_name = name_match.group(1).strip()
            data.first_name = name_match.group(2).strip()

        # Extract birth date (format: "geb. am DD.MM.YYYY")
        # Digits may be on separate lines, need to collect them
        birth_match = re.search(
            r"geb\.\s*am(.{0,100}?)(?:Eingang|Kostenträger|Jahre)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if birth_match:
            birth_section = birth_match.group(1)
            # Extract digits and periods, then reconstruct date
            chars = re.findall(r"[\d.]", birth_section)
            if chars:
                date_str = "".join(chars)
                # Match DD.MM.YYYY pattern in the extracted string
                date_pattern = re.match(r"(\d{2}\.\d{2}\.\d{4})", date_str)
                if date_pattern:
                    data.birth_date = date_pattern.group(1)

        # Extract Barcodenummer (digits may be on separate lines in PDF extraction)
        # Find text between "Barcodenummer" and next field (Kostenträger/Tagesnummer/Endbefund)
        barcode_match = re.search(
            r"Barcodenummer(.{0,100}?)(?:Kostenträger|Tagesnummer|Endbefund)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if barcode_match:
            # Extract all consecutive digits from the matched section
            digits = re.findall(r"\d", barcode_match.group(1))
            if digits:
                data.barcode_number = "".join(digits)

        # Extract Entnahme (sample collection date)
        samplecollectiondate_match = re.search(
            r"Entnahme\s+(\d{2}\.\d{2}\.\d{4})", text, re.IGNORECASE
        )
        if samplecollectiondate_match:
            data.samplecollectiondate = samplecollectiondate_match.group(1).strip()

        # Extract Eingang (receipt date and time)
        receiptdate_match = re.search(
            r"Eingang\s+(\d{2}\.\d{2}\.\d{4}(?:\s+\d{2}:\d{2})?)", text, re.IGNORECASE
        )
        if receiptdate_match:
            data.receiptdate = receiptdate_match.group(1).strip()

        # Extract Endbefund (final report date)
        finalreport_match = re.search(
            r"Endbefund\s+(\d{2}\.\d{2}\.\d{4})", text, re.IGNORECASE
        )
        if finalreport_match:
            data.finalreport = finalreport_match.group(1).strip()

        logger.debug(f"Extracted data: {data}")
        return data

    except Exception as e:
        logger.error(f"Failed to extract data from PDF {pdf_path}: {e}")
        return None


def format_date(date_str: str, output_format: str = "%Y%m%d") -> str:
    """
    Convert date from DD.MM.YYYY to specified format.

    Args:
        date_str: Date string in DD.MM.YYYY format (may include time)
        output_format: strftime format string (default: %Y%m%d)

    Returns:
        Formatted date string, or original string if parsing fails
    """
    try:
        # Handle date with optional time (e.g., "24.02.2026 12:30")
        date_part = date_str.split()[0]  # Get just the date part
        date_obj = datetime.strptime(date_part, "%d.%m.%Y")
        return date_obj.strftime(output_format)
    except (ValueError, AttributeError):
        return date_str


def apply_rename_pattern(pattern: str, pdf_data: PDFData) -> str:
    """
    Apply rename pattern to PDF data.

    Supports variables:
    - {last_name} - Last name
    - {first_name} - First name
    - {birth_date} - Birth date (DD.MM.YYYY)
    - {barcode_number} - Barcode number
    - {samplecollectiondate} - Sample collection date
    - {receiptdate} - Receipt date
    - {finalreport} - Final report date
    - {samplecollectiondate_yyyymmdd} - Sample date in YYYYMMDD format
    - {receiptdate_yyyymmdd} - Receipt date in YYYYMMDD format
    - {finalreport_yyyymmdd} - Final report date in YYYYMMDD format

    Example patterns:
    - "{last_name}_{first_name}_{barcode_number}.pdf"
    - "{finalreport_yyyymmdd}_{last_name}_{barcode_number}.pdf"
    - "Lab_{barcode_number}_{samplecollectiondate_yyyymmdd}.pdf"

    Args:
        pattern: Rename pattern with variable placeholders
        pdf_data: Extracted PDF data

    Returns:
        Formatted filename
    """
    data = pdf_data.to_dict()

    # Add formatted date versions
    if pdf_data.samplecollectiondate:
        data["samplecollectiondate_yyyymmdd"] = format_date(
            pdf_data.samplecollectiondate
        )
    if pdf_data.receiptdate:
        data["receiptdate_yyyymmdd"] = format_date(pdf_data.receiptdate)
    if pdf_data.finalreport:
        data["finalreport_yyyymmdd"] = format_date(pdf_data.finalreport)

    # Apply pattern
    try:
        new_name = pattern.format(**data)
        # Sanitize filename (remove invalid characters)
        new_name = re.sub(r'[<>:"/\\|?*]', "_", new_name)
        return new_name
    except KeyError as e:
        logger.error(f"Invalid variable in rename pattern: {e}")
        raise ValueError(f"Unknown variable in pattern: {e}")


def rename_pdf(
    pdf_path: str, rename_pattern: str, dry_run: bool = False
) -> Optional[str]:
    """
    Rename PDF file based on extracted data and pattern.

    Args:
        pdf_path: Path to original PDF file
        rename_pattern: Rename pattern with variable placeholders
        dry_run: If True, only log the new name without renaming

    Returns:
        New file path if successful, None otherwise
    """
    # Extract data from PDF
    pdf_data = extract_pdf_data(pdf_path)
    if not pdf_data:
        logger.error(f"Could not extract data from PDF: {pdf_path}")
        return None

    # Apply rename pattern
    try:
        new_filename = apply_rename_pattern(rename_pattern, pdf_data)
    except ValueError as e:
        logger.error(f"Invalid rename pattern: {e}")
        return None

    # Ensure .pdf extension
    if not new_filename.lower().endswith(".pdf"):
        new_filename += ".pdf"

    # Build new path
    original_path = Path(pdf_path)
    new_path = original_path.parent / new_filename

    # Check if file already exists
    if new_path.exists() and new_path != original_path:
        logger.warning(f"Target file already exists: {new_path}")
        # Add counter suffix
        counter = 1
        base_name = new_path.stem
        while new_path.exists():
            new_filename = f"{base_name}_{counter}.pdf"
            new_path = original_path.parent / new_filename
            counter += 1
        logger.info(f"Using alternative filename: {new_filename}")

    if dry_run:
        logger.info(f"[DRY RUN] Would rename: {original_path.name} -> {new_filename}")
        return str(new_path)

    # Perform rename
    try:
        os.rename(pdf_path, new_path)
        logger.info(f"Renamed: {original_path.name} -> {new_filename}")
        return str(new_path)
    except OSError as e:
        logger.error(f"Failed to rename file: {e}")
        return None
