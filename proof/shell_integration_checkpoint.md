# Vendor_Guard Shell Checkpoint

## Proven

- `saaf-manifest.yaml`, `saaf_entrypoint.py`, and `saaf_run.sh` exist.
- Vendor_Guard can start inside the shell.
- Guest logs are visible in AgentFS.
- Vendor profile extraction can be reached inside the VM path.

## Current blocker

- Specialist agent execution and final output generation still need hardening before the full in-shell run completes cleanly.

## Useful artifact

- `debug_http_probe.py` is kept here as a lightweight exact prompt probe for the profile extraction request.
