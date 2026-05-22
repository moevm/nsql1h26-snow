from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.models.enums import (
    MapObjectType,
    SimulationStatus,
    VehicleStatus,
    VehicleType,
)

class LatLng(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)

class MapObjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    type: MapObjectType
    location: LatLng
    capacity: Optional[int] = None
    description: Optional[str] = None

class MapObjectRead(MapObjectCreate):
    id: str
    lat: float
    lng: float
    is_infrastructure: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None

class MapObjectUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[LatLng] = None
    capacity: Optional[int] = None
    description: Optional[str] = None

class VehicleConfig(BaseModel):
    type: VehicleType
    count: int = Field(1, ge=1)
    initial_status: VehicleStatus = VehicleStatus.IDLE
    travel_speed_kmh: float = Field(30.0, gt=0)
    cleaning_speed_kmh: float = Field(10.0, gt=0)
    speed_kmh: Optional[float] = Field(None, gt=0, exclude=True)
    capacity_m3: float = Field(10.0, gt=0, description="Объём снега (м³)")
    fuel_capacity_l: float = Field(200.0, gt=0)
    fuel_consumption_l_per_km: float = Field(0.4, gt=0)
    breakdown_probability: float = Field(0.02, ge=0, le=1)
    repair_time_min: float = Field(60.0, ge=0)

    @model_validator(mode="after")
    def _fill_legacy_speed(self) -> "VehicleConfig":
        if self.speed_kmh is not None:
            if self.travel_speed_kmh == 30.0:
                self.travel_speed_kmh = self.speed_kmh
            if self.cleaning_speed_kmh == 10.0:
                self.cleaning_speed_kmh = self.speed_kmh
        return self

class CleaningTask(BaseModel):
    start: LatLng
    end: LatLng
    label: Optional[str] = None
    route_id: Optional[str] = None

class WaypointItem(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    role: str = Field("waypoint", pattern="^(start|waypoint|end)$")

class RouteCreate(BaseModel):
    label: Optional[str] = None
    start: LatLng
    end: LatLng
    path_nodes: list[LatLng] = Field(default_factory=list)
    waypoints: list[WaypointItem] = Field(default_factory=list, description="Промежуточные точки маршрута")

class RouteRead(BaseModel):
    id: str
    label: str
    start: LatLng
    end: LatLng
    path_nodes: list[LatLng] = Field(default_factory=list)
    streets: list[str] = Field(default_factory=list)
    distance_m: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

class RouteUpdate(BaseModel):
    label: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

class SimulationParams(BaseModel):
    vehicles: list[VehicleConfig] = Field(default_factory=lambda: [
        VehicleConfig(type=VehicleType.TRACTOR, count=80),
    ])
    cleaning_tasks: list[CleaningTask] = Field(
        default_factory=list,
        description="Маршруты уборки (от точки A до точки B). Если пусто — симуляция не запустится.",
    )
    speed_multiplier: float = Field(1.0, gt=0, description="Множитель скорости симуляции")
    tick_duration_min: float = Field(5.0, gt=0, description="Длительность тика модели")
    refuel_threshold_pct: float = Field(15.0, ge=0, le=100, description="Порог топлива для заправки")
    dump_threshold_pct: float = Field(90.0, ge=0, le=100, description="Порог загрузки снега для разгрузки")
    snow_melt_rate_m3_per_tick: float = Field(10.0, gt=0, description="Сколько снегоплавильня разгружает за тик")
    snowfall_cm: float = Field(5.0, ge=0, description="Высота снегопада (см)")
    use_real_weather: bool = Field(False, description="Интеграция реальных данных о погоде")
    use_traffic: bool = Field(False, description="Учитывать пробки")

class SimulationState(BaseModel):
    id: str
    name: Optional[str] = None
    status: SimulationStatus
    tick: int = 0
    elapsed_minutes: float = 0.0
    vehicles_active: int = 0
    vehicles_broken: int = 0
    roads_cleaned_pct: float = 0.0
    snow_collected_m3: float = 0.0
    fuel_spent_l: float = 0.0
    vehicles_en_route: int = 0
    vehicles_cleaning: int = 0
    vehicles_dumping: int = 0
    vehicles_refueling: int = 0
    vehicles_maintenance: int = 0
    avg_fuel_pct: float = 0.0
    avg_snow_load_pct: float = 0.0
    streets: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

class SimulationCreate(BaseModel):
    name: Optional[str] = None
    params: SimulationParams = Field(default_factory=SimulationParams)

class RouteRequest(BaseModel):
    start: LatLng
    end: LatLng
    avoid_traffic: bool = False

class RouteSegment(BaseModel):
    coords: list[LatLng]
    distance_m: float
    duration_s: float
    road_name: Optional[str] = None

class RouteResponse(BaseModel):
    segments: list[RouteSegment]
    total_distance_m: float
    total_duration_s: float

class SimulationStats(BaseModel):
    simulation_id: str
    total_time_min: float = 0.0
    roads_cleaned_pct: float = 0.0
    snow_collected_m3: float = 0.0
    fuel_spent_l: float = 0.0
    breakdowns: int = 0
    repair_cost_rub: float = 0.0
    efficiency: float = 0.0

class VehicleState(BaseModel):
    id: str
    type: VehicleType
    status: VehicleStatus = VehicleStatus.IDLE
    location: LatLng
    home_parking_id: Optional[str] = None
    home_parking_location: Optional[LatLng] = None
    fuel_level: float = 100.0
    snow_loaded_m3: float = 0.0
    distance_travelled_km: float = 0.0
    speed_kmh: float = 0.0
    travel_speed_kmh: float = 30.0
    cleaning_speed_kmh: float = 10.0
    fuel_consumption_l_per_km: float = 0.4
    fuel_capacity_l: float = 100.0
    snow_capacity_m3: float = 10.0
    breakdown_probability: float = 0.02
    repair_time_min: float = 60.0
    repair_remaining_min: float = 0.0
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    target_location: Optional[LatLng] = None
    road_target_location: Optional[LatLng] = None
    road_resume_location: Optional[LatLng] = None
    progress_m: float = 0.0
    current_edge: Optional[str] = None
    current_road: Optional[str] = None
    path_waypoints: list[LatLng] = Field(default_factory=list, description="Промежуточные точки пути по графу")

    @model_validator(mode="after")
    def _fill_legacy_vehicle_speed(self) -> "VehicleState":
        legacy = self.speed_kmh or 0.0
        if self.travel_speed_kmh == 30.0 and legacy > 0:
            self.travel_speed_kmh = legacy
        if self.cleaning_speed_kmh == 10.0 and legacy > 0:
            self.cleaning_speed_kmh = legacy
        return self

class TokenRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
