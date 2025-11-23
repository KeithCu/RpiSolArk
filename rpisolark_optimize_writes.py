#!/usr/bin/env python3
"""
rpisolark_optimize_writes.py

Purpose:
  Apply the README.md "MicroSD wear reduction (moderate)" recommendations
  to a Raspberry Pi running RpiSolarkMonitor, in a SAFE, IDEMPOTENT,
  and REVERSIBLE way.

Summary of what this script does (from README.md section 473+):
  1) Put systemd journal in RAM (Storage=volatile), optionally disable rsyslog.
  2) Disable APT periodic background jobs and their systemd timers.
  3) Ensure root/boot filesystems use noatime (and optionally commit=600).
  4) Use tmpfs for /tmp.
  5) Optionally disable fake-hwclock.timer if NTP is available and ensure
     systemd-timesyncd is enabled.

Design:
  - Idempotent: Running multiple times will not duplicate changes.
  - Cautious edits: Makes backups before changing system files.
  - Explicit output: Shows each action and its verification.
  - Reversible: Provides a --revert mode that attempts to undo changes
    made by this script (to the extent safely possible).

Usage:
  sudo python3 rpisolark_optimize_writes.py apply
  sudo python3 rpisolark_optimize_writes.py revert
  python3 rpisolark_optimize_writes.py status

Notes:
  - Must be run as root (sudo) because it edits system configuration.
  - Target systems: Raspberry Pi OS / Debian-like distros using systemd.
  - Review generated backups under:
      /etc/systemd/journald.conf.rpisolark.bak
      /etc/fstab.rpisolark.bak
      /etc/apt/apt.conf.d/02periodic-disable.rpisolark.bak (if present)

Warning:
  This script is tuned to the recommendations in this repo's README.
  If your system is significantly customized, review each step before use.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple


SCRIPT_NAME = Path(__file__).name
TEMP_FILES: List[Path] = []


def log(message: str) -> None:
    """Print a log message with script name prefix."""
    print(f"[{SCRIPT_NAME}] {message}")


def die(message: str) -> None:
    """Print an error message and exit with failure."""
    print(f"[{SCRIPT_NAME}][ERROR] {message}", file=sys.stderr)
    sys.exit(1)


def require_root() -> None:
    """Ensure script is running as root."""
    if os.geteuid() != 0:
        die(
            f"This script must be run as root. Re-run with: "
            f"sudo python3 {SCRIPT_NAME} apply|revert|status"
        )


def have_cmd(cmd: str) -> bool:
    """Check if a command is available in PATH."""
    return shutil.which(cmd) is not None


def backup_file_once(filepath: Path) -> None:
    """Create a backup of a file if it exists and backup doesn't exist."""
    backup = Path(f"{filepath}.rpisolark.bak")
    if filepath.exists() and not backup.exists():
        shutil.copy2(filepath, backup)
        log(f"Backup created: {backup}")


def restore_backup_if_exists(filepath: Path) -> None:
    """Restore a file from backup if backup exists."""
    backup = Path(f"{filepath}.rpisolark.bak")
    if backup.exists():
        shutil.copy2(backup, filepath)
        log(f"Restored from backup: {backup} -> {filepath}")
    else:
        log(f"No backup to restore for: {filepath}")


def validate_fstab(fstab_path: Path) -> bool:
    """Validate fstab syntax by checking structure."""
    if not fstab_path.exists():
        return False

    valid_lines = 0
    total_lines = 0

    try:
        with open(fstab_path, "r", encoding="utf-8") as f:
            for line in f:
                total_lines += 1
                stripped = line.strip()

                # Skip comments and empty lines
                if stripped.startswith("#") or not stripped:
                    continue

                # Basic structure check: fstab entries should have at least 4 fields
                fields = re.split(r"\s+", stripped)
                if len(fields) >= 4:
                    valid_lines += 1
                else:
                    # Malformed line found
                    return False
    except (OSError, IOError) as e:
        log(f"Error reading fstab: {e}")
        return False

    # If we have at least some valid-looking lines, consider it OK
    # (allows for fstab files that are mostly comments)
    return valid_lines > 0 or total_lines == 0


def run_systemctl(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run systemctl command and return result."""
    cmd = ["systemctl"] + list(args)
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
        )
    except subprocess.CalledProcessError as e:
        if check:
            raise
        return e


def systemctl_list_unit_files() -> List[str]:
    """Get list of systemd unit files."""
    if not have_cmd("systemctl"):
        return []
    result = run_systemctl("list-unit-files", "--no-pager")
    if result.returncode == 0:
        return result.stdout.splitlines()
    return []


def systemctl_unit_exists(unit: str) -> bool:
    """Check if a systemd unit exists."""
    units = systemctl_list_unit_files()
    return any(line.startswith(unit) for line in units)


def systemctl_is_enabled(unit: str) -> str:
    """Get enabled status of a systemd unit."""
    if not have_cmd("systemctl"):
        return "unknown"
    result = run_systemctl("is-enabled", unit)
    if result.returncode == 0:
        return result.stdout.strip()
    return "unknown"


# ------------------------------------------------------------------------------
# 1) systemd-journald: set Storage=volatile, optionally disable rsyslog
# ------------------------------------------------------------------------------


def apply_journald_volatile() -> None:
    """Configure systemd-journald to use volatile storage."""
    conf = Path("/etc/systemd/journald.conf")

    if not conf.exists():
        log(f"Skip: {conf} not found")
        return

    backup_file_once(conf)

    # Read current content
    try:
        content = conf.read_text(encoding="utf-8")
    except (OSError, IOError) as e:
        die(f"Failed to read {conf}: {e}")

    # Remove existing Storage= lines (commented or uncommented)
    pattern = re.compile(r"^[#\s]*Storage=.*$", re.MULTILINE)
    if pattern.search(content):
        content = pattern.sub("Storage=volatile", content)
    else:
        content += "\nStorage=volatile\n"

    # Write back
    try:
        conf.write_text(content, encoding="utf-8")
    except (OSError, IOError) as e:
        die(f"Failed to write {conf}: {e}")

    log("Configured systemd-journald Storage=volatile")

    # Restart journald to apply
    if have_cmd("systemctl"):
        result = run_systemctl("restart", "systemd-journald", check=True)
        if result.returncode != 0:
            die("Failed to restart systemd-journald")

    # Optional: disable rsyslog if installed
    if have_cmd("systemctl") and systemctl_unit_exists("rsyslog.service"):
        run_systemctl("disable", "--now", "rsyslog")
        log("Disabled rsyslog.service to reduce disk writes (if it was enabled)")


def revert_journald_volatile() -> None:
    """Revert journald volatile configuration."""
    conf = Path("/etc/systemd/journald.conf")
    restore_backup_if_exists(conf)

    if have_cmd("systemctl"):
        run_systemctl("restart", "systemd-journald")

    log("If rsyslog was disabled and you want it back, run: systemctl enable --now rsyslog")


def status_journald_volatile() -> None:
    """Show status of journald and rsyslog."""
    if not have_cmd("systemctl"):
        log("systemctl not available; cannot query journald status")
        return

    result = run_systemctl("show", "-p", "Storage", "systemd-journald")
    storage = result.stdout.strip() if result.returncode == 0 else "Storage=unknown"
    log(f"systemd-journald: {storage}")

    if systemctl_unit_exists("rsyslog.service"):
        rsyslog_state = systemctl_is_enabled("rsyslog")
        log(f"rsyslog.service: {rsyslog_state}")


# ------------------------------------------------------------------------------
# 2) Disable APT periodic background jobs
# ------------------------------------------------------------------------------

APT_PERIODIC_FILE = Path("/etc/apt/apt.conf.d/02periodic-disable")


def apply_apt_periodic_disable() -> None:
    """Disable APT periodic background jobs."""
    # Backup existing file if it exists
    if APT_PERIODIC_FILE.exists():
        backup_file_once(APT_PERIODIC_FILE)

    # Write APT periodic disable configuration
    content = """APT::Periodic::Enable "0";
APT::Periodic::Update-Package-Lists "0";
APT::Periodic::Download-Upgradeable-Packages "0";
APT::Periodic::AutocleanInterval "0";
"""

    try:
        APT_PERIODIC_FILE.parent.mkdir(parents=True, exist_ok=True)
        APT_PERIODIC_FILE.write_text(content, encoding="utf-8")
    except (OSError, IOError) as e:
        die(f"Failed to write {APT_PERIODIC_FILE}: {e}")

    log(f"Configured APT periodic tasks disabled in {APT_PERIODIC_FILE}")

    if have_cmd("systemctl"):
        run_systemctl("disable", "--now", "apt-daily.timer", "apt-daily-upgrade.timer")
        log("Disabled apt-daily.timer and apt-daily-upgrade.timer")


def revert_apt_periodic_disable() -> None:
    """Revert APT periodic disable configuration."""
    if APT_PERIODIC_FILE.exists():
        APT_PERIODIC_FILE.unlink()
        log(f"Removed {APT_PERIODIC_FILE}")

    restore_backup_if_exists(APT_PERIODIC_FILE)

    if have_cmd("systemctl"):
        log("If you want APT periodic timers back, run:")
        log("  systemctl enable --now apt-daily.timer")
        log("  systemctl enable --now apt-daily-upgrade.timer")


def status_apt_periodic_disable() -> None:
    """Show status of APT periodic configuration."""
    if APT_PERIODIC_FILE.exists():
        log(f"APT periodic override present: {APT_PERIODIC_FILE}")
        try:
            content = APT_PERIODIC_FILE.read_text(encoding="utf-8")
            for line in content.splitlines():
                if line.strip():
                    log(line)
        except (OSError, IOError):
            pass
    else:
        log("APT periodic override file not present.")

    if have_cmd("systemctl"):
        t1 = systemctl_is_enabled("apt-daily.timer")
        t2 = systemctl_is_enabled("apt-daily-upgrade.timer")
        log(f"apt-daily.timer: {t1}")
        log(f"apt-daily-upgrade.timer: {t2}")


# ------------------------------------------------------------------------------
# 3) noatime (and optional commit=600) in /etc/fstab
# ------------------------------------------------------------------------------


def parse_fstab_line(line: str) -> Optional[Tuple[str, str, str, str, str, str]]:
    """Parse a single fstab line into fields."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    fields = re.split(r"\s+", stripped)
    if len(fields) < 3:
        return None

    # Return: fs_spec, fs_file, fs_vfstype, fs_mntops, fs_freq, fs_passno
    return (
        fields[0] if len(fields) > 0 else "",
        fields[1] if len(fields) > 1 else "",
        fields[2] if len(fields) > 2 else "",
        fields[3] if len(fields) > 3 else "",
        fields[4] if len(fields) > 4 else "0",
        fields[5] if len(fields) > 5 else "0",
    )


def apply_noatime_fstab() -> None:
    """Add noatime option to root and boot filesystems in fstab."""
    fstab = Path("/etc/fstab")
    if not fstab.exists():
        log(f"Skip: {fstab} not found")
        return

    backup_file_once(fstab)

    # Read current fstab
    try:
        lines = fstab.read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, IOError) as e:
        die(f"Failed to read {fstab}: {e}")

    # Create temp file
    tmp_fd, tmp_path = tempfile.mkstemp(prefix="rpisolark_fstab_", suffix=".tmp")
    TEMP_FILES.append(Path(tmp_path))

    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_file:
            for line in lines:
                # Preserve comments and empty lines exactly as-is
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    tmp_file.write(line)
                    continue

                parsed = parse_fstab_line(line)
                if not parsed:
                    # Malformed line, preserve as-is
                    tmp_file.write(line)
                    continue

                fs_spec, fs_file, fs_vfstype, fs_mntops, fs_freq, fs_passno = parsed

                # Check if this is a root or boot mount point
                if fs_file in ("/", "/boot", "/boot/firmware"):
                    if "noatime" not in fs_mntops:
                        if fs_mntops:
                            fs_mntops = f"{fs_mntops},noatime"
                        else:
                            fs_mntops = "defaults,noatime"
                        log(f"Added noatime for {fs_file} in fstab")

                    # Reconstruct line with proper spacing
                    new_line = f"{fs_spec} {fs_file} {fs_vfstype} {fs_mntops} {fs_freq} {fs_passno}\n"
                    tmp_file.write(new_line)
                else:
                    # Preserve original line formatting for other entries
                    tmp_file.write(line)

        # Validate the new fstab before replacing the original
        tmp_path_obj = Path(tmp_path)
        if not validate_fstab(tmp_path_obj):
            log("ERROR: Generated fstab failed validation. Restoring backup and aborting.")
            restore_backup_if_exists(fstab)
            tmp_path_obj.unlink()
            TEMP_FILES.remove(tmp_path_obj)
            die("fstab validation failed; changes not applied")

        # Replace original with validated temp file
        shutil.move(tmp_path, fstab)
        TEMP_FILES.remove(Path(tmp_path))

    except Exception as e:
        # Cleanup on error
        if Path(tmp_path).exists():
            Path(tmp_path).unlink()
        if Path(tmp_path) in TEMP_FILES:
            TEMP_FILES.remove(Path(tmp_path))
        raise

    log("Updated fstab with noatime for / and /boot (if applicable).")
    log("To also apply commit=600 (less frequent journal flush, higher risk), edit /etc/fstab manually.")


def revert_noatime_fstab() -> None:
    """Revert noatime fstab changes."""
    fstab = Path("/etc/fstab")
    restore_backup_if_exists(fstab)
    log("If you added noatime manually beyond our changes, adjust /etc/fstab to your needs.")


def status_noatime_fstab() -> None:
    """Show status of noatime mount options."""
    if not have_cmd("findmnt"):
        log("findmnt not available; cannot verify runtime mount options")
        return

    try:
        result = subprocess.run(
            ["findmnt", "-no", "OPTIONS", "/"],
            capture_output=True,
            text=True,
            check=False,
        )
        root_opts = result.stdout.strip() if result.returncode == 0 else "unknown"
        log(f"Root mount options: {root_opts}")

        result = subprocess.run(
            ["findmnt", "-no", "OPTIONS", "/boot"],
            capture_output=True,
            text=True,
            check=False,
        )
        boot_opts = result.stdout.strip() if result.returncode == 0 else "unknown"
        log(f"/boot mount options: {boot_opts}")

        if "noatime" in root_opts:
            log("Root filesystem has noatime: OK")
        else:
            log("Root filesystem missing noatime")
    except Exception:
        log("Error querying mount options")


# ------------------------------------------------------------------------------
# 4) Use tmpfs for /tmp
# ------------------------------------------------------------------------------


def apply_tmpfs_tmp() -> None:
    """Configure /tmp as tmpfs in fstab."""
    fstab = Path("/etc/fstab")
    if not fstab.exists():
        log(f"Skip: {fstab} not found")
        return

    backup_file_once(fstab)

    # Check for existing /tmp tmpfs entries more robustly
    has_tmpfs_tmp = False
    try:
        content = fstab.read_text(encoding="utf-8")
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            parsed = parse_fstab_line(line)
            if parsed:
                _, fs_file, fs_vfstype, _, _, _ = parsed
                if fs_file == "/tmp" and fs_vfstype == "tmpfs":
                    has_tmpfs_tmp = True
                    break
    except (OSError, IOError) as e:
        die(f"Failed to read {fstab}: {e}")

    if has_tmpfs_tmp:
        log("/tmp is already configured as tmpfs in fstab")
    else:
        try:
            with open(fstab, "a", encoding="utf-8") as f:
                f.write("tmpfs /tmp tmpfs defaults,nosuid,nodev 0 0\n")
        except (OSError, IOError) as e:
            die(f"Failed to write {fstab}: {e}")

        log("Added tmpfs /tmp entry to fstab")

        # Validate fstab after adding entry
        if not validate_fstab(fstab):
            log("ERROR: fstab validation failed after adding /tmp entry. Restoring backup.")
            restore_backup_if_exists(fstab)
            die("fstab validation failed; /tmp tmpfs entry not added")

    if have_cmd("mount"):
        result = subprocess.run(
            ["mount", "-a"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            die("mount -a failed after /tmp tmpfs change; check /etc/fstab")


def revert_tmpfs_tmp() -> None:
    """Revert tmpfs /tmp configuration."""
    fstab = Path("/etc/fstab")
    restore_backup_if_exists(fstab)
    log("If additional /tmp lines remain, manually clean up fstab.")


def status_tmpfs_tmp() -> None:
    """Show status of /tmp filesystem."""
    if not have_cmd("findmnt"):
        log("findmnt not available; cannot verify /tmp mount type")
        return

    try:
        result = subprocess.run(
            ["findmnt", "-no", "FSTYPE", "/tmp"],
            capture_output=True,
            text=True,
            check=False,
        )
        tmp_type = result.stdout.strip() if result.returncode == 0 else "unknown"
        log(f"/tmp filesystem type: {tmp_type}")
    except Exception:
        log("Error querying /tmp filesystem type")


# ------------------------------------------------------------------------------
# 5) Optional: fake-hwclock vs NTP (systemd-timesyncd)
# ------------------------------------------------------------------------------


def apply_fake_hwclock_ntp() -> None:
    """Configure NTP (systemd-timesyncd) and disable fake-hwclock."""
    if not have_cmd("systemctl"):
        log("systemctl not available; skipping fake-hwclock/systemd-timesyncd adjustments")
        return

    if systemctl_unit_exists("systemd-timesyncd.service"):
        # Disable fake-hwclock.timer (if present)
        if systemctl_unit_exists("fake-hwclock.timer"):
            run_systemctl("disable", "--now", "fake-hwclock.timer")
            log("Disabled fake-hwclock.timer (NTP via systemd-timesyncd expected)")

        if systemctl_unit_exists("fake-hwclock.service"):
            run_systemctl("disable", "--now", "fake-hwclock.service")
            log("Disabled fake-hwclock.service")

        # Enable timesyncd
        run_systemctl("enable", "--now", "systemd-timesyncd")
        log("Enabled systemd-timesyncd for NTP time sync")
    else:
        log("systemd-timesyncd not present; leaving fake-hwclock as-is")


def revert_fake_hwclock_ntp() -> None:
    """Revert fake-hwclock/NTP configuration."""
    if not have_cmd("systemctl"):
        log("systemctl not available; skipping revert of fake-hwclock/systemd-timesyncd")
        return

    log("To re-enable fake-hwclock (if desired), run:")
    log("  systemctl enable --now fake-hwclock.service fake-hwclock.timer")
    log("To disable timesyncd, run:")
    log("  systemctl disable --now systemd-timesyncd")


def status_fake_hwclock_ntp() -> None:
    """Show status of fake-hwclock and NTP configuration."""
    if not have_cmd("systemctl"):
        log("systemctl not available; cannot check fake-hwclock/timesyncd status")
        return

    if systemctl_unit_exists("fake-hwclock.service"):
        state = systemctl_is_enabled("fake-hwclock.service")
        log(f"fake-hwclock.service: {state}")

    if systemctl_unit_exists("fake-hwclock.timer"):
        state = systemctl_is_enabled("fake-hwclock.timer")
        log(f"fake-hwclock.timer: {state}")

    if systemctl_unit_exists("systemd-timesyncd.service"):
        state = systemctl_is_enabled("systemd-timesyncd.service")
        log(f"systemd-timesyncd.service: {state}")


# ------------------------------------------------------------------------------
# Aggregate operations
# ------------------------------------------------------------------------------


def do_apply() -> None:
    """Apply all optimizations."""
    require_root()
    log("Applying MicroSD wear reduction settings (moderate)...")
    apply_journald_volatile()
    apply_apt_periodic_disable()
    apply_noatime_fstab()
    apply_tmpfs_tmp()
    apply_fake_hwclock_ntp()
    log("Apply complete. A reboot is recommended to ensure all changes (fstab/mounts) are in effect.")


def do_revert() -> None:
    """Revert all optimizations."""
    require_root()
    log("Reverting MicroSD wear reduction settings applied by this script...")
    revert_journald_volatile()
    revert_apt_periodic_disable()
    revert_noatime_fstab()
    revert_tmpfs_tmp()
    revert_fake_hwclock_ntp()
    log("Revert complete. A reboot is recommended.")


def do_status() -> None:
    """Show status of all optimizations."""
    log("Status: journald / rsyslog")
    status_journald_volatile()
    print()
    log("Status: APT periodic")
    status_apt_periodic_disable()
    print()
    log("Status: noatime / fstab mounts")
    status_noatime_fstab()
    print()
    log("Status: /tmp tmpfs")
    status_tmpfs_tmp()
    print()
    log("Status: fake-hwclock / NTP")
    status_fake_hwclock_ntp()
    print()
    log("Status check complete.")


def cleanup_temp_kfiles() -> None:
    """Clean up any remaining temp files."""
    for temp_file in TEMP_FILES:
        try:
            if temp_file.exists():
                temp_file.unlink()
        except Exception:
            pass
    TEMP_FILES.clear()


# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Apply or revert MicroSD wear reduction settings for RpiSolarkMonitor host",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
These operations implement the README "MicroSD wear reduction (moderate)" steps:
  1) Journald in RAM (Storage=volatile), optional rsyslog disable
  2) Disable APT periodic jobs & timers
  3) Add noatime for / and /boot in /etc/fstab
  4) Mount /tmp as tmpfs
  5) Prefer NTP (systemd-timesyncd) over fake-hwclock when available
        """,
    )

    parser.add_argument(
        "command",
        choices=["apply", "revert", "status"],
        help="Command to execute: apply, revert, or status",
    )

    args = parser.parse_args()

    try:
        if args.command == "apply":
            do_apply()
        elif args.command == "revert":
            do_revert()
        elif args.command == "status":
            do_status()
    finally:
        cleanup_temp_files()


if __name__ == "__main__":
    main()

