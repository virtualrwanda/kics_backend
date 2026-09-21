"""
Backup the MySQL database to a timestamped .sql file.
Schedule with Windows Task Scheduler or cron.
"""

import os
import subprocess
import gzip
import logging
from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

BACKUP_DIR = Path("backups")
BACKUP_DIR.mkdir(exist_ok=True)
KEEP_DAYS = 30


def backup():
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    raw_file = BACKUP_DIR / f"kics_{timestamp}.sql"
    gz_file = BACKUP_DIR / f"kics_{timestamp}.sql.gz"

    cmd = [
        "mysqldump",
        f"-h{settings.MYSQL_HOST}",
        f"-P{settings.MYSQL_PORT}",
        f"-u{settings.MYSQL_USER}",
        f"-p{settings.MYSQL_PASSWORD}" if settings.MYSQL_PASSWORD else "",
        "--single-transaction",
        "--routines",
        "--triggers",
        settings.MYSQL_DB,
    ]
    cmd = [c for c in cmd if c]

    logger.info(f"🗄️  Backing up {settings.MYSQL_DB} → {gz_file}")

    with raw_file.open("wb") as f:
        result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE)
        if result.returncode != 0:
            logger.error(f"❌ mysqldump failed: {result.stderr.decode()}")
            raw_file.unlink(missing_ok=True)
            return False

    # Compress
    with raw_file.open("rb") as f_in, gzip.open(gz_file, "wb") as f_out:
        f_out.writelines(f_in)
    raw_file.unlink()

    size_mb = gz_file.stat().st_size / (1024 * 1024)
    logger.info(f"✅ Backup created: {gz_file.name} ({size_mb:.2f} MB)")

    # Cleanup old backups
    cutoff = datetime.utcnow() - timedelta(days=KEEP_DAYS)
    removed = 0
    for old in BACKUP_DIR.glob("kics_*.sql.gz"):
        if datetime.fromtimestamp(old.stat().st_mtime) < cutoff:
            old.unlink()
            removed += 1
    if removed:
        logger.info(f"🧹 Removed {removed} old backups")

    return True


if __name__ == "__main__":
    backup()