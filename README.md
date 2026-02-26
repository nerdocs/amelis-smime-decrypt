# 📧 amelis-smime-decrypt

A Python library and CLI tool that connects to an IMAP email mailbox, fetches S/MIME encrypted emails, decrypts them using a P12/PFX certificate, and extracts PDF attachments with intelligent deduplication and flexible post-processing.

## 🚀 Features

✔️ **IMAP Integration** - Connect to any IMAP email server<br>
✔️ **S/MIME Decryption** - Decrypt emails using P12/PFX certificates (RSA-OAEP support)<br>
✔️ **Subject Filtering** - Fetch emails matching specific keywords<br>
✔️ **Deduplication** - Automatically handle duplicate emails (same subject)<br>
✔️ **Flexible Actions** - Mark as seen, delete, or move emails after processing<br>
✔️ **CLI + Library** - Use as standalone tool or import as Python library<br>
✔️ **PDF Data Extraction** - Extract patient data from PDFs and rename files with flexible patterns<br>

## 📦 Installation

### For Users
```bash
pip install amelis-smime-decrypt
```

### For Development

#### Prerequisites (Linux/Debian)
```bash
sudo apt-get install libssl-dev swig python3-dev gcc python3-virtualenv
```

#### Clone and Setup
```bash
git clone https://github.com/nerdocs/amelis-smime-decrypt.git
cd amelis-smime-decrypt

# Using uv (recommended)
uv venv
. .venv/bin/activate  # or: source .venv/bin/activate
uv sync

# Or using pip
pip install -e ".[dev]"
```

## 🔑 Configuration

### Using .env File

Create an `.env` file from the template:

```bash
cp .env.example .env
```

Edit the configuration:

```bash
# IMAP Configuration
IMAP_SERVER=imap.example.com
IMAP_PORT=993
EMAIL_ACCOUNT=info@example.com
EMAIL_PASSWORD=supersecretpassword

# S/MIME Certificate (P12/PFX format)
P12_CERTIFICATE_PATH=./certificate.p12
PFX_PASSWORD=your_certificate_password

# Output Configuration
SAVE_DIRECTORY=./output
SUBJECT_KEYWORD="Auftrag"

# Email Post-Processing
EMAIL_ACTION=mark_seen           # Options: mark_seen | delete | move:FolderName
DUPLICATE_ACTION=mark_seen       # Action for older duplicate emails

# PDF Renaming Pattern (optional)
# Available variables: {last_name}, {first_name}, {birth_date}, {barcode_number},
#                      {samplecollectiondate}, {receiptdate}, {finalreport}, etc.
RENAME_PATTERN="{last_name}_{first_name}_{birth_date}_{barcode_number}.pdf"
```

### Using CLI Arguments (Override .env)

All settings can be overridden via command-line arguments:

```bash
amelis-smime-decrypt \
  --imap-server imap.example.com \
  --imap-port 993 \
  --imap-user user@example.com \
  --imap-pass secret \
  --cert certificate.p12 \
  --password pfx_pass \
  --subject "Order" \
  --output ./orders \
  --email-action delete \
  --duplicate-action "move:Archive"
```

## 🛠️ Usage

### Basic Usage

Run with default configuration from `.env`:

```bash
amelis-smime-decrypt
```

### With Custom Arguments

```bash
amelis-smime-decrypt --subject "Auftrag" --output ./output_directory
```

### Get Help

```bash
amelis-smime-decrypt --help
```

### How It Works

1. **Connects** to IMAP server with provided credentials
2. **Fetches** emails matching the subject keyword
3. **Deduplicates** emails with same subject (keeps latest)
4. **Decrypts** S/MIME encrypted messages
5. **Extracts** PDF attachments
6. **Renames** PDFs based on extracted data (if pattern configured)
7. **Performs** configured action (mark seen/delete/move)

### 📂 Output

Extracted PDFs are saved to `SAVE_DIRECTORY` (default: `./output/`):

```
output/
 ├── Mueller_Hans_01.01.1980_BC123456.pdf
 ├── Schmidt_Anna_15.05.1975_BC789012.pdf
```

### Security Considerations

- **Protect your certificate**: Keep P12/PFX files secure, never commit to version control
- **Use environment variables**: Store credentials in `.env` (add to `.gitignore`)
- **Limit IMAP access**: Use app-specific passwords when available
- **Secure storage**: Restrict file permissions on certificates and `.env`

## 🧪 Development

### Commands

```bash
# Run with arguments
amelis-smime-decrypt --subject "Auftrag" --output ./output_directory

# Format code
black src/

# Run tests
pytest

# Run tests with coverage
pytest --cov=amelis_smime_decrypt --cov-report=term-missing

# Verbose test output
pytest -v
```

## 📚 Architecture

Modular library structure in `src/amelis_smime_decrypt/`:

### Core Modules

1. **certificate.py** - `SMIMECertificate` class for P12/PFX certificate loading
2. **imap.py** - `MailboxClient` class for IMAP operations with context manager support
3. **smime.py** - `decrypt_email()` function for S/MIME decryption
4. **attachment.py** - `extract_attachments()` function for PDF extraction
5. **cli.py** - CLI entry point with argparse support

### Key Dependencies

- **endesive** - S/MIME decryption (RSA-OAEP support)
- **cryptography** - Certificate/key handling
- **imapclient** - IMAP protocol wrapper
- **python-dotenv** - Environment configuration
- **pypdf** - PDF data extraction

## 📝 License

This project is licensed under the GPL v3.0 License or later.

## 🤝 Contributing

Pull requests are welcome! Feel free to fork and submit PRs.

## 📧 Support

For issues, please open a [GitHub Issue](https://github.com/nerdocs/amelis-smime-decrypt/issues).
