def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value == "":
        return True
    return False


def build_filters(
    specs,
    prefix="WHERE ",
    joiner=" AND ",
):
    conditions = list()
    params = dict()
    for condition, name, value in specs:
        params[name] = value
        if _is_empty(value):
            continue
        conditions.append(condition)
    if not conditions:
        return "", params
    return prefix + joiner.join(conditions), params
