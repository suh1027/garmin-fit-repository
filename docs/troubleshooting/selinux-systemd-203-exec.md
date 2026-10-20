# SELinux troubleshooting — systemd 203/EXEC (Rocky Linux 9)

> Incident: 2026-10-20. Service: `garmin-fit-sync.service`. Entrypoint: `/garmin/garmin-fit-pipeline/scripts/run_sync.sh`.

## Symptom / 증상

```text
garmin-fit-sync.service: Failed at step EXEC
Failed to locate executable /garmin/garmin-fit-pipeline/scripts/run_sync.sh: Permission denied
status=203/EXEC
```

The timer triggered correctly; the script was **not executed**, so Garmin download, Git commit and Git push never started.

## Confirmed root cause / 확인된 원인

```text
avc: denied { execute } ...
scontext=system_u:system_r:init_t:s0
tcontext=unconfined_u:object_r:user_home_t:s0
tclass=file permissive=0
```

- SELinux `Enforcing` was enabled, and the entrypoint had type `user_home_t`.
- Ordinary Unix file permissions were `-rwxr-xr-x`; `sudo -u garmin test -x ...` returned `0`.
- XFS was mounted without `noexec`.
- `systemd` runs the **system service manager as root**, while the existing service runs the collector as **`User=garmin`**. That design is correct and should be retained.

**Do not** solve this by changing the collector to root, disabling SELinux, or running `chmod -R 777`.

## Diagnostics / 진단

```bash
sudo systemctl status garmin-fit-sync.service --no-pager -l
sudo journalctl -u garmin-fit-sync.service -n 100 --no-pager
getenforce
namei -l /garmin/garmin-fit-pipeline/scripts/run_sync.sh
ls -lZ /garmin/garmin-fit-pipeline/scripts/run_sync.sh
findmnt -T /garmin/garmin-fit-pipeline/scripts/run_sync.sh -o TARGET,FSTYPE,OPTIONS
sudo ausearch -m AVC,USER_AVC -ts recent
```

`203/EXEC` can also occur with invalid shebangs, missing executables, DAC permissions or `noexec`; here the AVC audit entry identifies SELinux execute denial.

## Targeted permanent fix / 영구 수정

```bash
sudo dnf install -y policycoreutils-python-utils

sudo semanage fcontext -a -t bin_t \
  '/garmin/garmin-fit-pipeline/scripts/run_sync\.sh'

sudo restorecon -v /garmin/garmin-fit-pipeline/scripts/run_sync.sh
ls -lZ /garmin/garmin-fit-pipeline/scripts/run_sync.sh
matchpathcon -V /garmin/garmin-fit-pipeline/scripts/run_sync.sh
```

If the identical local rule already exists, inspect `sudo semanage fcontext -l -C` and use `semanage fcontext -m` for that rule rather than adding a duplicate. **Do not** apply `bin_t` to the whole `/garmin` tree, Garmin credentials or health data.

## Prevent recurrence / 재발 방지

The committed `systemd/garmin-fit-sync.service` now includes this pre-start step:

```ini
[Service]
Type=oneshot
User=garmin
WorkingDirectory=/garmin/garmin-fit-pipeline
Environment=HOME=/home/garmin
ExecStartPre=+/usr/sbin/restorecon -v /garmin/garmin-fit-pipeline/scripts/run_sync.sh
ExecStart=/garmin/garmin-fit-pipeline/scripts/run_sync.sh --days 30
```

The `+` prefix permits **only the pre-start restorecon** to run with elevated credentials; the Garmin collector still runs as `garmin`. The persistent file-context rule is required. This protects against Git checkout or replacement of the entrypoint changing the actual SELinux label.

The GitHub unit file is *not* automatically installed under `/etc/systemd/system/`. Deploy the actual service file and verify drop-ins:

```bash
sudo cp /garmin/garmin-fit-pipeline/systemd/garmin-fit-sync.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/garmin-fit-sync.service
sudo systemctl cat garmin-fit-sync.service
sudo systemctl reset-failed garmin-fit-sync.service
sudo systemctl start garmin-fit-sync.service
sudo systemctl status garmin-fit-sync.service --no-pager -l
sudo journalctl -u garmin-fit-sync.service -n 150 --no-pager -o cat
```

`Type=oneshot` commonly finishes as `inactive (dead)` with `Result=success`; this is not a failure. Check the collector-specific `[OK]`, `[WARN]` and final Git Push result before declaring the *data* sync successful. New AVC denials after startup must be diagnosed independently.

## Separate issue: Git dubious ownership

Running Git as root in a working tree owned by `garmin` may show `fatal: detected dubious ownership`. Do not change the repository owner or blindly add `safe.directory` for root; run Git as the correct service account:

```bash
sudo -u garmin git -C /garmin/garmin-fit-pipeline status -sb
```

## References

- [Red Hat SELinux file contexts](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/using_selinux/assembly_managing-file-contexts_using-selinux)
- [systemd.service](https://www.freedesktop.org/software/systemd/man/systemd.service.html)
