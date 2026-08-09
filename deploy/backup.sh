#!/bin/sh
# Nightly Postgres dump, pruned locally and pushed offsite.
#
# A dump sitting on the same disk as the database is not a backup — it dies
# with the box. Set BACKUP_REMOTE to an rclone destination (Hetzner Storage
# Box, Backblaze B2, S3...) and dumps are copied there after every run.
#
# Runs as its own container on a sleep loop rather than host cron, so the
# whole stack stays inside `docker compose`.

set -eu

BACKUP_DIR=${BACKUP_DIR:-/backups}
KEEP_DAYS=${BACKUP_KEEP_DAYS:-14}
INTERVAL=${BACKUP_INTERVAL_SECONDS:-86400}
DB_NAME=${DB_NAME:-sauron_vision}
DB_USER=${DB_USER:-sauron}
DB_HOST=${DB_HOST:-postgres}

mkdir -p "$BACKUP_DIR"

while true; do
	STAMP=$(date -u +%Y%m%dT%H%M%SZ)
	FILE="$BACKUP_DIR/sauron-$STAMP.dump"

	echo "[backup] dumping $DB_NAME -> $FILE"
	if pg_dump -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -Fc -f "$FILE"; then
		echo "[backup] ok ($(du -h "$FILE" | cut -f1))"
	else
		echo "[backup] FAILED — leaving previous dumps in place" >&2
		rm -f "$FILE"
		sleep "$INTERVAL"
		continue
	fi

	# Offsite copy. Without this the backup dies with the machine.
	if [ -n "${BACKUP_REMOTE:-}" ]; then
		if command -v rclone >/dev/null 2>&1; then
			echo "[backup] copying to $BACKUP_REMOTE"
			rclone copy "$FILE" "$BACKUP_REMOTE" || \
				echo "[backup] offsite copy FAILED" >&2
		else
			echo "[backup] BACKUP_REMOTE set but rclone is not installed" >&2
		fi
	else
		echo "[backup] WARNING: BACKUP_REMOTE unset — dumps are local only," \
		     "so a disk failure loses them with the database" >&2
	fi

	find "$BACKUP_DIR" -name 'sauron-*.dump' -mtime "+$KEEP_DAYS" -delete
	sleep "$INTERVAL"
done
