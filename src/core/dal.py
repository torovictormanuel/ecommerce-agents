"""
Data Access Layer — adaptador intercambiable entre Google Sheets y Excel.
Los agentes sólo usan DataAccessLayer; nunca la implementación subyacente.
Cambiar DAL_MODE=sheets|excel en .env es suficiente para cambiar la fuente.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


# ── Interfaz base ─────────────────────────────────────────────────────────────

class DataAdapter(ABC):
    @abstractmethod
    def read(self, sheet: str, filters: dict | None = None) -> list[dict]:
        """Lee filas de una hoja/tabla, opcionalmente filtradas por {col: valor}."""

    @abstractmethod
    def write(self, sheet: str, row_id: str, updates: dict) -> bool:
        """Actualiza campos de la fila identificada por su columna 'ID'."""

    @abstractmethod
    def append(self, sheet: str, row: dict) -> str:
        """Inserta una fila nueva y retorna el ID asignado."""


# ── Google Sheets ─────────────────────────────────────────────────────────────

class GoogleSheetsAdapter(DataAdapter):
    _SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

    def __init__(self, credentials_path: str, spreadsheet_id: str) -> None:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_service_account_file(
            credentials_path, scopes=self._SCOPES)
        self._svc = build("sheets", "v4", credentials=creds)
        self._sid = spreadsheet_id
        logger.info("GoogleSheetsAdapter inicializado — spreadsheet: %s", spreadsheet_id)

    def _get_all(self, sheet: str) -> tuple[list[str], list[dict]]:
        res = (self._svc.spreadsheets().values()
               .get(spreadsheetId=self._sid, range=sheet).execute())
        rows = res.get("values", [])
        if not rows:
            return [], []
        headers = rows[0]
        data = [
            {h: (row[i] if i < len(row) else "") for i, h in enumerate(headers)}
            for row in rows[1:]
        ]
        return headers, data

    def read(self, sheet: str, filters: dict | None = None) -> list[dict]:
        _, data = self._get_all(sheet)
        if filters:
            for k, v in filters.items():
                data = [r for r in data if r.get(k) == str(v)]
        return data

    def write(self, sheet: str, row_id: str, updates: dict) -> bool:
        headers, data = self._get_all(sheet)
        for i, row in enumerate(data, start=2):  # fila 1 = encabezados
            if row.get("ID") == str(row_id):
                for col, val in updates.items():
                    if col in headers:
                        col_idx = headers.index(col)
                        cell = f"{sheet}!{chr(65 + col_idx)}{i}"
                        (self._svc.spreadsheets().values()
                         .update(spreadsheetId=self._sid, range=cell,
                                 valueInputOption="USER_ENTERED",
                                 body={"values": [[str(val)]]}).execute())
                return True
        return False

    def append(self, sheet: str, row: dict) -> str:
        headers, existing = self._get_all(sheet)
        if not headers:
            headers = list(row.keys())
        new_id = f"row_{len(existing) + 1}"
        row.setdefault("ID", new_id)
        values = [[str(row.get(h, "")) for h in headers]]
        (self._svc.spreadsheets().values()
         .append(spreadsheetId=self._sid, range=f"{sheet}!A1",
                 valueInputOption="USER_ENTERED",
                 body={"values": values}).execute())
        return str(row["ID"])


# ── Excel (.xlsx) ─────────────────────────────────────────────────────────────

class ExcelAdapter(DataAdapter):
    def __init__(self, file_path: str) -> None:
        self._path = file_path
        self._cache: dict[str, pd.DataFrame] = {}
        logger.info("ExcelAdapter inicializado — archivo: %s", file_path)

    def _load(self, sheet: str) -> pd.DataFrame:
        if sheet not in self._cache:
            self._cache[sheet] = pd.read_excel(
                self._path, sheet_name=sheet, dtype=str).fillna("")
        return self._cache[sheet]

    def _flush(self, sheet: str, df: pd.DataFrame) -> None:
        self._cache[sheet] = df
        with pd.ExcelWriter(
            self._path, engine="openpyxl", mode="a", if_sheet_exists="replace"
        ) as w:
            df.to_excel(w, sheet_name=sheet, index=False)

    def read(self, sheet: str, filters: dict | None = None) -> list[dict]:
        df = self._load(sheet).copy()
        if filters:
            for k, v in filters.items():
                if k in df.columns:
                    df = df[df[k] == str(v)]
        return df.to_dict("records")

    def write(self, sheet: str, row_id: str, updates: dict) -> bool:
        df = self._load(sheet).copy()
        mask = df["ID"] == str(row_id)
        if not mask.any():
            return False
        for col, val in updates.items():
            if col in df.columns:
                df.loc[mask, col] = str(val)
        self._flush(sheet, df)
        return True

    def append(self, sheet: str, row: dict) -> str:
        df = self._load(sheet)
        new_id = f"row_{len(df) + 1}"
        row.setdefault("ID", new_id)
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        self._flush(sheet, df)
        return str(row["ID"])


# ── DAL facade ────────────────────────────────────────────────────────────────

class DataAccessLayer:
    """
    Punto de entrada único para todos los agentes.
    El adaptador subyacente se selecciona por el tipo configurado.
    """

    def __init__(self, adapter: DataAdapter, sheets_map: dict[str, str]) -> None:
        self._adapter = adapter
        self._sheets_map = sheets_map  # lógico → nombre real en la hoja

    def _resolve(self, logical: str) -> str:
        return self._sheets_map.get(logical, logical)

    def read(self, sheet: str, filters: dict | None = None) -> list[dict]:
        try:
            return self._adapter.read(self._resolve(sheet), filters)
        except Exception as e:
            logger.error("DAL.read(%s) error: %s", sheet, e)
            return []

    def write(self, sheet: str, row_id: str, updates: dict) -> bool:
        try:
            return self._adapter.write(self._resolve(sheet), row_id, updates)
        except Exception as e:
            logger.error("DAL.write(%s, %s) error: %s", sheet, row_id, e)
            return False

    def append(self, sheet: str, row: dict) -> str:
        try:
            return self._adapter.append(self._resolve(sheet), row)
        except Exception as e:
            logger.error("DAL.append(%s) error: %s", sheet, e)
            return ""

    def get_product(self, sku: str) -> dict | None:
        rows = self.read("inventory", {"SKU": sku})
        return rows[0] if rows else None

    def get_order(self, order_id: str) -> dict | None:
        rows = self.read("orders", {"Order_ID": order_id})
        return rows[0] if rows else None

    def get_catalog_item(self, sku: str) -> dict | None:
        rows = self.read("catalog", {"SKU": sku})
        return rows[0] if rows else None


# ── Factory ───────────────────────────────────────────────────────────────────

def build_dal(config: "AppConfig") -> DataAccessLayer:  # type: ignore[name-defined]
    ds = config.data_source
    if ds.type == "sheets":
        adapter = GoogleSheetsAdapter(
            ds.sheets.credentials_path,
            ds.sheets.spreadsheet_id,
        )
        sheets_map = ds.sheets.sheets_map
    else:
        adapter = ExcelAdapter(ds.excel.file_path)
        sheets_map = ds.excel.sheets_map

    return DataAccessLayer(adapter, sheets_map)
