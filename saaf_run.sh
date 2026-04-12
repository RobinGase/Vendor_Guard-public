#!/bin/sh
set -eu

cd /audit_workspace/vendor_guard
printf '%s\n' "wrapper_start" >> /audit_workspace/saaf_wrapper.log
printf '%s\n' "wrapper_exec" >> /audit_workspace/saaf_entrypoint.stdout
printf '%s\n' "wrapper_exec" >> /audit_workspace/saaf_entrypoint.stderr
exec /opt/vendor-guard-venv/bin/python saaf_entrypoint.py >> /audit_workspace/saaf_entrypoint.stdout 2>> /audit_workspace/saaf_entrypoint.stderr
