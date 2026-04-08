#!/bin/bash
set -e

CRON_SCHEDULE="${BACKUP_CRON:-0 3 * * *}"

# Write env vars for cron to source. Use printf %q so values containing spaces
# or shell metacharacters survive sourcing. BACKUP_CRON itself is excluded
# because backup.sh does not need it and its unquoted value would otherwise
# break ". /etc/backup.env" (e.g. "BACKUP_CRON=0 3 * * *").
: > /etc/backup.env
while IFS='=' read -r k v; do
    printf '%s=%q\n' "$k" "$v" >> /etc/backup.env
done < <(env | grep -E '^(MONGO_|BACKUP_)' | grep -v '^BACKUP_CRON=')

# Create cron job
cat > /etc/cron.d/backup << EOF
${CRON_SCHEDULE} root . /etc/backup.env && /usr/local/bin/backup.sh >> /var/log/backup.log 2>&1
EOF
chmod 0644 /etc/cron.d/backup

# Create log file
touch /var/log/backup.log

echo "Backup cron configured: ${CRON_SCHEDULE}"
echo "Retention: ${BACKUP_RETENTION_DAYS:-7} days"

# Start cron in foreground
exec cron -f
