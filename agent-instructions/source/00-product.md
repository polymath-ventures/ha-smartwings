# ha-smartwings

Home Assistant support for SmartWings WM25/L-Z Zigbee roller shades under ZHA.

## Spec of record

`docs/` (Parts 1-3) is the specification. Part 3 (`docs/3-what-must-be-built.md`) states
the user-visible contract, constraints, failure modes F1-F18 and the definition of done.
Every behaviour change cites the Part 1 measurement or Part 3 requirement it serves.

## Two deliverables, one quirk ID

- **U — the quirk.** The SmartWings quirk in zha-device-handlers layout and style,
  developed here and later submitted upstream. It owns delivery (send once, re-send once
  after the travel time), commands as ZHA sends them (no vendor swap), the firmware's
  double reply, refusing the commands the radio mangles, and a truthful position.
  It reads nothing outside the zigpy device object: no files, no Home Assistant imports.
- **I — the integration** (`custom_components/smartwings`). It installs U into ZHA's
  `custom_quirks_path` and tells the user when U is not loaded. It identifies U only by
  the quirk ID U declares (`smartwings.wm25lz` in ZHA's `exposes_features`), never by
  class or module name.
- **The limits are the remote's.** The motor stops Zigbee commands at the limits set with
  its remote (#54, Part 1 §3a). "Stops at" (a closed limit kept in software) was retired.

## Rules that have cost real shades before

- ZCL lift is 0 = open, 100 = closed. HA cover position is 0 = closed, 100 = open.
  Name the space of every stored or transmitted position; convert in exactly one place.
- Never synthesise a Stop (a go-to built from a stale read reversed a shade).
- An unreadable position is not movement. Movement away from the target is not success.
- Opens send `up_open` and closes `down_close`, unswapped (#34, #54); a position is
  ZHA's `go_to_lift_percentage`, unscaled.

## Hardware

Nine shades on the owner's HAOS box (Home Assistant Yellow, EZSP/bellows). Nothing is
sent to a real shade without the owner's say-so.
