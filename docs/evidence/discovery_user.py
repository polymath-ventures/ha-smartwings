# ruff: noqa: PLR0917
"""ha-smartwings issue #36: ask the Office Shade what it supports. Office Shade only.

Install as /config/custom_components/zha_toolkit/local/user.py for one session, run
`user_discovery_run` once, then delete the file. See docs/evidence/discovery-procedure.md.

Only ZCL general (foundation) frames leave this script, and only four of them:
Discover Attributes Extended (0x15), Discover Commands Received (0x11), Discover
Commands Generated (0x13) and Read Attributes (0x00). No cluster-specific command is
ever built, so nothing here can move the shade.

One exception to "only four": zigpy itself may answer a late reply. If a reply arrives
after this script has stopped waiting for it, or after zigpy has already taken a
colliding frame of the shade's own as the reply (see _is_reply_to), no request is pending
to match it (device.py:1246-1247), so zigpy passes it to the cluster's handle_message (:1264-1266).
For any general command other than Read Attributes, handle_cluster_general_request ends
by sending a Default Response (0x0B, SUCCESS) unless the reply's disable-default-response
bit is set (zcl/__init__.py:918-931, :1068-1072). The shade leaves that bit clear. A Default
Response cannot move the shade. A late reply on 0xFC01 or 0xEF00 gets none, because zigpy
drops it as "unknown cluster" first. Not observed in the run: its one late reply was on
0xEF00.

Every frame goes through zigpy's Cluster.request(general=True, ...) with retries=0, so
zigpy sends it once and hands its answer back here unprocessed. Nothing on that path
writes zigpy's attribute cache. In zigpy 2.3.0 an attribute is marked unsupported only
when Cluster.read_attributes() sees UNSUPPORTED_ATTRIBUTE: it emits
AttributeUnsupportedEvent (zcl/__init__.py:1336-1348), whose handler marks the cache
(:555-557, :1365-1368), and the mark is then saved to zigbee.db. request() skips all of
that: Device.packet_received hands a matched reply to the waiting request and returns
(device.py:1246-1247) before any cluster handler runs (:1266).

Replies are decoded here from their raw bytes, which an application listener receives
before zigpy routes the frame (application.py:1373-1381). That is also the only way to
see a reply on 0xFC01 or 0xEF00: the shade does not advertise those clusters, so zigpy
drops their frames as "unknown cluster" (device.py:1152-1159).
"""

import asyncio
from datetime import UTC, datetime
import json
import logging
import os
from pathlib import Path
import time
from typing import Any

from zigpy import types as t
from zigpy.zcl import Cluster, foundation

LOGGER = logging.getLogger(__name__)

OFFICE_SHADE = "60:83:da:ff:fe:a0:00:02"
ENDPOINT_ID = 1
# Node descriptor manufacturer code (4098): the Silicon Labs/Ember SDK default,
# not a SmartWings code (firmware analysis §7).
MANUFACTURER_CODE = 0x1002

# (cluster ID, side of the cluster on the shade). The shade advertises the first eight.
# 0xFC01 and 0xEF00 are probes: common manufacturer-specific cluster IDs it does not
# advertise, asked as server clusters.
TARGETS = (
    (0x0000, "server"),
    (0x0001, "server"),
    (0x0003, "server"),
    (0x0004, "server"),
    (0x0005, "server"),
    (0x0102, "server"),
    (0x0003, "client"),
    (0x0019, "client"),
    (0xFC01, "server"),
    (0xEF00, "server"),
)
MANUFACTURER_MODES = (None, MANUFACTURER_CODE)

OUTPUT_PATH = Path("/config/zha_discovery_office_shade.json")
FRAME_TIMEOUT = 5.0  # seconds to wait for each reply before giving up on that frame
ATTEMPTS_PER_FRAME = 2  # the first send plus at most one manual re-send
MAX_CONSECUTIVE_TIMEOUTS = 3  # stop the whole run after this many unanswered frames
MAX_ATTRIBUTE_IDS = 16  # per Discover Attributes Extended page
MAX_COMMAND_IDS = 32  # per Discover Commands page
MAX_PAGES = 32  # per discovery, in case the shade never reports discovery complete

GC = foundation.GeneralCommand
DISCOVER_ATTRIBUTES = GC.Discover_Attribute_Extended  # 0x15
DISCOVER_RECEIVED = GC.Discover_Commands_Received  # 0x11
DISCOVER_GENERATED = GC.Discover_Commands_Generated  # 0x13
READ_ATTRIBUTES = GC.Read_Attributes  # 0x00
ALLOWED_COMMANDS = frozenset(
    {DISCOVER_ATTRIBUTES, DISCOVER_RECEIVED, DISCOVER_GENERATED, READ_ATTRIBUTES}
)
# The response each request expects. A Default Response naming the request's command is
# also accepted as its reply (ZCL rev 8 §2.5.12.2).
RESPONSE_FOR = {
    DISCOVER_ATTRIBUTES: GC.Discover_Attribute_Extended_rsp,  # 0x16
    DISCOVER_RECEIVED: GC.Discover_Commands_Received_rsp,  # 0x12
    DISCOVER_GENERATED: GC.Discover_Commands_Generated_rsp,  # 0x14
    READ_ATTRIBUTES: GC.Read_Attributes_rsp,  # 0x01
}


class StopEarlyError(Exception):
    """Raised after MAX_CONSECUTIVE_TIMEOUTS unanswered frames in a row."""


def _hex(value: int | None, width: int = 4) -> str | None:
    return None if value is None else f"0x{value:0{width}X}"


def _manufacturer_key(manufacturer: int | None) -> str:
    return (
        "no_manufacturer"
        if manufacturer is None
        else f"manufacturer_{manufacturer:#06x}"
    )


def _status(status: Any) -> dict[str, Any]:
    try:
        name = foundation.Status(status).name
    except ValueError:
        name = None
    return {"status": name, "status_code": _hex(int(status), 2)}


def _plain(value: Any) -> Any:
    """Turn a decoded zigpy value into something json can write."""
    if value is None or isinstance(value, bool | float | str):
        return value
    if isinstance(value, t.EUI64):
        return str(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, bytes | bytearray):
        return value.hex(" ")
    if isinstance(value, list | tuple | set | frozenset):
        return [_plain(item) for item in value]
    return repr(value)


def _cache_snapshot(cluster: Cluster | None) -> dict[str, Any]:
    """Read (never write) what zigpy already holds for this cluster."""
    cache = getattr(cluster, "_attr_cache", None)
    if cache is None:
        return {"values": {}, "unsupported": [], "legacy": {}}
    values = {
        f"{_hex(attrid)}/{_hex(manufacturer)}": _plain(item.value)
        for (attrid, manufacturer), item in getattr(cache, "_cache", {}).items()
    }
    unsupported = sorted(
        f"{_hex(attrid)}/{_hex(manufacturer)}"
        for attrid, manufacturer in getattr(cache, "_unsupported", set())
    )
    legacy = {
        _hex(attrid): _plain(item.value)
        for attrid, item in getattr(cache, "_legacy_cache", {}).items()
    }
    return {"values": values, "unsupported": unsupported, "legacy": legacy}


def _is_cached(cluster: Cluster | None, attrid: int, manufacturer: int | None) -> bool:
    cache = getattr(cluster, "_attr_cache", None)
    if cache is None:
        return False
    if (attrid, manufacturer) in getattr(cache, "_cache", {}):
        return True
    return manufacturer is None and attrid in getattr(cache, "_legacy_cache", {})


def _decode_reply(data: bytes) -> dict[str, Any]:
    """Decode a reply frame from its bytes, without zigpy's cluster handlers."""
    decoded: dict[str, Any] = {"raw": data.hex(" ")}
    try:
        hdr, rest = foundation.ZCLHeader.deserialize(data)
        decoded["frame_control"] = _hex(int(hdr.frame_control), 2)
        decoded["manufacturer"] = _hex(hdr.manufacturer)
        decoded["command_id"] = _hex(int(hdr.command_id), 2)
        if hdr.frame_control.frame_type != foundation.FrameType.GLOBAL_COMMAND:
            decoded["command"] = "cluster-specific"
            return decoded
        command_id = foundation.GeneralCommand(hdr.command_id)
        decoded["command"] = command_id.name
        response, _ = foundation.GENERAL_COMMANDS[command_id].schema.deserialize(rest)
    except Exception as err:  # noqa: BLE001 - keep the raw bytes and say why
        decoded["decode_error"] = repr(err)
        return decoded

    if command_id == GC.Default_Response:
        decoded["for_command"] = _hex(int(response.command_id), 2)
        decoded.update(_status(response.status))
    elif command_id == GC.Discover_Attribute_Extended_rsp:
        decoded["discovery_complete"] = bool(response.discovery_complete)
        decoded["attributes"] = [
            {
                "id": _hex(record.attrid),
                "datatype": _hex(int(record.datatype), 2),
                "acl": _hex(int(record.acl), 2),
            }
            for record in response.extended_attr_info
        ]
    elif command_id in (
        GC.Discover_Commands_Received_rsp,
        GC.Discover_Commands_Generated_rsp,
    ):
        decoded["discovery_complete"] = bool(response.discovery_complete)
        decoded["command_ids"] = [_hex(int(c), 2) for c in response.command_ids]
    elif command_id == GC.Read_Attributes_rsp:
        records = []
        for record in response.status_records:
            item = {"id": _hex(record.attrid), **_status(record.status)}
            if record.status == foundation.Status.SUCCESS and record.value is not None:
                item["datatype"] = _hex(int(record.value.type), 2)
                item["value"] = _plain(record.value.value)
            records.append(item)
        decoded["records"] = records
    else:
        decoded["response"] = repr(response)
    return decoded


def _is_reply_to(data: bytes, request: dict[str, Any]) -> bool:
    """Whether a frame on the request's cluster and TSN is that request's reply.

    The cluster and TSN alone are not enough: the shade also sends frames of its own,
    such as OTA Query Next Image Requests, whose TSN can collide. A reply must be a
    general command, travel in the opposite direction to the request, carry the same
    manufacturer code, and be the request's response command or a Default Response
    naming the request's command.
    """
    try:
        hdr, rest = foundation.ZCLHeader.deserialize(data)
    except Exception:  # noqa: BLE001
        return False
    if hdr.frame_control.frame_type != foundation.FrameType.GLOBAL_COMMAND:
        return False
    if hdr.frame_control.direction != request["direction"].flip():
        return False
    if hdr.manufacturer != request["manufacturer"]:
        return False
    if hdr.command_id == RESPONSE_FOR[request["command_id"]]:
        return True
    return hdr.command_id == GC.Default_Response and rest[:1] == bytes(
        [request["command_id"]]
    )


def _expected_zcl(cluster: Cluster, tsn: int, command_id, args, manufacturer) -> str:
    """Rebuild the ZCL bytes Cluster.request() sends (zcl/__init__.py:765-845)."""
    frame_control = foundation.FrameControl(
        frame_type=foundation.FrameType.GLOBAL_COMMAND,
        is_manufacturer_specific=manufacturer is not None,
        direction=(
            foundation.Direction.Server_to_Client
            if cluster.is_client
            else foundation.Direction.Client_to_Server
        ),
        disable_default_response=cluster.is_client,
        reserved=0b000,
    )
    hdr = foundation.ZCLHeader(
        frame_control=frame_control,
        manufacturer=manufacturer,
        tsn=tsn,
        command_id=command_id,
    )
    payload = foundation.GENERAL_COMMANDS[command_id].schema(*args).serialize()
    return (hdr.serialize() + payload).hex(" ")


class Discovery:
    """One discovery run against the Office Shade."""

    def __init__(self, app, device) -> None:
        """Hold the run's state; nothing is sent until run()."""
        self.app = app
        self.device = device
        self.endpoint = device.endpoints[ENDPOINT_ID]
        self.frames: list[dict[str, Any]] = []
        self.unmatched_frames: list[dict[str, Any]] = []
        self.clusters: list[dict[str, Any]] = []
        self.reads: list[dict[str, Any]] = []
        self.consecutive_timeouts = 0
        self.stopped_early: str | None = None
        # (cluster, TSN) -> (future for the reply, what the reply must match)
        self._waiters: dict[tuple[int, int], tuple[asyncio.Future, dict[str, Any]]] = {}
        self._started = datetime.now(UTC)
        self._finished: datetime | None = None

    # zigpy calls this for every received packet, before routing it to the device
    # (application.py:1373-1381). It only records; it never answers the shade.
    def handle_message(self, device, profile, cluster, src_ep, dst_ep, message):
        """Hand a reply from the Office Shade to the frame waiting for it."""
        if device is not self.device or src_ep != ENDPOINT_ID:
            return
        data = bytes(message)
        try:
            hdr, _ = foundation.ZCLHeader.deserialize(data)
        except Exception:  # noqa: BLE001
            hdr = None
        entry = None if hdr is None else self._waiters.get((cluster, hdr.tsn))
        if entry is not None:
            waiter, request = entry
            if not waiter.done() and _is_reply_to(data, request):
                waiter.set_result(data)
                return
        self.unmatched_frames.append(
            {
                "time": datetime.now(UTC).isoformat(),
                "cluster": _hex(cluster),
                **_decode_reply(data),
            }
        )

    def _cluster(self, cluster_id: int, side: str) -> tuple[Cluster, bool]:
        clusters = (
            self.endpoint.in_clusters
            if side == "server"
            else self.endpoint.out_clusters
        )
        if cluster_id in clusters:
            return clusters[cluster_id], True
        # Not on the endpoint: a bare zigpy Cluster, used only to build and send the
        # frame. It is not added to the endpoint, so the device is unchanged.
        cluster = Cluster(self.endpoint, is_server=side == "server")
        cluster.cluster_id = cluster_id
        return cluster, False

    async def _send_once(self, cluster, side, command_id, args, manufacturer, attempt):
        tsn = self.device.get_sequence()
        key = (cluster.cluster_id, tsn)
        loop = asyncio.get_running_loop()
        waiter = loop.create_future()
        self._waiters[key] = (
            waiter,
            {
                "direction": (
                    foundation.Direction.Server_to_Client
                    if cluster.is_client
                    else foundation.Direction.Client_to_Server
                ),
                "manufacturer": manufacturer,
                "command_id": int(command_id),
            },
        )
        frame: dict[str, Any] = {
            "n": len(self.frames) + 1,
            "time": datetime.now(UTC).isoformat(),
            "cluster": _hex(cluster.cluster_id),
            "side": side,
            "command": foundation.GeneralCommand(command_id).name,
            "command_id": _hex(int(command_id), 2),
            "manufacturer": _hex(manufacturer),
            "args": _plain(list(args)),
            "tsn": tsn,
            "attempt": attempt,
            "zcl_sent": _expected_zcl(cluster, tsn, command_id, args, manufacturer),
        }
        self.frames.append(frame)
        LOGGER.debug("discovery frame %d: %s", frame["n"], frame)
        started = time.monotonic()
        # retries=0: zigpy otherwise re-sends after a timeout or delivery error
        # (device.py:916-917, :959, :1003-1013); the one re-send here is explicit.
        request = asyncio.ensure_future(
            cluster.request(
                True,
                command_id,
                foundation.GENERAL_COMMANDS[command_id].schema,
                *args,
                manufacturer=manufacturer,
                expect_reply=True,
                retries=0,
                tsn=tsn,
            )
        )
        try:
            # zigpy waits up to 28 s for an end device (device.py:924-926), so the
            # 5 s limit is enforced here.
            await asyncio.wait(
                {waiter, request},
                timeout=FRAME_TIMEOUT,
                return_when=asyncio.FIRST_COMPLETED,
            )
            failed = request.done() and not request.cancelled() and request.exception()
            if not waiter.done() and request.done() and not failed:
                # zigpy matches replies on cluster, direction and TSN only
                # (device.py:938-944, :1181-1199), so it may have taken a colliding
                # frame of the shade's own. Keep waiting for the real reply.
                frame["zigpy_matched"] = repr(request.result())
                remaining = FRAME_TIMEOUT - (time.monotonic() - started)
                if remaining > 0:
                    await asyncio.wait({waiter}, timeout=remaining)
            if waiter.done():
                frame["outcome"] = "reply"
                frame["reply"] = _decode_reply(waiter.result())
            elif failed:
                frame["outcome"] = "error"
                frame["error"] = repr(request.exception())
            else:
                frame["outcome"] = "timeout"
        finally:
            self._waiters.pop(key, None)
            if not request.done():
                request.cancel()
            await asyncio.wait({request})
            if not request.cancelled():
                request.exception()  # retrieved, so asyncio does not log it
            frame["elapsed_s"] = round(time.monotonic() - started, 3)
            await self._save()
        return frame

    async def _exchange(self, cluster, side, command_id, args, manufacturer):
        """Send one discovery or read frame; re-send it once if it gets no reply."""
        if command_id not in ALLOWED_COMMANDS:
            raise ValueError(f"discovery: refusing general command {command_id!r}")
        for attempt in range(1, ATTEMPTS_PER_FRAME + 1):
            frame = await self._send_once(
                cluster, side, command_id, args, manufacturer, attempt
            )
            if frame["outcome"] == "reply":
                self.consecutive_timeouts = 0
                return frame["reply"]
            self.consecutive_timeouts += 1
            if self.consecutive_timeouts >= MAX_CONSECUTIVE_TIMEOUTS:
                raise StopEarlyError(
                    f"{self.consecutive_timeouts} frames in a row got no reply "
                    f"(last: frame {frame['n']}, {frame['outcome']})"
                )
        return None

    async def _discover(self, result, cluster, side, command_id, manufacturer):
        """Page one discovery command until the shade says it is complete."""
        start = 0
        last_id = 0xFFFF if command_id == DISCOVER_ATTRIBUTES else 0xFF
        for _ in range(MAX_PAGES):
            if command_id == DISCOVER_ATTRIBUTES:
                args = (t.uint16_t(start), t.uint8_t(MAX_ATTRIBUTE_IDS))
            else:
                args = (t.uint8_t(start), t.uint8_t(MAX_COMMAND_IDS))
            reply = await self._exchange(cluster, side, command_id, args, manufacturer)
            result["pages"] += 1
            if reply is None:
                result["outcome"] = "no reply"
                return
            items = reply.get("attributes", reply.get("command_ids"))
            if items is None:
                result["outcome"] = " ".join(
                    str(reply[k]) for k in ("command", "status") if reply.get(k)
                )
                result["reply"] = reply
                return
            result["found"].extend(items)
            ids = [int(i["id"] if isinstance(i, dict) else i, 16) for i in items]
            if reply["discovery_complete"]:
                result["outcome"] = "complete"
                return
            if not ids or max(ids) >= last_id:
                result["outcome"] = "incomplete, nothing further to ask for"
                return
            start = max(ids) + 1
        result["outcome"] = f"stopped after {MAX_PAGES} pages"

    def _summary(self) -> dict[str, Any]:
        replies = sum(1 for f in self.frames if f.get("outcome") == "reply")
        clusters = {}
        for entry in self.clusters:
            counts = {}
            for mode, kinds in entry["discovery"].items():
                for kind, found in kinds.items():
                    text = f"{len(found['found'])}"
                    if found["outcome"] != "complete":
                        text += f" ({found['outcome']})"
                    counts[f"{kind} {mode}"] = text
            clusters[f"{entry['cluster']} {entry['side']}"] = counts
        return {
            "frames_sent": len(self.frames),
            "replies": replies,
            "frames_without_reply": len(self.frames) - replies,
            "reads_sent": sum(1 for r in self.reads if "skipped" not in r),
            "reads_skipped_cached": sum(1 for r in self.reads if "skipped" in r),
            "unmatched_frames": len(self.unmatched_frames),
            "stopped_early": self.stopped_early,
            "found_per_cluster": clusters,
            "output": str(OUTPUT_PATH),
        }

    def document(self) -> dict[str, Any]:
        """Return the whole run as written to OUTPUT_PATH."""
        return {
            "issue": 36,
            "ieee": OFFICE_SHADE,
            "nwk": _hex(self.device.nwk),
            "endpoint": ENDPOINT_ID,
            "manufacturer_code": _hex(MANUFACTURER_CODE),
            "frame_timeout_s": FRAME_TIMEOUT,
            "started": self._started.isoformat(),
            "finished": None if self._finished is None else self._finished.isoformat(),
            "summary": self._summary(),
            "clusters": self.clusters,
            "reads": self.reads,
            "frames": self.frames,
            "unmatched_frames": self.unmatched_frames,
        }

    async def _save(self) -> None:
        text = json.dumps(self.document(), indent=2)

        def write() -> None:
            partial = OUTPUT_PATH.with_name(OUTPUT_PATH.name + ".partial")
            partial.write_text(text, encoding="utf-8")
            os.replace(partial, OUTPUT_PATH)

        await asyncio.get_running_loop().run_in_executor(None, write)

    async def run(self) -> dict[str, Any]:
        """Discover every target, then read what was found and is not cached."""
        LOGGER.warning(
            "discovery: Office Shade %s nwk=0x%04X: sending discovery and read frames "
            "only, one at a time; results go to %s",
            OFFICE_SHADE,
            self.device.nwk,
            OUTPUT_PATH,
        )
        self.app.add_listener(self)
        try:
            targets = []
            for cluster_id, side in TARGETS:
                cluster, on_endpoint = self._cluster(cluster_id, side)
                entry = {
                    "cluster": _hex(cluster_id),
                    "side": side,
                    "on_endpoint": on_endpoint,
                    "zigpy_class": type(cluster).__name__,
                    "cache_before": _cache_snapshot(cluster if on_endpoint else None),
                    "discovery": {},
                }
                self.clusters.append(entry)
                targets.append((cluster, side, on_endpoint, entry))

            for cluster, side, _, entry in targets:
                for manufacturer in MANUFACTURER_MODES:
                    modes = entry["discovery"][_manufacturer_key(manufacturer)] = {}
                    for kind, command_id in (
                        ("attributes", DISCOVER_ATTRIBUTES),
                        ("commands_received", DISCOVER_RECEIVED),
                        ("commands_generated", DISCOVER_GENERATED),
                    ):
                        # Filled in place, so a partial file shows the progress.
                        result = modes[kind] = {
                            "outcome": "interrupted",
                            "pages": 0,
                            "found": [],
                        }
                        await self._discover(
                            result, cluster, side, command_id, manufacturer
                        )

            for cluster, side, on_endpoint, entry in targets:
                plain = entry["discovery"][_manufacturer_key(None)]["attributes"]
                specific = entry["discovery"][_manufacturer_key(MANUFACTURER_CODE)][
                    "attributes"
                ]
                plain_ids = [int(a["id"], 16) for a in plain["found"]]
                specific_ids = [int(a["id"], 16) for a in specific["found"]]
                # Each attribute once: plainly if plain discovery listed it, else with
                # the manufacturer code it was found under.
                wanted = dict.fromkeys(
                    [(attrid, None) for attrid in plain_ids]
                    + [
                        (attrid, MANUFACTURER_CODE)
                        for attrid in specific_ids
                        if attrid not in plain_ids
                    ]
                )
                for attrid, manufacturer in wanted:
                    read = {
                        "cluster": entry["cluster"],
                        "side": side,
                        "attribute": _hex(attrid),
                        "manufacturer": _hex(manufacturer),
                    }
                    if on_endpoint and _is_cached(cluster, attrid, manufacturer):
                        read["skipped"] = "already in zigpy's attribute cache"
                        self.reads.append(read)
                        continue
                    self.reads.append(read)
                    read["reply"] = await self._exchange(
                        cluster,
                        side,
                        READ_ATTRIBUTES,
                        ([t.uint16_t(attrid)],),
                        manufacturer,
                    )
        except StopEarlyError as err:
            self.stopped_early = str(err)
            LOGGER.warning("discovery: stopped early: %s", err)
        finally:
            self.app.remove_listener(self)
            self._finished = datetime.now(UTC)
            await self._save()

        summary = self._summary()
        LOGGER.info("discovery: summary: %s", json.dumps(summary))
        return summary


# zha_toolkit calls every user_* handler with eight positional arguments (PLR0917).
async def user_discovery_run(
    app, listener, ieee, cmd, data, service, params, event_data
):
    """Discover the Office Shade's attributes and commands; write OUTPUT_PATH."""
    if str(ieee) != OFFICE_SHADE:
        raise ValueError(f"discovery: Office Shade {OFFICE_SHADE} only, got {ieee}")
    device = app.get_device(ieee=t.EUI64.convert(OFFICE_SHADE))
    event_data["discovery"] = await Discovery(app, device).run()
