# Economía Personal

App local para revisar tu economía personal: dashboard mensual de ingresos/gastos por categoría y un motor de consejos tipo "coach financiero". Los movimientos se traen desde ING vía la API de [Enable Banking](https://enablebanking.com) (Open Banking / PSD2) — nada de exportar CSVs a mano.

## Puesta en marcha

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # y rellena las credenciales de Enable Banking
uvicorn app.main:app --reload --port 8000 \
  --ssl-keyfile secrets/localhost.key --ssl-certfile secrets/localhost.crt
```

Abre https://localhost:8000 (el navegador avisará de "conexión no segura" por ser un certificado autofirmado — es normal en local, acepta el aviso una vez).

Enable Banking exige que la redirect URL de una app en Production sea HTTPS incluso en localhost, por eso el servidor local también corre con TLS (certificado autofirmado en `secrets/localhost.{key,crt}`, generado con OpenSSL, gitignored).

## Estado del proyecto

En construcción — ver el plan en `/home/marcware/.claude/plans/vale-mira-quiero-eh-cosmic-sloth.md`. Fases:

0. ✅ Andamiaje del proyecto
1. Modelo de datos (SQLAlchemy + Alembic + categorías semilla)
2. Cliente Enable Banking mínimo (confirmar cobertura de ING)
3. Flujo de conexión (autorización con ING)
4. Sincronización de movimientos
5. Categorización automática
6. Dashboard mensual
7. CRUD (movimientos, categorías, presupuestos)
8. Motor de consejos
9. Pulido v1

## Conectar con ING (cuando lleguemos a la Fase 2-3)

1. Crea una cuenta gratuita en https://enablebanking.com y genera tu par de claves/certificado desde su Control Panel.
2. Copia el `application_id` y la clave privada a `.env` / `secrets/` (nunca se suben al repo, están en `.gitignore`).
3. Registra `http://localhost:8000/conexiones/callback` como redirect URL permitido.
4. Desde `/conexiones`, pulsa "Conectar con ING" y autoriza el acceso iniciando sesión en tu banco. El consentimiento hay que renovarlo cada ~90 días (límite normativo PSD2).
