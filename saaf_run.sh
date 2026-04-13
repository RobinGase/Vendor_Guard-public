#!/bin/sh
set -eu

rm -f /audit_workspace/saaf_wrapper.log /audit_workspace/saaf_entrypoint.log /audit_workspace/saaf_entrypoint.stdout /audit_workspace/saaf_entrypoint.stderr /audit_workspace/vendor_profile_raw.txt
printf '%s\n' "wrapper_start" >> /audit_workspace/saaf_wrapper.log
printf '%s\n' "wrapper_exec" >> /audit_workspace/saaf_entrypoint.stdout
printf '%s\n' "wrapper_exec" >> /audit_workspace/saaf_entrypoint.stderr

rm -rf /tmp/vendor_guard_runtime
cp -a /audit_workspace/vendor_guard /tmp/vendor_guard_runtime
printf '%s\n' "wrapper_runtime_copied" >> /audit_workspace/saaf_wrapper.log

rm -rf /tmp/vendor-guard-venv
tar xf /opt/vendor-guard-venv.tar -C /tmp
printf '%s\n' "wrapper_venv_extracted" >> /audit_workspace/saaf_wrapper.log

cd /tmp/vendor_guard_runtime
printf '%s\n' "wrapper_python_exec" >> /audit_workspace/saaf_wrapper.log
PYTHONPATH="/tmp/vendor_guard_runtime:/tmp/vendor-guard-venv/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}" \
  exec /usr/bin/python3.12 /tmp/vendor_guard_runtime/saaf_entrypoint.py >> /audit_workspace/saaf_entrypoint.stdout 2>> /audit_workspace/saaf_entrypoint.stderr
