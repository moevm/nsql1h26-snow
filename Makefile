.PHONY: help infra download migrate app up down stop restart build pull logs ps clean reset

COMPOSE ?= docker compose
INFRA_SERVICES ?= db redis jaeger
APP_SERVICE ?= app
MIGRATION_SERVICE ?= neo4j-migrations
DOWNLOADER_SERVICE ?= osm-downloader

help:
	@awk 'BEGIN {FS = ":.*## "; printf "Available targets:\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

infra:
	$(COMPOSE) up -d $(INFRA_SERVICES)

download:
	$(COMPOSE) up --wait $(DOWNLOADER_SERVICE)

migrate:
	$(COMPOSE) run --rm $(MIGRATION_SERVICE)

app:
	$(COMPOSE) up -d $(APP_SERVICE)

up:
	$(MAKE) infra
	$(MAKE) download
	$(MAKE) migrate
	$(MAKE) app

down:
	$(COMPOSE) down

stop:
	$(COMPOSE) stop

restart:
	$(COMPOSE) restart $(APP_SERVICE) $(INFRA_SERVICES)

build:
	$(COMPOSE) build

pull:
	$(COMPOSE) pull

logs:
	$(COMPOSE) logs -f --tail=100 $(SERVICE)

ps:
	$(COMPOSE) ps

clean:
	$(COMPOSE) down --remove-orphans

reset:
	$(COMPOSE) down -v --remove-orphans
