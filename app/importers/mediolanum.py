"""Importador manual del extracto XLS de Banco Mediolanum.

Solución temporal mientras la conexión vía Enable Banking no funcione (su conector
beta para Mediolanum devuelve `server_error` de forma persistente). Formato propio
de Mediolanum: importe en dos columnas separadas (Pagos/Ingresos) en vez de un
importe único con signo como en ING, y cabecera no está en la primera fila.
"""

import pandas as pd

COL_DATE = "Fecha Operación"
COL_DESCRIPTION = "Concepto"
COL_PAGOS = "Pagos"
COL_INGRESOS = "Ingresos"
COL_BALANCE = "Saldo"


def _find_header_row(file_path: str) -> int:
    raw = pd.read_excel(file_path, header=None, nrows=30)
    for idx, row in raw.iterrows():
        values = {str(v).strip() for v in row.tolist()}
        if COL_DATE in values and COL_DESCRIPTION in values:
            return idx
    raise ValueError(f"No se encontró la fila de cabecera esperada en {file_path!r}")


def parse_mediolanum_xls(file_path: str) -> list[dict]:
    header_row = _find_header_row(file_path)
    df = pd.read_excel(file_path, header=header_row)
    df = df.dropna(subset=[COL_DATE, COL_DESCRIPTION])

    transactions = []
    for _, row in df.iterrows():
        pagos = row.get(COL_PAGOS)
        ingresos = row.get(COL_INGRESOS)

        if pd.notna(pagos) and float(pagos) != 0:
            amount = -float(pagos)
        elif pd.notna(ingresos) and float(ingresos) != 0:
            amount = float(ingresos)
        else:
            continue

        date_value = row[COL_DATE]
        if hasattr(date_value, "date"):
            date_value = date_value.date()

        transactions.append({
            "date": date_value,
            "description": str(row[COL_DESCRIPTION]).strip(),
            "amount": amount,
            "balance": row.get(COL_BALANCE),
        })
    return transactions
