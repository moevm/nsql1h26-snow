from enum import Enum

class VehicleType(str, Enum):
    TRACTOR = "tractor"

class VehicleStatus(str, Enum):
    IDLE = "idle"
    EN_ROUTE = "en_route"
    OFF_ROUTE = "off_route"
    CLEANING = "cleaning"
    DUMPING = "dumping"
    REFUELING = "refueling"
    BROKEN = "broken"
    MAINTENANCE = "maintenance"

class MapObjectType(str, Enum):
    PARKING = "parking"
    SNOW_POLYGON = "snow_polygon"
    SERVICE_STATION = "service_station"

class SimulationStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"
    ERROR = "error"
