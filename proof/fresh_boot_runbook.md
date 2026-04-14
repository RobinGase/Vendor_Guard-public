# Fresh-Boot Recovery Runbook

Bring Vendor_Guard back to a working end-to-end state after the Linux host has rebooted. Assumes `/tmp/saaf-shell-live` is gone and all services are cold.

This runbook pairs with the saaf-compliance-shell repo on the developer workstation. The shell repo is the thing that gets shipped to the Linux host; Vendor_Guard is checked out into the shell's VM rootfs via the manifest path.

## Preconditions

- Linux host reachable from the workstation.
- `/opt/saaf/rootfs/…` and `/opt/saaf/kernels/vmlinux` still in place (these survive reboot).
- `/opt/vendor-guard-venv.tar` still in place inside the target rootfs.
- Local model endpoint (Ollama) running and reachable from the Linux host.

## Step 1 — Ship the shell repo

From the developer workstation, package the shell repo and copy it to the Linux host. Exclude `.git`, `.venv`, caches, and compiled artefacts.

```bash
cd /path/to/saaf-compliance-shell
tar --exclude='.git' --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' \
    -czf /tmp/saaf-shell-live.tar.gz .
scp /tmp/saaf-shell-live.tar.gz <user>@<linux-host>:/tmp/saaf-shell-live.tar.gz
```

## Step 2 — Unpack and prepare the venv

On the Linux host:

```bash
mkdir -p /tmp/saaf-shell-live && cd /tmp/saaf-shell-live
tar -xzf /tmp/saaf-shell-live.tar.gz
python3.12 -m venv .venv
.venv/bin/pip install -q nemoguardrails uvicorn httpx fastapi aiohttp openai pyyaml
```

## Step 3 — Start the shell services

Two services, run in the background. Replace `<MODEL_HOST>` with the host running the local model endpoint.

```bash
nohup .venv/bin/python scripts/start-guardrails-local.py \
  > /tmp/guardrails-8088.log 2>&1 &

LOCAL_NIM_URL=http://<MODEL_HOST>:8000/v1/chat/completions \
  nohup .venv/bin/python -m uvicorn modules.router.privacy_router:app \
    --host 127.0.0.1 --port 8089 \
  > /tmp/router-8089.log 2>&1 &
```

Confirm both are alive:

```bash
sleep 6
curl -s http://127.0.0.1:8088/health
curl -s http://127.0.0.1:8089/health
```

## Step 4 — Run the Vendor_Guard pipeline

As root (Firecracker + iptables + NFS server need it):

```bash
cd /tmp/saaf-shell-live && .venv/bin/python -c "
import sys; sys.path.insert(0, '/tmp/saaf-shell-live')
from modules.isolation.runtime import run_manifest
print(run_manifest(
    '/opt/saaf/rootfs/vendor-guard-test/audit_workspace/vendor_guard/saaf-manifest.yaml',
    rootfs_path='/opt/saaf/rootfs/vendor-guard-test',
    overlay_dir='/tmp/vendor-guard-run/.agentfs',
    audit_log_path='/tmp/vendor-guard-run/audit.jsonl',
))
"
```

Expect `session_start → vm_exit(status=ok) → session_end` in ~2 minutes.

## Step 5 — Verify the outputs

The AgentFS overlay DB for the session lives at `/tmp/vendor-guard-run/.agentfs/<session-id>.db`. Query it (as root, since the DB is owned by root):

```bash
sudo .venv/bin/python -c "
import sqlite3
db = sqlite3.connect('/tmp/vendor-guard-run/.agentfs/<session-id>.db')
for name, size in db.execute('''
    SELECT d.name, length(data.blob)
    FROM fs_dentry d
    JOIN fs_data data ON d.inode_id = data.inode_id
    WHERE d.name LIKE '%.xlsx' OR d.name LIKE '%.csv'
       OR d.name LIKE '%.docx' OR d.name LIKE '%.html'
'''):
    print(f'{name}: {size} bytes')
"
```

Expected outputs (sizes vary slightly):

- `scorecard.xlsx` ~5 KB
- `scorecard.csv` ~100 B
- `gap_register.xlsx` ~8 KB
- `gap_register.csv` ~9 KB
- `audit_memo.docx` ~38 KB
- `audit_memo.html` ~17 KB

## Step 6 — Confirm audit chain

```bash
.venv/bin/python -m cli verify-log --log /tmp/vendor-guard-run/audit.jsonl
```

Expect `Chain intact. Verified N events.`

## If something goes wrong

| Symptom | Where to look |
|---|---|
| Guardrails health returns nothing | `/tmp/guardrails-8088.log` |
| Router health returns nothing | `/tmp/router-8089.log` |
| VM exits in under 10 seconds with `vm_exit=ok` | Check `<session>.console.log` — likely a guest crash that still let the process exit cleanly |
| Pipeline log stops at `inference_ready=timeout` | Model endpoint on `<MODEL_HOST>:8000` not reachable from the Linux host |
| Wrapper log stops after `wrapper_runtime_copied` | Venv tar missing or corrupt |
| AgentFS DB has no output files | Entrypoint crashed; check `saaf_entrypoint.stderr` in the overlay |

## Cleanup

After a run, if you need to retry:

```bash
rm -rf /tmp/vendor-guard-run
# TAP / iptables are torn down automatically by the shell on normal exit.
# On a crashed run, see QUICKSTART.md "Cleaning up between sessions" in the shell repo.
```
