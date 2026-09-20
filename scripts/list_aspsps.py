"""Consulta GET /aspsps para España y busca bancos que coincidan con ING/Mediolanum.

Uso:
    python scripts/list_aspsps.py
"""

from app.integrations.enablebanking.client import EnableBankingClient


def main() -> None:
    client = EnableBankingClient()
    aspsps = client.list_aspsps(country="ES")
    print(f"{len(aspsps)} ASPSPs encontrados para España.\n")

    for aspsp in aspsps:
        name = aspsp.get("name", "")
        if "ing" in name.lower() or "mediolanum" in name.lower():
            print(f"COINCIDENCIA -> {aspsp}")

    print("\n--- Listado completo de nombres ---")
    for aspsp in sorted(aspsps, key=lambda a: a.get("name", "")):
        print(f"- {aspsp.get('name')}")


if __name__ == "__main__":
    main()
