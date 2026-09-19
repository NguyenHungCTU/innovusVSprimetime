"""One numeric policy for imported values, calculations, JSON and CSV."""
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, getcontext
from pathlib import Path

getcontext().prec = 50
TIME_SCALE = {"s": "1e9", "ms": "1e6", "us": "1e3", "ns": "1", "ps": "1e-3", "fs": "1e-6"}
CAP_SCALE = {"f": "1e12", "nf": "1e3", "pf": "1", "ff": "1e-3"}


def number(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("Boolean is not a timing number")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid number: " + str(value))
    if not result.is_finite():
        raise ValueError("Non-finite number: " + str(value))
    return result


def rounded(value, quantum):
    value = number(value)
    if value is None:
        return None
    ticks = (value / quantum).to_integral_value(rounding=ROUND_HALF_UP)
    return (ticks * quantum).copy_abs() if ticks == 0 else ticks * quantum


def difference(a, b):
    """a - b; missing is propagated, never replaced by zero."""
    a, b = number(a), number(b)
    return None if a is None or b is None else a - b


def json_text(value, level=0):
    """Write Decimal as a real JSON number, without a float round trip."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite JSON number")
        return format(value, "f")
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(str(k), ensure_ascii=False) + ":" + json_text(v, level + 1)
                              for k, v in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(json_text(v, level + 1) for v in value) + "]"
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def read_json(path):
    def reject(value):
        raise ValueError("Non-finite JSON constant " + value)
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream, parse_float=Decimal, parse_constant=reject)


def write_json(path, value):
    Path(path).write_text(json_text(value) + "\n", encoding="utf-8")
