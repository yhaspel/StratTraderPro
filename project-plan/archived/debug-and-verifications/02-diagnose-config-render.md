# 02 — Diagnose why the Dockerfile IBC patch isn't appearing in the live config

**Goal.** Determine the precise reason `./scripts/verify_ibgw_config.sh` reports the live `/home/ibgateway/ibc/config.ini` is missing `AcceptIncomingConnectionAction=accept`, `AllowBlindTrading=yes`, `OverrideTwsApiPort=4002` — despite the `docker/ib-gateway/Dockerfile` containing a `RUN` step that appends those lines to `/home/ibgateway/ibc/config.ini.tmpl`.

The cause is one of:

- **Cause A — Build skip.** The `RUN` step never executed (cache hit despite `--no-cache`, or wrong image was started).
- **Cause B — Permission deny.** The `RUN` step executed but couldn't write to the .tmpl (file owned by root, USER ibgateway can't append).
- **Cause C — Render strips additions.** The patch is in the .tmpl but gnzsnz's render mechanism filters out unrecognized lines when copying to live config.
- **Cause D — Wrong template path.** Gnzsnz uses a *different* template than the one at `/home/ibgateway/ibc/config.ini.tmpl`.

This file resolves which cause is real.

## Steps

```bash
# 1. Is our patch in the template inside the running container?
docker compose exec ib-gateway tail -15 /home/ibgateway/ibc/config.ini.tmpl

# 2. Last lines of live config (compare against template)
docker compose exec ib-gateway tail -15 /home/ibgateway/ibc/config.ini

# 3. Identify the gnzsnz entrypoint chain
docker compose exec ib-gateway sh -c '
  echo "=== PID 1 ==="; ps -o pid,user,args -p 1 2>/dev/null
  echo "=== children of PID 1 ==="; ps -ef 2>/dev/null | awk "\$3==1"
'

# 4. Find the render script(s) — focused search, no /proc, no recursion past 3 levels
docker compose exec --user root ib-gateway sh -c '
  for dir in /root /usr/local/bin /opt /home/ibgateway/scripts /home/ibgateway/ibc/scripts /entrypoint.sh /run.sh; do
    if [ -e "$dir" ]; then
      echo "=== $dir ==="
      if [ -d "$dir" ]; then
        find "$dir" -maxdepth 3 -type f \( -name "*.sh" -o -name "*.py" \) 2>/dev/null
      else
        echo "(file)"
      fi
    fi
  done
  echo "=== grep render hits in known dirs only ==="
  grep -lE "config\.ini\.tmpl|envsubst|>\s*config\.ini" /root/*.sh /root/scripts/*.sh /usr/local/bin/*.sh /home/ibgateway/scripts/*.sh /home/ibgateway/ibc/scripts/*.sh /entrypoint.sh /run.sh 2>/dev/null
'

# 5. Permissions on the template
docker compose exec ib-gateway ls -la /home/ibgateway/ibc/config.ini.tmpl /home/ibgateway/ibc/config.ini

# 6. Image digest sanity-check — confirm we actually rebuilt
docker compose images ib-gateway
docker inspect $(docker compose ps -q ib-gateway) --format '{{.Image}} {{.Config.Image}}'
```

## Decision tree

Based on step 1's output:

### Step 1 ENDS with the `StratTraderPro override` block

The template has our patch. **Cause is C or D.**

- If step 4 reveals a render script that explicitly writes specific lines (e.g., `envsubst` with a fixed allowlist, or `sed -e '/^TWS_USERID/...'` style explicit copies), it's Cause C.
- If step 4 reveals a render script that mentions a different template path (e.g., `/root/ibc/config.ini.template`), it's Cause D.
- **Action:** read that script, identify what it does, decide between two fixes — patch the render script itself (intrusive), or switch to a startup-shim that appends after render (less intrusive).
- Document which one you chose and why in memory.
- Proceed to `03-apply-config-fix.md` with the diagnosis.

### Step 1 DOES NOT end with our override block

The template was not patched. **Cause is A or B.**

- Check step 5: if `config.ini.tmpl` is owned by `root:root` and not world-writable, and the Dockerfile's RUN runs `USER root` then `USER ibgateway`, the RUN should still have worked (it runs as root at that point in the build). So Cause B is unlikely.
- More likely Cause A: rebuild didn't actually use the patched Dockerfile. Check the build output by re-running:
  ```bash
  docker compose --profile ibkr-spike build --no-cache --progress=plain ib-gateway 2>&1 | tee /tmp/build.log
  grep -E "patched IBC template|already patched" /tmp/build.log
  ```
- If the build log shows neither "patched" nor "already patched", the RUN statement isn't executing — check `docker/ib-gateway/Dockerfile` for syntax issues (e.g., a stray `USER ibgateway` *before* the RUN that's preventing root write).
- If the build log shows "patched" but the running container's .tmpl still doesn't have it, the running container is using a stale image — explicitly recreate:
  ```bash
  docker compose --profile ibkr-spike down
  docker image prune -f  # only if you're sure no other StratTraderPro image is being pruned
  docker compose --profile ibkr-spike up -d ib-gateway --force-recreate
  ```
- Document the root cause in memory before proceeding.

## Verify

You have a definitive answer to: "Why isn't the live config.ini receiving our patch?" If you can write a one-sentence root cause that names the specific script/file/permission/cache issue, you're done with this file.

If you cannot, do NOT proceed — gather more data (e.g., `cat` the suspect render script and read it in full, run the build with `--progress=plain` and read every line of the RUN section's output).

## FALLBACK

If steps 1–6 all return clean but no answer crystallizes:

- Inspect the gnzsnz upstream Dockerfile and entrypoint at <https://github.com/gnzsnz/ib-gateway-docker> for tag `10.45.1e`. Read the entrypoint logic to confirm whether it copies `.tmpl` → `.ini` whole-file or line-by-line.
- If that confirms whole-file copy, our template patch *should* have worked — repeat step 6 to ensure the running container is actually using the rebuilt image (check the image digest vs the freshly built one).

Note any insight in memory.

## NEXT

Read `03-apply-config-fix.md` carrying the named cause (A / B / C / D) forward.
