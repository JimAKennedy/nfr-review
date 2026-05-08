"""Mutable default argument anti-patterns for testing PythonAstCollector."""


def mutable_list_default(items=[]):  # noqa: B006
    items.append(1)
    return items


def mutable_dict_default(config={}):  # noqa: B006
    config["key"] = "value"
    return config


def mutable_set_default(seen=set()):  # noqa: B006
    seen.add("item")
    return seen


def immutable_default(count=0, name="default", flag=True):
    """Immutable defaults — should NOT be flagged."""
    return count, name, flag


def none_default(data=None):
    """None default — idiomatic Python, should NOT be flagged."""
    if data is None:
        data = []
    return data


def multiple_defaults(x=[], y={}, z=42):  # noqa: B006
    """Mix of mutable and immutable defaults."""
    return x, y, z
