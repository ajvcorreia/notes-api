# notes-api

A small FastAPI service that puts a plain REST API in front of a
self-hosted [Joplin Server](https://joplinapp.org/help/apps/sync/joplin_server/)
instance, so third-party apps can create, read, update and delete notes,
notebooks and attachments without speaking Joplin's internal sync protocol.

## Why

Joplin Server (the sync target you self-host) has no friendly HTTP API of
its own - it exposes the same low-level *item* API the desktop/mobile apps
use to sync, where every note or notebook is a single flat text blob in
Joplin's own serialization format, addressed by a 32-character id. (Joplin's
actual [Data API](https://joplinapp.org/help/api/references/rest_api/) *is*
a normal REST API, but it only runs inside the desktop app, not the server.)

`notes-api` logs into Joplin Server with its own account, serializes and
parses that text format, and exposes ordinary JSON over HTTP instead -
protected by a single API key, containerized, and deployable next to your
Joplin Server stack.

## Related projects

[Joppy](https://github.com/marph91/joppy) is a Python library that wraps
both the Joplin desktop and Joplin Server APIs, including its own
reverse-engineered handling of the server's item format - if you're working
in Python and don't need a standalone HTTP service, it's worth a look
instead of (or alongside) this.

## Features

- CRUD for notes and notebooks (`/notes`, `/notebooks`)
- File attachments: `POST /notes/{id}/attachments` uploads a file as a
  Joplin resource and links it into the note body
- Single `X-API-Key` header for auth
- Ships as a Docker image; `docker compose up` and it's running

## Requirements

A running Joplin Server instance and a dedicated Joplin account for this
service to log in as (don't reuse your personal or admin account - see
below).

## Deploying

Pull the published image:

```bash
cp .env.example .env   # fill in real values
docker compose up -d   # pulls ajvcorreia/notes-api:latest
```

Or build it yourself - comment out `image:` and uncomment `build: .` in
`compose.yaml`, then `docker compose up -d --build`.

`JOPLIN_BASE_URL` must exactly match your Joplin Server's configured
`APP_BASE_URL` - Joplin Server rejects requests whose Origin doesn't match
it, so pointing this at an internal docker hostname generally won't work
even if it's network-reachable; use the same base URL your other Joplin
clients connect to.

### Creating the account notes-api logs in as

Don't reuse an admin account. Log in as an existing admin to create a
dedicated user, then confirm its email directly in Postgres (there's no
mail flow for made-up addresses like `notes-api@example.local`):

```bash
# get an admin session
curl -X POST http://<joplin-host>:22300/api/sessions \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@localhost","password":"admin"}'

# create the service account (use the session id from above)
curl -X POST http://<joplin-host>:22300/api/users \
  -H "X-API-AUTH: <session id>" -H 'Content-Type: application/json' \
  -d '{"email":"notes-api@example.local","password":"<pick one>","full_name":"Notes API Service"}'

# confirm the email and clear must_set_password so it can log in
docker exec <joplin-postgres-container> psql -U <pg user> -d joplin -c \
  "UPDATE users SET email_confirmed=1, must_set_password=0 WHERE email='notes-api@example.local';"
```

Any Joplin client (desktop, mobile) that syncs using this same account will
share the exact same notes the API manages.

## API

All routes except `/health` require `X-API-Key: <API_KEY>`.

| Method | Path                      | Description                                      |
|--------|---------------------------|---------------------------------------------------|
| GET    | `/notes`                  | List notes, **without body** (`?parent_id=` to filter) |
| GET    | `/notes/{id}`              | Get one note, including body                       |
| POST   | `/notes`                    | Create a note                                       |
| PUT    | `/notes/{id}`              | Update a note (partial)                            |
| DELETE | `/notes/{id}`              | Delete a note                                       |
| POST   | `/notes/{id}/attachments`  | Upload a file, attach it to the note (multipart)    |
| GET    | `/notebooks`                | List notebooks                                      |
| POST   | `/notebooks`                | Create a notebook                                    |
| DELETE | `/notebooks/{id}`          | Delete a notebook                                    |

```bash
curl -X POST http://localhost:8000/notes \
  -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' \
  -d '{"title": "Hello", "body": "World", "parent_id": "<notebook id>"}'

curl -X POST http://localhost:8000/notes/<note id>/attachments \
  -H "X-API-Key: $API_KEY" -F "file=@photo.png;type=image/png"
```

Interactive docs at `/docs` once the service is running.

## Publishing (Docker Hub)

`.github/workflows/docker-publish.yml` builds and pushes
[`ajvcorreia/notes-api`](https://hub.docker.com/r/ajvcorreia/notes-api)
(linux/amd64 + linux/arm64) automatically:

- every push to `main` updates the `latest` tag
- pushing a tag like `v1.2.3` also publishes `1.2.3` and `1.2` tags

It needs two repository secrets under **Settings > Secrets and variables >
Actions**:

- `DOCKERHUB_USERNAME` - your Docker Hub username
- `DOCKERHUB_TOKEN` - a Docker Hub [access token](https://hub.docker.com/settings/security)
  (Account Settings > Security > New Access Token), **not** your password

## Limitations

- **`GET /notes` is O(n) in your total note count.** Joplin Server has no
  metadata-only listing endpoint - every note's raw content still has to be
  downloaded and parsed to know its title/type/parent_id, even though the
  response now omits `body`. On a library with thousands of notes this can
  still take several seconds; it just no longer also ships megabytes of
  body text in the response.
- **End-to-end encryption is not supported.** If any client syncing to
  this Joplin Server account enables E2EE, note bodies become encrypted
  blobs that `notes-api` cannot read or write without the encryption
  master key.
- The item-format parser assumes the single-blank-line separator format
  Joplin itself generates. It's been tested against real Joplin Server
  round-trips (including bodies containing Joplin resource links, which
  contain colons) but hasn't been fuzzed against every note a desktop
  client might produce (conflicts, encrypted items, etc.).
