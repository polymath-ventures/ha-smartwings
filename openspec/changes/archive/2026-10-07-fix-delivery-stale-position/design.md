## Context

Issue #51: reads during travel return the lift from before the move, and the shade reports its position when travel ends. Delivery sends once and returns; position readback judges the movement after its travel time and re-sends once (see the proposal).

## Decisions

- **The re-send is one frame.** Only the frame sent before the command returns is retried once if lost; the readback's re-send is a single frame, never retried.
- **Stop cancels everything pending.** Stop moves the shade's generation on; a lost frame's retry and the readback's re-send both check the generation immediately before sending, so neither goes out after a Stop, even if the readback already holds the re-send. A Stop during a movement's delivery also means no readback starts for that movement; the shade's report of where it halted still updates the position.
- **Stop supersedes queued movements and is read back.** Stop bypasses the lock, so a movement issued before it could otherwise move the shade after it. A count of Stops is recorded when a movement is issued; if it has changed when the movement gets the lock, the movement releases the lock and answers SUCCESS unsent; such a movement also cancels nothing (its scheduled `_cancel_tracking()` is skipped), so it cannot kill the Stop's read (stock-like: ZHA shows success, and the user's Stop is what happens). After a Stop the quirk waits `STOP_SETTLE_S` (3 s, from sending it) for the shade's report and otherwise reads the lift once on a budget of `READ_ATTEMPTS`, so a lost report cannot leave the position stale.
- **Budget.** Delivery needs `SEND_ATTEMPTS` (2) operations; readback at most `TRACKING_NEEDED_OPS` (15): its reads before and after the re-send, the one re-send frame and the deferred re-read.

## Superseded

- A closed-limit change while a lost frame's retry is pending is not guarded (review 1c). Moot: on 2026-10-06 the owner saw Zigbee closes stop at the remote-programmed limit (Part 1 §3a), so closed-limit enforcement is being retired in the next change, before any deploy.
