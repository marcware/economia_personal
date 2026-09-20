# Economía Personal

App local para revisar tu economía personal: dashboard mensual de ingresos/gastos por categoría,
presupuestos mensuales con hitos, patrimonio neto y un "coach financiero" que avisa de desvíos. Los
movimientos de ING llegan solos vía [Enable Banking](https://enablebanking.com) (Open Banking/PSD2) —
nada de exportar CSVs a mano; Mediolanum se importa a mano de un Excel de vez en cuando (tiene pocos
movimientos, no compensa automatizarlo).

Guía técnica para quien programe esto (yo con Claude Code) en `CLAUDE.md`. Esto de aquí es la guía de
uso del día a día.

## Arrancar

```bash
cd ~/Develop/Marcos/economia_personal
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000 \
  --ssl-keyfile secrets/localhost.key --ssl-certfile secrets/localhost.crt
```

Abre **https://localhost:8000**. El navegador avisará de "conexión no segura" — es el certificado
autofirmado, normal en local; acepta el aviso una vez por sesión de navegador.

El `--reload` es importante: sin él, si se toca código con el servidor ya arrancado, la web sigue
sirviendo el código viejo y puede dar error 500 aunque el fichero en disco ya esté arreglado. Con
`--reload` puesto, cualquier cambio se recoge solo.

## Parar

`Ctrl+C` en la terminal donde está corriendo. Si lo lanzaste en segundo plano y no encuentras la
terminal:

```bash
pkill -f "uvicorn app.main:app"
```

## Tareas habituales

Todas se ejecutan con el entorno activado (`source .venv/bin/activate`) desde la raíz del proyecto.

| Quiero... | Comando |
|---|---|
| Traer movimientos nuevos de ING | `python scripts/sync_accounts.py` |
| Importar un Excel nuevo de Mediolanum | `python scripts/import_mediolanum.py ruta/al/fichero.xlsx` |
| Ver un resumen del mes por terminal (lo que uso yo para revisar tus cuentas) | `python scripts/informe_mensual.py [año] [mes]` (sin argumentos, el mes en curso) |
| Cargar presupuestos de un mes desde la plantilla anual | `python scripts/seed_presupuestos.py <año> <mes> --con-variables --dry-run` primero para revisar, luego sin `--dry-run` |
| Aplicar cambios de base de datos tras una actualización | `alembic upgrade head` |

Categorizar movimientos pendientes se hace desde la propia web, en **Movimientos → Categorizar
pendientes agrupados por comercio** — asigna una categoría una vez y se aplica también a los futuros.

## Instalación desde cero (otro ordenador, o si se corrompe el entorno)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env              # y rellena tus credenciales de Enable Banking (ver abajo)
alembic upgrade head              # crea/actualiza data/economia.db
python scripts/seed_categories.py # categorías y reglas de partida
```

Luego arranca normal (sección "Arrancar" arriba).

## Conectar un banco (ING vía Enable Banking)

Solo hace falta una vez, o cuando caduque el consentimiento (cada ~90 días, límite normativo PSD2 — la
web avisa con "(caducado, reautoriza)" en **Conexiones**):

1. Cuenta gratuita en https://enablebanking.com y genera tu par de claves desde su Control Panel.
2. Copia el `application_id` y la clave privada a `.env` / `secrets/` (nunca se suben al repo).
3. Registra `https://localhost:8000/conexiones/callback` como redirect URL permitida.
4. Desde `/conexiones`, "Conectar con ING" y autoriza iniciando sesión en tu banco.

Bit2Me y Quanloop no se conectan como cuentas bancarias: se registran a mano en **Patrimonio →
Inversiones declaradas** cada vez que quieras actualizar el valor (queda guardado el histórico, no solo
el último dato).

## Si algo no va

- **Error 500 justo después de tocar código**: reinicia el servidor con `--reload` (ver arriba); si ya
  lo tenía puesto, mira el mensaje de error en la terminal donde corre uvicorn.
- **"Conexión no segura" en el navegador**: normal, es el certificado autofirmado de desarrollo — acepta
  el aviso.
- **Un banco pide reautorizar**: el consentimiento PSD2 caduca cada ~90 días, repite el paso 4 de
  "Conectar un banco".
