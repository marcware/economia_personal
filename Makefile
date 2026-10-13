# Economía personal — atajos para levantar y mantener la app.
# Ejecuta `make` (o `make help`) para ver los comandos disponibles.

VENV   := .venv
PY     := $(VENV)/bin/python
PORT   ?= 8000
KEY    := secrets/localhost.key
CRT    := secrets/localhost.crt

.DEFAULT_GOAL := help
.PHONY: help setup install certs migrate seed run sync informe import-mediolanum test

help: ## Muestra esta ayuda
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Primera vez:  make setup   (luego rellena .env)  →  make run"

setup: install certs migrate ## Primera instalación completa (venv, certificados, .env, BD)
	@test -f .env || (cp .env.example .env && echo "Creado .env: rellena las credenciales de Enable Banking")

$(PY):
	python3 -m venv $(VENV)

install: $(PY) ## Crea el venv e instala dependencias (incluidas las de dev)
	$(PY) -m pip install -e ".[dev]"

certs: $(CRT) ## Genera el certificado autofirmado para HTTPS en localhost

$(CRT):
	mkdir -p secrets
	openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
		-keyout $(KEY) -out $(CRT) -subj "/CN=localhost" \
		-addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

migrate: ## Aplica las migraciones de Alembic
	$(VENV)/bin/alembic upgrade head

seed: ## Carga el árbol de categorías y reglas iniciales
	$(PY) scripts/seed_categories.py

run: $(CRT) ## Levanta la app en https://localhost:8000 (PORT=… para cambiarlo) con recarga automática
	$(VENV)/bin/uvicorn app.main:app --reload --port $(PORT) \
		--ssl-keyfile $(KEY) --ssl-certfile $(CRT)

sync: ## Sincroniza movimientos de las cuentas vinculadas (ING)
	$(PY) scripts/sync_accounts.py

informe: ## Informe mensual (opcional: make informe Y=2026 M=9)
	$(PY) scripts/informe_mensual.py $(Y) $(M)

import-mediolanum: ## Importa un XLS de Mediolanum (make import-mediolanum FILE=ruta.xls)
	@test -n "$(FILE)" || (echo "Uso: make import-mediolanum FILE=ruta/al/extracto.xls" && exit 1)
	$(PY) scripts/import_mediolanum.py $(FILE)

test: ## Ejecuta los tests
	$(PY) -m pytest
