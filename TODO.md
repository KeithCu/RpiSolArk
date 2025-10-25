## RpiSolArk To-Do

### 1) Screen backlight management for longevity - COMPLETED ✅
- [x] **Comprehensive backlight management system** - Smart timeout, emergency detection, power events
- [x] **Display timeout functionality** - Configurable timeout with activity tracking
- [x] **Emergency state detection** - Keeps display on during off-grid/generator states  
- [x] **Power event handling** - Automatic display activation during power events
- [x] **Manual display control** - Button handler for user control
- [x] **Graceful degradation** - Falls back to console display when LCD unavailable

### 2) Frequency measurement system - COMPLETED ✅
- [x] **Fixed frequency calculation** - System now correctly reads 60.00-60.30 Hz on utility power
- [x] **Stable readings** - 5-second measurement duration provides excellent stability  
- [x] **Correct power source detection** - System properly identifies "Util" vs "Gen" power
- [x] **AC-into-DC-optocoupler documented** - Hardware setup and edge counting behavior documented
- [x] **No outlier filtering** - Preserves ability to detect generator instability patterns

### 3) Multiple H1AA1 modules working concurrently  
- [ ] Add multi-H1AA1 input support to GPIO and pulse counter
- [ ] Extend config schema to define multiple H1AA1 channels
- [ ] Implement per-channel calibration and cross-talk validation tests
- [ ] Bench test two H1AA1s concurrently and record accuracy

### 4) Sol-Ark: change settings on grid loss/restore
- [ ] Enumerate Sol-Ark API endpoints to change required settings
- [ ] Add change-settings functions for both inverters in `solark_cloud.py`
- [ ] Wire grid-loss/restore events to trigger Sol-Ark setting changes
- [ ] Implement retries, idempotency, and audit logging around API calls
- [ ] Add configuration for inverter IDs and loss/restore setting profiles
- [ ] Create tests simulating loss/restore to verify settings are applied

## Shopping List
- [ ] H11AA1 optocoupler (add one more) - **Priority: Medium** (system working well with single optocoupler)
- [ ] Small isolation/step-down transformer sized appropriately (order 1–2)
- [ ] Project case/enclosure for sensor + transformer  
- [ ] Other parts (TBD)

## Long-running Raspberry Pi system to-do (5-10 year target)
- [ ] Enable hardware watchdog and service (`/dev/watchdog`, `watchdog` service)
- [ ] Configure log rotation and limit writes; consider overlay/RO root if feasible
- [ ] Auto-restart core services via `systemd` (`Restart=always`, health checks)
- [ ] Health monitoring and auto-recovery (network, disk space, processes)
- [ ] Power stability: UPS/HAT support and clean shutdown on low battery
- [ ] Thermal management: heatsinks/fan and temperature monitoring
- [ ] Storage reliability: high-endurance SD or external SSD; periodic fsck
- [ ] Filesystem tuning: `noatime`, tune journaling, reduce write frequency
- [ ] Secure remote access and updates (SSH keys, update cadence)
- [ ] Backups/restore plan for config and data snapshots
- [ ] Monitoring/alerting pipeline for failures and anomalies
- [ ] Burn-in test plan (e.g., 72h continuous run with fault injections)
- [x] **Backlight strategy**: Keep backlight OFF - unnecessary for monitoring device ✅
- [ ] **Component selection**: Use industrial-grade components where possible
- [ ] **Environmental**: Proper enclosure, dust protection, temperature range validation
- [ ] **Power supply**: High-quality, regulated supply with surge protection
- [ ] **SD card**: Industrial/endurance grade or migrate to external SSD
- [ ] **Backup system**: Secondary Pi or failover mechanism for critical monitoring


- [ ] SD wear reduction (moderate):
  - [ ] Journald volatile (RAM) and disable rsyslog
  - [ ] Disable APT periodic timers and cron
  - [ ] Add noatime to / and /boot
  - [ ] Put /tmp on tmpfs
  - [ ] Optional: disable fake-hwclock.timer (with NTP)


