"""Small bounded OTLP protobuf reader, accepting logs and traces without pip.

Wire field numbers follow opentelemetry-proto v1 logs/trace/common/resource.
Unknown fields are skipped. Metrics are counted, never turned into request TPS.
"""
import struct


def varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError("Truncated varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
    raise ValueError("Oversize varint")


def fields(data):
    result, offset = {}, 0
    while offset < len(data):
        tag, offset = varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if number == 0:
            raise ValueError("Invalid field tag")
        if wire == 0:
            value, offset = varint(data, offset)
        elif wire in (1, 5):
            width = 8 if wire == 1 else 4
            if offset + width > len(data):
                raise ValueError("Truncated fixed field")
            value, offset = data[offset:offset + width], offset + width
        elif wire == 2:
            size, offset = varint(data, offset)
            if offset + size > len(data):
                raise ValueError("Truncated message")
            value, offset = data[offset:offset + size], offset + size
        else:
            raise ValueError("Unsupported wire type")
        result.setdefault(number, []).append(value)
    return result


def text(f, n, default=""):
    value = f.get(n, [default])[0]
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def fixed(f, n):
    value = f.get(n, [b"\x00" * 8])[0]
    return str(int.from_bytes(value, "little"))


def anyvalue(data, depth=0):
    if depth > 12:
        raise ValueError("Attribute nesting too deep")
    f = fields(data)
    if 1 in f:
        return {"stringValue": text(f, 1)}
    if 2 in f:
        return {"boolValue": bool(f[2][0])}
    if 3 in f:
        value = f[3][0]
        if value >= 1 << 63:
            value -= 1 << 64
        return {"intValue": str(value)}
    if 4 in f:
        if not isinstance(f[4][0], bytes) or len(f[4][0]) != 8:
            raise ValueError("Invalid double wire encoding")
        return {"doubleValue": struct.unpack("<d", f[4][0])[0]}
    if 5 in f:
        return {"arrayValue": {"values": [anyvalue(v, depth+1) for v in fields(f[5][0]).get(1, [])]}}
    if 6 in f:
        return {"kvlistValue": {"values": attrs(fields(f[6][0]).get(1, []), depth+1)}}
    return {}


def attrs(values, depth=0):
    result = []
    for data in values:
        f = fields(data)
        if 1 in f and 2 in f:
            result.append({"key": text(f, 1), "value": anyvalue(f[2][0], depth)})
    return result


def log(data):
    f = fields(data)
    return {"timeUnixNano": fixed(f, 1), "observedTimeUnixNano": fixed(f, 11),
            "body": anyvalue(f[5][0]) if 5 in f else {},
            "attributes": attrs(f.get(6, [])), "traceId": f.get(9, [b""])[0].hex(),
            "spanId": f.get(10, [b""])[0].hex(), "eventName": text(f, 12)}


def span(data):
    f = fields(data)
    status = fields(f[15][0]) if 15 in f else {}
    return {"traceId": f.get(1, [b""])[0].hex(), "spanId": f.get(2, [b""])[0].hex(),
            "parentSpanId": f.get(4, [b""])[0].hex(), "name": text(f, 5),
            "startTimeUnixNano": fixed(f, 7), "endTimeUnixNano": fixed(f, 8),
            "attributes": attrs(f.get(9, [])), "status": {"code": status.get(3, [0])[0]},
            "events": [event(e) for e in f.get(11, [])]}


def event(data):
    f = fields(data)
    return {"timeUnixNano": fixed(f, 1), "name": text(f, 2), "attributes": attrs(f.get(3, []))}


def decode_export(data, kind):
    if kind not in ("logs", "traces", "metrics"):
        raise ValueError("Unknown OTLP signal")
    resources = []
    for group in fields(data).get(1, []):
        f = fields(group)
        resource = {"attributes": attrs(fields(f[1][0]).get(1, []))} if 1 in f else {}
        scopes = []
        for scope in f.get(2, []):
            sf = fields(scope)
            if kind == "logs":
                scopes.append({"logRecords": [log(v) for v in sf.get(2, [])]})
            elif kind == "traces":
                scopes.append({"spans": [span(v) for v in sf.get(2, [])]})
            else:
                # Histogram sums cannot identify a single request; keep metric names only.
                scopes.append({"metrics": [{"name": text(fields(v), 1)} for v in sf.get(2, [])]})
        key = {"logs": "scopeLogs", "traces": "scopeSpans", "metrics": "scopeMetrics"}[kind]
        resources.append({"resource": resource, key: scopes})
    return {{"logs": "resourceLogs", "traces": "resourceSpans", "metrics": "resourceMetrics"}[kind]: resources}
