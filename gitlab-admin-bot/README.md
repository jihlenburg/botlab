# GitLab Admin Bot

AI-powered GitLab administration bot with automated monitoring, maintenance, and backup verification.

## Features

- **Health Monitoring**: GitLab endpoints, resources (disk, CPU, memory)
- **Backup Management**: Automated backups, age monitoring, restore testing
- **AI Analysis**: Claude-powered system analysis and recommendations
- **Alerting**: Email notifications with cooldown and deduplication
- **Maintenance**: Automated cleanup, registry GC, database vacuum
- **Disaster Recovery**: Automated server provisioning and restore

## Quick Start

```bash
# Install dependencies
pip install -e ".[dev]"

# Copy environment template
cp .env.example .env
# Edit .env with your values

# Run locally
python -m src.main

# Or with Docker
docker compose up -d
```

## Configuration

### Environment Variables

See `.env.example` for all available variables. Required:

- `GITLAB_PRIVATE_TOKEN` - GitLab API token with `api` scope
- `HETZNER_API_TOKEN` - Hetzner Cloud API token
- `BORG_PASSPHRASE` - BorgBackup encryption passphrase
- `SMTP_PASSWORD` - Email alerting credentials

### Config File

Edit `config/config.yaml` for non-secret settings (thresholds, intervals, etc.)

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/status` | GET | System status (health, resources, backup) |
| `/metrics` | GET | Prometheus metrics |
| `/analyze` | POST | Trigger AI analysis |
| `/backup` | POST | Trigger manual backup |
| `/scheduler/jobs` | GET | List scheduled jobs |
| `/maintenance/{task}` | POST | Run maintenance task |

## Development

```bash
# Run tests
pytest tests/ -v

# Run linting
ruff check src/ tests/

# Type checking
mypy src/ --ignore-missing-imports

# Format code
ruff format src/ tests/
```

## License

MIT
