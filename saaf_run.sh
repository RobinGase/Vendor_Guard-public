#!/bin/sh
set -eu

rm -rf /tmp/vendor_guard_runtime
cp -a /audit_workspace/vendor_guard /tmp/vendor_guard_runtime
cd /tmp/vendor_guard_runtime
rm -f /audit_workspace/saaf_wrapper.log /audit_workspace/saaf_entrypoint.log /audit_workspace/saaf_entrypoint.stdout /audit_workspace/saaf_entrypoint.stderr /audit_workspace/vendor_profile_raw.txt
printf '%s\n' "wrapper_start" >> /audit_workspace/saaf_wrapper.log
printf '%s\n' "wrapper_exec" >> /audit_workspace/saaf_entrypoint.stdout
printf '%s\n' "wrapper_exec" >> /audit_workspace/saaf_entrypoint.stderr
exec /opt/vendor-guard-venv/bin/python /tmp/vendor_guard_runtime/saaf_entrypoint.py >> /audit_workspace/saaf_entrypoint.stdout 2>> /audit_workspace/saaf_entrypoint.stderr
