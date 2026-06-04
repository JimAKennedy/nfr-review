"""Python anti-patterns for polyglot integration test."""


def swallow_all():
    try:
        open("/nonexistent")  # noqa: SIM115
    except:  # noqa: E722
        pass


def broad_catch():
    try:
        int("abc")
    except Exception:  # noqa: BLE001
        pass


def mutable_default(items=[]):  # noqa: B006
    items.append("x")
    return items


def log_to_stdout(msg):
    print(f"DEBUG: {msg}")
