# EventDrop

<p align="center">
  <img src="src/eventdrop/static/img/logo.png" alt="EventDrop" width="220">
</p>

EventDrop is a self-hosted web application for collecting and sharing photos and videos from events. Organizers create an event, share a link or QR code, and guests upload media directly from their devices — no account required. Media is stored in a gallery the organizer can browse, manage, and bulk-download as a ZIP archive.

## Table of Contents

- [Features](#features)
- [Quick Start](#quick-start)
- [Building from Source](#building-from-source)
- [Configuration](#configuration)
- [Development Setup](#development-setup)
- [Architecture Overview](#architecture-overview)
- [Usage Guide](#usage-guide)
  - [Upload Messages](#upload-messages)
  - [Gallery Filtering](#gallery-filtering)
  - [Media Attribution](#media-attribution)
  - [Contributors List](#contributors-list)
- [Email Ingestion](#email-ingestion)
- [Storage Backends](#storage-backends)
- [Database](#database)
- [Authentication](#authentication)
- [Security Notes](#security-notes)

---

## Features

- **Passwordless guest uploads** — guests enter only their email address before uploading; no registration required
- **Photo and video support** — accepts JPEG, PNG, HEIC/HEIF, WebP, GIF, MP4, MOV, AVI, MKV, and WebM files
- **Automatic EXIF extraction** — captures original photo date/time from image metadata
- **Automatic thumbnail generation** — creates 400×400 JPEG thumbnails for image previews
- **QR code generation** — each event has a downloadable QR code that links directly to the upload page
- **Public or private gallery** — event galleries can be opened to anonymous visitors or kept private
- **Bulk ZIP download** — download all or selected media as a single ZIP archive with a time-limited link
- **Email ingestion** — poll a dedicated IMAP or POP3 mailbox and automatically import photo/video attachments
- **S3-compatible storage** — store media on local disk or any S3-compatible object store (AWS, MinIO, Cloudflare R2, etc.)
- **SQLite or MySQL** — use embedded SQLite for simple deployments or MySQL for production
- **OIDC single sign-on** — optional OpenID Connect login alongside username/password authentication
- **Admin dashboard** — manage users, events, and monitor email ingestion status
- **Session-based authentication** — secure server-side sessions via signed cookies
- **Duplicate detection** — re-uploading the same filename by the same guest overwrites the previous file

---

## Quick Start

The fastest way to run EventDrop is with Docker Compose. The image is available on Docker Hub as `acaranta/eventdrop:latest`.

Download the `docker-compose.yml` file (or clone the repository) and start the stack:

```bash
docker compose up -d
```

No build step is needed — Docker will pull the pre-built image automatically.

The application starts on **http://localhost:8000**. Log in with the default credentials:

- **Username:** `admin`
- **Password:** `changeme`

> **Important:** Change the default password and the `EVENTDROP_SECRET_KEY` before exposing the application to any network. See the [Security Notes](#security-notes) section.

To follow logs:

```bash
docker compose logs -f
```

To stop:

```bash
docker compose down
```

Persistent data (database and media files) is stored in the `eventdrop_data` Docker volume.

---

## Building from Source

If you want to build the Docker image yourself instead of using the pre-built one from Docker Hub:

```bash
git clone <repository-url>
cd eventdrop
docker build -t acaranta/eventdrop:latest .
```

Then run with Docker Compose as normal — the locally built image will be used since its tag matches the one referenced in `docker-compose.yml`.

---

## Configuration

All settings are read from environment variables prefixed with `EVENTDROP_`. The Docker Compose file provides a ready-to-use template that you can customise.

### Full Variable Reference

| Variable | Default | Description |
|---|---|---|
| `EVENTDROP_ADMIN_USERNAME` | `admin` | Username for the built-in administrator account |
| `EVENTDROP_ADMIN_PASSWORD` | `changeme` | Password for the administrator account — **change this** |
| `EVENTDROP_SECRET_KEY` | `dev-secret-key-change-in-production` | Key used to sign session cookies and to encrypt stored email passwords — **change this** |
| `EVENTDROP_DB_TYPE` | `sqlite` | Database engine: `sqlite` or `mysql` |
| `EVENTDROP_DB_PATH` | `/data/eventdrop.db` | Filesystem path to the SQLite database file (used when `DB_TYPE=sqlite`) |
| `EVENTDROP_DB_HOST` | _(empty)_ | MySQL server hostname (used when `DB_TYPE=mysql`) |
| `EVENTDROP_DB_PORT` | `3306` | MySQL server port |
| `EVENTDROP_DB_NAME` | _(empty)_ | MySQL database name |
| `EVENTDROP_DB_USER` | _(empty)_ | MySQL username |
| `EVENTDROP_DB_PASSWORD` | _(empty)_ | MySQL password |
| `EVENTDROP_STORAGE_TYPE` | `local` | Storage backend: `local` or `s3` |
| `EVENTDROP_STORAGE_LOCAL_PATH` | `/data/media` | Directory for local media storage (used when `STORAGE_TYPE=local`) |
| `EVENTDROP_S3_ENDPOINT` | _(empty)_ | S3-compatible endpoint URL, e.g. `https://s3.example.com` (leave empty for AWS) |
| `EVENTDROP_S3_BUCKET` | _(empty)_ | S3 bucket name |
| `EVENTDROP_S3_ACCESS_KEY` | _(empty)_ | S3 access key ID |
| `EVENTDROP_S3_SECRET_KEY` | _(empty)_ | S3 secret access key |
| `EVENTDROP_S3_REGION` | `us-east-1` | S3 region |
| `EVENTDROP_S3_USE_SSL` | `true` | Whether to use SSL/TLS for S3 connections |
| `EVENTDROP_OIDC_ENABLED` | `false` | Enable OpenID Connect authentication |
| `EVENTDROP_OIDC_PROVIDER_URL` | _(empty)_ | OIDC provider base URL, e.g. `https://auth.example.com/realms/myrealm` |
| `EVENTDROP_OIDC_CLIENT_ID` | _(empty)_ | OIDC client ID |
| `EVENTDROP_OIDC_CLIENT_SECRET` | _(empty)_ | OIDC client secret |
| `EVENTDROP_OIDC_DISPLAY_NAME` | `Login with SSO` | Label shown on the SSO login button |
| `EVENTDROP_EMAIL_INGESTION_ENABLED` | `true` | Enable the email ingestion background service |
| `EVENTDROP_EMAIL_POLL_INTERVAL_SECONDS` | `120` | How often (in seconds) to poll configured mailboxes |
| `EVENTDROP_ARCHIVE_TEMP_PATH` | `/data/tmp` | Directory where ZIP archives are temporarily stored |
| `EVENTDROP_ARCHIVE_EXPIRY_MINUTES` | `15` | How many minutes a download link remains valid before expiry |
| `EVENTDROP_BASE_URL` | `http://localhost:8000` | Public base URL of the application — used in generated upload links and QR codes |
| `EVENTDROP_MAX_UPLOAD_SIZE_MB` | `500` | Maximum allowed size per uploaded file in megabytes |

---

## Development Setup

### Prerequisites

- Python 3.13+
- [uv](https://github.com/astral-sh/uv) package manager
- `libmagic` system library (for MIME type detection)

Install system dependencies on Debian/Ubuntu:

```bash
sudo apt-get install libmagic1 libmagic-dev libjpeg-dev libpng-dev libwebp-dev
```

### Install the Project

```bash
git clone <repository-url>
cd eventdrop

# Create a virtual environment and install all dependencies (including dev)
uv sync
```

### Run the Development Server

```bash
# Apply database migrations
uv run alembic upgrade head

# Start the server with auto-reload
uv run uvicorn eventdrop.main:app --reload --host 0.0.0.0 --port 8000
```

The application is available at **http://localhost:8000**.

On first startup, the application creates all database tables and provisions the admin user defined by `EVENTDROP_ADMIN_USERNAME` and `EVENTDROP_ADMIN_PASSWORD`.

### Run Tests

```bash
uv run pytest
```

### Create a New Database Migration

After modifying `src/eventdrop/database/models.py`, generate an Alembic migration:

```bash
uv run alembic revision --autogenerate -m "describe your change"
uv run alembic upgrade head
```

---

## Architecture Overview

### Technology Stack

| Layer | Technology |
|---|---|
| Language | Python 3.13 |
| Web framework | FastAPI |
| Templates | Jinja2 + Tailwind CSS |
| ORM | SQLAlchemy 2 (async) |
| Migrations | Alembic |
| Database | SQLite (aiosqlite) or MySQL (aiomysql) |
| Storage | Local filesystem (aiofiles) or S3 (boto3) |
| Session middleware | Starlette `SessionMiddleware` (signed cookies) |
| OIDC | Authlib |
| Email | Python standard library `imaplib` / `poplib` |
| QR codes | qrcode + Pillow |
| EXIF | exifread |
| MIME detection | python-magic |
| Build / package | uv + Hatchling |
| Container | Docker (multi-stage, `python:3.13-slim`) |

### Project Structure

```
eventdrop/
├── src/eventdrop/
│   ├── main.py                  # FastAPI app factory, lifespan, middleware
│   ├── config.py                # Pydantic Settings (all EVENTDROP_* vars)
│   ├── auth/
│   │   ├── dependencies.py      # get_current_user, require_admin
│   │   ├── oidc.py              # Authlib OAuth client setup
│   │   ├── passwords.py         # bcrypt hash/verify helpers
│   │   └── routes.py            # /auth/login, /auth/signup, /auth/oidc/*
│   ├── database/
│   │   ├── engine.py            # Async SQLAlchemy engine + session factory
│   │   ├── models.py            # ORM models (User, Event, MediaFile, …)
│   │   └── session.py           # get_db dependency
│   ├── routes/
│   │   ├── admin.py             # /admin/* (dashboard, users, events)
│   │   ├── api.py               # /api/* (download, delete, health)
│   │   ├── events.py            # /events/* (CRUD, QR code)
│   │   ├── gallery.py           # /e/{id}/gallery/
│   │   └── upload.py            # /e/{id}/ (upload page and file upload API)
│   ├── services/
│   │   ├── archive_service.py   # ZIP generation and timed-link management
│   │   ├── email_ingestion.py   # IMAP/POP3 polling background task
│   │   ├── event_service.py     # Event CRUD
│   │   ├── media_service.py     # File storage, thumbnails, EXIF, dedup
│   │   └── user_service.py      # User CRUD
│   ├── storage/
│   │   ├── base.py              # Abstract StorageBackend interface
│   │   ├── local.py             # LocalStorage — files on disk
│   │   └── s3.py                # S3Storage — boto3-backed
│   ├── templates/               # Jinja2 HTML templates
│   └── utils/
│       └── qrcode.py            # QR code generation helpers
├── alembic/                     # Alembic migration environment
├── tests/                       # pytest test suite
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

### Background Tasks

Two asyncio tasks run for the lifetime of the application process:

- **Email ingestion loop** — polls all enabled per-event mailboxes every `EVENTDROP_EMAIL_POLL_INTERVAL_SECONDS` seconds (disabled if `EVENTDROP_EMAIL_INGESTION_ENABLED=false`)
- **Archive cleanup loop** — runs every 5 minutes and deletes expired ZIP files from `EVENTDROP_ARCHIVE_TEMP_PATH`

---

## Usage Guide

### Creating an Event

1. Log in and navigate to **My Events**.
2. Click **Create Event**.
3. Enter a name and optional description.
4. Choose gallery visibility:
   - **Public gallery** — anyone with the gallery link can browse media without logging in.
   - **Allow public download** — guests can download media from the gallery; unchecked means only the owner can download.
5. Optionally configure email ingestion (see [Email Ingestion](#email-ingestion)).
6. Submit the form. You are redirected to the event edit page.

### Sharing the Upload Link

The event edit page shows:
- A shareable **upload URL** in the form `https://<base_url>/e/<event_id>/`
- An inline **QR code** for printing or sharing on screen
- A **Download QR PNG** button to save a high-resolution QR code image

Share either the URL or the QR code with guests. Guests open the link, enter their email address, and drag-and-drop or select files to upload. The email is stored in a browser cookie so guests do not need to re-enter it on subsequent visits.

### Gallery

Browse uploaded media at `/e/<event_id>/gallery/`. The gallery shows thumbnails for images and file info for videos. Event owners and admins see additional controls.

### Bulk Download

From the gallery, select individual files or click **Download All**. EventDrop assembles a ZIP archive on demand and provides a time-limited download link (default: 15 minutes). The archive is named after the event and the number of files included.

### Upload Messages

When uploading files, users can optionally add a text message (up to 500 characters) to their batch. The message is attached to every file in that upload session. A "Make message visible to everyone" toggle controls whether the message appears in the public gallery or only to the event owner/admin. Messages are sanitized: HTML is escaped, URLs are deactivated, and JavaScript injection is prevented.

### Gallery Filtering

The gallery supports filtering by uploader and upload type. Use the filter bar at the top of the gallery to view photos from a specific contributor or filter by "Web upload" vs "Email". Filters are applied via URL query parameters (`?uploader=email@example.com&source=upload`), making filtered views shareable.

### Media Attribution

Each media item in the gallery displays its filename, file size, upload date, uploader email, and source type. If the uploader added a message, it appears below the media thumbnail.

### Contributors List

The event management page and gallery both show a contributors panel listing everyone who uploaded media, with their upload count and a link to filter the gallery to their contributions only.

### Managing an Event

From the event edit page, the owner can:
- Update name, description, and visibility settings
- Activate or deactivate the event (deactivated events reject new uploads)
- Update or disable the email ingestion configuration
- Delete the event (removes all media from storage)

Administrators have full access to all events via the `/admin/` dashboard.

---

## Email Ingestion

EventDrop can automatically import photos and videos sent to a dedicated email address. This is useful when guests prefer to send media by email rather than using the web interface.

### How It Works

1. Create a dedicated email account (e.g. `mywedding@mail.example.com`).
2. On the event creation or edit page, enable **Email Ingestion** and provide the mailbox credentials.
3. EventDrop polls the mailbox on a background task at the configured interval.
4. All image and video attachments found in new/unread messages are imported into the event's media library.
5. The sender's email address is recorded as the uploader.

### Configuration Fields

| Field | Description |
|---|---|
| Protocol | `imap` (recommended) or `pop3` |
| Server host | Mail server hostname, e.g. `imap.gmail.com` |
| Server port | Default `993` (IMAP SSL) or `110`/`995` (POP3) |
| Use SSL | Enable TLS — strongly recommended |
| Username | Mailbox login username |
| Password | Mailbox password — stored encrypted using the `EVENTDROP_SECRET_KEY` |
| Email address | The address guests send media to (displayed on the upload page) |
| Delete after ingestion | Delete messages from the server after processing; if disabled, messages are marked as read (IMAP) or tracked by UID (POP3) |

### IMAP vs POP3

- **IMAP** is preferred. EventDrop fetches only `UNSEEN` messages and marks them read (or deletes them) after processing. No additional deduplication state is stored.
- **POP3** does not have a read/unread concept. EventDrop tracks processed message UIDs in the `processed_emails` table to avoid importing the same message twice.

### Testing the Connection

On the event edit page, click **Test Connection** to verify the credentials without saving, before the next scheduled poll.

### Poll Status

The admin dashboard shows the last poll time, status (`success` or `error`), error message, and number of files ingested for each configured mailbox.

---

## Storage Backends

### Local Filesystem (default)

Media files are written to the directory specified by `EVENTDROP_STORAGE_LOCAL_PATH` (default `/data/media`). Files are served directly by the application at `/media/<path>`.

The directory layout inside the storage root is:

```
<event_id>/<email_hash>/<YYYYMMDD_HHMMSS>_<original_filename>
```

Thumbnails are stored alongside originals with a `thumb_` prefix.

No additional configuration is required beyond ensuring the directory exists and is writable by the application process.

### S3-Compatible Object Storage

Set `EVENTDROP_STORAGE_TYPE=s3` and supply the remaining S3 variables:

```dotenv
EVENTDROP_STORAGE_TYPE=s3
EVENTDROP_S3_BUCKET=my-eventdrop-bucket
EVENTDROP_S3_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE
EVENTDROP_S3_SECRET_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
EVENTDROP_S3_REGION=eu-west-1
```

For self-hosted S3-compatible services (MinIO, Ceph, Cloudflare R2), also set:

```dotenv
EVENTDROP_S3_ENDPOINT=https://s3.example.com
```

Leave `EVENTDROP_S3_ENDPOINT` empty to use AWS S3.

Media URLs returned to clients are pre-signed URLs with a 1-hour expiry, generated on demand by boto3. No public bucket policy is required.

---

## Database

### SQLite (default)

SQLite requires no external server. The database is a single file at `EVENTDROP_DB_PATH`. This is the recommended choice for single-server deployments.

### MySQL

For higher-concurrency deployments or when an existing MySQL infrastructure is available:

```dotenv
EVENTDROP_DB_TYPE=mysql
EVENTDROP_DB_HOST=db.example.com
EVENTDROP_DB_PORT=3306
EVENTDROP_DB_NAME=eventdrop
EVENTDROP_DB_USER=eventdrop
EVENTDROP_DB_PASSWORD=secure-password
```

EventDrop uses `aiomysql` for async MySQL connectivity. The database must exist before starting the application; EventDrop will not create it automatically.

### Migrations

EventDrop uses **Alembic** for schema management. The Docker image runs `alembic upgrade head` automatically at container startup before launching the server.

For manual migration management:

```bash
# Apply all pending migrations
uv run alembic upgrade head

# Check current migration version
uv run alembic current

# Roll back one step
uv run alembic downgrade -1

# Generate a new migration after model changes
uv run alembic revision --autogenerate -m "add column foo to events"
```

> **Note:** On first startup (without a pre-existing database), the application also calls SQLAlchemy's `create_all` as a safety net. In production, prefer relying exclusively on Alembic to track the schema version.

---

## Authentication

### Username and Password

EventDrop ships with session-based username/password authentication backed by bcrypt password hashing (via `passlib`).

- Users can sign up at `/auth/signup`.
- The admin account is provisioned automatically from `EVENTDROP_ADMIN_USERNAME` and `EVENTDROP_ADMIN_PASSWORD` on every startup. If the account already exists its password is updated to match the environment variable.
- Passwords must be at least 8 characters.

### OpenID Connect (OIDC)

OIDC support is implemented with **Authlib** and works with any standards-compliant provider (Keycloak, Authentik, Auth0, Google, GitHub via OIDC proxy, etc.).

Enable OIDC by setting:

```dotenv
EVENTDROP_OIDC_ENABLED=true
EVENTDROP_OIDC_PROVIDER_URL=https://auth.example.com/realms/myrealm
EVENTDROP_OIDC_CLIENT_ID=eventdrop
EVENTDROP_OIDC_CLIENT_SECRET=your-client-secret
EVENTDROP_OIDC_DISPLAY_NAME=Login with Keycloak
```

EventDrop uses the `/.well-known/openid-configuration` discovery document from `EVENTDROP_OIDC_PROVIDER_URL` and requests the `openid email profile` scope.

> **Important:** `EVENTDROP_BASE_URL` must be set to the public-facing URL of your EventDrop instance (e.g. `https://eventdrop.yourdomain.com`). The redirect URI sent to the OIDC provider is built as:
>
> ```
> <EVENTDROP_BASE_URL>/auth/oidc/callback
> ```
>
> This value must exactly match a `redirect_uri` registered in your OIDC client configuration. If `EVENTDROP_BASE_URL` is left at its default (`http://localhost:8000`) or set incorrectly, the provider will reject the authorization request with an `invalid_request` error stating that the redirect URI does not match.

**Account linking behaviour:**

1. If a user with the matching OIDC `sub` claim already exists, they are logged in directly.
2. If no match is found but the email matches an existing local user, that user is linked to the OIDC subject.
3. Otherwise, a new account is created with the username derived from `preferred_username`, `name`, or the email prefix.

OIDC and local username/password authentication can coexist. When OIDC is configured, an SSO login button appears on the login page alongside the standard form.

#### Authelia

EventDrop works with [Authelia](https://www.authelia.com/) 4.38+. Add a client entry to your Authelia `configuration.yml`:

```yaml
identity_providers:
  oidc:
    clients:
      - client_id: eventdrop
        client_name: EventDrop
        # Generate with: authelia crypto hash generate pbkdf2 --random --random.length 64
        client_secret: '$pbkdf2-sha512$310000$<your-generated-hash>'
        public: false
        authorization_policy: one_factor  # change to two_factor to require MFA
        redirect_uris:
          # Must match <EVENTDROP_BASE_URL>/auth/oidc/callback exactly
          - https://eventdrop.example.com/auth/oidc/callback
        scopes:
          - openid
          - profile
          - email
        response_types:
          - code
        grant_types:
          - authorization_code
        token_endpoint_auth_method: client_secret_basic
```

Then configure EventDrop to point at your Authelia instance:

```dotenv
# Must match the redirect_uris entry in the Authelia client config above
# The redirect URI sent to Authelia will be: https://eventdrop.example.com/auth/oidc/callback
EVENTDROP_BASE_URL=https://eventdrop.example.com
EVENTDROP_OIDC_ENABLED=true
# Authelia issuer base URL — no path suffix needed, discovery is automatic
EVENTDROP_OIDC_PROVIDER_URL=https://auth.example.com
EVENTDROP_OIDC_CLIENT_ID=eventdrop
# Plain-text secret here; Authelia stores only the hash above
EVENTDROP_OIDC_CLIENT_SECRET=your-plain-text-secret
EVENTDROP_OIDC_DISPLAY_NAME=Login with Authelia
```

### Admin Access

Users with `is_admin=true` can access the `/admin/` panel. Admin status can be toggled from the admin users page. The initial admin user created from the environment variables always has admin access.

---

## Security Notes

### Secret Key

`EVENTDROP_SECRET_KEY` serves two purposes:

1. **Session cookie signing** — Starlette's `SessionMiddleware` uses it to sign the session cookie. If the key is compromised or rotated, all existing sessions are immediately invalidated.
2. **Email password encryption** — Per-event mailbox passwords are encrypted with Fernet symmetric encryption, using a key derived from `EVENTDROP_SECRET_KEY` via SHA-256. Rotating the secret key will make all stored email passwords unreadable; re-enter them after any key rotation.

Generate a strong key before deploying:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Default Credentials

The default admin password `changeme` must be replaced via the `EVENTDROP_ADMIN_PASSWORD` environment variable before any public-facing deployment. Setting the variable to a new value is sufficient — the admin account password is updated on every restart.

### Upload Size Limit

`EVENTDROP_MAX_UPLOAD_SIZE_MB` caps the size of each individual file upload. The limit is enforced in application code after reading the request body; it is advisable to also configure a matching limit at the reverse proxy level (nginx `client_max_body_size`, Caddy `request_body max_size`).

### MIME Type Validation

Uploaded file types are validated using `python-magic` (libmagic), which inspects file content rather than relying on the file extension or `Content-Type` header. Only the following types are accepted:

`image/jpeg`, `image/png`, `image/heic`, `image/heif`, `image/webp`, `image/gif`, `video/mp4`, `video/quicktime`, `video/x-msvideo`, `video/x-matroska`, `video/webm`

### Reverse Proxy

For production deployments, run EventDrop behind a TLS-terminating reverse proxy (nginx, Caddy, Traefik). Ensure the proxy forwards `X-Forwarded-For` and `X-Forwarded-Proto` headers if needed for correct URL generation.

Set `EVENTDROP_BASE_URL` to the public HTTPS URL so that generated upload links and QR codes point to the correct address.
