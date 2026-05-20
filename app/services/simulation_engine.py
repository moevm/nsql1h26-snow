import json
import logging
import math
import random
from datetime import datetime, timezone

from app.dao.cache_manager import CacheManager
from app.dao.graph_dao import GraphDAO
from app.models.enums import MapObjectType, SimulationStatus, VehicleStatus, VehicleType
from app.models.schemas import (
    LatLng,
    SimulationParams,
    SimulationState,
    SimulationStats,
    VehicleConfig,
    VehicleState,
)

logger = logging.getLogger(__name__)

class SimulationEngine:

    def __init__(
        self,
        sim_id: str,
        params: SimulationParams,
        graph: GraphDAO,
        cache: CacheManager,
    ) -> None:
        self.sim_id = sim_id
        self.params = params
        self.graph = graph
        self.cache = cache

        self.state = SimulationState(id=sim_id, status=SimulationStatus.IDLE)
        self.vehicles: list[VehicleState] = []
        self.route_coords: list[list[dict]] = []

        self._uncleaned: list[dict] = []
        self._roads_total: int = 0
        self._roads_cleaned: int = 0
        self._route_stats: dict[str, dict] = {}
        self._edge_route_map: dict[str, set[str]] = {}
        self._cleaned_edges: set[str] = set()
        self._assigned_roads: dict[str, dict] = {}
        self._streets: set[str] = set()
        self._total_fuel: float = 0.0
        self._total_breakdowns: int = 0
        self._last_tick_events: list[dict] = []
        self._all_roads_done: bool = False

        self._parking_locations: list[dict] = []
        self._snow_polygons: list[dict] = []
        self._service_stations: list[dict] = []
        self._vehicle_cfg_by_type: dict[VehicleType, VehicleConfig] = {}

    async def initialize(self) -> None:
        if not self.params.cleaning_tasks:
            raise ValueError("No cleaning tasks defined. Add at least one route.")

        self._vehicle_cfg_by_type = {cfg.type: cfg for cfg in self.params.vehicles}

        all_road_segments: list[dict] = []
        seen_edges: set[tuple[str, str]] = set()

        for task in self.params.cleaning_tasks:
            if task.route_id:
                route_row = await self.graph.get_route(task.route_id)
                route_points = await self.graph.get_route_points(task.route_id) if route_row else []
                if route_row and route_points:
                    raw = route_row.get("path_nodes_json") or "[]"
                    try:
                        stored_nodes = json.loads(raw)
                    except Exception:
                        stored_nodes = []
                    self.route_coords.append(
                        stored_nodes if stored_nodes else [{"lat": p["lat"], "lng": p["lng"]} for p in route_points]
                    )
                    for street in route_row.get("streets") or []:
                        if street:
                            self._streets.add(street)
                    ordered = sorted(route_points, key=lambda p: p.get("index", 0))
                    route_seg_count = 0
                    for idx in range(len(ordered) - 1):
                        src = ordered[idx]
                        dst = ordered[idx + 1]
                        edge_key = (src["id"], dst["id"])
                        if edge_key in seen_edges:
                            continue
                        seen_edges.add(edge_key)
                        all_road_segments.append(self._build_segment(src, dst, None, task.route_id))
                        self._register_edge_route(src["id"], dst["id"], task.route_id)
                        route_seg_count += 1
                    if route_seg_count:
                        self._route_stats[task.route_id] = {"total": route_seg_count, "cleaned": 0, "started": False}
                    continue
                logger.warning("Route %s not found or empty; fallback shortest-path", task.route_id)

            start_node = await self.graph.find_nearest_node(task.start.lat, task.start.lng)
            end_node = await self.graph.find_nearest_node(task.end.lat, task.end.lng)
            if not start_node or not end_node:
                logger.warning("Skipping task without nodes: %s -> %s", task.start, task.end)
                continue

            path = await self.graph.find_shortest_path(start_node["id"], end_node["id"])
            if path:
                self.route_coords.append(path["nodes"])

            roads = await self.graph.find_path_roads(start_node["id"], end_node["id"])
            route_seg_count = 0
            for road in roads:
                if road.get("name"):
                    self._streets.add(road["name"])
                edge_key = (road["src"], road["dst"])
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                all_road_segments.append({
                    **road,
                    "route_id": task.route_id,
                    "cleaned": False,
                })
                self._register_edge_route(road["src"], road["dst"], task.route_id)
                route_seg_count += 1
            if task.route_id and route_seg_count:
                self._route_stats[task.route_id] = {"total": route_seg_count, "cleaned": 0, "started": False}

        if not all_road_segments:
            raise ValueError("Could not resolve any roads from cleaning tasks.")

        road_pairs = [(r["src"], r["dst"]) for r in all_road_segments]
        await self.graph.reset_snow_on_roads(road_pairs, self.params.snowfall_cm)
        self._uncleaned = list(all_road_segments)
        self._roads_total = len(all_road_segments)

        await self._load_facilities(all_road_segments[0])
        self._create_vehicles()

        self.state.status = SimulationStatus.RUNNING
        self.state.started_at = datetime.now(timezone.utc)
        self.state.streets = sorted(self._streets)
        self._refresh_state_metrics()
        await self._assign_idle_vehicles()
        logger.info("Simulation %s init: %d roads, %d vehicles", self.sim_id, self._roads_total, len(self.vehicles))

    async def tick(self) -> None:
        if self.state.status != SimulationStatus.RUNNING:
            return

        self.state.tick += 1
        self.state.elapsed_minutes += self.params.tick_duration_min * self.params.speed_multiplier
        self._last_tick_events = []

        for vehicle in self.vehicles:
            await self._advance_vehicle(vehicle)

        self._reconcile_completion_state()

        if not self._all_roads_done and not self._uncleaned and self._roads_cleaned >= self._roads_total:
            self._all_roads_done = True
            logger.info("Simulation %s: all roads cleaned, sending vehicles to parking", self.sim_id)

        await self._assign_idle_vehicles()
        self._refresh_state_metrics()

        if self._should_finish():
            self.state.status = SimulationStatus.FINISHED
            self.state.finished_at = datetime.now(timezone.utc)
            logger.info("Simulation %s finished at tick %d", self.sim_id, self.state.tick)

        await self.cache.set(f"sim:{self.sim_id}:state", self.state.model_dump(), ttl=600)

    def pause(self) -> None:
        if self.state.status == SimulationStatus.RUNNING:
            self.state.status = SimulationStatus.PAUSED

    def resume(self) -> None:
        if self.state.status == SimulationStatus.PAUSED:
            self.state.status = SimulationStatus.RUNNING

    async def stop(self) -> None:
        self.state.status = SimulationStatus.FINISHED
        self.state.finished_at = datetime.now(timezone.utc)
        await self.cache.flush_simulation(self.sim_id)

    def get_stats(self) -> SimulationStats:
        return SimulationStats(
            simulation_id=self.sim_id,
            total_time_min=self.state.elapsed_minutes,
            roads_cleaned_pct=self.state.roads_cleaned_pct,
            snow_collected_m3=self.state.snow_collected_m3,
            fuel_spent_l=round(self._total_fuel, 1),
            breakdowns=self._total_breakdowns,
            repair_cost_rub=self._total_breakdowns * 15_000,
            efficiency=round(self.state.roads_cleaned_pct / max(self.state.elapsed_minutes, 1) * 60, 2),
        )

    async def _load_facilities(self, fallback_segment: dict) -> None:
        self._parking_locations = await self.graph.get_map_objects(MapObjectType.PARKING.value)
        self._snow_polygons = await self.graph.get_map_objects(MapObjectType.SNOW_POLYGON.value)
        self._service_stations = await self.graph.get_map_objects(MapObjectType.SERVICE_STATION.value)

        if not self._parking_locations:
            self._parking_locations = [{
                "id": "fallback-parking",
                "name": "Fallback parking",
                "type": MapObjectType.PARKING.value,
                "lat": fallback_segment["src_lat"],
                "lng": fallback_segment["src_lng"],
            }]

    def _create_vehicles(self) -> None:
        counters: dict[VehicleType, int] = {}
        for cfg in self.params.vehicles:
            if cfg.type not in counters:
                counters[cfg.type] = 0
            for _ in range(cfg.count):
                parking = random.choice(self._parking_locations)
                loc = LatLng(lat=float(parking["lat"]), lng=float(parking["lng"]))
                vehicle_index = counters[cfg.type]
                counters[cfg.type] += 1
                self.vehicles.append(
                    VehicleState(
                        id=f"{self.sim_id}-{cfg.type.value[:1]}-{vehicle_index:04d}",
                        type=cfg.type,
                        status=cfg.initial_status,
                        location=loc,
                        home_parking_id=parking.get("id"),
                        home_parking_location=LatLng(lat=loc.lat, lng=loc.lng),
                        fuel_level=cfg.fuel_capacity_l,
                        speed_kmh=0.0,
                        travel_speed_kmh=cfg.travel_speed_kmh,
                        cleaning_speed_kmh=cfg.cleaning_speed_kmh,
                        fuel_consumption_l_per_km=cfg.fuel_consumption_l_per_km,
                        fuel_capacity_l=cfg.fuel_capacity_l,
                        snow_capacity_m3=cfg.capacity_m3,
                        breakdown_probability=cfg.breakdown_probability,
                        repair_time_min=cfg.repair_time_min,
                        repair_remaining_min=cfg.repair_time_min if cfg.initial_status == VehicleStatus.MAINTENANCE else 0.0,
                    )
                )

    async def _advance_vehicle(self, vehicle: VehicleState) -> None:
        if vehicle.status == VehicleStatus.BROKEN:
            vehicle.speed_kmh = 0.0
            await self._send_to_maintenance(vehicle)
            return

        if vehicle.status == VehicleStatus.MAINTENANCE:
            if vehicle.target_location and (
                vehicle.path_waypoints
                or self._distance_m(vehicle.location, vehicle.target_location) > 0.5
            ):
                await self._move_to_target(vehicle)
                return
            vehicle.speed_kmh = 0.0
            vehicle.repair_remaining_min = max(0.0, vehicle.repair_remaining_min - self.params.tick_duration_min)
            if vehicle.repair_remaining_min <= 0:
                vehicle.target_type = None
                vehicle.target_id = None
                vehicle.target_location = None
                vehicle.path_waypoints = []
                vehicle.status = VehicleStatus.IDLE
                vehicle.speed_kmh = 0.0
                self._emit(vehicle, "repaired")
            return

        if vehicle.status == VehicleStatus.REFUELING:
            if vehicle.target_location and (
                vehicle.path_waypoints
                or self._distance_m(vehicle.location, vehicle.target_location) > 0.5
            ):
                await self._move_to_target(vehicle)
                return
            vehicle.speed_kmh = 0.0
            vehicle.fuel_level = vehicle.fuel_capacity_l
            vehicle.target_type = None
            vehicle.target_id = None
            vehicle.target_location = None
            vehicle.path_waypoints = []
            vehicle.status = VehicleStatus.IDLE
            vehicle.speed_kmh = 0.0
            self._emit(vehicle, "refueled")
            return

        if vehicle.status == VehicleStatus.DUMPING:
            if vehicle.target_location and (
                vehicle.path_waypoints
                or self._distance_m(vehicle.location, vehicle.target_location) > 0.5
            ):
                await self._move_to_target(vehicle)
                return
            vehicle.speed_kmh = 0.0
            vehicle.snow_loaded_m3 = max(0.0, vehicle.snow_loaded_m3 - self.params.snow_melt_rate_m3_per_tick)
            if vehicle.snow_loaded_m3 <= 0.001:
                vehicle.snow_loaded_m3 = 0.0
                if vehicle.current_edge and vehicle.road_target_location and vehicle.road_resume_location:
                    await self._set_target(vehicle, "road_resume", None, vehicle.road_resume_location)
                    vehicle.status = VehicleStatus.EN_ROUTE
                    self._emit(vehicle, "dumped_snow")
                    return
                vehicle.road_target_location = None
                vehicle.road_resume_location = None
                vehicle.target_type = None
                vehicle.target_id = None
                vehicle.target_location = None
                vehicle.path_waypoints = []
                vehicle.status = VehicleStatus.IDLE
                vehicle.speed_kmh = 0.0
                self._emit(vehicle, "dumped_snow")
            return

        if vehicle.status in {VehicleStatus.EN_ROUTE, VehicleStatus.OFF_ROUTE}:
            await self._move_to_target(vehicle)
            return

        if vehicle.status == VehicleStatus.CLEANING:
            if vehicle.current_edge:
                await self._clean_current_edge(vehicle)
                return
            if vehicle.target_type == "road_start":
                await self._move_to_target(vehicle)
                return
            vehicle.speed_kmh = 0.0
            vehicle.status = VehicleStatus.IDLE
            return

    async def _assign_idle_vehicles(self) -> None:
        for vehicle in self.vehicles:
            if vehicle.status != VehicleStatus.IDLE:
                continue
            vehicle.speed_kmh = 0.0
            if vehicle.current_edge:
                if vehicle.road_target_location or vehicle.target_location:
                    vehicle.status = VehicleStatus.CLEANING
                    continue
                vehicle.current_edge = None
                vehicle.current_road = None
                vehicle.progress_m = 0.0
            if self._all_roads_done:
                if vehicle.snow_loaded_m3 > 0.01:
                    await self._send_to_dump(vehicle)
                    continue
                await self._send_to_parking(vehicle)
                continue
            if self._should_dump(vehicle):
                await self._send_to_dump(vehicle)
                continue
            if vehicle.fuel_capacity_l > 0 and vehicle.fuel_level <= vehicle.fuel_capacity_l * (self.params.refuel_threshold_pct / 100):
                await self._send_to_refuel(vehicle)
                continue
            if self._uncleaned:
                road = self._uncleaned.pop(0)
                self._assigned_roads[vehicle.id] = road
                await self._set_target(vehicle, "road_start", road["src"], LatLng(lat=road["src_lat"], lng=road["src_lng"]))
                vehicle.status = VehicleStatus.CLEANING
                self._emit(vehicle, "assigned_task", road=self._road_label(road))
                continue
            if vehicle.snow_loaded_m3 > 0.01:
                await self._send_to_dump(vehicle)
                continue

    async def _move_to_target(self, vehicle: VehicleState) -> None:
        target = vehicle.target_location
        if not target:
            vehicle.target_type = None
            vehicle.target_id = None
            vehicle.path_waypoints = []
            vehicle.status = VehicleStatus.IDLE
            return

        distance_per_tick = self._distance_per_tick(vehicle)
        vehicle.speed_kmh = vehicle.travel_speed_kmh
        remaining = distance_per_tick
        total_travelled = 0.0

        while remaining > 0 and vehicle.path_waypoints:
            next_wp = vehicle.path_waypoints[0]
            dist_to_wp = self._distance_m(vehicle.location, next_wp)
            if dist_to_wp < 0.5:
                vehicle.location = LatLng(lat=next_wp.lat, lng=next_wp.lng)
                vehicle.path_waypoints.pop(0)
                continue
            if dist_to_wp <= remaining:
                vehicle.distance_travelled_km += dist_to_wp / 1000.0
                self._consume_fuel(vehicle, dist_to_wp)
                remaining -= dist_to_wp
                total_travelled += dist_to_wp
                vehicle.location = LatLng(lat=next_wp.lat, lng=next_wp.lng)
                vehicle.path_waypoints.pop(0)
            else:
                vehicle.location = self._move_towards(vehicle.location, next_wp, remaining)
                vehicle.distance_travelled_km += remaining / 1000.0
                self._consume_fuel(vehicle, remaining)
                total_travelled += remaining
                remaining = 0

        if not vehicle.path_waypoints:
            distance_to_target = self._distance_m(vehicle.location, target)
            if distance_to_target < 0.5:
                vehicle.location = LatLng(lat=target.lat, lng=target.lng)
                await self._arrive_at_target(vehicle)
                return
            travelled = min(remaining, distance_to_target)
            if travelled > 0:
                vehicle.location = self._move_towards(vehicle.location, target, travelled)
                vehicle.distance_travelled_km += travelled / 1000.0
                self._consume_fuel(vehicle, travelled)
                total_travelled += travelled
            distance_to_target = self._distance_m(vehicle.location, target)
            if distance_to_target > 0.5:
                if total_travelled > 0 and self._check_breakdown(vehicle):
                    return
                return
            vehicle.location = LatLng(lat=target.lat, lng=target.lng)
            await self._arrive_at_target(vehicle)
            return

        if total_travelled > 0 and self._check_breakdown(vehicle):
            return

    async def _arrive_at_target(self, vehicle: VehicleState) -> None:
        target_type = vehicle.target_type
        if target_type == "road_start":
            road = self._assigned_roads.pop(vehicle.id, None)
            if not road:
                vehicle.status = VehicleStatus.IDLE
                vehicle.speed_kmh = 0.0
                return
            src_id, dst_id = road["src"], road["dst"]
            road_state = await self.graph.get_road_state(src_id, dst_id)
            is_clean = bool(road_state and road_state.get("cleaned", False))
            total_distance = max(float((road_state or {}).get("distance") or road.get("distance") or 0.0), 1.0)
            cleaned_m = max(0.0, min(float((road_state or {}).get("cleaned_m") or 0.0), total_distance))
            if is_clean or cleaned_m + 0.1 >= total_distance:
                vehicle.target_type = None
                vehicle.target_id = None
                vehicle.target_location = None
                vehicle.path_waypoints = []
                vehicle.status = VehicleStatus.IDLE
                vehicle.speed_kmh = 0.0
                self._emit(vehicle, "skipped_already_clean", road=self._road_label(road))
                return
            vehicle.status = VehicleStatus.CLEANING
            vehicle.current_edge = f"{road['src']}->{road['dst']}"
            vehicle.current_road = self._road_label(road)
            vehicle.progress_m = cleaned_m
            vehicle.target_id = road["dst"]
            vehicle.target_location = LatLng(lat=road["dst_lat"], lng=road["dst_lng"])
            vehicle.road_target_location = LatLng(lat=road["dst_lat"], lng=road["dst_lng"])
            vehicle.road_resume_location = None
            vehicle.path_waypoints = []
            if road.get("route_id") and road["route_id"] in self._route_stats:
                route_stats = self._route_stats[road["route_id"]]
                if not route_stats["started"]:
                    route_stats["started"] = True
                    await self.graph.update_route(road["route_id"], {"started_at": datetime.now(timezone.utc)})
            self._emit(vehicle, "arrived_task", road=vehicle.current_road)
            return
        if target_type == "snow_polygon":
            vehicle.status = VehicleStatus.DUMPING
            vehicle.path_waypoints = []
            self._emit(vehicle, "snow_full")
            return
        if target_type == "road_resume":
            vehicle.status = VehicleStatus.CLEANING
            vehicle.target_type = None
            vehicle.target_id = None
            vehicle.target_location = vehicle.road_target_location
            vehicle.road_resume_location = None
            vehicle.path_waypoints = []
            self._emit(vehicle, "resumed_cleaning", road=vehicle.current_road)
            return
        if target_type == "service_station_refuel":
            vehicle.status = VehicleStatus.REFUELING
            vehicle.path_waypoints = []
            self._emit(vehicle, "low_fuel")
            return
        if target_type == "service_station_maintenance":
            vehicle.status = VehicleStatus.MAINTENANCE
            vehicle.path_waypoints = []
            vehicle.repair_remaining_min = vehicle.repair_time_min or self.params.tick_duration_min
            self._emit(vehicle, "maintenance_started")
            return
        if target_type == "parking":
            vehicle.target_type = None
            vehicle.target_id = None
            vehicle.target_location = None
            vehicle.path_waypoints = []
            vehicle.status = VehicleStatus.IDLE
            vehicle.speed_kmh = 0.0
            self._emit(vehicle, "returned_to_parking")
            return
        vehicle.status = VehicleStatus.IDLE
        vehicle.speed_kmh = 0.0

    async def _clean_current_edge(self, vehicle: VehicleState) -> None:
        road_target = vehicle.road_target_location or vehicle.target_location
        if not vehicle.current_edge or not road_target:
            vehicle.status = VehicleStatus.IDLE
            return

        vehicle.speed_kmh = vehicle.cleaning_speed_kmh
        remaining_cleaning_m = self._distance_per_tick(vehicle, mode="cleaning")

        while remaining_cleaning_m > 0 and vehicle.current_edge and road_target:
            src_id, dst_id = vehicle.current_edge.split("->", 1)
            total_distance = max(self._distance_m(vehicle.location, road_target) + vehicle.progress_m, 1.0)
            segment_remaining_m = max(0.0, total_distance - vehicle.progress_m)
            capacity_limited_m = self._capacity_limited_cleaning_distance(vehicle)
            if capacity_limited_m <= 0:
                vehicle.road_resume_location = LatLng(lat=vehicle.location.lat, lng=vehicle.location.lng)
                vehicle.target_location = road_target
                await self._send_to_dump(vehicle)
                return

            travelled = min(remaining_cleaning_m, segment_remaining_m, capacity_limited_m)
            vehicle.progress_m += travelled
            if travelled > 0:
                vehicle.location = self._move_towards(vehicle.location, road_target, travelled)
                vehicle.distance_travelled_km += travelled / 1000.0
                self._consume_fuel(vehicle, travelled)
                self.state.snow_collected_m3 = round(self.state.snow_collected_m3 + self._estimate_snow_volume(travelled), 2)
                vehicle.snow_loaded_m3 = min(
                    vehicle.snow_capacity_m3,
                    vehicle.snow_loaded_m3 + self._estimate_snow_volume(travelled),
                )
                remaining_cleaning_m -= travelled
                await self.graph.update_road_cleaning_progress(src_id, dst_id, vehicle.progress_m)

            if vehicle.progress_m + 0.1 < total_distance:
                if self._should_dump(vehicle):
                    vehicle.road_resume_location = LatLng(lat=vehicle.location.lat, lng=vehicle.location.lng)
                    vehicle.target_location = road_target
                    await self._send_to_dump(vehicle)
                    return
                self._check_breakdown(vehicle)
                return

            await self.graph.mark_road_cleaned(src_id, dst_id)
            vehicle.location = LatLng(lat=road_target.lat, lng=road_target.lng)
            vehicle.progress_m = 0.0
            self._mark_edge_cleaned(src_id, dst_id)
            self._emit(vehicle, "segment_cleaned", road=vehicle.current_road)

            await self._mark_route_edge_cleaned(src_id, dst_id)
            vehicle.current_edge = None
            vehicle.current_road = None
            vehicle.target_id = None
            vehicle.target_location = None
            vehicle.target_type = None
            vehicle.road_target_location = None
            vehicle.road_resume_location = None
            vehicle.path_waypoints = []

            if self._should_dump(vehicle):
                await self._send_to_dump(vehicle)
                return
            if (vehicle.fuel_capacity_l > 0
                    and vehicle.fuel_level <= vehicle.fuel_capacity_l * (self.params.refuel_threshold_pct / 100)):
                await self._send_to_refuel(vehicle)
                return

            if self._all_roads_done or not self._uncleaned:
                vehicle.status = VehicleStatus.IDLE
                vehicle.speed_kmh = 0.0
                return

            next_road = self._uncleaned.pop(0)
            self._assigned_roads[vehicle.id] = next_road
            await self._set_target(
                vehicle, "road_start", next_road["src"],
                LatLng(lat=next_road["src_lat"], lng=next_road["src_lng"]),
            )
            vehicle.status = VehicleStatus.CLEANING
            self._emit(vehicle, "assigned_task", road=self._road_label(next_road))

            if vehicle.path_waypoints or self._distance_m(vehicle.location, vehicle.target_location) > 0.5:
                return

            await self._arrive_at_target(vehicle)
            road_target = vehicle.road_target_location or vehicle.target_location

        if not vehicle.current_edge and vehicle.status == VehicleStatus.CLEANING:
            vehicle.status = VehicleStatus.IDLE
            vehicle.speed_kmh = 0.0

    async def _mark_route_edge_cleaned(self, src_id: str, dst_id: str) -> None:
        for route_id in self._edge_route_map.get(f"{src_id}->{dst_id}", set()):
            stats = self._route_stats.get(route_id)
            if not stats:
                continue
            if stats.get("cleaned_edges") is None:
                stats["cleaned_edges"] = set()
            edge_key = f"{src_id}->{dst_id}"
            if edge_key in stats["cleaned_edges"]:
                continue
            stats["cleaned_edges"].add(edge_key)
            stats["cleaned"] = min(stats["total"], stats.get("cleaned", 0) + 1)
            if stats["cleaned"] >= stats["total"] and not stats.get("finished"):
                stats["finished"] = True
                await self.graph.update_route(route_id, {"finished_at": datetime.now(timezone.utc)})

    def _register_edge_route(self, src_id: str, dst_id: str, route_id: str | None) -> None:
        if not route_id:
            return
        edge_key = f"{src_id}->{dst_id}"
        self._edge_route_map.setdefault(edge_key, set()).add(route_id)

    async def _send_to_maintenance(self, vehicle: VehicleState) -> None:
        facility = self._nearest_object(vehicle.location, self._service_stations)
        if not facility:
            cfg = self._vehicle_cfg(vehicle.type)
            vehicle.status = VehicleStatus.MAINTENANCE
            vehicle.repair_remaining_min = cfg.repair_time_min if cfg else self.params.tick_duration_min
            self._emit(vehicle, "maintenance_started")
            return
        cfg = self._vehicle_cfg(vehicle.type)
        vehicle.repair_remaining_min = cfg.repair_time_min if cfg else self.params.tick_duration_min
        await self._set_target(
            vehicle,
            "service_station_maintenance",
            facility.get("id"),
            LatLng(lat=float(facility["lat"]), lng=float(facility["lng"])),
        )
        vehicle.status = VehicleStatus.MAINTENANCE

    async def _send_to_dump(self, vehicle: VehicleState) -> None:
        facility = self._nearest_object(vehicle.location, self._snow_polygons)
        if not facility:
            vehicle.snow_loaded_m3 = 0.0
            if vehicle.current_edge and vehicle.road_target_location and vehicle.road_resume_location:
                vehicle.location = LatLng(lat=vehicle.road_resume_location.lat, lng=vehicle.road_resume_location.lng)
                vehicle.target_type = None
                vehicle.target_id = None
                vehicle.target_location = vehicle.road_target_location
                vehicle.road_resume_location = None
                vehicle.path_waypoints = []
                vehicle.status = VehicleStatus.CLEANING
                vehicle.speed_kmh = 0.0
                self._emit(vehicle, "dumped_snow")
                return
            vehicle.target_type = None
            vehicle.target_id = None
            vehicle.target_location = None
            vehicle.current_edge = None
            vehicle.current_road = None
            vehicle.road_target_location = None
            vehicle.road_resume_location = None
            vehicle.progress_m = 0.0
            vehicle.path_waypoints = []
            vehicle.status = VehicleStatus.IDLE
            vehicle.speed_kmh = 0.0
            self._emit(vehicle, "dumped_snow")
            return
        await self._set_target(
            vehicle,
            "snow_polygon",
            facility.get("id"),
            LatLng(lat=float(facility["lat"]), lng=float(facility["lng"])),
        )
        vehicle.status = VehicleStatus.DUMPING

    async def _send_to_refuel(self, vehicle: VehicleState) -> None:
        facility = self._nearest_object(vehicle.location, self._service_stations)
        if not facility:
            vehicle.fuel_level = vehicle.fuel_capacity_l
            vehicle.status = VehicleStatus.IDLE
            return
        await self._set_target(
            vehicle,
            "service_station_refuel",
            facility.get("id"),
            LatLng(lat=float(facility["lat"]), lng=float(facility["lng"])),
        )
        vehicle.status = VehicleStatus.REFUELING

    async def _send_to_parking(self, vehicle: VehicleState) -> None:
        parking_loc = vehicle.home_parking_location
        parking_id = vehicle.home_parking_id
        if not parking_loc:
            parking = self._nearest_object(vehicle.location, self._parking_locations)
            if not parking:
                return
            parking_id = parking.get("id")
            parking_loc = LatLng(lat=float(parking["lat"]), lng=float(parking["lng"]))
        if not parking_loc:
            return
        if self._distance_m(vehicle.location, parking_loc) < 1.0:
            vehicle.target_type = None
            vehicle.target_id = None
            vehicle.target_location = None
            vehicle.current_edge = None
            vehicle.current_road = None
            vehicle.road_target_location = None
            vehicle.road_resume_location = None
            vehicle.progress_m = 0.0
            vehicle.path_waypoints = []
            vehicle.status = VehicleStatus.IDLE
            return
        await self._set_target(vehicle, "parking", parking_id, parking_loc)
        vehicle.status = VehicleStatus.EN_ROUTE

    async def _set_target(self, vehicle: VehicleState, target_type: str, target_id: str | None, target_location: LatLng) -> None:
        vehicle.target_type = target_type
        vehicle.target_id = target_id
        vehicle.target_location = target_location
        vehicle.path_waypoints = await self._compute_path_waypoints(vehicle.location, target_location)

    async def _compute_path_waypoints(self, origin: LatLng, destination: LatLng) -> list[LatLng]:
        start_node = await self.graph.find_nearest_node(origin.lat, origin.lng)
        end_node = await self.graph.find_nearest_node(destination.lat, destination.lng)
        if not start_node or not end_node or start_node["id"] == end_node["id"]:
            return []
        path = await self.graph.find_shortest_path(start_node["id"], end_node["id"])
        if not path or not path.get("nodes"):
            return []
        waypoints: list[LatLng] = []
        nodes = path["nodes"]
        for i, node in enumerate(nodes):
            wp = LatLng(lat=float(node["lat"]), lng=float(node["lng"]))
            if i == 0:
                dist = self._distance_m(origin, wp)
                if dist < 1.0:
                    continue
            if i == len(nodes) - 1:
                dist = self._distance_m(wp, destination)
                if dist < 1.0:
                    continue
            waypoints.append(wp)
        return waypoints

    def _vehicle_cfg(self, vehicle_type: VehicleType) -> VehicleConfig | None:
        return self._vehicle_cfg_by_type.get(vehicle_type)

    def _distance_per_tick(self, vehicle: VehicleState, mode: str = "travel") -> float:
        speed_kmh = vehicle.cleaning_speed_kmh if mode == "cleaning" else vehicle.travel_speed_kmh
        return speed_kmh * 1000.0 * self.params.tick_duration_min / 60.0 * self.params.speed_multiplier

    def _consume_fuel(self, vehicle: VehicleState, distance_m: float) -> None:
        if distance_m <= 0:
            return
        fuel_used = vehicle.fuel_consumption_l_per_km * (distance_m / 1000.0)
        vehicle.fuel_level = max(0.0, vehicle.fuel_level - fuel_used)
        self._total_fuel += fuel_used

    def _check_breakdown(self, vehicle: VehicleState) -> bool:
        if vehicle.status not in {VehicleStatus.EN_ROUTE, VehicleStatus.OFF_ROUTE, VehicleStatus.CLEANING, VehicleStatus.DUMPING, VehicleStatus.REFUELING}:
            return False
        if random.random() >= vehicle.breakdown_probability:
            return False
        assigned_road = self._assigned_roads.pop(vehicle.id, None)
        if assigned_road:
            self._uncleaned.insert(0, assigned_road)
        elif vehicle.current_edge and (vehicle.road_target_location or vehicle.target_location):
            src_id, dst_id = vehicle.current_edge.split("->", 1)
            road_start = vehicle.road_resume_location or vehicle.location
            road_target = vehicle.road_target_location or vehicle.target_location
            self._uncleaned.insert(0, {
                "src": src_id,
                "dst": dst_id,
                "src_lat": road_start.lat,
                "src_lng": road_start.lng,
                "dst_lat": road_target.lat,
                "dst_lng": road_target.lng,
                "name": vehicle.current_road,
                "distance": max(self._distance_m(road_start, road_target), 1.0),
                "route_id": None,
                "cleaned": False,
            })
        vehicle.status = VehicleStatus.BROKEN
        vehicle.current_road = None
        vehicle.current_edge = None
        vehicle.progress_m = 0.0
        vehicle.road_target_location = None
        vehicle.road_resume_location = None
        vehicle.path_waypoints = []
        self._total_breakdowns += 1
        self._emit(vehicle, "breakdown")
        return True

    def _mark_edge_cleaned(self, src_id: str, dst_id: str) -> None:
        edge_key = f"{src_id}->{dst_id}"
        if edge_key in self._cleaned_edges:
            return
        self._cleaned_edges.add(edge_key)
        self._roads_cleaned = min(self._roads_total, self._roads_cleaned + 1)

    def _reconcile_completion_state(self) -> None:
        if self._uncleaned or self._assigned_roads:
            return
        if any(v.current_edge for v in self.vehicles):
            return
        if self._roads_total > 0:
            self._roads_cleaned = self._roads_total

    def _should_finish(self) -> bool:
        if not self._all_roads_done:
            return False
        if self._uncleaned or self._assigned_roads:
            return False
        for vehicle in self.vehicles:
            if vehicle.current_edge:
                return False
            if vehicle.status != VehicleStatus.IDLE:
                return False
            if vehicle.snow_loaded_m3 > 0.01:
                return False
            parking_loc = vehicle.home_parking_location
            if not parking_loc:
                parking = self._nearest_object(vehicle.location, self._parking_locations)
                if parking:
                    parking_loc = LatLng(lat=float(parking["lat"]), lng=float(parking["lng"]))
            if parking_loc and self._distance_m(vehicle.location, parking_loc) > 1.0:
                return False
        return True

    def _refresh_state_metrics(self) -> None:
        self.state.vehicles_active = sum(1 for v in self.vehicles if v.status != VehicleStatus.IDLE or v.target_type)
        self.state.vehicles_broken = sum(1 for v in self.vehicles if v.status == VehicleStatus.BROKEN)
        self.state.vehicles_en_route = sum(1 for v in self.vehicles if v.status in {VehicleStatus.EN_ROUTE, VehicleStatus.OFF_ROUTE})
        self.state.vehicles_cleaning = sum(1 for v in self.vehicles if v.status == VehicleStatus.CLEANING)
        self.state.vehicles_dumping = sum(1 for v in self.vehicles if v.status == VehicleStatus.DUMPING)
        self.state.vehicles_refueling = sum(1 for v in self.vehicles if v.status == VehicleStatus.REFUELING)
        self.state.vehicles_maintenance = sum(1 for v in self.vehicles if v.status == VehicleStatus.MAINTENANCE)
        self.state.roads_cleaned_pct = round((self._roads_cleaned / self._roads_total) * 100, 2) if self._roads_total else 0.0
        self.state.fuel_spent_l = round(self._total_fuel, 2)
        if self.vehicles:
            self.state.avg_fuel_pct = round(sum((v.fuel_level / max(v.fuel_capacity_l, 1)) * 100 for v in self.vehicles) / len(self.vehicles), 2)
            self.state.avg_snow_load_pct = round(sum((v.snow_loaded_m3 / max(v.snow_capacity_m3, 1)) * 100 for v in self.vehicles) / len(self.vehicles), 2)
        else:
            self.state.avg_fuel_pct = 0.0
            self.state.avg_snow_load_pct = 0.0

    def _estimate_snow_volume(self, distance_m: float) -> float:
        return round(distance_m * self._snow_volume_per_meter(), 3)

    def _snow_volume_per_meter(self) -> float:
        default_width_m = 8.0
        snow_height_m = self.params.snowfall_cm / 100.0
        return default_width_m * snow_height_m * 0.35

    def _dump_threshold_m3(self, vehicle: VehicleState) -> float:
        if vehicle.snow_capacity_m3 <= 0:
            return 0.0
        return vehicle.snow_capacity_m3 * (self.params.dump_threshold_pct / 100)

    def _should_dump(self, vehicle: VehicleState) -> bool:
        threshold = self._dump_threshold_m3(vehicle)
        return threshold > 0 and vehicle.snow_loaded_m3 + 0.001 >= threshold

    def _capacity_limited_cleaning_distance(self, vehicle: VehicleState) -> float:
        threshold = self._dump_threshold_m3(vehicle)
        if threshold <= 0:
            return math.inf
        remaining_m3 = max(0.0, threshold - vehicle.snow_loaded_m3)
        volume_per_meter = self._snow_volume_per_meter()
        if volume_per_meter <= 0:
            return math.inf
        return remaining_m3 / volume_per_meter

    def _emit(self, vehicle: VehicleState, event: str, road: str | None = None) -> None:
        self._last_tick_events.append({
            "vehicle_id": vehicle.id,
            "event": event,
            "road": road,
            "status": vehicle.status.value,
            "lat": vehicle.location.lat,
            "lng": vehicle.location.lng,
            "target_type": vehicle.target_type,
            "target_id": vehicle.target_id,
        })

    def _nearest_object(self, origin: LatLng, objects: list[dict]) -> dict | None:
        if not objects:
            return None
        return min(
            objects,
            key=lambda obj: self._distance_m(origin, LatLng(lat=float(obj["lat"]), lng=float(obj["lng"]))),
        )

    def _road_label(self, road: dict) -> str:
        return road.get("name") or f"{road['src']}->{road['dst']}"

    @staticmethod
    def _distance_m(a: LatLng, b: LatLng) -> float:
        lat_scale = 111_320.0
        lng_scale = max(1.0, 111_320.0 * math.cos(math.radians((a.lat + b.lat) / 2)))
        dy = (b.lat - a.lat) * lat_scale
        dx = (b.lng - a.lng) * lng_scale
        return math.hypot(dx, dy)

    def _move_towards(self, start: LatLng, target: LatLng, distance_m: float) -> LatLng:
        total = self._distance_m(start, target)
        if total <= 0 or distance_m >= total:
            return LatLng(lat=target.lat, lng=target.lng)
        ratio = distance_m / total
        return LatLng(
            lat=start.lat + (target.lat - start.lat) * ratio,
            lng=start.lng + (target.lng - start.lng) * ratio,
        )

    def _build_segment(self, src: dict, dst: dict, name: str | None, route_id: str | None) -> dict:
        src_loc = LatLng(lat=float(src["lat"]), lng=float(src["lng"]))
        dst_loc = LatLng(lat=float(dst["lat"]), lng=float(dst["lng"]))
        return {
            "src": src["id"],
            "dst": dst["id"],
            "src_lat": src_loc.lat,
            "src_lng": src_loc.lng,
            "dst_lat": dst_loc.lat,
            "dst_lng": dst_loc.lng,
            "name": name,
            "distance": round(self._distance_m(src_loc, dst_loc), 2),
            "route_id": route_id,
            "cleaned": False,
        }
