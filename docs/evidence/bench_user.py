# ruff: noqa: PLR0917
"""ha-smartwings issue #42: the test bench for the owner's sessions. Office Shade only.

Install as /config/custom_components/zha_toolkit/local/user.py for a session, run the
steps in docs/evidence/bench-run-sheets.md, copy the session file off, then delete both.
ZHA Toolkit re-imports this file on every call, so no restart is needed.

Each `user_bench_<action>` function is one action of the run sheets. It is called as
`zha_toolkit.execute` with `command: user_bench_<action>`, the Office Shade's IEEE, a
`session` name, the plan's `test_id`, an optional `step`, and the action's own fields
(read from the service call's data; ZHA Toolkit's schema allows extra keys).

What leaves this script, and only to the Office Shade (IEEE allow-list below):
1. ZCL general commands: Read Attributes (0x00), Write Attributes (0x02, writable
   attributes in WRITABLE only, with `confirm: true`), Read Reporting Configuration
   (0x08) and the three discovery commands (0x11, 0x13, 0x15). No reporting
   configuration and no binding is ever written (test plan §3b item 6.3).
2. ZCL cluster commands in CLUSTER_COMMANDS: Window Covering 0x00, 0x01, 0x02 and 0x05;
   Identify 0x00 and 0x01; Get Group Membership; Get Scene Membership. Window Covering
   0x04, 0x07 and 0x08 are NEVER sent (NEVER_SEND): the radio turns them into malformed
   motor frames (firmware-analysis.md §3 note 3).
3. ZDO: Node_Desc_req, Power_Desc_req and Mgmt_Bind_req (reads only).
Anything else is refused before a frame is built. A command that can move the shade
needs `remote_ready: true` and, unless it is a go-to to lift 0 (fully open), also
`may_go_down: true`.

Every frame goes through zigpy's Cluster.request() (or Device.request() for ZDO) with
retries=0, so zigpy sends it once. One frame is in flight at a time, and one bench call
runs at a time. The bench never re-sends; a re-send is a new call.

Never marks anything unsupported. Replies are decoded here from their raw bytes, which
an application listener receives before zigpy routes the frame (application.py:
1373-1381). Nothing on this path writes zigpy's attribute cache: zigpy 2.3.0 marks an
attribute unsupported only when Cluster.read_attributes() sees UNSUPPORTED_ATTRIBUTE
(zcl/__init__.py:1336-1348, :555-557, :1365-1368), and request() hands a matched reply
to the waiting request and returns (device.py:1246-1247) before any cluster handler runs.
Frames go through a bare zigpy Cluster, never the endpoint's (quirk) cluster object, so
no quirk code is on the path.

Strict reply matching. zigpy matches a reply on cluster, direction and TSN only
(device.py:938-944, :1181-1199). The shade also sends frames of its own whose TSN can
collide, such as OTA Query Next Image Requests. A frame here is a request's reply only
if it travels the other way, carries the request's manufacturer code (any code, for the
wildcard 0xFFFF), and is the request's response command or a Default Response naming the
request's command. A ZDO reply must be the request's response cluster with its TSN.
Everything else the shade sends during a call goes to `unmatched_frames`, with its time;
a second reply to a frame already answered (the shade sends SUCCESS, then 0x81) is
tagged `second_reply_to_frame`. A call listens for LINGER_S after its last frame, so
those late frames and any Report Attributes are caught.

As in the discovery handler, zigpy itself may answer a late reply that no request is
waiting for with a Default Response (zcl/__init__.py:918-931, :1068-1072). That frame
is zigpy's, cannot move the shade, and is not logged here.

Output: /config/smartwings_bench_<session>.json, written after every frame, so an
interrupted call leaves a file. Each call is appended to the same session file, with
every frame sent (time, TSN, bytes), its reply (time, bytes, decoded) or timeout, and
any unmatched frame. The call's summary is also the action's response.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import enum
import importlib.metadata
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any

from zigpy import types as t
from zigpy.zcl import Cluster, foundation
from zigpy.zcl.clusters.closures import WindowCovering
from zigpy.zcl.clusters.general import Groups, Identify, Scenes
import zigpy.zdo.types as zdo_t

LOGGER = logging.getLogger(__name__)

BENCH_VERSION = "2"
OFFICE_SHADE = "60:83:da:ff:fe:a0:00:02"
# A scope extension is a reviewed change to this set, never a call field.
ALLOWED_IEEES = frozenset({OFFICE_SHADE})
ENDPOINT_ID = 1
ZDO_ENDPOINT = 0
MANUFACTURER_CODE = 0x1002  # node descriptor manufacturer code (SmartWings, 4098)
WILDCARD_MANUFACTURER = 0xFFFF  # ZCL8 §2.5.19.1.1

OUTPUT_DIR = Path("/config")
FRAME_TIMEOUT = 5.0  # seconds to wait for each reply
MAX_CONSECUTIVE_TIMEOUTS = 3  # a call stops after this many unanswered frames in a row
MAX_WAIT_S = 900  # longest idle, watch or listen in one call
BUSY_FLAG = "_smartwings_bench_busy"  # on the application object: survives reloads
# After its last frame a call keeps listening this long, so a second reply to a frame
# (the shade answers every Window Covering command SUCCESS, then 0x81 with the same
# TSN: firmware-analysis.md §3) and any report the move triggers are logged too.
LINGER_S = 3.0
# A frame from the shade is tagged as a frame's second reply only this long after that
# frame's first reply: a TSN is reused after 256 frames.
SECOND_REPLY_WINDOW_S = 3.0

BASIC = 0x0000
POWER = 0x0001
IDENTIFY = 0x0003
GROUPS = 0x0004
SCENES = 0x0005
WINDOW_COVERING = 0x0102
SERVER_CLUSTERS = (BASIC, POWER, IDENTIFY, GROUPS, SCENES, WINDOW_COVERING)
LIFT_PERCENTAGE = 0x0008
IDENTIFY_TIME = 0x0000

GC = foundation.GeneralCommand
# The response each general request expects. A Default Response naming the request's
# command is also accepted as its reply (ZCL8 §2.5.12.2).
RESPONSE_FOR = {
    GC.Read_Attributes: GC.Read_Attributes_rsp,
    GC.Write_Attributes: GC.Write_Attributes_rsp,
    GC.Read_Reporting_Configuration: GC.Read_Reporting_Configuration_rsp,
    GC.Discover_Commands_Received: GC.Discover_Commands_Received_rsp,
    GC.Discover_Commands_Generated: GC.Discover_Commands_Generated_rsp,
    GC.Discover_Attribute_Extended: GC.Discover_Attribute_Extended_rsp,
}

WC = WindowCovering.ServerCommandDefs
# (cluster, command ID) -> zigpy's definition, for every cluster command allowed.
CLUSTER_COMMANDS = {
    (WINDOW_COVERING, d.id): d
    for d in (
        WC.up_open,  # 0x00
        WC.down_close,  # 0x01
        WC.stop,  # 0x02
        WC.go_to_lift_percentage,  # 0x05
    )
} | {
    (
        IDENTIFY,
        Identify.ServerCommandDefs.identify.id,
    ): Identify.ServerCommandDefs.identify,
    (IDENTIFY, Identify.ServerCommandDefs.identify_query.id): (
        Identify.ServerCommandDefs.identify_query
    ),
    (GROUPS, Groups.ServerCommandDefs.get_membership.id): (
        Groups.ServerCommandDefs.get_membership
    ),
    (SCENES, Scenes.ServerCommandDefs.get_scene_membership.id): (
        Scenes.ServerCommandDefs.get_scene_membership
    ),
}
# (cluster, request command ID) -> the cluster-specific response that answers it.
CLUSTER_REPLIES = {
    (IDENTIFY, 0x01): Identify.ClientCommandDefs.identify_query_response,
    (GROUPS, 0x02): Groups.ClientCommandDefs.get_membership_response,
    (SCENES, 0x06): Scenes.ClientCommandDefs.get_scene_membership_response,
}
REPLY_DECODERS = {(cluster, d.id): d for (cluster, _), d in CLUSTER_REPLIES.items()}

# (cluster, attribute) -> (ZCL type ID, python type) for the only writable attributes.
WRITABLE = {
    (WINDOW_COVERING, 0x0010): (0x21, t.uint16_t),  # InstalledOpenLimitLift
    (WINDOW_COVERING, 0x0011): (0x21, t.uint16_t),  # InstalledClosedLimitLift
    (WINDOW_COVERING, 0x0017): (0x18, t.bitmap8),  # Mode
    (IDENTIFY, IDENTIFY_TIME): (0x21, t.uint16_t),  # IdentifyTime
}
# (cluster, attribute) -> ZCL type ID, for the only reporting configuration allowed.
# Window Covering commands the bench never sends, whatever a call says. The radio turns
# Go to Lift Value (0x04), Go to Tilt Value (0x07) and Go to Tilt Percentage (0x08) into
# malformed serial frames that can repeat the previous command or corrupt the next
# (firmware-analysis.md §3 note 3; test plan §3b item 6.2).
NEVER_SEND = frozenset(
    {(WINDOW_COVERING, 0x04), (WINDOW_COVERING, 0x07), (WINDOW_COVERING, 0x08)}
)

ZDO_REQUESTS = {
    "node_descriptor": zdo_t.ZDOCmd.Node_Desc_req,
    "power_descriptor": zdo_t.ZDOCmd.Power_Desc_req,
    "binding_table": zdo_t.ZDOCmd.Mgmt_Bind_req,
}
ZDO_ALLOWED = frozenset(ZDO_REQUESTS.values())

COMMON_FIELDS = frozenset({"command", "ieee", "session", "test_id", "step"})
MOVE_FIELDS = frozenset({"remote_ready", "may_go_down"})
WATCH_FIELDS = frozenset({"watch_for_s", "watch_every_s"})
SESSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}")
TEST_ID_RE = re.compile(r"[A-Z][A-Z0-9-]{1,59}")
STEP_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,23}")
_MISSING = object()


class BenchRefusalError(ValueError):
    """The bench refuses a call or a step; the message says why in plain words."""


class StopEarlyError(Exception):
    """Raised after MAX_CONSECUTIVE_TIMEOUTS unanswered frames in a row."""


# ---------------------------------------------------------------------------------
# Shared core: formatting, decoding and reply matching (as in discovery_user.py).
# ---------------------------------------------------------------------------------


def _hex(value: int | None, width: int = 4) -> str | None:
    return None if value is None else f"0x{int(value):0{width}X}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


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
    if isinstance(value, enum.Flag):
        return int(value)
    if isinstance(value, enum.Enum):
        return value.name
    if isinstance(value, int):
        return int(value)
    if isinstance(value, bytes | bytearray):
        return value.hex(" ")
    as_dict = getattr(value, "as_dict", None)
    if callable(as_dict):  # zigpy structs and command schemas
        return _plain(as_dict())
    if isinstance(value, list | tuple | set | frozenset):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    fields = getattr(value, "__dict__", None)
    if fields:
        return {k: _plain(v) for k, v in fields.items() if not k.startswith("_")}
    return repr(value)


def _cache_snapshot(device) -> dict[str, Any]:
    """Read (never write) what zigpy holds for the shade's server clusters."""
    snapshot = {}
    for cluster_id, cluster in device.endpoints[ENDPOINT_ID].in_clusters.items():
        cache = getattr(cluster, "_attr_cache", None)
        if cache is None:
            continue
        snapshot[_hex(cluster_id)] = {
            "values": {
                f"{_hex(attrid)}/{_hex(manufacturer)}": _plain(item.value)
                for (attrid, manufacturer), item in getattr(cache, "_cache", {}).items()
            },
            "unsupported": sorted(
                f"{_hex(attrid)}/{_hex(manufacturer)}"
                for attrid, manufacturer in getattr(cache, "_unsupported", set())
            ),
        }
    return snapshot


def _attribute_records(records) -> list[dict[str, Any]]:
    out = []
    for record in records:
        item = {"id": _hex(record.attrid), **_status(record.status)}
        if record.status == foundation.Status.SUCCESS and record.value is not None:
            item["datatype"] = _hex(int(record.value.type), 2)
            item["value"] = _plain(record.value.value)
        out.append(item)
    return out


def _reporting_configs(configs) -> list[dict[str, Any]]:
    out = []
    for record in configs:
        config = record.config
        item = {
            **_status(record.status),
            "direction": int(config.direction),
            "id": _hex(config.attrid),
        }
        for field in ("datatype", "min_interval", "max_interval", "reportable_change"):
            if hasattr(config, field):
                item[field] = _plain(getattr(config, field))
        out.append(item)
    return out


def _decode_general(command_id, response, decoded: dict[str, Any]) -> None:
    if command_id == GC.Default_Response:
        decoded["for_command"] = _hex(int(response.command_id), 2)
        decoded.update(_status(response.status))
    elif command_id == GC.Read_Attributes_rsp:
        decoded["records"] = _attribute_records(response.status_records)
    elif command_id == GC.Write_Attributes_rsp:
        decoded["records"] = [
            {
                "id": _hex(getattr(record, "attrid", None)),
                **_status(record.status),
            }
            for record in response.status_records
        ]
    elif command_id == GC.Read_Reporting_Configuration_rsp:
        decoded["records"] = _reporting_configs(response.attribute_configs)
    elif command_id == GC.Report_Attributes:
        decoded["reports"] = [
            {
                "id": _hex(report.attrid),
                "datatype": _hex(int(report.value.type), 2),
                "value": _plain(report.value.value),
            }
            for report in response.attribute_reports
        ]
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
    else:
        decoded["response"] = _plain(response)


def _decode_zcl(cluster_id: int, data: bytes) -> dict[str, Any]:
    """Decode a ZCL frame from the shade from its bytes, without zigpy's handlers."""
    decoded: dict[str, Any] = {"raw": data.hex(" ")}
    try:
        hdr, rest = foundation.ZCLHeader.deserialize(data)
        decoded["frame_control"] = _hex(int(hdr.frame_control), 2)
        decoded["manufacturer"] = _hex(hdr.manufacturer)
        decoded["tsn"] = int(hdr.tsn)
        decoded["command_id"] = _hex(int(hdr.command_id), 2)
        if hdr.frame_control.frame_type != foundation.FrameType.GLOBAL_COMMAND:
            definition = REPLY_DECODERS.get((cluster_id, int(hdr.command_id)))
            if (
                definition is None
                or hdr.frame_control.direction != foundation.Direction.Server_to_Client
            ):
                decoded["command"] = "cluster-specific"
                return decoded
            decoded["command"] = definition.name
            response, _ = definition.schema.deserialize(rest)
            decoded["response"] = _plain(response)
            return decoded
        command_id = foundation.GeneralCommand(hdr.command_id)
        decoded["command"] = command_id.name
        response, _ = foundation.GENERAL_COMMANDS[command_id].schema.deserialize(rest)
        _decode_general(command_id, response, decoded)
    except Exception as err:  # noqa: BLE001 - keep the raw bytes and say why
        decoded["decode_error"] = repr(err)
    return decoded


def _decode_zdo(cluster_id: int, data: bytes) -> dict[str, Any]:
    decoded: dict[str, Any] = {"raw": data.hex(" ")}
    try:
        command = zdo_t.ZDOCmd(cluster_id)
        decoded["command"] = command.name
        names, schema = zdo_t.CLUSTERS[command]
        decoded["tsn"] = data[0]
        args, _ = t.deserialize(data[1:], schema)
        decoded["fields"] = {
            name: _plain(value) for name, value in zip(names, args, strict=False)
        }
    except Exception as err:  # noqa: BLE001
        decoded["decode_error"] = repr(err)
    return decoded


def _is_reply_to(data: bytes, request: dict[str, Any]) -> bool:
    """Whether a ZCL frame on the request's cluster and TSN is that request's reply."""
    try:
        hdr, rest = foundation.ZCLHeader.deserialize(data)
    except Exception:  # noqa: BLE001
        return False
    if hdr.frame_control.direction != foundation.Direction.Server_to_Client:
        return False
    if (
        request["manufacturer"] != WILDCARD_MANUFACTURER
        and hdr.manufacturer != request["manufacturer"]
    ):
        return False
    if hdr.frame_control.frame_type == foundation.FrameType.GLOBAL_COMMAND:
        if hdr.command_id == GC.Default_Response:
            return rest[:1] == bytes([request["command_id"]])
        return request["general"] and hdr.command_id == request["reply_id"]
    return not request["general"] and hdr.command_id == request["reply_id"]


def _summary(frame: dict[str, Any]) -> str:
    """One line, in words, of what came back for a frame."""
    if frame.get("outcome") == "timeout":
        return f"no reply within {frame['timeout_s']} s"
    if frame.get("outcome") == "error":
        return f"send failed: {frame.get('error')}"
    reply = frame.get("reply") or {}
    if "decode_error" in reply:
        return f"reply not decoded: {reply['raw']}"
    if reply.get("status") and "for_command" in reply:
        return f"Default Response {reply['status']} ({reply['status_code']})"
    if "records" in reply:
        parts = []
        for record in reply["records"]:
            if "value" in record:
                parts.append(f"{record['id']} = {record['value']}")
            elif "min_interval" in record:
                parts.append(
                    f"{record['id']} {record['status']}: min {record['min_interval']} s,"
                    f" max {record['max_interval']} s,"
                    f" change {record.get('reportable_change')}"
                )
            else:
                parts.append(f"{record['id'] or 'all'} {record['status']}")
        return "; ".join(parts)
    if "command_ids" in reply or "attributes" in reply:
        items = reply.get("command_ids", [a["id"] for a in reply.get("attributes", [])])
        complete = "complete" if reply["discovery_complete"] else "more to ask for"
        return f"{', '.join(items) or 'none'} ({complete})"
    if "fields" in reply:
        return f"{reply['command']}: {json.dumps(reply['fields'])}"
    if "response" in reply:
        return f"{reply['command']}: {json.dumps(reply['response'])}"
    return reply.get("command", "reply")


def _record_value(frame: dict[str, Any]) -> Any:
    """Return the value of a one-attribute read, or None if it returned none."""
    records = (frame.get("reply") or {}).get("records") or []
    if len(records) == 1 and records[0].get("status") == "SUCCESS":
        return records[0].get("value")
    return None


def _yaml_value(value: Any, key: str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and key in ("cluster", "attribute", "value"):
        return _hex(value, 4 if key != "value" or value > 0xFF else 2)
    if isinstance(value, int | float):
        return str(value)
    return f'"{value}"'


def _action_yaml(command: str, fields: dict[str, Any]) -> str:
    """Write the Developer tools YAML for a bench call."""
    lines = [
        "action: zha_toolkit.execute",
        "data:",
        f"  command: {command}",
        f'  ieee: "{OFFICE_SHADE}"',
    ]
    lines += [f"  {key}: {_yaml_value(value, key)}" for key, value in fields.items()]
    return "\n".join(lines)


def _software() -> dict[str, str | None]:
    versions = {}
    for name in ("zigpy", "bellows", "zha", "zha-quirks"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


# ---------------------------------------------------------------------------------
# Call fields
# ---------------------------------------------------------------------------------


class Fields:
    """The service call's own fields, checked against what the action accepts."""

    def __init__(self, service, allowed: frozenset[str]) -> None:
        """Refuse any field the action does not know (a typo, usually)."""
        self.data = dict(getattr(service, "data", None) or {})
        unknown = sorted(set(self.data) - COMMON_FIELDS - allowed)
        if unknown:
            raise BenchRefusalError(
                f"unknown field(s) {', '.join(unknown)}: check the spelling against "
                "the run sheet. Nothing was sent."
            )
        self.used: dict[str, Any] = {}

    def _get(self, name: str, default: Any) -> Any:
        if name not in self.data:
            if default is _MISSING:
                raise BenchRefusalError(f"`{name}` is required. Nothing was sent.")
            return default
        return self.data[name]

    @staticmethod
    def _number(name: str, value: Any, low: int, high: int) -> int:
        try:
            number = value if isinstance(value, int) else int(str(value), 0)
        except ValueError:
            number = None
        if isinstance(value, bool) or number is None or not low <= number <= high:
            raise BenchRefusalError(
                f"`{name}` must be a whole number from {low} to {high} "
                f"({_hex(low)}-{_hex(high)}), not {value!r}. Nothing was sent."
            )
        return number

    def integer(
        self, name: str, *, low: int, high: int, default: Any = _MISSING
    ) -> int | None:
        """Return an integer field, given as a number or as text such as "0x0102"."""
        value = self._get(name, default)
        if value is None:
            return None
        number = self._number(name, value, low, high)
        if name in self.data:
            self.used[name] = number
        return number

    def integers(self, name: str, *, low: int, high: int) -> list[int]:
        """Return a list of 1 to 16 integers (a single number is a list of one)."""
        value = self._get(name, _MISSING)
        items = value if isinstance(value, list) else [value]
        if not 1 <= len(items) <= 16:
            raise BenchRefusalError(f"`{name}` must list 1 to 16 numbers.")
        numbers = [self._number(name, item, low, high) for item in items]
        self.used[name] = numbers
        return numbers

    def seconds(
        self, name: str, *, low: float, high: float, default: Any = _MISSING
    ) -> float | None:
        """Return a time in seconds."""
        value = self._get(name, default)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise BenchRefusalError(f"`{name}` must be a number of seconds.")
        if not low <= value <= high:
            raise BenchRefusalError(
                f"`{name}` must be from {low} to {high} seconds, not {value}."
            )
        if name in self.data:
            self.used[name] = value
        return float(value)

    def flag(self, name: str) -> bool | None:
        """Return a true/false field; absent is None."""
        value = self.data.get(name)
        if value is None:
            return None
        if not isinstance(value, bool):
            raise BenchRefusalError(f"`{name}` must be true or false, not {value!r}.")
        self.used[name] = value
        return value

    def choice(self, name: str, choices, default: Any = _MISSING) -> str:
        """One of a fixed set of words."""
        value = self._get(name, default)
        if value not in choices:
            raise BenchRefusalError(
                f"`{name}` must be one of {', '.join(choices)}, not {value!r}."
            )
        if name in self.data:
            self.used[name] = value
        return value

    def text(self, name: str, pattern: re.Pattern, default: Any = _MISSING) -> str:
        """Return a short word, such as the session name."""
        value = self._get(name, default)
        if value is None:
            return None
        if not isinstance(value, str) or not pattern.fullmatch(value):
            raise BenchRefusalError(
                f"`{name}` {value!r} is not valid (letters, digits and dashes)."
            )
        return value


def _require_moves(fields: Fields, *, may_go_down: bool, what: str) -> None:
    """Refuse a moving command unless the call says the owner is ready for it."""
    if fields.flag("remote_ready") is not True:
        raise BenchRefusalError(
            f"{what} can move the shade. Put the shade mid-travel with the remote, "
            "hold the remote ready to press Stop, and add `remote_ready: true`. "
            "Nothing was sent."
        )
    ok_down = fields.flag("may_go_down")
    if may_go_down and ok_down is not True:
        raise BenchRefusalError(
            f"{what} could run the shade down past its stop. Be ready to press Stop "
            "on the remote within 2-3 s and add `may_go_down: true`. Nothing was sent."
        )


def _require_confirm(fields: Fields, what: str) -> None:
    if fields.flag("confirm") is not True:
        raise BenchRefusalError(
            f"{what} changes a setting on the shade. Add `confirm: true` once the run "
            "sheet's undo is at hand. Nothing was sent."
        )


# ---------------------------------------------------------------------------------
# The bench: one call, its frames, and the session file
# ---------------------------------------------------------------------------------


class Bench:
    """One bench call against the Office Shade, appended to the session file."""

    def __init__(self, app, device, session: str, call: dict[str, Any]) -> None:
        """Hold the call's state; nothing is sent until a frame method runs."""
        self.app = app
        self.device = device
        self.endpoint = device.endpoints[ENDPOINT_ID]
        self.session = session
        self.path = OUTPUT_DIR / f"smartwings_bench_{self.session}.json"
        self.doc: dict[str, Any] = {}
        self.call: dict[str, Any] = {
            **call,
            "started": _now(),
            "finished": None,
            "outcome": "running",
            "frames": [],
            "unmatched_frames": [],
            "result": {},
        }
        self.result = self.call["result"]
        self.consecutive_timeouts = 0
        self._started = time.monotonic()
        self._waiters: dict[tuple, tuple[asyncio.Future, dict[str, Any]]] = {}
        # (zcl, cluster, TSN) -> (frame number, what its reply had to match, when the
        # first reply came)
        self._answered: dict[tuple, tuple[int, dict[str, Any], float]] = {}

    # zigpy calls this for every received packet, before routing it to the device
    # (application.py:1373-1381). It only records; it never answers the shade.
    def handle_message(self, device, profile, cluster, src_ep, dst_ep, message):
        """Hand a reply from the Office Shade to the frame waiting for it."""
        if device is not self.device:
            return
        data = bytes(message)
        received = (time.monotonic(), _now())
        if src_ep == ZDO_ENDPOINT and profile == 0:
            key = ("zdo", cluster, data[0] if data else None)
            entry = self._waiters.get(key)
            if entry is not None and not entry[0].done():
                entry[0].set_result((data, *received))
                return
            decoded = _decode_zdo(cluster, data)
        else:
            try:
                hdr, _ = foundation.ZCLHeader.deserialize(data)
            except Exception:  # noqa: BLE001
                hdr = None
            entry = (
                None if hdr is None else self._waiters.get(("zcl", cluster, hdr.tsn))
            )
            if (
                entry is not None
                and src_ep == ENDPOINT_ID
                and not entry[0].done()
                and _is_reply_to(data, entry[1])
            ):
                entry[0].set_result((data, *received))
                # Recorded here, not when the bench resumes: the shade's second reply
                # can arrive a few ms later, before the waiting coroutine runs again.
                self._answered["zcl", cluster, hdr.tsn] = (
                    entry[1]["frame_n"],
                    entry[1],
                    received[0],
                )
                return
            decoded = _decode_zcl(cluster, data)
            answered = (
                None if hdr is None else self._answered.get(("zcl", cluster, hdr.tsn))
            )
            if (
                answered is not None
                and received[0] - answered[2] <= SECOND_REPLY_WINDOW_S
                and _is_reply_to(data, answered[1])
            ):
                decoded["second_reply_to_frame"] = answered[0]
        self.call["unmatched_frames"].append(
            {
                "time": received[1],
                "t_s": round(received[0] - self._started, 3),
                "cluster": _hex(cluster),
                "src_ep": src_ep,
                **decoded,
            }
        )

    async def __aenter__(self) -> Bench:
        """Load the session file, claim the bench and start listening."""
        # Check and claim with no await in between, so two calls cannot both pass.
        if getattr(self.app, BUSY_FLAG, False):
            raise BenchRefusalError(
                "another bench action is still running; wait for it to finish. "
                "Nothing was sent."
            )
        setattr(self.app, BUSY_FLAG, True)
        try:
            self.doc = await self._load()
        except BaseException:
            setattr(self.app, BUSY_FLAG, False)
            raise
        self.call["n"] = len(self.doc["calls"]) + 1
        self.call["software"] = _software()
        self.doc["calls"].append(self.call)
        self.app.add_listener(self)
        LOGGER.warning(
            "bench %s call %d: %s (%s) on %s nwk=0x%04X; log: %s",
            self.session,
            self.call["n"],
            self.call["action"],
            self.call["test_id"],
            OFFICE_SHADE,
            self.device.nwk,
            self.path,
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        """Stop listening, record how the call ended, save, then release the bench."""
        self.app.remove_listener(self)
        if exc_type is StopEarlyError:
            self.call["outcome"] = "stopped early"
            self.call["message"] = str(exc)
        elif exc_type is BenchRefusalError:
            self.call["outcome"] = "refused"
            self.call["message"] = str(exc)
        elif exc is not None:
            self.call["outcome"] = "error"
            self.call["message"] = repr(exc)
        else:
            self.call["outcome"] = "done"
        self.call["finished"] = _now()
        # The final save runs as its own task, shielded from cancellation, and the
        # bench is released only when that write has finished (or failed): no other
        # call can start while the session file is still being written, even if this
        # call is cancelled meanwhile.
        save = asyncio.ensure_future(self._save())
        save.add_done_callback(self._release)
        await asyncio.shield(save)
        return exc_type is StopEarlyError

    def _release(self, save: asyncio.Future) -> None:
        setattr(self.app, BUSY_FLAG, False)
        if not save.cancelled() and save.exception() is not None:
            LOGGER.warning("bench: final save failed: %r", save.exception())

    async def _load(self) -> dict[str, Any]:
        def read() -> str | None:
            try:
                return self.path.read_text(encoding="utf-8")
            except FileNotFoundError:
                return None

        text = await asyncio.get_running_loop().run_in_executor(None, read)
        if text is None:
            return {
                "bench": "ha-smartwings test bench (issue #42)",
                "bench_version": BENCH_VERSION,
                "session": self.session,
                "ieee": OFFICE_SHADE,
                "endpoint": ENDPOINT_ID,
                "created": _now(),
                "zigpy_cache_at_start": _cache_snapshot(self.device),
                "calls": [],
            }
        try:
            doc = json.loads(text)
            if not isinstance(doc.get("calls"), list):
                raise TypeError("no calls list")
            found = (doc.get("bench_version"), doc.get("session"), doc.get("ieee"))
            if found != (BENCH_VERSION, self.session, OFFICE_SHADE):
                raise TypeError(
                    f"it holds bench version {found[0]}, session {found[1]}, shade "
                    f"{found[2]}; this call is bench version {BENCH_VERSION}, session "
                    f"{self.session}, shade {OFFICE_SHADE}"
                )
        except (ValueError, TypeError) as err:
            raise BenchRefusalError(
                f"{self.path} is not a bench session file ({err}); move it aside or "
                "use another session name. Nothing was sent."
            ) from err
        return doc

    async def _save(self) -> None:
        text = json.dumps(self.doc, indent=2)
        path = self.path

        def write() -> None:
            partial = path.with_name(path.name + ".partial")
            partial.write_text(text, encoding="utf-8")
            os.replace(partial, path)

        await asyncio.get_running_loop().run_in_executor(None, write)

    def _frame_number(self) -> int:
        return sum(len(call["frames"]) for call in self.doc["calls"]) + 1

    def _last_sent(self) -> datetime | None:
        for call in reversed(self.doc["calls"]):
            if call["frames"]:
                return datetime.fromisoformat(call["frames"][-1]["time_sent"])
        return None

    def _cluster(self, cluster_id: int) -> Cluster:
        if cluster_id not in SERVER_CLUSTERS:
            raise BenchRefusalError(
                f"cluster {_hex(cluster_id)} is not one the bench may address "
                f"({', '.join(_hex(c) for c in SERVER_CLUSTERS)}). Nothing was sent."
            )
        # A bare zigpy Cluster, used only to build and send the frame: no quirk code
        # runs, and the endpoint is unchanged.
        cluster = Cluster(self.endpoint, is_server=True)
        cluster.cluster_id = cluster_id
        return cluster

    async def zcl(
        self,
        cluster_id: int,
        command_id: int,
        args: tuple = (),
        *,
        general: bool,
        manufacturer: int | None = None,
        disable_default_response: bool | None = None,
        ask_for_ack: bool | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        """Send one allowed ZCL frame and wait for its reply."""
        if not general and (cluster_id, command_id) in NEVER_SEND:
            _never_send(command_id)
        cluster = self._cluster(cluster_id)
        if general:
            if command_id not in RESPONSE_FOR:
                raise BenchRefusalError(f"general command {command_id!r} not allowed")
            command_id = foundation.GeneralCommand(command_id)
            schema = foundation.GENERAL_COMMANDS[command_id].schema
            name = command_id.name
            reply_id = int(RESPONSE_FOR[command_id])
        else:
            definition = CLUSTER_COMMANDS.get((cluster_id, command_id))
            if definition is None:
                raise BenchRefusalError(
                    f"command {_hex(command_id, 2)} on {_hex(cluster_id)} not allowed"
                )
            schema = definition.schema
            name = definition.name
            reply = CLUSTER_REPLIES.get((cluster_id, command_id))
            reply_id = None if reply is None else reply.id
        # zigpy's default for a server cluster is a clear bit (zcl/__init__.py:824-825).
        ddr = bool(disable_default_response)
        tsn = self.device.get_sequence()
        hdr = foundation.ZCLHeader(
            frame_control=foundation.FrameControl(
                frame_type=(
                    foundation.FrameType.GLOBAL_COMMAND
                    if general
                    else foundation.FrameType.CLUSTER_COMMAND
                ),
                is_manufacturer_specific=manufacturer is not None,
                direction=foundation.Direction.Client_to_Server,
                disable_default_response=ddr,
                reserved=0b000,
            ),
            manufacturer=manufacturer,
            tsn=tsn,
            command_id=command_id,
        )
        sent = hdr.serialize() + schema(*args).serialize()
        frame = {
            "kind": "zcl general" if general else "zcl cluster command",
            "cluster": _hex(cluster_id),
            "command": name,
            "command_id": _hex(int(command_id), 2),
            "manufacturer": _hex(manufacturer),
            "args": _plain(list(args)),
            "disable_default_response": ddr,
            "ask_for_ack": ask_for_ack,
        }

        def send():
            return cluster.request(
                general,
                command_id,
                schema,
                *args,
                manufacturer=manufacturer,
                expect_reply=True,
                retries=0,
                tsn=tsn,
                disable_default_response=disable_default_response,
                ask_for_ack=ask_for_ack,
            )

        expect = {
            "general": general,
            "manufacturer": manufacturer,
            "command_id": int(command_id),
            "reply_id": reply_id,
        }
        return await self._exchange(
            ("zcl", cluster_id, tsn), expect, frame, tsn, sent, send, label
        )

    async def zdo(self, command, *args, label: str | None = None) -> dict[str, Any]:
        """Send one allowed ZDO request and wait for its response."""
        if command not in ZDO_ALLOWED:
            raise BenchRefusalError(f"ZDO request {command!r} not allowed")
        tsn = self.device.get_sequence()
        sent = t.uint8_t(tsn).serialize() + t.serialize(
            args, zdo_t.CLUSTERS[command][1]
        )
        frame = {
            "kind": "zdo",
            "cluster": _hex(int(command)),
            "command": command.name,
            "args": _plain(list(args)),
        }

        def send():
            # As ZDO.request() does (zdo/__init__.py:53-84), with our TSN and retries=0.
            return self.device.request(
                profile=0x0000,
                cluster=command,
                src_ep=ZDO_ENDPOINT,
                dst_ep=ZDO_ENDPOINT,
                sequence=tsn,
                data=sent,
                expect_reply=True,
                retries=0,
            )

        return await self._exchange(
            ("zdo", int(command) | 0x8000, tsn), {}, frame, tsn, sent, send, label
        )

    async def _exchange(self, key, expect, frame, tsn, sent, send, label):
        last = self._last_sent()
        loop = asyncio.get_running_loop()
        waiter = loop.create_future()
        number = self._frame_number()
        self._waiters[key] = (waiter, {**expect, "frame_n": number})
        now = datetime.now(UTC)
        frame = {
            "n": number,
            "label": label,
            "time_sent": now.isoformat(),
            "t_s": round(time.monotonic() - self._started, 3),
            "idle_before_s": (
                None if last is None else round((now - last).total_seconds(), 1)
            ),
            **frame,
            "tsn": tsn,
            "bytes_sent": sent.hex(" "),
            "timeout_s": FRAME_TIMEOUT,
            "outcome": "sending",
        }
        self.call["frames"].append(frame)
        # Saved before the send starts, so an interrupted call still shows the frame.
        await self._save()
        frame["time_sent"] = _now()
        frame["t_s"] = round(time.monotonic() - self._started, 3)
        LOGGER.debug("bench frame %d: %s", frame["n"], frame)
        started = time.monotonic()
        # retries=0: zigpy otherwise re-sends after a timeout or delivery error
        # (device.py:916-917, :959, :1003-1013).
        request = asyncio.ensure_future(send())
        try:
            # zigpy waits up to 28 s for an end device (device.py:924-926), so the
            # 5 s limit is enforced here.
            await asyncio.wait(
                {waiter, request},
                timeout=FRAME_TIMEOUT,
                return_when=asyncio.FIRST_COMPLETED,
            )
            failed = request.done() and not request.cancelled() and request.exception()
            if not waiter.done() and request.done():
                # zigpy may have taken a colliding frame of the shade's own as the
                # reply, or failed to parse one; keep waiting for the real reply.
                if failed:
                    frame["zigpy_error"] = repr(failed)
                else:
                    frame["zigpy_matched"] = repr(request.result())
                remaining = FRAME_TIMEOUT - (time.monotonic() - started)
                if remaining > 0:
                    await asyncio.wait({waiter}, timeout=remaining)
            if waiter.done():
                data, received, received_at = waiter.result()
                frame["outcome"] = "reply"
                frame["time_reply"] = received_at
                frame["latency_s"] = round(received - started, 3)
                frame["reply"] = (
                    _decode_zdo(key[1], data)
                    if key[0] == "zdo"
                    else _decode_zcl(key[1], data)
                )
            elif failed:
                frame["outcome"] = "error"
                frame["error"] = repr(request.exception())
            else:
                frame["outcome"] = "timeout"
            frame["summary"] = _summary(frame)
        finally:
            self._waiters.pop(key, None)
            if not request.done():
                request.cancel()
            await asyncio.wait({request})
            if not request.cancelled():
                request.exception()  # retrieved, so asyncio does not log it
            frame["elapsed_s"] = round(time.monotonic() - started, 3)
            await self._save()
        if frame["outcome"] == "reply":
            self.consecutive_timeouts = 0
        else:
            self.consecutive_timeouts += 1
            if self.consecutive_timeouts >= MAX_CONSECUTIVE_TIMEOUTS:
                raise StopEarlyError(
                    f"{self.consecutive_timeouts} frames in a row got no reply "
                    f"(last: frame {frame['n']}, {frame['outcome']}); the call stopped"
                )
        return frame

    # Building blocks used by the actions --------------------------------------

    async def read(self, cluster_id, attrid, manufacturer=None, label=None):
        """Read one attribute, uncached: one Read Attributes frame."""
        return await self.zcl(
            cluster_id,
            GC.Read_Attributes,
            ([t.uint16_t(attrid)],),
            general=True,
            manufacturer=manufacturer,
            label=label,
        )

    async def command(self, cluster_id, command_id, *args, label=None, **kwargs):
        """Send one cluster command."""
        return await self.zcl(
            cluster_id, command_id, args, general=False, label=label, **kwargs
        )

    async def wait(self, seconds: float) -> None:
        """Wait, still logging whatever the shade sends meanwhile."""
        if seconds > 0:
            await asyncio.sleep(seconds)

    async def watch(self, for_s: float | None, every_s: float | None) -> None:
        """Stay listening for `for_s`; read 0x0102/0x0008 every `every_s` if given."""
        if not for_s:
            return
        end = time.monotonic() + for_s
        positions = self.result.setdefault("positions", [])
        if every_s is None:
            await self.wait(for_s)
        else:
            next_at = time.monotonic()
            while (now := time.monotonic()) < end:
                if next_at > now:
                    await self.wait(min(next_at, end) - now)
                    if time.monotonic() >= end:
                        break
                frame = await self.read(WINDOW_COVERING, LIFT_PERCENTAGE, label="watch")
                positions.append(
                    {"t_s": frame["t_s"], "lift": _record_value(frame)}
                    | (
                        {}
                        if frame["outcome"] == "reply"
                        else {"no_value": frame["summary"]}
                    )
                )
                next_at = max(next_at + every_s, time.monotonic())


# ---------------------------------------------------------------------------------
# The actions
# ---------------------------------------------------------------------------------


def _device(app, ieee):
    if str(ieee) not in ALLOWED_IEEES:
        raise BenchRefusalError(
            f"bench: Office Shade {OFFICE_SHADE} only, got {ieee}. Nothing was sent."
        )
    return app.get_device(ieee=t.EUI64.convert(str(ieee)))


def _open(app, ieee, service, action: str, allowed=frozenset()):
    """Check the device and the call's common fields; return (fields, bench)."""
    device = _device(app, ieee)
    fields = Fields(service, frozenset(allowed))
    call = {
        "action": action,
        "test_id": fields.text("test_id", TEST_ID_RE),
        "step": fields.text("step", STEP_RE, default=None),
        # Filled in place as the action reads its fields.
        "fields": fields.used,
    }
    return fields, Bench(app, device, fields.text("session", SESSION_RE), call)


def _respond(bench: Bench, event_data: dict[str, Any]) -> None:
    call = bench.call
    event_data["bench"] = {
        "session": bench.session,
        "call": call["n"],
        "action": call["action"],
        "test_id": call["test_id"],
        "step": call["step"],
        "outcome": call["outcome"],
        "message": call.get("message"),
        "frames": [
            {
                "n": f["n"],
                "label": f["label"],
                "command": f"{f['cluster']} {f['command']}",
                "time_sent": f["time_sent"],
                "idle_before_s": f["idle_before_s"],
                "outcome": f.get("outcome"),
                "latency_s": f.get("latency_s"),
                "answer": f.get("summary"),
            }
            for f in call["frames"]
        ],
        "frames_from_shade_unasked": len(call["unmatched_frames"]),
        # The shade's second reply to a frame (SUCCESS, then 0x81), in words.
        "second_replies": [
            f"frame {u['second_reply_to_frame']}: "
            + (
                f"Default Response {u['status']} ({u['status_code']})"
                if u.get("status")
                else u.get("command", "reply")
            )
            for u in call["unmatched_frames"]
            if "second_reply_to_frame" in u
        ],
        # Report Attributes the shade sent during the call (REPORT-NONE-OBSERVED).
        "reports": [
            {"t_s": u["t_s"], "cluster": u["cluster"], "reports": u.get("reports")}
            for u in call["unmatched_frames"]
            if u.get("command") == "Report_Attributes"
        ],
        "result": call["result"],
        "log": str(bench.path),
    }


async def _run(bench: Bench, event_data, body) -> None:
    """Run an action's body inside the bench, then fill the action's response."""
    try:
        async with bench:
            await body()
            await bench.wait(LINGER_S)
    finally:
        if bench.call["outcome"] != "running":
            _respond(bench, event_data)
    if bench.call["outcome"] == "stopped early":
        LOGGER.warning("bench: %s", bench.call["message"])


def _watch_fields(fields: Fields) -> tuple[float | None, float | None]:
    for_s = fields.seconds("watch_for_s", low=1, high=MAX_WAIT_S, default=None)
    every_s = fields.seconds("watch_every_s", low=1, high=60, default=None)
    if every_s is not None and for_s is None:
        raise BenchRefusalError("`watch_every_s` needs `watch_for_s`.")
    return for_s, every_s


async def _simple_move(app, ieee, service, event_data, action, command_id, what):
    fields, bench = _open(app, ieee, service, action, MOVE_FIELDS | WATCH_FIELDS)
    _require_moves(fields, may_go_down=True, what=what)
    for_s, every_s = _watch_fields(fields)

    async def body():
        await bench.command(WINDOW_COVERING, command_id, label=action)
        await bench.watch(for_s, every_s)

    await _run(bench, event_data, body)


# zha_toolkit calls every user_* handler with eight positional arguments (PLR0917).
async def user_bench_up_open(
    app, listener, ieee, cmd, data, service, params, event_data
):
    """Raw Up/Open, 0x0102 command 0x00, no payload. Moves; may go down."""
    await _simple_move(
        app, ieee, service, event_data, "up_open", 0x00, "Up/Open (0x00)"
    )


async def user_bench_down_close(
    app, listener, ieee, cmd, data, service, params, event_data
):
    """Raw Down/Close, 0x0102 command 0x01, no payload. Moves down."""
    await _simple_move(
        app, ieee, service, event_data, "down_close", 0x01, "Down/Close (0x01)"
    )


async def user_bench_stop(app, listener, ieee, cmd, data, service, params, event_data):
    """Stop, 0x0102 command 0x02, with optional frame variants."""
    fields, bench = _open(
        app,
        ieee,
        service,
        "stop",
        {"disable_default_response", "ask_for_ack", "manufacturer"},
    )
    ddr = fields.flag("disable_default_response")
    ack = fields.flag("ask_for_ack")
    manufacturer = fields.integer("manufacturer", low=0, high=0xFFFF, default=None)

    async def body():
        await bench.command(
            WINDOW_COVERING,
            0x02,
            label="stop",
            manufacturer=manufacturer,
            disable_default_response=ddr,
            ask_for_ack=ack,
        )

    await _run(bench, event_data, body)


def _goto_value(fields: Fields, name: str) -> int:
    return fields.integer(name, low=0, high=0xFF)


async def user_bench_goto(app, listener, ieee, cmd, data, service, params, event_data):
    """Go to Lift Percentage (0x05): optional idle or read first, optional watch."""
    fields, bench = _open(
        app,
        ieee,
        service,
        "goto",
        MOVE_FIELDS | WATCH_FIELDS | {"value", "idle_s", "read_before_s"},
    )
    value = _goto_value(fields, "value")
    # Every move needs `may_go_down: true` but a go-to to fully open (lift 0): the
    # direction can be wrong (a reversed motor) and the target can be misjudged.
    _require_moves(fields, may_go_down=value != 0, what=f"A go-to to lift {value}")
    idle_s = fields.seconds("idle_s", low=0, high=MAX_WAIT_S, default=None)
    read_before_s = fields.seconds("read_before_s", low=0, high=60, default=None)
    for_s, every_s = _watch_fields(fields)

    async def body():
        if idle_s:
            await bench.wait(idle_s)
        if read_before_s is not None:
            started = time.monotonic()
            await bench.read(WINDOW_COVERING, LIFT_PERCENTAGE, label="read before")
            await bench.wait(read_before_s - (time.monotonic() - started))
        await bench.command(WINDOW_COVERING, 0x05, t.uint8_t(value), label="goto")
        await bench.watch(for_s, every_s)

    await _run(bench, event_data, body)


def _never_send(command_id: int) -> None:
    raise BenchRefusalError(
        f"Window Covering command {_hex(command_id, 2)} is never sent: the shade's radio "
        "turns it into a malformed motor frame (firmware analysis §3 note 3; test plan "
        "§3b item 6.2). Nothing was sent."
    )


async def user_bench_goto_lift_value(
    app, listener, ieee, cmd, data, service, params, event_data
):
    """Refuse: Go to Lift Value (0x04) is never sent."""
    _never_send(0x04)


async def user_bench_tilt_value(
    app, listener, ieee, cmd, data, service, params, event_data
):
    """Refuse: Go to Tilt Value (0x07) is never sent."""
    _never_send(0x07)


async def user_bench_tilt_percentage(
    app, listener, ieee, cmd, data, service, params, event_data
):
    """Refuse: Go to Tilt Percentage (0x08) is never sent."""
    _never_send(0x08)


async def user_bench_goto_then_stop(
    app, listener, ieee, cmd, data, service, params, event_data
):
    """Go-to, then Stop `stop_after_s` after the go-to's reply (or its timeout)."""
    fields, bench = _open(
        app,
        ieee,
        service,
        "goto_then_stop",
        MOVE_FIELDS | WATCH_FIELDS | {"value", "stop_after_s"},
    )
    _require_moves(fields, may_go_down=True, what="A go-to")
    value = _goto_value(fields, "value")
    stop_after_s = fields.seconds("stop_after_s", low=0, high=60)
    for_s, every_s = _watch_fields(fields)

    async def body():
        await bench.command(WINDOW_COVERING, 0x05, t.uint8_t(value), label="goto")
        await bench.wait(stop_after_s)
        await bench.command(WINDOW_COVERING, 0x02, label="stop")
        await bench.watch(for_s, every_s)

    await _run(bench, event_data, body)


async def user_bench_goto_twice(
    app, listener, ieee, cmd, data, service, params, event_data
):
    """Send the same go-to twice, the second `gap_s` after the first was sent."""
    fields, bench = _open(
        app,
        ieee,
        service,
        "goto_twice",
        MOVE_FIELDS | WATCH_FIELDS | {"value", "gap_s"},
    )
    _require_moves(fields, may_go_down=True, what="A go-to")
    value = _goto_value(fields, "value")
    gap_s = fields.seconds("gap_s", low=0, high=60, default=2.5)
    for_s, every_s = _watch_fields(fields)

    async def body():
        started = time.monotonic()
        await bench.command(WINDOW_COVERING, 0x05, t.uint8_t(value), label="goto 1")
        # One frame in flight: if the reply took longer than the gap, send now.
        await bench.wait(gap_s - (time.monotonic() - started))
        await bench.command(WINDOW_COVERING, 0x05, t.uint8_t(value), label="goto 2")
        await bench.watch(for_s, every_s)

    await _run(bench, event_data, body)


async def user_bench_goto_then_goto(
    app, listener, ieee, cmd, data, service, params, event_data
):
    """Go-to `value`, then `after_s` after its reply a second go-to `then_value`."""
    fields, bench = _open(
        app,
        ieee,
        service,
        "goto_then_goto",
        MOVE_FIELDS | WATCH_FIELDS | {"value", "then_value", "after_s"},
    )
    _require_moves(fields, may_go_down=True, what="A go-to")
    value = _goto_value(fields, "value")
    then_value = _goto_value(fields, "then_value")
    after_s = fields.seconds("after_s", low=0, high=60)
    for_s, every_s = _watch_fields(fields)

    async def body():
        await bench.command(WINDOW_COVERING, 0x05, t.uint8_t(value), label="goto 1")
        await bench.wait(after_s)
        await bench.command(
            WINDOW_COVERING, 0x05, t.uint8_t(then_value), label="goto 2"
        )
        await bench.watch(for_s, every_s)

    await _run(bench, event_data, body)


async def user_bench_identify(
    app, listener, ieee, cmd, data, service, params, event_data
):
    """Identify for `identify_time` s, Identify Query, then read IdentifyTime."""
    fields, bench = _open(
        app, ieee, service, "identify", MOVE_FIELDS | {"identify_time", "query_after_s"}
    )
    _require_moves(fields, may_go_down=True, what="Identify")
    identify_time = fields.integer("identify_time", low=0, high=30, default=5)
    query_after_s = fields.seconds("query_after_s", low=0, high=30, default=1)

    async def body():
        await bench.command(IDENTIFY, 0x00, t.uint16_t(identify_time), label="identify")
        await bench.wait(query_after_s)
        await bench.command(IDENTIFY, 0x01, label="identify query")
        await bench.read(IDENTIFY, IDENTIFY_TIME, label="IdentifyTime")

    await _run(bench, event_data, body)


async def user_bench_read(app, listener, ieee, cmd, data, service, params, event_data):
    """Read attributes uncached, one per frame; optional idle before each, trials."""
    fields, bench = _open(
        app,
        ieee,
        service,
        "read",
        {"cluster", "attributes", "manufacturer", "idle_s", "trials"},
    )
    cluster_id = fields.integer("cluster", low=0, high=0xFFFF)
    attributes = fields.integers("attributes", low=0, high=0xFFFF)
    manufacturer = fields.integer("manufacturer", low=0, high=0xFFFF, default=None)
    idle_s = fields.seconds("idle_s", low=0, high=MAX_WAIT_S, default=None)
    trials = fields.integer("trials", low=1, high=5, default=1)
    bench._cluster(cluster_id)  # refuse an unknown cluster before anything is sent

    async def body():
        values = bench.result["values"] = []
        for trial in range(1, trials + 1):
            for attrid in attributes:
                if idle_s:
                    await bench.wait(idle_s)
                frame = await bench.read(
                    cluster_id, attrid, manufacturer, label=f"trial {trial}"
                )
                values.append(
                    {
                        "trial": trial,
                        "attribute": _hex(attrid),
                        "idle_before_s": frame["idle_before_s"],
                        "latency_s": frame.get("latency_s"),
                        "answer": frame["summary"],
                    }
                )

    await _run(bench, event_data, body)


async def user_bench_write(app, listener, ieee, cmd, data, service, params, event_data):
    """Guarded write: read the value before, write, read back; record the undo."""
    fields, bench = _open(
        app,
        ieee,
        service,
        "write",
        {"cluster", "attribute", "value", "confirm", "expect_before"},
    )
    cluster_id = fields.integer("cluster", low=0, high=0xFFFF)
    attrid = fields.integer("attribute", low=0, high=0xFFFF)
    if (cluster_id, attrid) not in WRITABLE:
        raise BenchRefusalError(
            f"{_hex(cluster_id)}/{_hex(attrid)} is not writable on the bench (only "
            + ", ".join(f"{_hex(c)}/{_hex(a)}" for c, a in WRITABLE)
            + "). Nothing was sent."
        )
    type_id, python_type = WRITABLE[cluster_id, attrid]
    high = 0xFF if type_id == 0x18 else 0xFFFF
    value = fields.integer("value", low=0, high=high)
    expect_before = fields.integer("expect_before", low=0, high=high, default=None)
    _require_confirm(fields, f"Writing {_hex(cluster_id)}/{_hex(attrid)}")

    async def body():
        result = bench.result
        before = _record_value(await bench.read(cluster_id, attrid, label="before"))
        result["before"] = before
        if before is None:
            raise BenchRefusalError(
                "the value before could not be read, so there would be no undo; "
                "nothing was written"
            )
        if expect_before is not None and before != expect_before:
            raise BenchRefusalError(
                f"the shade reads {before} ({_hex(before, 2)}), not the expected "
                f"{expect_before}; nothing was written"
            )
        write = await bench.zcl(
            cluster_id,
            GC.Write_Attributes,
            (
                [
                    foundation.Attribute(
                        attrid,
                        foundation.TypeValue(type=type_id, value=python_type(value)),
                    )
                ],
            ),
            general=True,
            label="write",
        )
        result["written"] = value
        result["write_answer"] = write["summary"]
        after = _record_value(await bench.read(cluster_id, attrid, label="read back"))
        result["after"] = after
        result["undo_needed"] = after != before
        undo = {
            "session": bench.session,
            "test_id": bench.call["test_id"],
            "step": f"{bench.call['step'] or 'write'}-undo"[:24],
            "cluster": cluster_id,
            "attribute": attrid,
            "value": before,
            "confirm": True,
        }
        result["undo"] = _action_yaml("user_bench_write", undo)

    await _run(bench, event_data, body)


async def user_bench_read_reporting(
    app, listener, ieee, cmd, data, service, params, event_data
):
    """Read Reporting Configuration (0x08), one attribute per frame."""
    fields, bench = _open(
        app, ieee, service, "read_reporting", {"cluster", "attributes"}
    )
    cluster_id = fields.integer("cluster", low=0, high=0xFFFF)
    attributes = fields.integers("attributes", low=0, high=0xFFFF)
    bench._cluster(cluster_id)

    async def body():
        for attrid in attributes:
            await bench.zcl(
                cluster_id,
                GC.Read_Reporting_Configuration,
                ([foundation.ReadReportingConfigRecord(direction=0, attrid=attrid)],),
                general=True,
                label=f"{_hex(attrid)}",
            )

    await _run(bench, event_data, body)


async def user_bench_discover(
    app, listener, ieee, cmd, data, service, params, event_data
):
    """One page of Discover Attributes Extended or Discover Commands."""
    fields, bench = _open(
        app,
        ieee,
        service,
        "discover",
        {"cluster", "kind", "manufacturer", "start", "max"},
    )
    cluster_id = fields.integer("cluster", low=0, high=0xFFFF)
    kind = fields.choice(
        "kind", ("attributes", "commands_received", "commands_generated")
    )
    manufacturer = fields.integer("manufacturer", low=0, high=0xFFFF, default=None)
    bench._cluster(cluster_id)
    if kind == "attributes":
        command_id = GC.Discover_Attribute_Extended
        start = fields.integer("start", low=0, high=0xFFFF, default=0)
        args = (
            t.uint16_t(start),
            t.uint8_t(fields.integer("max", low=1, high=16, default=16)),
        )
    else:
        command_id = (
            GC.Discover_Commands_Received
            if kind == "commands_received"
            else GC.Discover_Commands_Generated
        )
        start = fields.integer("start", low=0, high=0xFF, default=0)
        args = (
            t.uint8_t(start),
            t.uint8_t(fields.integer("max", low=1, high=32, default=32)),
        )

    async def body():
        await bench.zcl(
            cluster_id,
            command_id,
            args,
            general=True,
            manufacturer=manufacturer,
            label=kind,
        )

    await _run(bench, event_data, body)


async def user_bench_group_membership(
    app, listener, ieee, cmd, data, service, params, event_data
):
    """Get Group Membership (0x0004 command 0x02) with an empty group list."""
    _, bench = _open(app, ieee, service, "group_membership")

    async def body():
        await bench.command(GROUPS, 0x02, [], label="get group membership")

    await _run(bench, event_data, body)


async def user_bench_scene_membership(
    app, listener, ieee, cmd, data, service, params, event_data
):
    """Get Scene Membership (0x0005 command 0x06) for one group."""
    fields, bench = _open(app, ieee, service, "scene_membership", {"group"})
    group = fields.integer("group", low=0, high=0xFFF7, default=0x0000)

    async def body():
        await bench.command(SCENES, 0x06, t.Group(group), label="get scene membership")

    await _run(bench, event_data, body)


async def user_bench_zdo(app, listener, ieee, cmd, data, service, params, event_data):
    """ZDO Node_Desc_req, Power_Desc_req or Mgmt_Bind_req to the shade."""
    fields, bench = _open(app, ieee, service, "zdo", {"request", "start_index"})
    request = fields.choice("request", tuple(ZDO_REQUESTS))
    start_index = fields.integer("start_index", low=0, high=0xFF, default=0)
    command = ZDO_REQUESTS[request]
    args = (
        (t.uint8_t(start_index),)
        if command == zdo_t.ZDOCmd.Mgmt_Bind_req
        else (t.NWK(bench.device.nwk),)
    )

    async def body():
        await bench.zdo(command, *args, label=request)

    await _run(bench, event_data, body)


async def user_bench_watch(app, listener, ieee, cmd, data, service, params, event_data):
    """Listen for `for_s` s, reading 0x0102/0x0008 every `every_s` s if given."""
    fields, bench = _open(app, ieee, service, "watch", {"for_s", "every_s"})
    for_s = fields.seconds("for_s", low=1, high=MAX_WAIT_S)
    every_s = fields.seconds("every_s", low=1, high=60, default=None)

    async def body():
        await bench.watch(for_s, every_s)

    await _run(bench, event_data, body)
