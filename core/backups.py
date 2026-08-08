"""Phase-33 daily PostgreSQL backup + retention.

Calls `pg_dump -Fc` against the configured DB and writes to BACKUP_DIR
(default `/app/backups`, mounted as a volume in docker-compose.prod.yml).
Retention: keep last `BACKUP_KEEP_DAYS` (default 30) of dumps; older are
unlinked.

Skipped silently when:
  - DB engine isn't postgres (sqlite dev box has no pg_dump)
  - BACKUP_DIR doesn't exist or isn't writable
  - pg_dump binary not on PATH

Returns {ok, path, size_bytes, deleted, reason}. Never raises.
"""
import logging
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)


def _backup_dir() -> Path:
    return Path(os.getenv("BACKUP_DIR", "/app/backups"))


def _keep_days() -> int:
    try:
        return max(1, int(os.getenv("BACKUP_KEEP_DAYS", "30")))
    except ValueError:
        return 30


def run_postgres_backup() -> dict:
    """Take a single `pg_dump -Fc` dump + prune older ones.

    Looks up DB credentials from Django's `settings.DATABASES["default"]`.
    Output filename: `sauron-YYYYMMDD-HHMMSS.dump`.
    """
    db = settings.DATABASES.get("default", {})
    engine = db.get("ENGINE", "")
    if "postgresql" not in engine:
        return {"ok": False, "reason": "not_postgres", "engine": engine}

    backup_dir = _backup_dir()
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"ok": False, "reason": "backup_dir_unwritable", "error": str(e)}

    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        return {"ok": False, "reason": "pg_dump_not_found"}

    name = db.get("NAME") or os.getenv("DB_NAME", "sauron_vision")
    user = db.get("USER") or os.getenv("DB_USER", "sauron")
    host = db.get("HOST") or os.getenv("DB_HOST", "db")
    port = str(db.get("PORT") or os.getenv("DB_PORT", "5432"))
    password = db.get("PASSWORD") or os.getenv("DB_PASSWORD", "")

    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    out_path = backup_dir / f"sauron-{timestamp}.dump"

    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password

    try:
        result = subprocess.run(
            [pg_dump,
              "-Fc",                # custom binary format (compressed)
              "-h", host, "-p", port, "-U", user, "-d", name,
              "-f", str(out_path)],
            env=env, capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            logger.error("pg_dump failed: %s", result.stderr[:500])
            return {"ok": False, "reason": "pg_dump_failed",
                     "stderr": result.stderr[:500]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "pg_dump_timeout"}
    except Exception as e:
        return {"ok": False, "reason": "pg_dump_exception", "error": str(e)}

    size = out_path.stat().st_size if out_path.exists() else 0

    # Retention: delete older than BACKUP_KEEP_DAYS.
    cutoff = datetime.utcnow() - timedelta(days=_keep_days())
    deleted = 0
    try:
        for old in backup_dir.glob("sauron-*.dump"):
            if datetime.utcfromtimestamp(old.stat().st_mtime) < cutoff:
                try:
                    old.unlink()
                    deleted += 1
                except Exception:
                    pass
    except Exception as e:
        logger.warning("Backup retention sweep failed: %s", e)

    return {
        "ok": True, "path": str(out_path),
        "size_bytes": size, "deleted": deleted,
        "kept_days": _keep_days(),
    }
