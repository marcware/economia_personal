"""Formato de importes y números a la española, compartido por plantillas y textos de consejos."""


def numero(valor: float, decimales: int = 2) -> str:
    """1234.5 -> "1.234,50" (miles con punto, decimales con coma)."""
    texto = f"{abs(valor):,.{decimales}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    negativo = valor < 0 and texto.strip("0,.") != ""
    return f"{'−' if negativo else ''}{texto}"


def eur(valor: float, decimales: int = 2) -> str:
    """Importe con su símbolo: 1.234,50 € (espacio de no separación)."""
    return f"{numero(valor, decimales)} €"
