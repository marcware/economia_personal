"""Reconstruye la cartera de Bit2Me a partir de su propio historial, sin mirar el banco.

Entradas: las operaciones del wallet (/v2/wallet/transaction), las compras/ventas de Pro
(/v1/trading/trade) y los saldos actuales por moneda. Salidas:

- aportaciones: dinero de fuera (tarjeta, transferencia) que entra en Bit2Me (+) o sale a
  una cuenta o tarjeta (−). Pasar de wallet a Earn o a Pro, o comprar con el saldo en
  euros, es interno y no cuenta.
- por moneda: coste de lo que queda (FIFO, como lo calcula Hacienda para las criptos),
  resultado ya realizado en las ventas y recompensas de Earn (lo que hay de más respecto a
  lo comprado, a coste cero).
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date

EXTERNAS = {"card", "bank-transfer", "bank-account"}
EUR = "EUR"


@dataclass
class Moneda:
    lotes: deque = field(default_factory=deque)  # [cantidad, coste] por compra, la más antigua primero
    comprado_eur: float = 0.0
    vendido_eur: float = 0.0
    realizado: float = 0.0  # ganancia/pérdida ya cerrada en ventas

    def comprar(self, cantidad: float, coste: float) -> None:
        if cantidad > 0:
            self.lotes.append([cantidad, coste])
            self.comprado_eur += coste

    def consumir(self, cantidad: float) -> float:
        """Saca `cantidad` de los lotes más antiguos y devuelve su coste."""
        coste = 0.0
        while cantidad > 1e-12 and self.lotes:
            lote = self.lotes[0]
            usado = min(cantidad, lote[0])
            parte = lote[1] * usado / lote[0]
            coste += parte
            lote[0] -= usado
            lote[1] -= parte
            cantidad -= usado
            if lote[0] <= 1e-12:
                self.lotes.popleft()
        return coste

    def vender(self, cantidad: float, ingreso: float) -> None:
        self.realizado += ingreso - self.consumir(cantidad)
        self.vendido_eur += ingreso

    @property
    def cantidad(self) -> float:
        return sum(l[0] for l in self.lotes)

    @property
    def coste(self) -> float:
        return sum(l[1] for l in self.lotes)


def _lado(op: dict, clave: str) -> tuple[str, float, str]:
    lado = op.get(clave) or {}
    return (lado.get("currency") or "").upper(), float(lado.get("amount") or 0), lado.get("class") or ""


def _fecha(texto: str) -> date:
    return date.fromisoformat(texto[:10])


def calcular(operaciones: list[dict], trades_pro: list[dict], saldos: dict[str, float]) -> dict:
    monedas: dict[str, Moneda] = defaultdict(Moneda)
    aportaciones = []
    comisiones = 0.0
    avisos = []

    eventos = [("wallet", op["date"], op) for op in operaciones if op.get("status") == "completed"]
    eventos += [("pro", t.get("createdAt") or "", t) for t in trades_pro]
    for fuente, _, op in sorted(eventos, key=lambda e: e[1]):
        if fuente == "pro":
            base, _, cotiza = (op.get("symbol") or "").upper().partition("/")
            cantidad, coste = float(op.get("amount") or 0), float(op.get("cost") or 0)
            if cotiza != EUR:
                avisos.append(f"Operación de Pro en {op.get('symbol')} sin euros: no se cuenta")
            elif op.get("side") == "buy":
                monedas[base].comprar(cantidad, coste)
            elif op.get("side") == "sell":
                monedas[base].vender(cantidad, coste)
            continue

        o_mon, o_cant, o_clase = _lado(op, "origin")
        d_mon, d_cant, d_clase = _lado(op, "destination")
        if o_clase in EXTERNAS:  # entra dinero de fuera
            if o_mon != EUR:
                avisos.append(f"Entrada externa en {o_mon} el {op['date'][:10]}: no se cuenta")
                continue
            aportaciones.append({"id": op["id"], "fecha": _fecha(op["date"]), "importe": o_cant})
            if d_mon == EUR:
                comisiones += o_cant - d_cant  # la tarjeta cobra al cargar saldo
            else:
                monedas[d_mon].comprar(d_cant, o_cant)
        elif d_clase in EXTERNAS:  # sale dinero a una cuenta o tarjeta
            if o_mon != EUR:
                avisos.append(f"Salida externa en {o_mon} el {op['date'][:10]}: no se cuenta")
                continue
            aportaciones.append({"id": op["id"], "fecha": _fecha(op["date"]), "importe": -d_cant})
        elif op.get("type") == "transfer" and o_mon == EUR and d_mon != EUR:
            monedas[d_mon].comprar(d_cant, o_cant)
        elif op.get("type") == "transfer" and o_mon != EUR and d_mon == EUR:
            monedas[o_mon].vender(o_cant, d_cant)
        elif op.get("type") == "transfer" and o_mon != d_mon:
            avisos.append(f"Cambio {o_mon}→{d_mon} el {op['date'][:10]}: no se cuenta")
        # El resto (wallet ↔ Earn ↔ Pro) son movimientos internos.

    posiciones = []
    for simbolo in sorted(set(monedas) | set(saldos)):
        if simbolo == EUR:
            continue
        m = monedas[simbolo]
        tengo = saldos.get(simbolo, 0.0)
        diferencia = tengo - m.cantidad
        recompensas = 0.0
        if diferencia > 0:
            recompensas = diferencia  # Earn: llega sin pagar nada
            m.lotes.append([diferencia, 0.0])
        elif diferencia < 0:
            comisiones += m.consumir(-diferencia)  # comisiones cobradas en la propia cripto
        posiciones.append({
            "symbol": simbolo, "cantidad": tengo, "coste": m.coste, "realizado": m.realizado,
            "recompensas": recompensas, "comprado": m.comprado_eur, "vendido": m.vendido_eur,
        })
    return {"aportaciones": aportaciones, "posiciones": posiciones, "comisiones": comisiones, "avisos": avisos}
