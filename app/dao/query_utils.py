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


_ROUTE_SORT_MAP = {
    "id": "r.id",
    "label": "r.label",
    "distance_m": "r.distance_m",
    "created_at": "r.created_at",
    "updated_at": "r.updated_at",
    "started_at": "r.started_at",
    "finished_at": "r.finished_at",
    "streets": "size(coalesce(r.streets, []))",
    "path_nodes_count": "CASE WHEN r.path_nodes_json IS NOT NULL THEN size(apoc.convert.fromJsonList(coalesce(r.path_nodes_json, '[]'))) ELSE 0 END",
}

_POINT_SORT_MAP = {
    "id": "p.id",
    "object_name": "p.object_name",
    "object_type": "p.object_type",
    "lat": "p.lat",
    "lng": "p.lng",
    "capacity": "p.capacity",
    "created_at": "p.created_at",
    "updated_at": "p.updated_at",
}

_SIM_SORT_MAP = {
    "id": "s.id",
    "name": "s.name",
    "status": "s.status",
    "tick": "s.tick",
    "elapsed_minutes": "s.elapsed_minutes",
    "vehicles_total": "coalesce(s.vehicles_total, s.vehicles_active, 0)",
    "vehicles_en_route": "coalesce(s.vehicles_en_route, 0)",
    "vehicles_cleaning": "coalesce(s.vehicles_cleaning, 0)",
    "vehicles_dumping": "coalesce(s.vehicles_dumping, 0)",
    "vehicles_refueling": "coalesce(s.vehicles_refueling, 0)",
    "vehicles_maintenance": "coalesce(s.vehicles_maintenance, 0)",
    "roads_cleaned_pct": "coalesce(s.roads_cleaned_pct, 0)",
    "snow_collected_m3": "coalesce(s.snow_collected_m3, 0)",
    "fuel_spent_l": "coalesce(s.fuel_spent_l, 0)",
    "avg_fuel_pct": "coalesce(s.avg_fuel_pct, 0)",
    "avg_snow_load_pct": "coalesce(s.avg_snow_load_pct, 0)",
    "roads_total": "coalesce(s.roads_total, 0)",
    "streets": "size(coalesce(s.streets, []))",
    "created_at": "s.created_at",
    "updated_at": "s.updated_at",
    "started_at": "s.started_at",
    "finished_at": "s.finished_at",
}


def build_order_by(sort_by, sort_order, sort_map, default):
    if sort_order and sort_order.lower() == "asc":
        direction = "ASC"
    else:
        direction = "DESC"
    if sort_by and sort_by in sort_map:
        return f"ORDER BY {sort_map[sort_by]} {direction}"
    return default
