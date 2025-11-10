#!/usr/bin/env bash
# rpisolark-optimize-writes.sh
#
# Purpose:
#   Apply the README.md "MicroSD wear reduction (moderate)" recommendations
#   to a Raspberry Pi running RpiSolarkMonitor, in a SAFE, IDEMPOTENT,
#   and REVERSIBLE way.
#
# Summary of what this script does (from README.md section 473+):
#   1) Put systemd journal in RAM (Storage=volatile), optionally disable rsyslog.
#   2) Disable APT periodic background jobs and their systemd timers.
#   3) Ensure root/boot filesystems use noatime (and optionally commit=600).
#   4) Use tmpfs for /tmp.
#   5) Optionally disable fake-hwclock.timer if NTP is available and ensure
#      systemd-timesyncd is enabled.
#
# Design:
#   - Idempotent: Running multiple times will not duplicate changes.
#   - Cautious edits: Makes backups before changing system files.
#   - Explicit output: Shows each action and its verification.
#   - Reversible: Provides a --revert mode that attempts to undo changes
#     made by this script (to the extent safely possible).
#
# Usage:
#   sudo ./rpisolark-optimize-writes.sh apply
#   sudo ./rpisolark-optimize-writes.sh revert
#   sudo ./rpisolark-optimize-writes.sh status
#
# Notes:
#   - Must be run as root (sudo) because it edits system configuration.
#   - Target systems: Raspberry Pi OS / Debian-like distros using systemd.
#   - Review generated backups under:
#       /etc/systemd/journald.conf.rpisolark.bak
#       /etc/fstab.rpisolark.bak
#       /etc/apt/apt.conf.d/02periodic-disable.rpisolark.bak (if present)
#
# Warning:
#   This script is tuned to the recommendations in this repo's README.
#   If your system is significantly customized, review each step before use.

set -euo pipefail

SCRIPT_NAME="$(basename "$0")"

log() {
    echo "[$SCRIPT_NAME] $*"
}

die() {
    echo "[$SCRIPT_NAME][ERROR] $*" >&2
    exit 1
}

require_root() {
    if [[ "$(id -u)" -ne 0 ]]; then
        die "This script must be run as root. Re-run with: sudo ./$SCRIPT_NAME apply|revert|status"
    fi
}

backup_file_once() {
    # backup_file_once /path/to/file
    local file="$1"
    local backup="${file}.rpisolark.bak"
    if [[ -f "$file" && ! -f "$backup" ]]; then
        cp -p "$file" "$backup"
        log "Backup created: $backup"
    fi
}

restore_backup_if_exists() {
    # restore_backup_if_exists /path/to/file
    local file="$1"
    local backup="${file}.rpisolark.bak"
    if [[ -f "$backup" ]]; then
        cp -p "$backup" "$file"
        log "Restored from backup: $backup -> $file"
    else
        log "No backup to restore for: $file"
    fi
}

have_cmd() {
    command -v "$1" >/dev/null 2>&1
}

# ------------------------------------------------------------------------------
# 1) systemd-journald: set Storage=volatile, optionally disable rsyslog
# ------------------------------------------------------------------------------

apply_journald_volatile() {
    local conf="/etc/systemd/journald.conf"

    if [[ -f "$conf" ]]; then
        backup_file_once "$conf"

        # Remove existing Storage= lines (commented or uncommented), then append Storage=volatile
        if grep -qE '^[#\s]*Storage=' "$conf"; then
            sed -i 's/^[#\s]*Storage=.*/Storage=volatile/' "$conf"
        else
            printf '\nStorage=volatile\n' >>"$conf"
        fi

        log "Configured systemd-journald Storage=volatile"

        # restart journald to apply
        if have_cmd systemctl; then
            systemctl restart systemd-journald || die "Failed to restart systemd-journald"
        fi
    else
        log "Skip: $conf not found"
    fi

    # Optional: disable rsyslog if installed
    if have_cmd systemctl && systemctl list-unit-files | grep -q '^rsyslog.service'; then
        systemctl disable --now rsyslog || true
        log "Disabled rsyslog.service to reduce disk writes (if it was enabled)"
    fi
}

revert_journald_volatile() {
    local conf="/etc/systemd/journald.conf"
    restore_backup_if_exists "$conf"

    if have_cmd systemctl; then
        systemctl restart systemd-journald || true
    fi

    # Re-enabling rsyslog is left to the admin; we only log here.
    log "If rsyslog was disabled and you want it back, run: systemctl enable --now rsyslog"
}

status_journald_volatile() {
    if have_cmd systemctl; then
        local storage
        storage="$(systemctl show -p Storage systemd-journald 2>/dev/null || true)"
        log "systemd-journald: ${storage:-Storage=unknown}"
        if systemctl list-unit-files | grep -q '^rsyslog.service'; then
            local rsyslog_state
            rsyslog_state="$(systemctl is-enabled rsyslog 2>/dev/null || echo 'not-installed/disabled')"
            log "rsyslog.service: $rsyslog_state"
        fi
    else
        log "systemctl not available; cannot query journald status"
    fi
}

# ------------------------------------------------------------------------------
# 2) Disable APT periodic background jobs
# ------------------------------------------------------------------------------

APT_PERIODIC_FILE="/etc/apt/apt.conf.d/02periodic-disable"

apply_apt_periodic_disable() {
    # Backup existing file if it exists
    if [[ -f "$APT_PERIODIC_FILE" ]]; then
        backup_file_once "$APT_PERIODIC_FILE"
    fi

    cat >"$APT_PERIODIC_FILE" <<'EOF'
APT::Periodic::Enable "0";
APT::Periodic::Update-Package-Lists "0";
APT::Periodic::Download-Upgradeable-Packages "0";
APT::Periodic::AutocleanInterval "0";
EOF

    log "Configured APT periodic tasks disabled in $APT_PERIODIC_FILE"

    if have_cmd systemctl; then
        systemctl disable --now apt-daily.timer apt-daily-upgrade.timer || true
        log "Disabled apt-daily.timer and apt-daily-upgrade.timer"
    fi
}

revert_apt_periodic_disable() {
    # Remove our override file (does not restore previous intervals automatically).
    if [[ -f "$APT_PERIODIC_FILE" ]]; then
        rm -f "$APT_PERIODIC_FILE"
        log "Removed $APT_PERIODIC_FILE"
    fi

    # Restore backup if any (legacy behavior)
    restore_backup_if_exists "$APT_PERIODIC_FILE"

    if have_cmd systemctl; then
        log "If you want APT periodic timers back, run:"
        log "  systemctl enable --now apt-daily.timer"
        log "  systemctl enable --now apt-daily-upgrade.timer"
    fi
}

status_apt_periodic_disable() {
    if [[ -f "$APT_PERIODIC_FILE" ]]; then
        log "APT periodic override present: $APT_PERIODIC_FILE"
        grep -v '^\s*$' "$APT_PERIODIC_FILE" || true
    else
        log "APT periodic override file not present."
    fi

    if have_cmd systemctl; then
        local t1 t2
        t1="$(systemctl is-enabled apt-daily.timer 2>/dev/null || echo 'unknown')"
        t2="$(systemctl is-enabled apt-daily-upgrade.timer 2>/dev/null || echo 'unknown')"
        log "apt-daily.timer: $t1"
        log "apt-daily-upgrade.timer: $2"
    fi
}

# ------------------------------------------------------------------------------
# 3) noatime (and optional commit=600) in /etc/fstab
# ------------------------------------------------------------------------------

apply_noatime_fstab() {
    local fstab="/etc/fstab"
    [[ -f "$fstab" ]] || { log "Skip: $fstab not found"; return; }

    backup_file_once "$fstab"

    # EDIT STRATEGY:
    # - For lines mounting / and /boot (common RPi layout), ensure 'noatime' is in options.
    # - Do NOT force commit=600 automatically (higher risk); instead, log instruction.
    #
    # We avoid complex parsing; we operate on typical fstab formats.
    local tmp
    tmp="$(mktemp)"

    while read -r line; do
        if [[ "$line" =~ ^# ]] || [[ -z "$line" ]]; then
            echo "$line" >>"$tmp"
            continue
        fi

        # fields: fs_spec fs_file fs_vfstype fs_mntops fs_freq fs_passno
        # shellcheck disable=SC2086
        set -- $line
        local fs_spec="$1"
        local fs_file="$2"
        local fs_vfstype="$3"
        local fs_mntops="$4"
        local fs_freq="$5"
        local fs_passno="$6"

        if [[ "$fs_file" == "/" || "$fs_file" == "/boot" || "$fs_file" == "/boot/firmware" ]]; then
            if [[ "$fs_mntops" != *noatime* ]]; then
                if [[ -n "$fs_mntops" ]]; then
                    fs_mntops="${fs_mntops},noatime"
                else
                    fs_mntops="defaults,noatime"
                fi
                log "Added noatime for $fs_file in fstab"
            fi
            echo "$fs_spec $fs_file $fs_vfstype $fs_mntops ${fs_freq:-0} ${fs_passno:-0}" >>"$tmp"
        else
            echo "$line" >>"$tmp"
        fi
    done <"$fstab"

    mv "$tmp" "$fstab"
    log "Updated $fstab with noatime for / and /boot (if applicable)."
    log "To also apply commit=600 (less frequent journal flush, higher risk), edit /etc/fstab manually."
}

revert_noatime_fstab() {
    local fstab="/etc/fstab"
    restore_backup_if_exists "$fstab"
    log "If you added noatime manually beyond our changes, adjust /etc/fstab to your needs."
}

status_noatime_fstab() {
    local root_opts boot_opts
    if have_cmd findmnt; then
        root_opts="$(findmnt -no OPTIONS / 2>/dev/null || true)"
        boot_opts="$(findmnt -no OPTIONS /boot 2>/dev/null || true)"
        log "Root mount options: ${root_opts:-unknown}"
        log "/boot mount options: ${boot_opts:-unknown}"
        if echo "$root_opts" | grep -q noatime; then
            log "Root filesystem has noatime: OK"
        else
            log "Root filesystem missing noatime"
        fi
    else
        log "findmnt not available; cannot verify runtime mount options"
    fi
}

# ------------------------------------------------------------------------------
# 4) Use tmpfs for /tmp
# ------------------------------------------------------------------------------

apply_tmpfs_tmp() {
    local fstab="/etc/fstab"
    [[ -f "$fstab" ]] || { log "Skip: $fstab not found"; return; }

    backup_file_once "$fstab"

    if grep -qE '^[^#]*\s+/tmp\s+tmpfs' "$fstab"; then
        log "/tmp is already configured as tmpfs in $fstab"
    else
        echo 'tmpfs /tmp tmpfs defaults,nosuid,nodev 0 0' >>"$fstab"
        log "Added tmpfs /tmp entry to $fstab"
    fi

    if have_cmd mount; then
        mount -a || die "mount -a failed after /tmp tmpfs change; check /etc/fstab"
    fi
}

revert_tmpfs_tmp() {
    local fstab="/etc/fstab"
    restore_backup_if_exists "$fstab"
    log "If additional /tmp lines remain, manually clean up $fstab."
}

status_tmpfs_tmp() {
    if have_cmd findmnt; then
        local tmp_type
        tmp_type="$(findmnt -no FSTYPE /tmp 2>/dev/null || true)"
        log "/tmp filesystem type: ${tmp_type:-unknown}"
    else
        log "findmnt not available; cannot verify /tmp mount type"
    fi
}

# ------------------------------------------------------------------------------
# 5) Optional: fake-hwclock vs NTP (systemd-timesyncd)
# ------------------------------------------------------------------------------

apply_fake_hwclock_ntp() {
    # Only adjust if systemd present
    if ! have_cmd systemctl; then
        log "systemctl not available; skipping fake-hwclock/systemd-timesyncd adjustments"
        return
    fi

    # If systemd-timesyncd exists, we assume NTP can be used
    if systemctl list-unit-files | grep -q '^systemd-timesyncd.service'; then
        # Disable fake-hwclock.timer (if present)
        if systemctl list-unit-files | grep -q '^fake-hwclock.timer'; then
            systemctl disable --now fake-hwclock.timer || true
            log "Disabled fake-hwclock.timer (NTP via systemd-timesyncd expected)"
        fi
        if systemctl list-unit-files | grep -q '^fake-hwclock.service'; then
            systemctl disable --now fake-hwclock.service || true
            log "Disabled fake-hwclock.service"
        fi

        # Enable timesyncd
        systemctl enable --now systemd-timesyncd || true
        log "Enabled systemd-timesyncd for NTP time sync"
    else
        log "systemd-timesyncd not present; leaving fake-hwclock as-is"
    fi
}

revert_fake_hwclock_ntp() {
    if ! have_cmd systemctl; then
        log "systemctl not available; skipping revert of fake-hwclock/systemd-timesyncd"
        return
    fi

    log "To re-enable fake-hwclock (if desired), run:"
    log "  systemctl enable --now fake-hwclock.service fake-hwclock.timer"
    log "To disable timesyncd, run:"
    log "  systemctl disable --now systemd-timesyncd"
}

status_fake_hwclock_ntp() {
    if ! have_cmd systemctl; then
        log "systemctl not available; cannot check fake-hwclock/timesyncd status"
        return
    fi

    if systemctl list-unit-files | grep -q '^fake-hwclock.service'; then
        log "fake-hwclock.service: $(systemctl is-enabled fake-hwclock.service 2>/dev/null || echo 'unknown')"
    fi
    if systemctl list-unit-files | grep -q '^fake-hwclock.timer'; then
        log "fake-hwclock.timer: $(systemctl is-enabled fake-hwclock.timer 2>/dev/null || echo 'unknown')"
    fi
    if systemctl list-unit-files | grep -q '^systemd-timesyncd.service'; then
        log "systemd-timesyncd.service: $(systemctl is-enabled systemd-timesyncd.service 2>/dev/null || echo 'unknown')"
    fi
}

# ------------------------------------------------------------------------------
# Aggregate operations
# ------------------------------------------------------------------------------

do_apply() {
    require_root
    log "Applying MicroSD wear reduction settings (moderate)..."
    apply_journald_volatile
    apply_apt_periodic_disable
    apply_noatime_fstab
    apply_tmpfs_tmp
    apply_fake_hwclock_ntp
    log "Apply complete. A reboot is recommended to ensure all changes (fstab/mounts) are in effect."
}

do_revert() {
    require_root
    log "Reverting MicroSD wear reduction settings applied by this script..."
    revert_journald_volatile
    revert_apt_periodic_disable
    revert_noatime_fstab
    revert_tmpfs_tmp
    revert_fake_hwclock_ntp
    log "Revert complete. A reboot is recommended."
}

do_status() {
    log "Status: journald / rsyslog"
    status_journald_volatile
    echo
    log "Status: APT periodic"
    status_apt_periodic_disable
    echo
    log "Status: noatime / fstab mounts"
    status_noatime_fstab
    echo
    log "Status: /tmp tmpfs"
    status_tmpfs_tmp
    echo
    log "Status: fake-hwclock / NTP"
    status_fake_hwclock_ntp
    echo
    log "Status check complete."
}

# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------

usage() {
    cat <<EOF
$SCRIPT_NAME - Apply or revert MicroSD wear reduction settings for RpiSolarkMonitor host

Usage:
  sudo ./$SCRIPT_NAME apply    # Apply all recommended optimizations
  sudo ./$SCRIPT_NAME revert   # Revert changes made by this script (where backed up)
  ./$SCRIPT_NAME status        # Show current status (read-only; root not required)

These operations implement the README "MicroSD wear reduction (moderate)" steps:
  1) Journald in RAM (Storage=volatile), optional rsyslog disable
  2) Disable APT periodic jobs & timers
  3) Add noatime for / and /boot in /etc/fstab
  4) Mount /tmp as tmpfs
  5) Prefer NTP (systemd-timesyncd) over fake-hwclock when available
EOF
}

cmd="${1:-}"

case "$cmd" in
    apply)
        do_apply
        ;;
    revert)
        do_revert
        ;;
    status)
        do_status
        ;;
    ""|-h|--help|help)
        usage
        ;;
    *)
        die "Unknown command: $cmd. Use: apply | revert | status"
        ;;
esac