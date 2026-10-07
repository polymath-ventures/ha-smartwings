## 1. Close with no stop

- [x] 1.1 Failing test through the real Home Assistant + ZHA harness: a no-stop `cover.close_cover` puts command id 0x01 (`down_close`, no payload) on the wire, not 0x00.
- [x] 1.2 `_translate()`: with no closed limit set, `down_close` stays `down_close`; docstrings updated; bundled copy regenerated.
- [x] 1.3 Tests that asserted the swapped close updated; the harness motor models the real units (raw `down_close` lowers) by default.

## 2. Docs

- [x] 2.1 Part 1 §3c records the box evidence and records that `down_close` is known to lower the units; §8 8a records why #4 was closed and that `up_open` stays unobserved.
- [x] 2.2 README: the no-stop close limitation replaced.
