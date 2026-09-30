"""
Data Extraction Layer (plan_v2.md Section 0).

Supports:
- SQL Server extraction via Windows/Integrated Authentication (no stored credentials)
- Manual file upload (CSV/XLSX) as a secondary intake path
- Both write into the same Bronze landing contract: data/bronze/<dataset>/<run_id>/data.parquet
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from app.config import BRONZE_DIR, RUN_LOG_DIR, upload_dir_for


@dataclass
class ExtractionResult:
    dataset: str
    run_id: str
    project_id: str
    source: str  # "sql" or "file"
    row_count: int
    duration_seconds: float
    success: bool
    error: Optional[str] = None
    bronze_path: Optional[str] = None


def _bronze_path(project_id: str, dataset: str, run_id: str) -> Path:
    p = BRONZE_DIR / project_id / dataset / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p / "data.parquet"


def _log_extraction(result: ExtractionResult) -> None:
    log_dir = RUN_LOG_DIR / result.project_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{result.run_id}_extraction.jsonl"
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(result.__dict__) + "\n")


def land_dataframe_to_bronze(
    df: pd.DataFrame,
    dataset: str,
    run_id: str,
    project_id: str,
    source: str,
    duration_seconds: float = 0.0,
) -> ExtractionResult:
    """Write a raw DataFrame (unchanged) into the Bronze layer and log the run."""
    path = _bronze_path(project_id, dataset, run_id)
    df.to_parquet(path, index=False)
    result = ExtractionResult(
        dataset=dataset,
        run_id=run_id,
        project_id=project_id,
        source=source,
        row_count=len(df),
        duration_seconds=duration_seconds,
        success=True,
        bronze_path=str(path),
    )
    _log_extraction(result)
    return result


class SqlServerExtractor:
    """
    Extracts data from SQL Server using Windows/Integrated Authentication.

    Connection string uses Trusted_Connection=yes -- no username/password ever
    stored in code or config, per plan_v2.md Section 0 / Section 19 (Security).
    """

    def __init__(self, server: str, database: str, driver: str = "ODBC Driver 17 for SQL Server"):
        self.server = server
        self.database = database
        self.driver = driver

    def _connection_string(self) -> str:
        return (
            f"mssql+pyodbc://@{self.server}/{self.database}"
            f"?driver={self.driver.replace(' ', '+')}&trusted_connection=yes"
        )

    def extract(
        self,
        dataset: str,
        query: str,
        run_id: str,
        project_id: str,
    ) -> ExtractionResult:
        """Run a full or incremental extraction query and land results to Bronze."""
        from sqlalchemy import create_engine  # local import: optional heavy dep

        start = time.time()
        try:
            engine = create_engine(self._connection_string())
            df = pd.read_sql(query, engine)
            duration = time.time() - start
            return land_dataframe_to_bronze(df, dataset, run_id, project_id, source="sql", duration_seconds=duration)
        except Exception as exc:  # noqa: BLE001
            duration = time.time() - start
            result = ExtractionResult(
                dataset=dataset,
                run_id=run_id,
                project_id=project_id,
                source="sql",
                row_count=0,
                duration_seconds=duration,
                success=False,
                error=str(exc),
            )
            _log_extraction(result)
            return result


class FileExtractor:
    """Secondary intake path: manual CSV/XLSX upload, landed into the same Bronze contract."""

    @staticmethod
    def extract(
        file_path: str,
        dataset: str,
        run_id: str,
        project_id: str,
    ) -> ExtractionResult:
        start = time.time()
        try:
            path = Path(file_path)
            if path.suffix.lower() in (".csv",):
                df = pd.read_csv(path)
            elif path.suffix.lower() in (".xlsx", ".xls"):
                df = pd.read_excel(path)
            else:
                raise ValueError(f"Unsupported file type: {path.suffix}")
            duration = time.time() - start
            return land_dataframe_to_bronze(df, dataset, run_id, project_id, source="file", duration_seconds=duration)
        except Exception as exc:  # noqa: BLE001
            duration = time.time() - start
            result = ExtractionResult(
                dataset=dataset,
                run_id=run_id,
                project_id=project_id,
                source="file",
                row_count=0,
                duration_seconds=duration,
                success=False,
                error=str(exc),
            )
            _log_extraction(result)
            return result


def load_bronze(project_id: str, dataset: str, run_id: str) -> pd.DataFrame:
    path = _bronze_path(project_id, dataset, run_id)
    if not path.exists():
        raise FileNotFoundError(f"No bronze data found for {project_id}/{dataset}/{run_id}")
    return pd.read_parquet(path)


# ---------------------------------------------------------------------------
# Config-driven extraction (configs/extraction_sources.yaml)
# ---------------------------------------------------------------------------

def load_extraction_config() -> dict:
    """Load configs/extraction_sources.yaml (connection + per-dataset queries)."""
    import yaml
    from app.config import CONFIG_DIR

    path = CONFIG_DIR / "extraction_sources.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Extraction source config not found at {path}")
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def sql_extraction_is_configured() -> bool:
    """True if extraction_sources.yaml has a non-empty server/database configured."""
    try:
        cfg = load_extraction_config()
    except FileNotFoundError:
        return False
    conn = cfg.get("connection", {})
    return bool(conn.get("server")) and bool(conn.get("database"))


def extract_dataset_from_sql_config(
    dataset: str, run_id: str, project_id: str
) -> ExtractionResult:
    """Extract a single dataset using the query defined in extraction_sources.yaml."""
    cfg = load_extraction_config()
    conn = cfg["connection"]
    dataset_cfg = cfg["datasets"].get(dataset)
    if dataset_cfg is None:
        raise KeyError(f"No extraction config entry for dataset '{dataset}'")

    extractor = SqlServerExtractor(
        server=conn["server"], database=conn["database"], driver=conn.get("driver", "ODBC Driver 17 for SQL Server")
    )
    return extractor.extract(dataset=dataset, query=dataset_cfg["query"], run_id=run_id, project_id=project_id)


def extract_all_datasets_from_sql_config(run_id: str, project_id: str) -> Dict[str, ExtractionResult]:
    """Extract all datasets defined in extraction_sources.yaml."""
    cfg = load_extraction_config()
    results = {}
    for dataset in cfg["datasets"]:
        results[dataset] = extract_dataset_from_sql_config(dataset, run_id, project_id)
    return results


def save_extraction_config(cfg: dict) -> None:
    """Persist the extraction_sources.yaml config (connection + per-dataset queries)."""
    import yaml
    from app.config import CONFIG_DIR

    path = CONFIG_DIR / "extraction_sources.yaml"
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False, default_flow_style=False)


def test_sql_connection(server: str, database: str, driver: str = "ODBC Driver 17 for SQL Server") -> dict:
    """
    Attempt a live connection using Windows/Integrated Authentication and run
    a trivial query to confirm connectivity. Never stores credentials -- uses
    Trusted_Connection=yes exclusively.
    """
    from sqlalchemy import create_engine, text

    extractor = SqlServerExtractor(server=server, database=database, driver=driver)
    try:
        engine = create_engine(extractor._connection_string())
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"success": True, "message": f"Connected to '{server}/{database}' successfully."}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "message": str(exc)}


def list_available_odbc_drivers() -> List[str]:
    import pyodbc

    return [d for d in pyodbc.drivers() if "SQL Server" in d]


# ---------------------------------------------------------------------------
# Uploaded-file extraction (per-project persistent upload storage)
# ---------------------------------------------------------------------------

def save_uploaded_file(project_id: str, dataset: str, filename: str, content: bytes) -> Path:
    """Persist an uploaded CSV/XLSX to data/uploads/<project_id>/<dataset><ext>."""
    ext = Path(filename).suffix.lower()
    if ext not in (".csv", ".xlsx", ".xls"):
        raise ValueError(f"Unsupported file type '{ext}'. Only .csv, .xlsx, .xls are supported.")
    dest = upload_dir_for(project_id) / f"{dataset}{ext}"
    with open(dest, "wb") as fh:
        fh.write(content)
    return dest


def get_uploaded_file_path(project_id: str, dataset: str) -> Optional[Path]:
    """Return the path to the dataset's uploaded file, if one exists."""
    d = upload_dir_for(project_id)
    for ext in (".csv", ".xlsx", ".xls"):
        candidate = d / f"{dataset}{ext}"
        if candidate.exists():
            return candidate
    return None


def extract_dataset_from_uploaded_file(dataset: str, run_id: str, project_id: str) -> ExtractionResult:
    """Extract a single dataset from its previously uploaded CSV/XLSX file into Bronze."""
    path = get_uploaded_file_path(project_id, dataset)
    if path is None:
        return ExtractionResult(
            dataset=dataset,
            run_id=run_id,
            project_id=project_id,
            source="file",
            row_count=0,
            duration_seconds=0.0,
            success=False,
            error=f"No uploaded file found for dataset '{dataset}'.",
        )
    return FileExtractor.extract(str(path), dataset, run_id, project_id)
