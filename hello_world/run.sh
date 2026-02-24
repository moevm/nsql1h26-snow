#!/bin/sh
docker compose up --build --abort-on-container-exit --exit-code-from hello
docker compose down -v
