# Agent instructions

## Agent skills

### Issue tracker

Issues and specifications live in GitHub Issues for `eliancanul/iot-indoor-positioning`. Use the `gh` CLI for tracker operations. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the canonical labels `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository. Read `CONTEXT.md` and relevant ADRs in `docs/adr/` before exploring or changing domain behavior. See `docs/agents/domain.md`.

## Current project direction

The project is an IoT indoor-positioning platform using ESP32 RSSI readings over MQTT. It currently supports calibration, geometric position estimation, data collection, and normalized capture records. The planned next major capability is an RSSI fingerprinting algorithm backed by a trustworthy collection dataset.

Do not treat the legacy geometric estimators as interchangeable with fingerprinting. Preserve circles as a comparison method, and keep data-quality and estimation diagnostics distinct from accepted training examples.
