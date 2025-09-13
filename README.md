# TechMC Discord Bot

A modular Discord bot for TechMC with auto-discovered cogs, per-feature configuration, i18n, and Docker deployment.

## Features
- Auto-loading extensions: `features/*/cog.py`, `features/*/cogs/*.py`, `system/**/cog.py`, `system/**/cogs/*.py` with duplicate-prevention.
- Per-feature modular configuration under `config/` (health, verification, forums, etc.).
- i18n for messages and UI (`lang/`).
- Docker-friendly: supports `${VAR}` placeholders in YAML files.

## Requirements
- Python 3.11+
- Dependencies in `requirements.txt`
- Discord bot token

## Configuration
- Main file: `config.yml`
  - `command_prefix`: text command prefix
  - `log_level`: logging level
  - `guild_ids`: server IDs to speed up slash command registration during development
  - `token`: bot token (read EXCLUSIVELY from `config.yml`)
  - `features`: toggles per module
- Per-feature YAMLs under `config/<feature>/*.yml`. Examples:
  - `config/verification/api.yml`: base_url, api_key, timeout_seconds, user_agent
  - `config/verification/polymart.yml`: api_key, timeout_seconds, base

You can use `${VAR}` placeholders in YAML. The container replaces them on startup using environment variables.

## Run locally (without Docker)
1. Create and activate a virtualenv (optional):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Edit `config.yml` and set your token:
   ```yaml
   token: "YOUR_TOKEN"
   ```
4. Run:
   ```bash
   python run.py
   ```

## Docker
### Use the official image
```bash
docker pull ghcr.io/techmc-studios/discord-bot:latest
```

### Run with Docker (simple)
```bash
docker run --rm \
  -v $(pwd)/config:/app/config \
  ghcr.io/techmc-studios/discord-bot:latest
```
Note: the bot reads the token from `config.yml`. If you use `${...}` placeholders in YAML, prefer Docker Compose with `.env` (below) so they are substituted automatically.

## Docker Compose
A small templating script replaces `${VAR}` variables in all `.yml/.yaml` files at container start. To inject variables, the recommended approach is using a `.env` file and `env_file` in compose.

### docker-compose.yml (example)
```yaml
services:
  bot:
    image: ghcr.io/techmc-studios/discord-bot:latest
    container_name: techmc-discord-bot
    restart: unless-stopped
    env_file:
      - .env
```

### .env (example)
```env
# Discord
BOT_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Verification
VERIFICATION_API_BASE_URL=https://verifier.example.com
VERIFICATION_API_KEY=sk_xxxxxxxxxxxxxxxxxxxx
VERIFICATION_API_USER_AGENT=AGENT_VERIFY/1.0
```

In your YAML you can reference those variables with `${VAR}`. For example:
```yaml
# config.yml
token: "${BOT_TOKEN}"
```
```yaml
# config/verification/api.yml
verification:
  api:
    base_url: "${VERIFICATION_API_BASE_URL}"
    api_key: "${VERIFICATION_API_KEY}"
    user_agent: "${VERIFICATION_API_USER_AGENT}"
    timeout_seconds: 60
```

### Start
```bash
docker compose up -d
```
On startup, `scripts/template-configs.sh` will replace `${VAR}` placeholders in all `.yml/.yaml` under `/app` and then execute `python run.py`.

Important notes:
- If you mount `./config` as read-only (`:ro`), templating cannot write; avoid `:ro` while substituting.
- If a variable is missing in the container, `envsubst` will substitute an empty string.
- The bot token is used exclusively from `config.yml`.

## CI/CD: GitHub Actions + GHCR
A workflow in `.github/workflows/docker-image.yml`:
- Builds and publishes to GHCR (`ghcr.io/<owner>/<repo>`) for branches (`main`, `master`) and tags/releases (`v*`).
- Multi-arch builds (`linux/amd64`, `linux/arm64`).
- Branch tags: `branch`, `sha`.
- Release tags: `semver` (`x.y.z`, `x.y`, `x`), `sha`, `latest`.

Pulling a published image:
```bash
docker pull ghcr.io/techmc-studios/discord-bot:latest
# or a specific version/tag, e.g.
# docker pull ghcr.io/techmc-studios/discord-bot:<tag>
```

## Directory structure (summary)
```
core/                  # Config, i18n, logging setup
features/              # Modular features (health, verification, forums, ...)
  <feature>/cog.py     # Root cog (optional when cogs/* is present)
  <feature>/cogs/*.py  # Per-feature cogs
  <feature>/services/  # External/HTTP services
  <feature>/ui/        # Views/embeds
system/                # System cogs (admin, help, ...)
config/                # Per-module and global configuration
lang/                  # Translations
scripts/               # Scripts (templating, etc.)
run.py                 # Bot entry point
Dockerfile             # Docker image definition
docker-compose.yml     # Compose definition
```

## Troubleshooting
- "Invalid bot token!": token is invalid or `config.yml` was not properly templated. Check `.env` and ensure `token` in `config.yml` references `${BOT_TOKEN}` or has the correct value.
- Placeholders not substituted: confirm `TEMPLATE_GLOBS` covers the file extension (default `*.yml:*.yaml`) and the variable is defined in the container env (`.env`/compose).
- Need more file types: adjust `TEMPLATE_GLOBS` (e.g., `*.yml:*.yaml:*.json`).


If you need more detailed configuration examples for a specific module (e.g., verification or health), let me know and I’ll extend the README.
