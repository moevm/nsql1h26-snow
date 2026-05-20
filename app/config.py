from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "snowcleaning2026"

    redis_url: str = "redis://localhost:6379/0"

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    secret_key: str = "super-secret-jwt-key-change-in-production"
    access_token_expire_minutes: int = 60

    openweathermap_api_key: str = ""
    traffic_api_key: str = ""

    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "snow-cleaning-simulation"

    geojson_path: str = "./app/saint-petersburg.osm"

    pbf_url: str = "https://download.geofabrik.de/russia/northwestern-fed-district-latest.osm.pbf"
    osm_bbox: str = "30.2970,59.9665,30.3305,59.9805"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

@lru_cache
def get_settings() -> Settings:
    return Settings()
