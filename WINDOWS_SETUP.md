# Windows Setup — Docker + WSL 2

Getting this project running on Windows from a clean machine. Follow the steps
in order; each one lists the problems we actually hit there and how they were
resolved.

Verified on **Windows 10 Pro 22H2 (build 19045.6466)** with **Docker Desktop
4.88.1**. Windows 11 follows the same path with fewer detours.

**Estimated time:** 30–45 minutes, including two mandatory reboots.

---

## Overview

Docker Desktop on Windows does not run containers on Windows itself — it runs
them inside a Linux VM managed by **WSL 2** (Windows Subsystem for Linux).
Almost every failure below is really a WSL problem wearing a Docker error
message. Get WSL healthy first and Docker follows.

```
Windows
  └── WSL 2 (Hyper-V lightweight VM)
        ├── docker-desktop      ← Docker Desktop creates this; runs the engine
        └── Ubuntu              ← optional, only for the docker CLI inside Linux
```

---

## Step 0 — Confirm virtualization is enabled

Open **Task Manager → Performance → CPU** and look for **Virtualization:
Enabled**.

If it says Disabled, stop here and enable **Intel VT-x** or **AMD-V** in your
BIOS/UEFI. WSL 2 cannot run without it, and nothing further in this guide will
work.

---

## Step 1 — Check what WSL currently sees

Open **PowerShell as Administrator**:

```powershell
wsl --list --verbose
```

> ### ⚠️ Struggle: the command printed the WSL help text instead of a list
>
> **Symptom:** `wsl --list --verbose` dumped the full usage/help output
> (`Usage: wsl.exe [Argument] …`) rather than a table of distros. Docker Desktop
> was separately reporting **"Failed to find installed WSL 2 distros."**
>
> **Cause:** The WSL Windows feature was never enabled. On a machine without it,
> `wsl.exe` is only a stub — it doesn't recognize `--list` at all, so it falls
> back to printing help. This is easy to misread as a bad argument.
>
> **Solution:** Treat a help dump here as *"WSL is not installed"* and continue
> to Step 2. Don't waste time on the command syntax; it's correct.

---

## Step 2 — Enable the two Windows features

Still in **PowerShell as Administrator**:

```powershell
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
```

Both must report success.

> ### ⚠️ Struggle: `VirtualMachinePlatform` is easy to miss
>
> **Cause:** Most older guides only mention `Microsoft-Windows-Subsystem-Linux`.
> That feature alone gives you WSL **1**. WSL 2 needs the virtual machine
> platform as well.
>
> **Solution:** Always run both DISM commands. If Docker later complains about
> WSL 2 specifically while WSL 1 distros work fine, this is the missing piece.

---

## Step 3 — Reboot

A real restart, not `wsl --shutdown`. The features do not take effect until you
reboot, and every subsequent step will misbehave if you skip it.

---

## Step 4 — Install the modern WSL

```powershell
wsl --update
```

You want it to report *"Windows Subsystem for Linux has been installed."* Run it
a second time to confirm you get *"the latest version is already installed."*

Verify you're on the modern build:

```powershell
wsl --version
```

A real version table (`WSL version: 2.x.x.x`, `Kernel version: …`) means you're
set. If this still dumps help text, the update didn't take — install the
`.msixbundle` from <https://github.com/microsoft/WSL/releases> or the
**Windows Subsystem for Linux** app from the Microsoft Store.

> ### ⚠️ Struggle: the standalone kernel MSI is a trap
>
> **Symptom:** Following older documentation, we installed the standalone kernel
> package (`wsl_update_x64.msi`, dated **October 2021**). WSL appeared to work,
> but Docker Desktop crashed later with a proxy error (see Step 7).
>
> **Cause:** That MSI installs the *legacy inbox* WSL. Current Docker Desktop
> expects modern WSL 2.x, and `systemd=true` in a distro's `wsl.conf` requires
> WSL **0.67.6+** — which the 2021 kernel predates.
>
> **Solution:** Skip the MSI entirely; use `wsl --update`, the Store, or the
> GitHub release, all of which bundle their own kernel. **If you already
> installed the MSI**, remove it: **Settings → Apps → Apps & features →
> "Windows Subsystem for Linux Update" → Uninstall**, then reboot.

---

## Step 5 — Set the default version

```powershell
wsl --set-default-version 2
```

New distros — including the one Docker creates — inherit this.

---

## Step 6 — (Optional) Install a Linux distro

```powershell
wsl --install -d Ubuntu
```

> ### ℹ️ Not required for Docker
>
> Docker Desktop provisions its **own** distro (`docker-desktop`) automatically
> on first launch. It does not need Ubuntu or any other user distro.
>
> **Install one anyway if you want:** the `docker` CLI available inside a Linux
> shell, Linux-native filesystem performance (see Step 11), or a clean way to
> test whether WSL itself is healthy independently of Docker.
>
> **Note:** before Docker's first successful start, `wsl -l -v` legitimately
> reports no distributions. That's expected at that point, not a relapse.

> ### ⚠️ Struggle: `E_UNEXPECTED` when launching the distro
>
> **Symptom:** `wsl -d Ubuntu` failed with `E_UNEXPECTED` (often prefixed
> `Wsl/Service/CreateInstance/…`).
>
> **Cause:** The WSL implementation was swapped underneath a running system —
> legacy kernel MSI first, then the Store version via `wsl --update`. The old and
> new components conflict until Windows fully restarts.
>
> **Solution:**
> 1. **Reboot Windows** (not just `wsl --shutdown`). This alone usually fixes it.
> 2. Uninstall the legacy **"Windows Subsystem for Linux Update"** MSI, reboot again.
> 3. Check the service: `Get-Service LxssManager` — restart it if stopped.
> 4. Check for a stale `%USERPROFILE%\.wslconfig` with impossible values
>    (oversized `memory`, bad `kernel` path). Rename it to `.wslconfig.bak` and retry.
> 5. Last resort — rebuild the distro:
>    `wsl --unregister Ubuntu` then `wsl --install -d Ubuntu`.
>    ⚠️ **This deletes everything inside that distro.**

---

## Step 7 — Install and start Docker Desktop

Download from <https://www.docker.com/products/docker-desktop/> and install with
the **"Use WSL 2 instead of Hyper-V"** option ticked. Reboot if prompted, then
launch it and wait — the first start has to build the `docker-desktop` distro
from scratch.

Watch the status bar at the bottom left. **Engine running** with non-zero RAM/CPU
means success.

> ### ⚠️ Struggle: `docker-desktop-user-distro proxy` crash loop
>
> **Symptom:** Startup failed with a Go stack trace ending in:
>
> ```
> dial unix /mnt/wsl/docker-desktop/shared-sockets/host-services/backend.sock:
>   connect: no such file or directory
> ```
>
> preceded by `failed to read component versions: open
> /opt/docker-desktop/componentsVersion.json: no such file or directory`.
>
> **Cause:** Docker's proxy inside **Ubuntu** couldn't reach the backend socket
> that the `docker-desktop` distro publishes into the shared `/mnt/wsl` mount.
> Two contributing factors: the legacy WSL from the kernel MSI (Step 4), and
> `systemd=true` in Ubuntu's `wsl.conf`, which old WSL doesn't support. Both
> break the cross-distro `/mnt/wsl` mounts.
>
> **Solution:**
> 1. Upgrade to modern WSL — `wsl --update` (Step 4). This is the actual fix.
> 2. `wsl --shutdown`, then relaunch Docker. `/mnt/wsl` is shared only *within* a
>    single WSL session, so a torn state persists until everything restarts together.
> 3. If it still fails, disable the Ubuntu integration — see the next struggle.

> ### ⚠️ Struggle: disabling WSL integration didn't disable it
>
> **Symptom:** With the **Ubuntu** toggle switched off under
> **Settings → Resources → WSL integration**, Docker still launched the failing
> Ubuntu proxy and hung on *Engine starting* with `RAM 0.00 GB · CPU 0.00%`.
>
> **Cause:** The separate checkbox **"Enable integration with my default WSL
> distro"** was still ticked — and Ubuntu *was* the default distro (the `*` in
> `wsl -l -v` marks it). That checkbox bypasses the per-distro toggles entirely.
>
> **Solution:** Untick **"Enable integration with my default WSL distro"** *and*
> leave the per-distro toggle off, then **Apply & Restart**. The engine runs in
> Docker's own `docker-desktop` distro; the Ubuntu proxy is only needed to run
> `docker` from inside Ubuntu, so removing it is a safe way to get a working
> engine. Re-enable later once WSL is healthy.

**Recovery of last resort:** **Troubleshoot** (bug icon) → **Reset to factory
defaults** rebuilds Docker's distro from scratch. ⚠️ Wipes all images,
containers, and volumes — cheap on a fresh install, expensive later.

---

## Step 8 — Verify Docker

```powershell
docker version              # client AND server sections both populated
docker context ls           # expect: desktop-linux *
docker info --format "{{.Name}}"   # expect: docker-desktop
wsl -l -v                   # expect docker-desktop, VERSION 2, Running
docker run --rm hello-world
```

Then a test that exercises port forwarding from Windows into the WSL VM — the
part most likely to still be broken:

```powershell
docker run -d -p 8080:80 --name web nginx
curl http://localhost:8080
docker rm -f web
```

> ### ⚠️ Struggle: "no containers show up in Docker Desktop"
>
> **Symptom:** `hello-world` ran successfully and the image appeared under
> Images, but the **Containers** tab stayed empty.
>
> **Cause:** Not a bug — there genuinely were zero containers. `docker ps` only
> lists *running* containers, and `hello-world` prints its message and exits
> immediately. The `--rm` flag then deletes the container on exit, so it doesn't
> even survive as a stopped entry.
>
> **Solution:** Use `docker ps -a` to include exited containers. To see something
> persist, drop `--rm` (`docker run --name hello2 hello-world` → shows as
> `Exited (0)`, which means it ran correctly) or run something long-lived
> (`docker run -d -p 8080:80 --name web nginx`).

> ### ⚠️ Struggle: two Docker daemons at once
>
> **Symptom:** Containers visible from one shell but not in the Docker Desktop
> GUI — or vice versa.
>
> **Cause:** Installing Docker Engine *inside* Ubuntu (a common workaround when
> Docker Desktop won't start) gives you a **second, independent daemon** with its
> own images, containers, and volumes. With WSL integration off, Ubuntu's CLI
> talks to that daemon, not to Docker Desktop's.
>
> **Solution:** Identify which daemon you're on:
>
> ```powershell
> docker context ls                    # the * marks the active context
> docker info --format "{{.Name}}"     # docker-desktop = Docker Desktop's engine
> ```
>
> Then pick **one** and stop the other — inside Ubuntu,
> `sudo systemctl disable --now docker` stops the Ubuntu engine.
> ⚠️ **Never run both daemons simultaneously**; they fight over networking and
> iptables rules.

---

## Step 9 — Fallback: Docker Engine without Docker Desktop

If Docker Desktop cannot be made to start, run Docker Engine natively inside
Ubuntu. It skips Docker Desktop entirely and isn't subject to its licensing
terms. **Quit Docker Desktop first.**

Inside Ubuntu (`wsl -d Ubuntu`):

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin

sudo systemctl enable --now docker    # or: sudo service docker start
sudo usermod -aG docker $USER
```

Run `wsl --shutdown` from PowerShell and reopen Ubuntu — group membership only
refreshes in a new session. Then `docker run --rm hello-world`.

> ### ⚠️ Common failure: `dockerd` won't start
>
> **Cause:** Ubuntu 22.04+ defaults to nftables; Docker expects iptables.
>
> **Solution:**
> ```bash
> sudo update-alternatives --set iptables /usr/sbin/iptables-legacy
> sudo service docker restart
> ```
> For anything else, run `sudo dockerd` directly — it prints the real error
> instead of hiding it behind a service failure.

---

## Step 10 — Size WSL 2 memory before the first build

Docker Desktop gives the WSL 2 VM roughly **half the host's RAM** by default. On
an 8 GB machine that is ~3.8 GB, shared between the API container, Postgres, and
the VM itself. The image pipeline peaks around **2.1 GB in the API container
alone**, so the default is not enough and the container gets OOM-killed mid-build.

Check what you have now:

```powershell
wsl -d docker-desktop -e free -m
```

If `total` is under ~6000, raise it. Create `%USERPROFILE%\.wslconfig` —

**PowerShell:**

```powershell
Set-Content -Path "$env:USERPROFILE\.wslconfig" -Encoding ASCII -Value @("[wsl2]","memory=6GB","swap=8GB")
```

**CMD** (note: no space before `>` or `>>` — `echo` would include it in the value):

```
echo [wsl2]> "%USERPROFILE%\.wslconfig"
echo memory=6GB>> "%USERPROFILE%\.wslconfig"
echo swap=8GB>> "%USERPROFILE%\.wslconfig"
```

Apply and verify:

```powershell
wsl --shutdown          # stops all containers
                        # then restart Docker Desktop and wait for the engine
wsl -d docker-desktop -e free -m     # total should now read ~6000
```

**Do not continue until that number changes.** Everything below depends on it.

On an 8 GB host, `memory=6GB` is the ceiling worth taking — leave Windows 2 GB or
you trade container OOMs for desktop thrashing. Swap larger than RAM is
deliberate: the ML model loads are short allocation spikes, and generous swap
lets the kernel page instead of invoking the OOM killer.

Two settings worth pairing with this, in [docker-compose.yml](docker-compose.yml)
and `.env` respectively:

```yaml
    mem_limit: 4g          # under api: — kills only this container, not the VM
```

```
IMAGE_GEN_CONCURRENCY=1    # in .env — serializes the AI image calls
```

> ### ⚠️ Struggle: an out-of-memory kill that looks like a Postgres failure
>
> **Symptom:** Several of these in the Postgres log, all at once, seconds after
> `image_pipeline_start`:
>
> ```
> LOG:  unexpected EOF on client connection with an open transaction
> ```
>
> **Cause:** Not a database problem. The API container was OOM-killed, and
> Postgres logged one EOF per connection that vanished with it. Six at once is
> the giveaway — a single pipeline run holds *one* session, so six dying together
> means the whole pool went with the process. `restart: unless-stopped` then
> brings the API back quietly, so there is no obvious crash to find.
>
> **Solution:** Confirm before chasing it as a DB issue:
>
> ```powershell
> docker inspect etsy_taki_api --format "{{.RestartCount}} {{.State.OOMKilled}}"
> ```
>
> `OOMKilled true` settles it — raise the WSL 2 ceiling above. A second tell: the
> `GET /health` lines (logged every 10 s by the compose healthcheck) stop
> appearing at the exact moment the image phase begins, because the VM is
> thrashing. `ExitCode` may read `0`, and `RestartCount` resets to `0` after a
> `--build` since that creates a fresh container — trust the `OOMKilled` flag.

> ### ⚠️ Struggle: `.wslconfig` silently ignored
>
> **Symptom:** `free -m` still reports the old total after `wsl --shutdown` and a
> Docker restart.
>
> **Cause:** Almost always the file, not the setting. Notepad appends `.txt` with
> extensions hidden, so you get `.wslconfig.txt`. PowerShell 5.1's
> `-Encoding UTF8` writes a byte-order mark, which can make WSL skip the file. Or
> it landed in a subfolder rather than `C:\Users\<you>\`.
>
> **Solution:** Verify the file itself, not the value:
>
> ```powershell
> Get-Item "$env:USERPROFILE\.wslconfig" | Select-Object FullName, Length
> Get-Content "$env:USERPROFILE\.wslconfig"
> ```
>
> `FullName` must end in `.wslconfig` exactly. Use `-Encoding ASCII`.

> ### ⚠️ Struggle: `Set-Content is not recognized`
>
> **Cause:** You're in **cmd.exe**, not PowerShell — `Set-Content` is a
> PowerShell cmdlet. Easy to miss when a terminal opens to CMD by default.
>
> **Solution:** `echo %COMSPEC%` prints `C:\WINDOWS\system32\cmd.exe` in CMD and
> the literal `%COMSPEC%` in PowerShell. Either use the CMD form above, or type
> `powershell` to switch shells first.

---

## Step 11 — Run this project

```powershell
cd backend
copy .env.example .env      # then fill in your API keys
docker compose up --build
```

The API comes up at <http://localhost:8000>. Postgres starts first and the API
waits on its healthcheck, then runs `alembic upgrade head` before uvicorn.

ML models (`all-MiniLM-L6-v2`, `clip-ViT-B-32`, rembg's `u2net`) download on
first use into named volumes — the first background removal or originality check
is slow, and every one after that is not. `u2net` is preloaded at startup;
`rembg_warmup_complete` in the log means it is resident and later builds will not
reload it.

A healthy full build looks like this — roughly two minutes per SKU, with the
warm-up appearing **once** at boot and never again:

```
[info] rembg_warmup_complete
[info] preprocessing_done    sku=TAKI-0007
[info] image_pipeline_done   sku=TAKI-0007 mode=jewelry_9
```

> ### ⚠️ Struggle: `docker compose` says "no configuration file provided"
>
> **Cause:** You're in the wrong directory. `docker compose` locates services via
> `docker-compose.yml` in the current folder; running it from the extension repo
> or your home directory finds nothing.
>
> **Solution:** `cd` into `backend/`, or address the container by name instead —
> `docker logs etsy_taki_api` and `docker inspect etsy_taki_api` work from
> anywhere. Note that `docker logs | findstr …` only filters **stdout**; uvicorn
> and alembic write to stderr, so use `docker logs etsy_taki_api 2>&1 | findstr …`
> to filter everything.

> ### ⚠️ Struggle: `psql` fails with `role "root" does not exist`
>
> **Symptom:** Inside the Postgres container, bare `psql` fails. Typing `\dt` at
> the container's shell prompt gives `/bin/sh: dt: not found`.
>
> **Cause:** Two things. `psql` with no `-U` uses the OS username — `root` inside
> the container — and no such role exists. Separately, `\dt` and `\l` are *psql*
> commands, not shell commands; they only work once you're at a `psql` prompt.
>
> **Cause of the missing role:** because `POSTGRES_USER: etsy` is set in
> [docker-compose.yml](docker-compose.yml), the image creates **only** that
> superuser. There is no `postgres` role either.
>
> **Solution:** Name the user and database explicitly — easiest from the host:
>
> ```powershell
> docker compose exec postgres psql -U etsy -d etsy_taki
> docker compose exec postgres psql -U etsy -d etsy_taki -c "\dt"
> ```

> ### ⚠️ Struggle: `npm` blocked by PowerShell execution policy
>
> **Symptom:** Building the Chrome extension, `npm` fails with *"File
> `C:\Program Files\nodejs\npm.ps1` cannot be loaded because running scripts is
> disabled on this system."*
>
> **Cause:** PowerShell's default `Restricted` execution policy refuses the
> `npm.ps1` wrapper. npm itself is fine.
>
> **Solution:** Allow local scripts for your user (no admin needed), then reopen
> the terminal:
>
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```
>
> Or sidestep it per-command with `npm.cmd install`, which CMD's wrapper runs
> without policy checks.

> ### ⚠️ Struggle: `--reload` silently never fires
>
> **Symptom:** Editing files under `./src` doesn't restart uvicorn. No error, no
> log line — edits simply don't apply.
>
> **Cause:** inotify filesystem events don't cross the Windows→WSL2 boundary. If
> the repo lives on `C:\`, the container never learns a file changed. Bind-mount
> I/O is also much slower there.
>
> **Solution:** **Put the repo inside the WSL2 filesystem** —
> `\\wsl$\Ubuntu\home\you\…`, not `C:\`. If you must work from `C:\`, uncomment
> `WATCHFILES_FORCE_POLLING: "true"` in [docker-compose.yml](docker-compose.yml)
> (line 42); it costs some idle CPU but makes reload work.

> ### ⚠️ Struggle: things that don't arrive via `git clone`
>
> Three items must be copied by hand when moving to a Windows machine:
>
> | Item | How to move it |
> |---|---|
> | `.env` | Copy manually — not tracked |
> | `data/images/` | Copy manually — not tracked |
> | Postgres contents | `pg_dump -U etsy etsy_taki` on source → `psql -U etsy -d etsy_taki` on target |
>
> `data/etsy_encryption.key` **is** tracked, so it travels and there's no Fernet
> key mismatch. You will still need to redo the Etsy OAuth flow, since the token
> file isn't tracked.
>
> Also: **rebuild rather than copying an image across machines** —
> `docker compose up --build` pulls the right architecture.

> ### ⚠️ Struggle: the machine was set up from a ZIP, so there's no `git`
>
> **Symptom:** `git` isn't recognized, and the project folder has no `.git` — so
> there's no way to pull a fix made on another machine.
>
> **Solution:** Install git (`winget install --id Git.Git -e --source winget`),
> then **reopen the terminal** — the installer updates PATH but existing shells
> don't see it. To refresh the current session instead:
>
> ```powershell
> $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
> ```
>
> To adopt an existing ZIP-derived folder into the repo **without overwriting
> anything** — note `data/etsy_encryption.key` is tracked, so back it up first:
>
> ```powershell
> copy data\etsy_encryption.key data\etsy_encryption.key.bak
> git init
> git config core.autocrlf false
> git remote add origin https://github.com/sfkse/etsy-automation-backend.git
> git fetch origin
> git reset --mixed origin/main        # points HEAD at the branch, touches no files
> git status --short                   # now shows how the ZIP differs
> ```
>
> `--mixed` leaves every file on disk exactly as it is; check out only the
> specific files you want. `core.autocrlf false` matters because the container
> runs Linux — CRLF line endings break the shell in the compose `command:`.

---

## Quick reference

| Symptom | Likely cause | Fix |
|---|---|---|
| `wsl --list` prints help text | WSL feature not enabled | DISM both features (Step 2), reboot |
| "Failed to find installed WSL 2 distros" | No WSL at all | Steps 2–5 |
| `E_UNEXPECTED` from `wsl -d <distro>` | Legacy/Store WSL conflict | Reboot; uninstall the kernel MSI |
| Proxy crash, `backend.sock` missing | Legacy WSL + `systemd=true` | `wsl --update`, then `wsl --shutdown` |
| Stuck on "Engine starting", 0.00 RAM | Default-distro integration checkbox | Untick it, Apply & Restart |
| No containers in the GUI | `--rm`, or container already exited | `docker ps -a` |
| Containers visible in CLI but not GUI | Two daemons running | `docker context ls`, disable one |
| `--reload` doesn't fire | Repo on `C:\`, not in WSL2 | Move repo to `\\wsl$\`, or force polling |
| Postgres `unexpected EOF … open transaction` | API container OOM-killed | Raise WSL 2 memory (Step 10) |
| `GET /health` stops logging mid-build | Container starved or event loop blocked | Check `OOMKilled` (Step 10) |
| `free -m` unchanged after editing `.wslconfig` | `.wslconfig.txt`, BOM, or wrong folder | Check `Get-Item … FullName` |
| `Set-Content is not recognized` | You're in cmd.exe, not PowerShell | `echo %COMSPEC%`; use the CMD form |
| `no configuration file provided` | Wrong directory for `docker compose` | `cd backend`, or use `docker logs <name>` |
| `psql`: `role "root" does not exist` | No `-U`; only the `etsy` role exists | `psql -U etsy -d etsy_taki` |
| `npm.ps1 cannot be loaded` | PowerShell execution policy | `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` |

## Useful commands

```powershell
wsl --version           # modern WSL confirmation
wsl --status            # default distro and version
wsl -l -v               # all distros, state, WSL version
wsl --shutdown          # stop all distros; fixes most stuck states
wsl --update            # upgrade WSL itself
docker context ls       # which daemon the CLI targets

wsl -d docker-desktop -e free -m     # RAM/swap the VM actually has
docker stats etsy_taki_api           # live memory; watch during a build
docker inspect etsy_taki_api --format "{{.RestartCount}} {{.State.OOMKilled}}"
```

Peak memory since the container started (`docker stats` only shows the instant
value). Counts page cache, so it reads a little above the live figure:

```powershell
docker exec etsy_taki_api python -c "import os; f='/sys/fs/cgroup/memory.peak'; g='/sys/fs/cgroup/memory/memory.max_usage_in_bytes'; p=f if os.path.exists(f) else g; print(round(int(open(p).read())/1048576), 'MiB peak')"
```

---

## Related docs

- [README.md](README.md) — project quick start and stack
- [docker-compose.yml](docker-compose.yml) — service definitions and the Windows polling flag
- [docs/00-overview.md](docs/00-overview.md) — implementation specs
