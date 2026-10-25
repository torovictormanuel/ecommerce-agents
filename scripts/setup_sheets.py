"""
setup_sheets.py — Crea el Google Spreadsheet con todas las pestañas del sistema.

Uso:
    python scripts/setup_sheets.py

Requisitos:
    pip install gspread google-auth
    Tener config/credentials.json (Service Account de Google Cloud)

El script imprime el SHEETS_SPREADSHEET_ID al final para pegarlo en .env
"""

import sys
from pathlib import Path

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    print("Instalando dependencias...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "gspread", "google-auth"])
    import gspread
    from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

CREDENTIALS_PATH = Path(__file__).parent.parent / "config" / "credentials.json"

SHEETS = {
    "Inventario": [
        "ID", "Nombre", "SKU", "Precio", "Stock",
        "Descripcion", "Categoria", "Activo",
    ],
    "Ordenes": [
        "ID_Orden", "Fecha", "Estado", "Cliente",
        "Productos", "Total", "Canal", "Notas",
    ],
    "Catalogo": [
        "ID", "Nombre", "Descripcion", "Precio",
        "URL_Imagen", "Categoria", "Tags", "Activo",
    ],
    "Contactos": [
        "ID", "Nombre", "Telefono", "Email",
        "Canal", "Ultima_Interaccion", "Tags", "Notas",
    ],
    "PregunSinRespuesta": [
        "Timestamp", "Agente", "Pregunta", "Razon", "Canal",
    ],
}

SPREADSHEET_ID = "1IpyfjI3yeD5BQwioVBqBBC_nUgqsfI3ms_Xw4PWuDQs"


def main() -> None:
    if not CREDENTIALS_PATH.exists():
        print(f"ERROR: No se encontró {CREDENTIALS_PATH}")
        sys.exit(1)

    print(f"Autenticando con {CREDENTIALS_PATH}...")
    creds = Credentials.from_service_account_file(str(CREDENTIALS_PATH), scopes=SCOPES)
    gc = gspread.authorize(creds)

    print(f"Abriendo spreadsheet {SPREADSHEET_ID}...")
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)

    # Renombrar primera pestaña si tiene nombre genérico
    first_ws = spreadsheet.sheet1
    first_sheet_name = list(SHEETS.keys())[0]
    if first_ws.title in ("Sheet1", "Hoja 1", "Hoja1"):
        first_ws.update_title(first_sheet_name)
        print(f"  ✓ Pestaña renombrada a '{first_sheet_name}'")

    existing = [ws.title for ws in spreadsheet.worksheets()]

    for name, headers in SHEETS.items():
        if name in existing:
            ws = spreadsheet.worksheet(name)
            print(f"  ~ Pestaña '{name}' ya existe, actualizando encabezados...")
        else:
            ws = spreadsheet.add_worksheet(title=name, rows=500, cols=len(headers))
            print(f"  ✓ Pestaña '{name}' creada")
        ws.update("A1", [headers])

    url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}"
    print()
    print("=" * 60)
    print(f"✅ Spreadsheet configurado: {url}")
    print(f"SHEETS_SPREADSHEET_ID={SPREADSHEET_ID}  ← ya está en .env")
    print("=" * 60)


if __name__ == "__main__":
    main()
