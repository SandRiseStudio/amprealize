#!/usr/bin/env bash
# Replace the amprealize-api container in-place with a different --workers value.
# Reads the current container's config via `podman inspect` and recreates it
# with the new cmd. Everything else (image, env, mounts, network, ports) is
# preserved.
#
# Usage: ./set-api-workers.sh <count>
set -euo pipefail

WORKERS=${1:-1}
API_NAME=$(podman ps --filter 'name=amprealize-api' --format '{{.Names}}' | head -1)
if [[ -z "$API_NAME" ]]; then
  echo "No running amprealize-api container found" >&2
  exit 1
fi
echo "Target container: $API_NAME"
echo "Setting --workers $WORKERS"

SPEC_FILE=$(mktemp)
podman inspect "$API_NAME" --format '{{json .}}' > "$SPEC_FILE"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SECRET_FILE="$SCRIPT_DIR/.jwt-secret"

python3 - "$SPEC_FILE" "$WORKERS" "$API_NAME" "$SECRET_FILE" <<'PY'
import json, os, shlex, subprocess, sys
spec_path, workers, name, secret_file = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
with open(spec_path) as f:
    c = json.load(f)
cfg = c["Config"]
hcfg = c["HostConfig"]

image = cfg["Image"]
workdir = cfg.get("WorkingDir") or "/"
env = cfg.get("Env") or []
old_cmd = cfg.get("Cmd") or []

# Rewrite --workers N in the cmd
new_cmd = []
for part in old_cmd:
    if "--workers " in part:
        import re
        part = re.sub(r"--workers\s+\d+", f"--workers {workers}", part)
    new_cmd.append(part)

# Mounts: bind + volume
mount_args = []
for m in c.get("Mounts") or []:
    mtype = m.get("Type")
    src = m.get("Source")
    dst = m.get("Destination")
    ro = ",ro" if m.get("RW") is False else ""
    if mtype == "bind":
        mount_args.extend(["-v", f"{src}:{dst}{ro}"])
    elif mtype == "volume":
        mount_args.extend(["-v", f"{m.get('Name')}:{dst}{ro}"])

port_args = []
for port, bindings in (hcfg.get("PortBindings") or {}).items():
    for b in bindings or []:
        hip = b.get("HostIp") or "0.0.0.0"
        hport = b.get("HostPort")
        port_args.extend(["-p", f"{hip}:{hport}:{port.split('/')[0]}"])

network_args = []
net_mode = hcfg.get("NetworkMode") or "bridge"
networks = (c.get("NetworkSettings") or {}).get("Networks") or {}
if networks:
    seen_aliases = set()
    for net, ninfo in networks.items():
        network_args.extend(["--network", net])
        for alias in (ninfo.get("Aliases") or []):
            # Skip auto-generated aliases (container name, short id)
            if not alias or alias == name or len(alias) == 12:
                continue
            if alias in seen_aliases:
                continue
            seen_aliases.add(alias)
            network_args.extend(["--network-alias", alias])
    # Guarantee the canonical service alias even if inspect didn't list it.
    if "amprealize-api" not in seen_aliases:
        network_args.extend(["--network-alias", "amprealize-api"])
else:
    network_args.extend(["--network", net_mode])

extra_hosts = []
for h in hcfg.get("ExtraHosts") or []:
    extra_hosts.extend(["--add-host", h])

env_args = []
have_jwt_secret = any(e.startswith("AMPREALIZE_JWT_SECRET=") for e in env)
have_perf_log = any(e.startswith("AMPREALIZE_PERF_LOG=") for e in env)
for e in env:
    env_args.extend(["-e", e])

# Inject persistent JWT secret so token recreates don't invalidate the saved
# storageState.json used by the perf harness.
if not have_jwt_secret and os.path.isfile(secret_file):
    with open(secret_file) as f:
        secret_val = f.read().strip()
    if secret_val:
        env_args.extend(["-e", f"AMPREALIZE_JWT_SECRET={secret_val}"])
        print(f"[info] injecting pinned AMPREALIZE_JWT_SECRET from {secret_file}")

# Honour AMPREALIZE_PERF_LOG from the caller's env so the perf harness can
# turn on server-side perf_span output without editing container config.
caller_perf_log = os.environ.get("AMPREALIZE_PERF_LOG")
if not have_perf_log and caller_perf_log:
    env_args.extend(["-e", f"AMPREALIZE_PERF_LOG={caller_perf_log}"])
    print(f"[info] injecting AMPREALIZE_PERF_LOG={caller_perf_log} from caller env")

# Stop + rm the old one
subprocess.run(["podman", "stop", "-t", "5", name], check=False)
subprocess.run(["podman", "rm", "-f", name], check=False)

run_cmd = [
    "podman", "run", "-d",
    "--name", name,
    "--workdir", workdir,
    *env_args,
    *mount_args,
    *port_args,
    *network_args,
    *extra_hosts,
    image,
    *new_cmd,
]
print("Running:", " ".join(shlex.quote(p) for p in run_cmd[:8] + ["…"] + run_cmd[-len(new_cmd):]))
subprocess.run(run_cmd, check=True)
PY

rm -f "$SPEC_FILE"

echo "Waiting for API to become healthy..."
for i in $(seq 1 30); do
  status=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/health 2>/dev/null || echo 000)
  if [[ "$status" == "200" ]]; then
    echo "api healthy (attempt $i, ${status})"
    exit 0
  fi
  sleep 2
done
echo "api did not become healthy" >&2
exit 1
