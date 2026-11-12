#!/bin/sh
set -e

. /etc/apache2/envvars
export LANG=C.UTF-8
export LC_ALL=C.UTF-8

mkdir -p "$APACHE_RUN_DIR" "$APACHE_LOCK_DIR" "$APACHE_LOG_DIR"
chown "$APACHE_RUN_USER:$APACHE_RUN_GROUP" "$APACHE_LOCK_DIR"
rm -f "$APACHE_PID_FILE"

exec apache2 -D FOREGROUND