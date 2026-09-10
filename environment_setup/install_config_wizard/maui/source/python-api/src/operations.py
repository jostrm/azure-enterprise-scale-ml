"""Read-only operational views and persisted operations configuration."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from http.client import HTTPException as HTTPTransportError
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from src.region_findings import RegionFindingsStore
from src.project_metadata import owner_from_project_state


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def resolve_azure_cli() -> str:
    """Resolve an executable Azure CLI entry point for shell-free subprocesses."""
    candidates = ("az.exe", "az.cmd", "az") if sys.platform == "win32" else ("az",)
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    searched = ", ".join(candidates)
    raise RuntimeError(
        "Azure CLI executable was not found on PATH "
        f"(looked for: {searched}). Install Azure CLI or add its executable "
        "directory to the API process PATH."
    )


def _azure_cli_command(executable: str) -> list[str]:
    """Return an argv prefix that avoids Windows batch-file command parsing."""
    path = Path(executable)
    if sys.platform == "win32" and path.suffix.casefold() in {".cmd", ".bat"}:
        bundled_python = path.parent.parent / "python.exe"
        if bundled_python.is_file():
            return [str(bundled_python), "-IBm", "azure.cli"]
        raise RuntimeError(
            f"Azure CLI launcher '{executable}' is a batch file, but its bundled "
            f"Python executable was not found at '{bundled_python}'. Reinstall "
            "Azure CLI or add an az.exe installation to PATH."
        )
    return [executable]


# Public Azure cloud regions. Coordinates are city/metro centroids and are
# normalized for direct use by a map whose axes span -1..1.
_REGION_DATA = [
    ("australiacentral", "Australia Central", "Australia", "Canberra", -35.28, 149.13),
    ("australiacentral2", "Australia Central 2", "Australia", "Canberra", -35.28, 149.13),
    ("australiaeast", "Australia East", "Australia", "New South Wales", -33.87, 151.21),
    ("australiasoutheast", "Australia Southeast", "Australia", "Victoria", -37.81, 144.96),
    ("austriaeast", "Austria East", "Europe", "Vienna", 48.21, 16.37),
    ("belgiumcentral", "Belgium Central", "Europe", "Brussels", 50.85, 4.35),
    ("brazilsouth", "Brazil South", "South America", "São Paulo State", -23.55, -46.63),
    ("brazilsoutheast", "Brazil Southeast", "South America", "Rio de Janeiro", -22.91, -43.17),
    ("canadacentral", "Canada Central", "Canada", "Toronto", 43.65, -79.38),
    ("canadaeast", "Canada East", "Canada", "Quebec City", 46.81, -71.21),
    ("centralindia", "Central India", "India", "Pune", 18.52, 73.86),
    ("centralus", "Central US", "United States", "Iowa", 41.59, -93.62),
    ("chilecentral", "Chile Central", "South America", "Santiago", -33.45, -70.67),
    ("denmarkeast", "Denmark East", "Europe", "Copenhagen", 55.68, 12.57),
    ("eastasia", "East Asia", "Asia Pacific", "Hong Kong", 22.32, 114.17),
    ("eastus", "East US", "United States", "Virginia", 37.43, -78.66),
    ("eastus2", "East US 2", "United States", "Virginia", 36.67, -78.39),
    ("eastus2euap", "East US 2 EUAP", "United States", "Virginia", 36.67, -78.39),
    ("francecentral", "France Central", "Europe", "Paris", 48.86, 2.35),
    ("francesouth", "France South", "Europe", "Marseille", 43.30, 5.37),
    ("germanynorth", "Germany North", "Europe", "Berlin", 52.52, 13.41),
    ("germanywestcentral", "Germany West Central", "Europe", "Frankfurt", 50.11, 8.68),
    ("greececentral", "Greece Central", "Europe", "Athens", 37.98, 23.73),
    ("indonesiacentral", "Indonesia Central", "Asia Pacific", "Jakarta", -6.21, 106.85),
    ("israelcentral", "Israel Central", "Middle East", "Israel", 32.09, 34.78),
    ("italynorth", "Italy North", "Europe", "Milan", 45.46, 9.19),
    ("japaneast", "Japan East", "Asia Pacific", "Tokyo, Saitama", 35.68, 139.69),
    ("japanwest", "Japan West", "Asia Pacific", "Osaka", 34.69, 135.50),
    ("jioindiacentral", "Jio India Central", "India", "Nagpur", 21.15, 79.09),
    ("jioindiawest", "Jio India West", "India", "Jamnagar", 22.47, 70.07),
    ("koreacentral", "Korea Central", "Asia Pacific", "Seoul", 37.57, 126.98),
    ("koreasouth", "Korea South", "Asia Pacific", "Busan", 35.18, 129.08),
    ("malaysiasouth", "Malaysia South", "Asia Pacific", "Johor", 1.49, 103.74),
    ("malaysiawest", "Malaysia West", "Asia Pacific", "Kuala Lumpur", 3.14, 101.69),
    ("mexicocentral", "Mexico Central", "Mexico", "Querétaro State", 20.59, -100.39),
    ("newzealandnorth", "New Zealand North", "Asia Pacific", "Auckland", -36.85, 174.76),
    ("northcentralus", "North Central US", "United States", "Illinois", 41.88, -87.63),
    ("northeurope", "North Europe", "Europe", "Ireland", 53.35, -6.26),
    ("norwayeast", "Norway East", "Europe", "Oslo", 59.91, 10.75),
    ("norwaywest", "Norway West", "Europe", "Stavanger", 58.97, 5.73),
    ("polandcentral", "Poland Central", "Europe", "Warsaw", 52.23, 21.01),
    ("qatarcentral", "Qatar Central", "Middle East", "Doha", 25.29, 51.53),
    ("southafricanorth", "South Africa North", "Africa", "Johannesburg", -26.20, 28.05),
    ("southafricawest", "South Africa West", "Africa", "Cape Town", -33.92, 18.42),
    ("southcentralus", "South Central US", "United States", "Texas", 29.42, -98.49),
    ("southeastasia", "Southeast Asia", "Asia Pacific", "Singapore", 1.35, 103.82),
    ("southindia", "South India", "India", "Chennai", 13.08, 80.27),
    ("spaincentral", "Spain Central", "Europe", "Madrid", 40.42, -3.70),
    ("swedencentral", "Sweden Central", "Europe", "Gävle", 60.67, 17.14),
    ("swedensouth", "Sweden South", "Europe", "Staffanstorp", 55.64, 13.21),
    ("switzerlandnorth", "Switzerland North", "Europe", "Zürich", 47.38, 8.54),
    ("switzerlandwest", "Switzerland West", "Europe", "Geneva", 46.20, 6.14),
    ("taiwannorth", "Taiwan North", "Asia Pacific", "Taipei", 25.03, 121.57),
    ("taiwannorthwest", "Taiwan Northwest", "Asia Pacific", "Taoyuan", 24.99, 121.30),
    ("uaecentral", "UAE Central", "Middle East", "Abu Dhabi", 24.45, 54.38),
    ("uaenorth", "UAE North", "Middle East", "Dubai", 25.20, 55.27),
    ("uksouth", "UK South", "Europe", "London", 51.51, -0.13),
    ("ukwest", "UK West", "Europe", "Cardiff", 51.48, -3.18),
    ("westcentralus", "West Central US", "United States", "Wyoming", 41.14, -104.82),
    ("westeurope", "West Europe", "Europe", "Netherlands", 52.37, 4.90),
    ("westindia", "West India", "India", "Mumbai", 19.08, 72.88),
    ("westus", "West US", "United States", "California", 37.34, -121.89),
    ("westus2", "West US 2", "United States", "Washington", 47.61, -122.33),
    ("westus3", "West US 3", "United States", "Arizona", 33.45, -112.07),
    ("centraluseuap", "Central US EUAP", "United States", "Iowa", 41.59, -93.62),
]


def azure_region_catalog() -> list[dict[str, Any]]:
    """Return the public Azure region catalog in a JSON-ready shape."""
    return [
        {
            "name": name,
            "display_name": display,
            "geography": geography,
            "physical_location": location,
            "latitude": latitude,
            "longitude": longitude,
            "normalized_latitude": round(latitude / 90.0, 6),
            "normalized_longitude": round(longitude / 180.0, 6),
        }
        for name, display, geography, location, latitude, longitude in _REGION_DATA
    ]


DRIFT_EXPLANATIONS = {
    "data": (
        "Data Drift means input distributions change while the input-output "
        "relationship remains stable."
    ),
    "concept": (
        "Concept Drift means the input-output relationship changes."
    ),
    "model": (
        "Model Drift means model behavior degrades or changes because of "
        "system or model issues."
    ),
}

ML_METRICS = {
    "classification": [
        "accuracy", "precision", "recall", "f1_score", "roc_auc",
        "log_loss", "average_precision", "matthews_correlation",
        "balanced_accuracy", "cohen_kappa",
    ],
    "regression": [
        "mae", "mse", "rmse", "r2", "mape", "smape", "median_absolute_error",
        "explained_variance", "max_error", "mean_squared_log_error",
    ],
    "forecasting": [
        "mae", "mse", "rmse", "mape", "smape", "wape", "mase",
        "rmsle", "normalized_rmse", "forecast_bias",
    ],
}

CONFIG_DEFAULTS: dict[str, dict[str, Any]] = {
    "dataops": {
        "schedule": "0 2 * * *",
        "frequency": "daily",
        "load_mode": "delta",
        "watermark_column": "modified_at",
        "source_watermark_column": "modified_at",
        "late_arrival_minutes": 60,
        "window_type": "tumbling",
        "window_types": ["sliding", "hopping", "tumbling", "session"],
        "window_size_minutes": 60,
        "slide_minutes": 15,
        "session_gap_minutes": 30,
        "retry_count": 3,
    },
    "mlops": {
        "schedule": "0 3 * * 1",
        "frequency": "weekly",
        "task_type": "classification",
        "metric": "f1_score",
        "metric_catalogs": ML_METRICS,
        "threshold": 0.80,
        "target_environment": "stage",
        "promotion_environment": "stage",
        "retrain_on_data_drift": True,
        "retrain_on_concept_drift": True,
        "retrain_on_model_drift": True,
        "drift_threshold": 0.15,
        "minimum_samples": 1000,
        "drift_explanations": DRIFT_EXPLANATIONS,
    },
    "rag": {
        "schedule": "0 */6 * * *",
        "frequency": "six_hourly",
        "index_update_mode": "delta",
        "index_update_modes": ["delta", "full"],
        "vector_store": "azure_ai_search",
        "embedding_model": "text-embedding-3-large",
        "chunk_size": 1000,
        "chunk_overlap": 150,
        "retrieval_top_k": 5,
        "hybrid_search": True,
        "semantic_reranking": True,
        "freshness_threshold_hours": 24,
        "evaluation_metric": "groundedness",
        "evaluation_threshold": 0.80,
        "target_environment": "stage",
        "promotion_environment": "stage",
    },
    "finetuning": {
        "training_type": "SFT",
        "training_types": ["SFT", "DPO", "RFT"],
        "base_model": "gpt-4.1-mini",
        "dataset_uri": "",
        "validation_split": 0.10,
        "epochs": 2,
        "learning_rate_multiplier": 0.75,
        "batch_size": 4,
        "evaluation_metric": "validation_loss",
        "evaluation_threshold": 0.80,
        "target_environment": "stage",
        "promotion_environment": "stage",
        "checkpoint_strategy": "best_validation",
        "responsible_ai_evaluation": True,
        "estimated_training_examples": 1000,
        "training_guidance": {
            "SFT": "Supervised fine-tuning learns from prompt and ideal-response examples.",
            "DPO": "Direct preference optimization learns from chosen and rejected response pairs.",
            "RFT": "Reinforcement fine-tuning optimizes against a task-specific grader or reward.",
            "baseline": "Evaluate the base model first and compare every checkpoint to that baseline.",
            "ranges": "Start with 2 epochs and a 0.5-1.0 learning-rate multiplier, then evaluate held-out data and checkpoints.",
        },
    },
}


class OperationsStore:
    """SQLite persistence for operation configuration, snapshots, and drafts."""

    def __init__(self, db_path: str | os.PathLike[str] | None = None):
        configured = db_path or os.environ.get("AIFACTORY_OPERATIONS_DB")
        self.db_path = Path(configured).expanduser() if configured else (
            Path.home() / ".aifactory_operations.db"
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            try:
                connection.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError:
                pass
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS operation_configs (
                    aifactory_folder TEXT NOT NULL,
                    project_number TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (
                        aifactory_folder, project_number, environment, kind
                    )
                );
                CREATE TABLE IF NOT EXISTS monitoring_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    aifactory_folder TEXT NOT NULL,
                    source TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_monitoring_folder_created
                    ON monitoring_snapshots(aifactory_folder, created_at DESC);
                CREATE TABLE IF NOT EXISTS factory_action_requests (
                    request_id TEXT PRIMARY KEY,
                    aifactory_folder TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_region TEXT NOT NULL,
                    source_region TEXT,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_actions_folder_created
                    ON factory_action_requests(aifactory_folder, created_at DESC);
                CREATE TABLE IF NOT EXISTS prompt_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    aifactory_folder TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    conversation_id TEXT,
                    response_id TEXT,
                    timestamp TEXT NOT NULL,
                    project_number TEXT,
                    environment TEXT,
                    region TEXT,
                    model TEXT,
                    category TEXT NOT NULL,
                    prompt TEXT,
                    response TEXT,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    cached_input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    latency_ms REAL,
                    success INTEGER NOT NULL DEFAULT 1,
                    error_type TEXT,
                    source TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(aifactory_folder, operation_id, response_id, timestamp)
                );
                CREATE INDEX IF NOT EXISTS idx_prompts_folder_time
                    ON prompt_records(aifactory_folder, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_prompts_filters
                    ON prompt_records(
                        aifactory_folder, project_number, environment,
                        model, category, success
                    );
                """
            )

    @staticmethod
    def _folder(folder: str | os.PathLike[str]) -> str:
        return os.path.normcase(os.path.normpath(str(Path(folder).expanduser().resolve())))

    def save_config(
        self, folder: str, project_number: str, environment: str,
        kind: str, config: dict[str, Any],
    ) -> dict[str, Any]:
        now = _utc_now()
        payload = json.dumps(config, ensure_ascii=False, sort_keys=True)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO operation_configs
                    (aifactory_folder, project_number, environment, kind,
                     payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(aifactory_folder, project_number, environment, kind)
                DO UPDATE SET payload_json=excluded.payload_json,
                              updated_at=excluded.updated_at
                """,
                (self._folder(folder), project_number, environment, kind, payload, now),
            )
        return self.load_config(folder, project_number, environment, kind)

    def load_config(
        self, folder: str, project_number: str, environment: str, kind: str,
    ) -> dict[str, Any]:
        defaults = copy.deepcopy(CONFIG_DEFAULTS[kind])
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json, updated_at FROM operation_configs
                WHERE aifactory_folder=? AND project_number=?
                  AND environment=? AND kind=?
                """,
                (self._folder(folder), project_number, environment, kind),
            ).fetchone()
        saved = json.loads(row["payload_json"]) if row else {}
        defaults.update(saved)
        return {
            "aifactory_folder": self._folder(folder),
            "project_number": project_number,
            "environment": environment,
            "kind": kind,
            "config": defaults,
            "is_saved": row is not None,
            "updated_at": row["updated_at"] if row else None,
        }

    def list_configs(self, folder: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT project_number, environment, kind, payload_json, updated_at
                FROM operation_configs WHERE aifactory_folder=?
                ORDER BY project_number, environment, kind
                """,
                (self._folder(folder),),
            ).fetchall()
        result = []
        for row in rows:
            config = copy.deepcopy(CONFIG_DEFAULTS[row["kind"]])
            config.update(json.loads(row["payload_json"]))
            result.append({
                "project_number": row["project_number"],
                "environment": row["environment"],
                "kind": row["kind"],
                "config": config,
                "updated_at": row["updated_at"],
            })
        return result

    def save_snapshot(
        self, folder: str, source: str, payload: dict[str, Any],
        created_at: str | None = None,
    ) -> dict[str, Any]:
        timestamp = created_at or _utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO monitoring_snapshots
                    (aifactory_folder, source, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    self._folder(folder), source,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    timestamp,
                ),
            )
        return {"id": cursor.lastrowid, "source": source, "created_at": timestamp}

    def latest_snapshot(
        self, folder: str, sources: tuple[str, ...] = ("azure", "cached"),
    ) -> dict[str, Any] | None:
        placeholders = ",".join("?" for _ in sources)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT source, payload_json, created_at
                FROM monitoring_snapshots
                WHERE aifactory_folder=? AND source IN ({placeholders})
                ORDER BY id DESC LIMIT 1
                """,
                (self._folder(folder), *sources),
            ).fetchone()
        if not row:
            return None
        return {
            "source": row["source"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
        }

    def list_snapshots(self, folder: str, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT source, payload_json, created_at
                FROM monitoring_snapshots WHERE aifactory_folder=?
                ORDER BY id DESC LIMIT ?
                """,
                (self._folder(folder), limit),
            ).fetchall()
        return [
            {
                "source": row["source"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in reversed(rows)
        ]

    def load_snapshots(
        self, folder: str, limit: int = 30,
    ) -> list[dict[str, Any]]:
        return self.list_snapshots(folder, limit)

    def create_action_request(
        self, folder: str, action: str, target_region: str,
        source_region: str | None = None, **details: Any,
    ) -> dict[str, Any]:
        request = {
            "request_id": str(uuid.uuid4()),
            "aifactory_folder": self._folder(folder),
            "action": action,
            "target_region": target_region,
            "source_region": source_region,
            "status": "draft",
            "created_at": _utc_now(),
            "message": "Draft only; no Azure resources were changed.",
            **details,
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO factory_action_requests
                    (request_id, aifactory_folder, action, target_region,
                     source_region, status, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request["request_id"], request["aifactory_folder"], action,
                    target_region, source_region, "draft",
                    json.dumps(request, ensure_ascii=False, sort_keys=True),
                    request["created_at"],
                ),
            )
        return request

    def list_action_requests(self, folder: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM factory_action_requests
                WHERE aifactory_folder=? ORDER BY created_at DESC
                """,
                (self._folder(folder),),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def create_project_action(
        self, folder: str, project_number: str, source_environment: str,
        target_environment: str, action: str,
    ) -> dict[str, Any]:
        return self.create_action_request(
            folder, action, target_environment, source_environment,
            request_type="project",
            project_number=project_number,
            source_environment=source_environment,
            target_environment=target_environment,
        )

    def upsert_prompt_record(
        self, folder: str, record: dict[str, Any],
    ) -> dict[str, Any]:
        value = _normalize_prompt_record(record)
        self._upsert_prompt_values(folder, [value])
        return value

    @staticmethod
    def _prompt_parameters(folder: str, value: dict[str, Any]) -> tuple[Any, ...]:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return (
            folder, value["operation_id"], value["conversation_id"],
            value["response_id"], value["timestamp"], value["project_number"],
            value["environment"], value["region"], value["model"],
            value["category"], value["prompt"], value["response"],
            value["input_tokens"], value["cached_input_tokens"],
            value["output_tokens"], value["total_tokens"], value["latency_ms"],
            int(value["success"]), value["error_type"], value["source"], payload,
        )

    def _upsert_prompt_values(
        self, folder: str, values: list[dict[str, Any]],
    ) -> None:
        if not values:
            return
        statement = """
                INSERT INTO prompt_records (
                    aifactory_folder, operation_id, conversation_id, response_id,
                    timestamp, project_number, environment, region, model,
                    category, prompt, response, input_tokens,
                    cached_input_tokens, output_tokens, total_tokens, latency_ms,
                    success, error_type, source, payload_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(aifactory_folder, operation_id, response_id, timestamp)
                DO UPDATE SET
                    conversation_id=excluded.conversation_id,
                    project_number=excluded.project_number,
                    environment=excluded.environment,
                    region=excluded.region, model=excluded.model,
                    category=excluded.category, prompt=excluded.prompt,
                    response=excluded.response,
                    input_tokens=excluded.input_tokens,
                    cached_input_tokens=excluded.cached_input_tokens,
                    output_tokens=excluded.output_tokens,
                    total_tokens=excluded.total_tokens,
                    latency_ms=excluded.latency_ms, success=excluded.success,
                    error_type=excluded.error_type, source=excluded.source,
                    payload_json=excluded.payload_json
                """
        normalized_folder = self._folder(folder)
        parameters = [
            self._prompt_parameters(normalized_folder, value) for value in values
        ]
        with self._connect() as connection:
            connection.executemany(statement, parameters)

    def upsert_prompt_records(
        self, folder: str, records: Iterable[dict[str, Any]],
    ) -> int:
        values = [_normalize_prompt_record(record) for record in records]
        self._upsert_prompt_values(folder, values)
        return len(values)

    def query_prompt_records(
        self, folder: str, project_number: str | None = None,
        environment: str | None = None, model: str | None = None,
        category: str | None = None, search: str | None = None,
        success: bool | None = None, limit: int = 100, offset: int = 0,
    ) -> dict[str, Any]:
        clauses = ["aifactory_folder=?"]
        parameters: list[Any] = [self._folder(folder)]
        for column, value in (
            ("project_number", project_number), ("environment", environment),
            ("model", model), ("category", category),
        ):
            if value is not None:
                clauses.append(f"{column}=?")
                parameters.append(value)
        if success is not None:
            clauses.append("success=?")
            parameters.append(int(success))
        if search:
            clauses.append(
                "(prompt LIKE ? ESCAPE '\\' OR response LIKE ? ESCAPE '\\' "
                "OR operation_id LIKE ? ESCAPE '\\')"
            )
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            parameters.extend([f"%{escaped}%"] * 3)
        where = " AND ".join(clauses)
        with self._connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM prompt_records WHERE {where}", parameters
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT payload_json FROM prompt_records WHERE {where}
                ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?
                """,
                (*parameters, limit, offset),
            ).fetchall()
        return {
            "rows": [json.loads(row["payload_json"]) for row in rows],
            "total": total, "limit": limit, "offset": offset,
        }

    def prompt_filter_metadata(self, folder: str) -> dict[str, list[Any]]:
        columns = ("project_number", "environment", "model", "category")
        result: dict[str, list[Any]] = {}
        with self._connect() as connection:
            for column in columns:
                rows = connection.execute(
                    f"""
                    SELECT DISTINCT {column} FROM prompt_records
                    WHERE aifactory_folder=? AND {column} IS NOT NULL
                      AND {column} <> '' ORDER BY {column}
                    """,
                    (self._folder(folder),),
                ).fetchall()
                result[f"{column}s"] = [row[0] for row in rows]
        result["success_values"] = [True, False]
        return result


class LocalFactoryDiscovery:
    """Discover factory metadata from wizard-owned local configuration."""

    _PROJECT_RE = re.compile(r"project[-_]?(\d+)", re.IGNORECASE)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _usable(value: Any) -> str:
        text = str(value or "").strip()
        return "" if not text or "<todo>" in text.lower() else text

    @classmethod
    def _has_github_json_evidence(
        cls, *sections: dict[str, Any],
    ) -> bool:
        for section in sections:
            values = {
                str(key).casefold(): value for key, value in section.items()
            }
            if cls._usable(values.get("github_username")) or cls._usable(values.get("github_new_repo")):
                return True
        return False

    @staticmethod
    def _has_sibling_env(folder: Path) -> bool:
        return (folder.parent / ".env").is_file() or (folder / ".env").is_file()

    def _detect_orchestrator(
        self, folder: Path, dev: dict[str, Any], stage_prod: dict[str, Any],
        snapshots: list[dict[str, Any]],
    ) -> str:
        # Current repository evidence is authoritative over historical snapshots.
        if self._has_sibling_env(folder) or self._has_github_json_evidence(
            dev, stage_prod
        ):
            return "gha"

        current_project = (
            self._usable(dev.get("project_number_000"))
            or self._usable(stage_prod.get("project_number_000"))
        )
        if current_project:
            for snapshot in snapshots:
                if snapshot["project_number"] != current_project:
                    continue
                route = self._usable(snapshot["state"].get("orchestrator")).casefold()
                if route in {"ado", "gha"}:
                    return route

        votes = Counter(
            self._usable(snapshot["state"].get("orchestrator")).casefold()
            for snapshot in snapshots
        )
        votes.pop("", None)
        ado_votes, gha_votes = votes["ado"], votes["gha"]
        if ado_votes != gha_votes:
            return "ado" if ado_votes > gha_votes else "gha"

        # A tied history falls back to the most recently saved valid snapshot.
        for snapshot in sorted(
            snapshots,
            key=lambda item: (item["modified_ns"], item["path"]),
            reverse=True,
        ):
            route = self._usable(snapshot["state"].get("orchestrator")).casefold()
            if route in {"ado", "gha"}:
                return route
        return "ado"

    def discover(self, aifactory_folder: str) -> dict[str, Any]:
        from src import wizard
        from src.factory_scope import current_factory_scope
        folder = Path(aifactory_folder).expanduser().resolve()
        azure_scope = current_factory_scope(folder)
        variables = self._read_json(folder / "variables.json")
        dev = variables.get("dev") if isinstance(variables.get("dev"), dict) else {}
        stage_prod = (
            variables.get("stage_prod")
            if isinstance(variables.get("stage_prod"), dict) else {}
        )
        factory_path = folder / "config-wizard" / "factory_state.json"
        factory_state = self._read_json(factory_path)
        scale_set_states = [
            self._read_json(path)
            for path in sorted((folder / "config-wizard" / "scalesets").glob("scaleset_*.json"))
        ]
        snapshots: list[dict[str, Any]] = []
        project_numbers: set[str] = set()
        for path in sorted(folder.glob("config-wizard/project-*/project_state.json")):
            state = self._read_json(path)
            directory_match = self._PROJECT_RE.search(path.parent.name)
            number = self._usable(state.get("project_number_000"))
            if not number and directory_match:
                number = directory_match.group(1)
            if number.isdigit():
                project_numbers.add(number)
                try:
                    modified_ns = path.stat().st_mtime_ns
                except OSError:
                    modified_ns = 0
                snapshots.append({
                    "project_number": number, "path": str(path),
                    "modified_ns": modified_ns, "state": state,
                })

        if not project_numbers and not factory_path.exists():
            number = self._usable(dev.get("project_number_000"))
            if number.isdigit():
                project_numbers.add(number)

        def setting(name: str, prefer_stage: bool = False) -> str:
            value = self._usable(factory_state.get(name))
            if value:
                return value
            first, second = (stage_prod, dev) if prefer_stage else (dev, stage_prod)
            value = self._usable(first.get(name)) or self._usable(second.get(name))
            if value:
                return value
            for snapshot in snapshots:
                value = self._usable(snapshot["state"].get(name))
                if value:
                    return value
            for scale_set in scale_set_states:
                value = self._usable(scale_set.get(name))
                if value:
                    return value
            return ""

        subscriptions = azure_scope["subscriptions"]
        regions = sorted({
            value for value in (
                self._usable(dev.get("admin_location")),
                self._usable(stage_prod.get("admin_location")),
                self._usable(factory_state.get("admin_location")),
                *(self._usable(item.get("admin_location")) for item in scale_set_states),
                *(self._usable(item["state"].get("admin_location")) for item in snapshots),
            ) if value
        })
        orchestrator = self._detect_orchestrator(
            folder, dev, stage_prod, snapshots
        )
        orchestrator = wizard._json_orchestrator(variables) or orchestrator
        if factory_state.get("orchestrator") in ("ado", "gha"):
            orchestrator = factory_state["orchestrator"]
        prefix = setting("admin_aifactoryPrefixRG")
        suffix = setting("admin_aifactorySuffixRG")
        factory_name = (
            "-".join(filter(None, (prefix.rstrip("-_"), suffix.lstrip("-_"))))
            or folder.name
        )
        environment_cards = []
        for project in sorted(project_numbers, key=lambda value: (int(value), value)):
            for environment in ("dev", "stage", "prod"):
                environment_cards.append({
                    "project_number": project,
                    "environment": environment,
                    "status": (
                        "configured" if subscriptions.get(environment)
                        else "not_configured"
                    ),
                    "subscription_id": subscriptions.get(environment),
                    "region": regions[0] if regions else None,
                    "resource_group": None,
                    "resource_count": 0,
                })
        return {
            "folder": str(folder),
            "name": factory_name,
            "dashboard_url": wizard._current_dashboard_url(str(folder)),
            "orchestrator": orchestrator,
            "active_regions": regions,
            "primary_region": setting("admin_location"),
            "subscriptions": subscriptions,
            **azure_scope,
            "project_numbers": sorted(project_numbers),
            "project_snapshots": snapshots,
            "prefix_rg": prefix,
            "suffix_rg": suffix,
            "variables_found": bool(variables),
            "environment_cards": environment_cards,
        }

    def annotate_with_inventory(
        self, discovered: dict[str, Any], groups: list[dict[str, Any]],
        resources: list[dict[str, Any]],
    ) -> dict[str, Any]:
        projects: set[str] = set(discovered["project_numbers"])
        environments: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        common_groups: list[dict[str, Any]] = []
        owners: dict[str, str] = {}
        group_owners: dict[str, list[str]] = defaultdict(list)
        for snapshot in discovered.get("project_snapshots", []):
            number = str(snapshot.get("project_number") or "")
            if not number.isdigit():
                continue
            snapshot_path = snapshot.get("path")
            if snapshot_path and discovered.get("folder"):
                path = Path(snapshot_path).resolve()
                directory_project = self._PROJECT_RE.search(path.parent.name)
                if not path.is_relative_to(Path(discovered["folder"]).resolve()) or (
                    directory_project and directory_project.group(1).lstrip("0") != number.lstrip("0")
                ):
                    continue
            owner = owner_from_project_state(snapshot.get("state") or {}, number)
            if owner != "Unknown":
                owners[number.lstrip("0") or "0"] = owner

        for group in groups:
            name = str(group.get("name", ""))
            match = self._PROJECT_RE.search(name)
            if not match:
                if re.search(r"(^|[-_])(common|shared|hub)([-_]|$)", name, re.I):
                    common_groups.append({
                        "name": name,
                        "id": group.get("id", ""),
                        "location": group.get("location", ""),
                        "subscription_id": group.get("subscriptionId", ""),
                        "subscriptionId": group.get("subscriptionId", ""),
                        "tenant_id": discovered.get("subscription_tenants", {}).get(group.get("subscriptionId", ""), ""),
                    })
                continue
            project = match.group(1)
            projects.add(project)
            owner = owner_from_project_state({"tags": group.get("tags")})
            if owner != "Unknown":
                group_owners[project.lstrip("0") or "0"].append(owner)
            environment = _environment_from_name(name)
            if environment:
                environments[project][environment].append({
                    "resource_group": name,
                    "location": group.get("location", ""),
                    "subscription_id": group.get("subscriptionId", ""),
                    "resource_id": group.get("id", ""),
                })

        resources_by_group = Counter(
            str(item.get("resourceGroup", "")) for item in resources
        )
        cards = []
        for project in sorted(projects, key=lambda value: (int(value), value)):
            project_environments = []
            for environment in ("dev", "stage", "prod"):
                details = environments[project].get(environment, [])
                resource_count = sum(
                    resources_by_group[item["resource_group"]] for item in details
                )
                project_environments.append({
                    "environment": environment,
                    "status": "active" if details else "not_deployed",
                    "resource_group": details[0]["resource_group"] if details else None,
                    "resource_groups": [
                        item["resource_group"] for item in details
                    ],
                    "resource_group_refs": [
                        {"name": item["resource_group"], "subscription_id": item["subscription_id"],
                         "id": item["resource_id"],
                         "tenant_id": discovered.get("subscription_tenants", {}).get(item["subscription_id"], "")}
                        for item in details
                    ],
                    "region": details[0]["location"] if details else None,
                    "regions": sorted({
                        item["location"] for item in details if item["location"]
                    }),
                    "subscription_id": details[0]["subscription_id"] if details else (
                        discovered["subscriptions"].get(environment)
                    ),
                    "resource_count": resource_count,
                })
            cards.append({
                "project_number": project,
                "display_name": f"Project {project}",
                "owner": owners.get(project.lstrip("0") or "0") or (
                    ", ".join(dict.fromkeys(group_owners[project.lstrip("0") or "0"])) or "Unknown"
                ),
                "environments": project_environments,
                "resource_count": sum(item["resource_count"] for item in project_environments),
            })
        return {"projects": cards, "common_resource_groups": common_groups}


def _environment_from_name(name: str) -> str | None:
    lowered = name.lower()
    tokens = set(filter(None, re.split(r"[^a-z0-9]+", lowered)))
    if "prod" in tokens or "production" in tokens:
        return "prod"
    if {"stage", "stg", "test", "tst"} & tokens:
        return "stage"
    if {"dev", "development"} & tokens:
        return "dev"
    return None


def parse_resource_group_name(name: str) -> dict[str, Any]:
    """Parse project/environment identity from an AIFactory resource group."""
    project = LocalFactoryDiscovery._PROJECT_RE.search(name)
    common = bool(re.search(r"(^|[-_])(common|shared|hub)([-_]|$)", name, re.I))
    return {
        "name": name,
        "project_number": project.group(1) if project else None,
        "environment": _environment_from_name(name),
        "is_common": common,
    }


class PromptCategorizer:
    """Deterministic local-only prompt categorization."""

    RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("Security/Governance", (
            "security", "secure", "vulnerability", "rbac", "policy", "compliance",
            "governance", "identity", "permission", "secret", "key vault",
        )),
        ("MLOps", (
            "mlops", "model drift", "data drift", "concept drift", "retrain",
            "fine-tun", "training job", "model deploy", "endpoint deployment",
        )),
        ("Search/RAG", (
            "rag", "retrieval", "vector", "embedding", "semantic search",
            "ai search", "chunking", "indexer", "groundedness",
        )),
        ("Data/Analytics", (
            "sql", "dataframe", "analytics", "etl", "pipeline", "data lake",
            "warehouse", "spark", "kusto", "kql", "dataset",
        )),
        ("Operations", (
            "monitor", "telemetry", "incident", "latency", "availability",
            "resource group", "azure cli", "cost", "deploy", "production",
            "troubleshoot", "log analytics",
        )),
        ("Coding", (
            "code", "python", "javascript", "typescript", "c#", "function",
            "class", "api", "debug", "test", "refactor", "algorithm", "regex",
        )),
        ("Content/Communication", (
            "email", "write", "rewrite", "summarize", "translate", "blog",
            "presentation", "message", "copy", "tone",
        )),
        ("Planning", (
            "plan", "roadmap", "strategy", "milestone", "estimate",
            "prioritize", "architecture", "design",
        )),
    )

    def categorize(self, prompt: str | None) -> dict[str, Any]:
        text = str(prompt or "").casefold()
        for category, keywords in self.RULES:
            matches = [keyword for keyword in keywords if keyword in text]
            if matches:
                confidence = min(0.98, 0.68 + 0.08 * (len(matches) - 1))
                return {
                    "category": category,
                    "confidence": round(confidence, 2),
                    "reason": f"Matched ordered keyword rule: {matches[0]}",
                }
        return {
            "category": "General",
            "confidence": 0.4,
            "reason": "No explicit category keyword matched.",
        }


def _integer(value: Any) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def _normal_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    text = str(value or "").strip()
    return text or _utc_now()


def _normalize_prompt_record(record: dict[str, Any]) -> dict[str, Any]:
    input_tokens = _integer(record.get("input_tokens"))
    cached = _integer(record.get("cached_input_tokens"))
    cached = min(cached, input_tokens) if input_tokens else cached
    output_tokens = _integer(record.get("output_tokens"))
    total = _integer(record.get("total_tokens")) or input_tokens + output_tokens
    timestamp = _normal_timestamp(record.get("timestamp"))
    conversation_id = _nullable_text(record.get("conversation_id"))
    response_id = str(record.get("response_id") or "")
    project_number = _nullable_text(record.get("project_number"))
    environment = _nullable_text(record.get("environment"))
    region = _nullable_text(record.get("region"))
    model = _nullable_text(record.get("model")) or "unknown"
    category = str(record.get("category") or "General")
    prompt = str(record.get("prompt") or "")
    response = str(record.get("response") or "")
    latency_ms = _float(record.get("latency_ms"))
    error_type = _nullable_text(record.get("error_type"))
    source = str(record.get("source") or "azure")
    success_value = record.get("success", True)
    if isinstance(success_value, str):
        success_value = success_value.casefold() not in {"false", "0", "failed", "error"}
    operation_id = _nullable_text(record.get("operation_id") or record.get("id"))
    if not operation_id:
        identity = {
            "timestamp": timestamp,
            "conversation_id": conversation_id,
            "response_id": response_id,
            "project_number": project_number,
            "environment": environment,
            "region": region,
            "model": model,
            "category": category,
            "prompt": prompt,
            "response": response,
            "input_tokens": input_tokens,
            "cached_input_tokens": cached,
            "output_tokens": output_tokens,
            "total_tokens": total,
            "latency_ms": latency_ms,
            "success": bool(success_value),
            "error_type": error_type,
            "source": source,
        }
        encoded = json.dumps(
            identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        operation_id = f"synthetic-{hashlib.sha256(encoded).hexdigest()}"
    return {
        "operation_id": operation_id,
        "conversation_id": conversation_id,
        "response_id": response_id,
        "timestamp": timestamp,
        "project_number": project_number,
        "environment": environment,
        "region": region,
        "model": model,
        "category": category,
        "prompt": prompt,
        "response": response,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "output_tokens": output_tokens,
        "total_tokens": total,
        "latency_ms": latency_ms,
        "success": bool(success_value),
        "error_type": error_type,
        "source": source,
    }


def _nullable_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _dynamic_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}


def _message_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in "[{":
            try:
                return _message_text(json.loads(stripped))
            except ValueError:
                return value
        return value
    if isinstance(value, list):
        parts = [_message_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        role = str(value.get("role") or "").strip()
        content = (
            value.get("content") or value.get("text") or value.get("message")
            or value.get("value")
        )
        if isinstance(content, list):
            text = "\n".join(filter(None, (_message_text(item) for item in content)))
        else:
            text = _message_text(content) if content is not value else ""
        return f"{role}: {text}" if role and text else text
    return str(value)


def _genai_kql(*, application_insights: bool = False) -> str:
    # The application-scoped endpoint exposes the legacy table/column names,
    # even for workspace-based components. Do not union both schemas.
    tables = "dependencies, requests, traces" if application_insights else "AppDependencies, AppRequests, AppTraces"
    duration = 'todouble(column_ifexists("duration", customMeasurements["duration_ms"]))' if application_insights else (
        'todouble(column_ifexists("DurationMs", customMeasurements["duration_ms"]))'
    )
    return "union isfuzzy=true " + tables + r"""
| extend event_time=todatetime(coalesce(
    column_ifexists("TimeGenerated", datetime(null)),
    column_ifexists("timestamp", datetime(null))))
| where event_time > ago(30d)
| extend customDimensions = todynamic(column_ifexists("customDimensions",
    column_ifexists("Properties", dynamic({}))))
| extend customMeasurements = todynamic(column_ifexists("customMeasurements",
    column_ifexists("Measurements", dynamic({}))))
| where tostring(customDimensions["gen_ai.system"]) != ""
    or tostring(customDimensions["gen_ai.request.model"]) != ""
    or tostring(customDimensions["gen_ai.response.model"]) != ""
    or tostring(customDimensions["gen_ai.usage.input_tokens"]) != ""
| project timestamp=event_time,
    operation_id=tostring(column_ifexists("operation_Id",
        column_ifexists("OperationId", ""))),
    conversation_id=tostring(customDimensions["gen_ai.conversation.id"]),
    response_id=tostring(customDimensions["gen_ai.response.id"]),
    model=coalesce(tostring(customDimensions["gen_ai.response.model"]),
        tostring(customDimensions["gen_ai.request.model"]),
        tostring(customDimensions["azure.openai.deployment.name"])),
    input_tokens=toint(customDimensions["gen_ai.usage.input_tokens"]),
    cached_input_tokens=toint(coalesce(
        customDimensions["gen_ai.usage.cached_input_tokens"],
        customDimensions["gen_ai.usage.cache_read.input_tokens"],
        customDimensions["gen_ai.usage.input_tokens.cache_read"],
        customDimensions["openai.usage.prompt_tokens_details.cached_tokens"],
        customDimensions["azure.openai.usage.cached_prompt_tokens"])),
    output_tokens=toint(customDimensions["gen_ai.usage.output_tokens"]),
    prompt=tostring(customDimensions["gen_ai.input.messages"]),
    response=tostring(customDimensions["gen_ai.output.messages"]),
    duration_ms=__DURATION_EXPRESSION__,
    success=column_ifexists("success", column_ifexists("Success", true)),
    resultCode=tostring(column_ifexists("resultCode",
        column_ifexists("ResultCode", ""))),
    customDimensions, customMeasurements
| order by timestamp desc
| take 5000
""".replace("__DURATION_EXPRESSION__", duration).rstrip()


class AzureCollectionError(RuntimeError):
    """An expected Azure CLI or telemetry response failure."""


class _NoTelemetryRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_TELEMETRY_MAX_BYTES = 16 * 1024 * 1024
_TELEMETRY_ERROR_BYTES = 8192
_TENANT_GUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.I)


def _telemetry_error_detail(error: Any, token: str = "") -> str:
    detail = json.dumps(error, ensure_ascii=False)
    if token:
        detail = detail.replace(token, "[redacted]")
    detail = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~+/\-=]+", "Bearer [redacted]", detail)
    detail = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[redacted]", detail)
    detail = re.sub(r'(?i)("(?:access_?token|authorization)"\s*:\s*")[^"]*', r"\1[redacted]", detail)
    return detail[:4096]


def _combined_warnings(*warnings: str | None) -> str | None:
    return "\n".join(dict.fromkeys(
        warning.strip() for warning in warnings if warning and warning.strip()
    )) or None


def _records_source(rows: list[dict[str, Any]], empty: str = "unavailable") -> str:
    sources = {str(row.get("source") or "local") for row in rows}
    return next(iter(sources)) if len(sources) == 1 else "mixed" if sources else empty


def _collection_warning(resource: dict[str, Any], error: AzureCollectionError) -> str:
    detail = str(error)
    scope = str(resource.get("id") or resource.get("name") or "unknown resource")
    lowered = detail.casefold()
    if any(code in lowered for code in (
        "aadsts70043", "interactive authentication is needed",
        "invalidauthenticationtoken", "invalidtoken", "authenticationfailed",
        "azure token", "azure access token", "http 401",
    )):
        return (
            f"Azure sign-in has expired or requires verification for {scope}. Sign in again with Azure CLI "
            "to the tenant for this subscription, then Refresh Azure. "
            "This is separate from resource permissions; no credentials were changed."
        )
    if "nspvalidationfailed" in lowered or "network security perimeter" in lowered:
        return (
            f"Telemetry unavailable for {scope}: workspace network policy denied "
            "this request (NspValidationFailedError). Contact the resource owner; "
            "network policy has not been changed."
        )
    if "authorizationfailed" in lowered or "does not have authorization" in lowered:
        action = re.search(r"perform action ['\"]([^'\"]+)['\"]", detail)
        permission = action.group(1) if action else "the requested Azure read operation"
        return (
            f"Permission denied for {permission} on {scope}. "
            "Ask the resource owner for Reader on the affected resource only; "
            "no roles have been changed."
        )
    if any(code in lowered for code in ("insufficientaccess", "forbidden", "403")):
        return (
            f"Telemetry permission denied for {scope}. Ask the resource owner to "
            "review query access on this resource; no permissions have been changed. "
            f"Details: {detail}"
        )
    return f"Collection failed for {scope}: {detail}"


class AzureInventoryProvider:
    """Collect read-only inventory and explicitly authenticated HTTPS telemetry."""

    def __init__(
        self, store: OperationsStore, timeout: int = 45,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        azure_cli: str | os.PathLike[str] | None = None,
        transport: Callable[..., Any] | None = None,
    ):
        self.store = store
        self.timeout = timeout
        self.runner = runner or subprocess.run
        self._uses_default_runner = runner is None
        self.azure_cli = str(azure_cli) if azure_cli else None
        self._telemetry_transport = transport or build_opener(_NoTelemetryRedirect()).open

    def _run_json(self, arguments: list[str], *, sensitive: bool = False) -> Any:
        executable = self.azure_cli
        if not executable:
            try:
                executable = resolve_azure_cli() if self._uses_default_runner else "az"
            except RuntimeError as exc:
                raise AzureCollectionError(str(exc)) from exc
            self.azure_cli = executable
        argv = [
            *_azure_cli_command(executable),
            *arguments, "--output", "json", "--only-show-errors",
        ]
        options: dict[str, Any] = {}
        if sensitive:
            env = os.environ.copy()
            env.update({
                "AZURE_CORE_LOGIN_EXPERIENCE_V2": "off",
                "AZURE_CORE_ENABLE_BROKER_ON_WINDOWS": "false",
                "AZURE_CORE_LOG_LEVEL": "critical",
                "AZURE_LOGGING_ENABLE_LOG_FILE": "false",
            })
            options.update(
                env=env, stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace",
            )
        try:
            result = self.runner(
                argv, capture_output=True, text=True,
                timeout=max(1, min(self.timeout, 30)) if sensitive else self.timeout,
                check=False, shell=False, **options,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            if sensitive:
                raise AzureCollectionError("Azure access token unavailable; verify Azure CLI sign-in.") from None
            raise AzureCollectionError(f"Azure CLI command failed: {exc}") from exc
        if result.returncode:
            if sensitive:
                raise AzureCollectionError("Azure access token unavailable; verify Azure CLI sign-in.") from None
            detail = (result.stderr or result.stdout or "unknown Azure CLI error").strip()
            raise AzureCollectionError(f"Azure CLI command failed: {detail}")
        if sensitive and len(result.stdout or "") > 65536:
            raise AzureCollectionError("Azure token response exceeded the size limit.")
        try:
            return json.loads(result.stdout or "null")
        except ValueError as exc:
            if sensitive:
                raise AzureCollectionError("Azure token response was not valid JSON.") from None
            raise AzureCollectionError("Azure CLI command returned invalid JSON") from exc

    def _run_az(self, entity: str, subscription: str) -> list[dict[str, Any]]:
        payload = self._run_json([
            entity, "list", "--subscription", subscription,
        ])
        if not isinstance(payload, list):
            raise AzureCollectionError(f"Azure CLI {entity} inventory was not a JSON array")
        for item in payload:
            if isinstance(item, dict):
                item.setdefault("subscriptionId", subscription)
        return [item for item in payload if isinstance(item, dict)]

    @staticmethod
    def _resource_subscription(resource: dict[str, Any]) -> str:
        resource_id = str(resource.get("id") or "")
        match = re.match(r"^/subscriptions/([a-zA-Z0-9-]+)/", resource_id, re.IGNORECASE)
        from_id = match.group(1) if match else ""
        from_metadata = str(resource.get("subscriptionId") or "").strip()
        if from_id and from_metadata and from_id.casefold() != from_metadata.casefold():
            raise AzureCollectionError("Resource subscription metadata conflicts with its resource ID; query was not sent.")
        subscription = from_id or from_metadata
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]*", subscription):
            raise AzureCollectionError("Resource subscription is missing or invalid; refusing to use the Azure CLI default account.")
        return subscription

    def _run_resource_json(self, resource: dict[str, Any], arguments: list[str]) -> Any:
        return self._run_json([
            *arguments, "--subscription", self._resource_subscription(resource),
        ])

    def _telemetry_token(self, resource: dict[str, Any], audience: str) -> str:
        subscription = self._resource_subscription(resource)
        expected_tenants = [
            resource[key] for key in ("tenantId", "tenant_id", "_expected_tenant_id")
            if resource.get(key)
        ]
        if any(not isinstance(value, str) or not _TENANT_GUID.fullmatch(value)
               for value in expected_tenants) or len({value.casefold() for value in expected_tenants}) > 1:
            raise AzureCollectionError("Azure token tenant scope is invalid or conflicting; query was not sent.")
        document = self._run_json([
            "account", "get-access-token", "--subscription", subscription,
            "--resource", audience,
        ], sensitive=True)
        if (not isinstance(document, dict)
                or str(document.get("subscription") or "").casefold() != subscription.casefold()
                or not isinstance(document.get("tenant"), str)
                or not _TENANT_GUID.fullmatch(document["tenant"])
                or (expected_tenants and document["tenant"].casefold() != expected_tenants[0].casefold())):
            raise AzureCollectionError("Azure token account does not match the resource subscription and tenant.")
        token = document.get("accessToken")
        if (not isinstance(token, str)
                or not re.fullmatch(r"[A-Za-z0-9._~+/-]{1,32768}=*", token)
                or str(document.get("tokenType", "Bearer")).casefold() != "bearer"):
            raise AzureCollectionError("Azure token response did not contain a usable bearer token.")
        for key in ("resource", "audience"):
            if key in document and str(document[key]).rstrip("/") != audience:
                raise AzureCollectionError("Azure token audience does not match the telemetry endpoint.")
        if token.count(".") == 2:
            # Claims are a consistency check, not signature verification; Azure
            # remains responsible for validating the token at the fixed endpoint.
            try:
                segment = token.split(".")[1]
                claims = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
            except (ValueError, UnicodeError):
                raise AzureCollectionError("Azure token claims could not be read.") from None
            if (not isinstance(claims, dict)
                    or str(claims.get("tid") or "").casefold() != document["tenant"].casefold()
                    or str(claims.get("aud") or "").rstrip("/") != audience):
                raise AzureCollectionError("Azure token claims do not match the telemetry audience and tenant.")
        return token

    def _telemetry_post(
        self, resource: dict[str, Any], identity: str, *, application_insights: bool = False,
    ) -> Any:
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,127}", identity):
            raise AzureCollectionError("Telemetry endpoint resource ID is invalid; query was not sent.")
        audience, collection = (
            ("https://api.applicationinsights.io", "apps") if application_insights
            else ("https://api.loganalytics.io", "workspaces")
        )
        url = f"{audience}/v1/{collection}/{identity}/query"
        token = self._telemetry_token(resource, audience)
        request = Request(
            url, data=json.dumps({"query": _genai_kql(application_insights=application_insights)}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        request.add_unredirected_header("Authorization", "Bearer " + token)
        try:
            try:
                response = self._telemetry_transport(request, timeout=max(1, min(self.timeout, 60)))
            except HTTPError as exc:
                response = exc
            with response:
                if response.geturl() != url:
                    raise AzureCollectionError("Telemetry response identity changed; redirects are not allowed.")
                status = response.status
                if 300 <= status < 400:
                    raise AzureCollectionError(f"Telemetry HTTP {status}: redirects are not allowed.")
                limit = _TELEMETRY_MAX_BYTES if status == 200 else _TELEMETRY_ERROR_BYTES
                raw = response.read(limit + 1)
                if len(raw) > limit:
                    raise AzureCollectionError(f"Telemetry HTTP {status}: response exceeded the size limit.")
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeError):
                raise AzureCollectionError(f"Telemetry HTTP {status}: response was not valid JSON.") from None
            if status != 200:
                detail = _telemetry_error_detail(payload.get("error", {}) if isinstance(payload, dict) else {}, token)
                raise AzureCollectionError(f"Telemetry HTTP {status}: {detail}")
            if not isinstance(payload, dict):
                raise AzureCollectionError("Telemetry response was not a JSON object.")
            if payload.get("error"):
                raise AzureCollectionError(f"Telemetry query failed: {_telemetry_error_detail(payload['error'], token)}")
            return payload
        except (OSError, URLError, HTTPTransportError):
            raise AzureCollectionError("Telemetry HTTPS request failed or timed out; no query result was collected.") from None

    @staticmethod
    def _is_relevant_group(
        name: str, factory: dict[str, Any] | None, subscription: str | None = None,
    ) -> bool:
        if not factory:
            return True
        targets = factory.get("monitoring_targets")
        if targets:
            for target in targets:
                if subscription and target["subscription_id"].casefold() != subscription.casefold():
                    continue
                prefix = target["prefix"].strip("-_").casefold()
                suffix = target["suffix"].strip("-_").casefold()
                lowered = name.casefold()
                if prefix and not lowered.startswith(prefix + "-"):
                    continue
                env = "(?:stage|test)" if target["environment"] == "stage" else re.escape(target["environment"])
                tail = rf"-{re.escape(target['location_suffix'])}-{env}"
                if suffix:
                    tail += rf"-{re.escape(suffix)}"
                project_suffix = target.get("project_suffix", "").strip("-_").casefold()
                if project_suffix:
                    tail += rf"(?:-{re.escape(project_suffix)})?"
                if re.search(tail + r"(?:-rg)?$", lowered):
                    return True
            return False
        parsed = parse_resource_group_name(name)
        projects = set(factory.get("project_numbers", []))
        prefix = str(factory.get("prefix_rg") or "").strip("-_").casefold()
        suffix = str(factory.get("suffix_rg") or "").strip("-_").casefold()
        lowered = name.casefold()
        prefix_match = not prefix or lowered.startswith(prefix + "-")
        suffix_match = not suffix or bool(re.search(
            rf"(^|[-_]){re.escape(suffix)}([-_]|$)", lowered
        ))
        identity_match = prefix_match and suffix_match
        if prefix or suffix:
            if not identity_match:
                return False
        project_match = (
            parsed["project_number"]
            and (not projects or parsed["project_number"] in projects)
        )
        return bool(
            parsed["is_common"] or project_match
            or ((prefix or suffix) and identity_match)
        )

    def get_inventory(
        self, folder: str, subscription_ids: list[str],
        force_refresh: bool = False, factory: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scope = {
            "telemetry_auth_scope": "explicit-token-https-v3",
            "telemetry_query_schema": "endpoint-specific-tables-v1",
            "monitoring_targets": (factory or {}).get("monitoring_targets", []),
            "monitoring_regions": (factory or {}).get("monitoring_regions", []),
            "subscriptions": sorted(set(subscription_ids)),
            "subscription_tenants": (factory or {}).get("subscription_tenants", {}),
            "tenant_ids": (factory or {}).get("tenant_ids", []),
            "prefix": (factory or {}).get("prefix_rg", ""),
            "suffix": (factory or {}).get("suffix_rg", ""),
        }
        cached = self._scoped_snapshot(folder, scope)
        if cached and not force_refresh:
            return self._cached_inventory(
                cached, "Using cached Azure inventory; request a refresh for current data."
            )

        if not subscription_ids:
            return self._fallback(
                folder, "No valid Azure subscription IDs were found in current factory variables.", scope
            )
        try:
            groups: list[dict[str, Any]] = []
            resources: list[dict[str, Any]] = []
            inventory_warnings: list[str] = []
            successful_collections = 0
            for subscription in sorted(set(subscription_ids)):
                expected_tenant = scope["subscription_tenants"].get(subscription)
                if expected_tenant:
                    try:
                        metadata = self._run_json([
                            "account", "show", "--subscription", subscription, "--query", "tenantId",
                        ])
                        if not isinstance(metadata, str) or metadata.casefold() != expected_tenant.casefold():
                            inventory_warnings.append(
                                f"Skipped subscription {subscription}: Azure CLI tenant does not match "
                                f"the configured tenant {expected_tenant}. Verify the active factory configuration."
                            )
                            continue
                    except AzureCollectionError as exc:
                        inventory_warnings.append(_collection_warning(
                            {"id": f"/subscriptions/{subscription}"}, exc
                        ))
                        continue
                for entity, target in (("group", groups), ("resource", resources)):
                    try:
                        target.extend(self._run_az(entity, subscription))
                        successful_collections += 1
                    except AzureCollectionError as exc:
                        inventory_warnings.append(_collection_warning(
                            {"id": f"/subscriptions/{subscription} ({entity} inventory)"},
                            exc,
                        ))
            if not successful_collections:
                return self._fallback(folder, _combined_warnings(*inventory_warnings) or "", scope)
            all_resources = resources
            relevant_groups = {
                (str(group.get("subscriptionId") or "").casefold(), str(group.get("name") or "").casefold())
                for group in groups
                if self._is_relevant_group(str(group.get("name") or ""), factory, group.get("subscriptionId"))
            }
            if factory:
                relevant_app_insights = [
                    resource for resource in all_resources
                    if str(resource.get("type", "")).casefold()
                    == "microsoft.insights/components"
                    and (str(resource.get("subscriptionId") or "").casefold(), str(resource.get("resourceGroup") or "").casefold())
                    in relevant_groups
                ]
                linked_workspace_ids = {
                    str((item.get("properties") or {}).get("WorkspaceResourceId") or "").casefold()
                    for item in relevant_app_insights
                } - {""}
                groups = [
                    group for group in groups
                    if (str(group.get("subscriptionId") or "").casefold(), str(group.get("name") or "").casefold()) in relevant_groups
                ]
                resources = [
                    resource for resource in resources
                    if self._is_relevant_group(
                        str(resource.get("resourceGroup") or ""), factory, resource.get("subscriptionId")
                    )
                    or (not factory.get("monitoring_targets") and
                        str(resource.get("id") or "").casefold() in linked_workspace_ids)
                ]
            tenant_map = {key.casefold(): value for key, value in scope["subscription_tenants"].items()}
            telemetry_resources = [
                resource | {"_expected_tenant_id": tenant_map.get(str(resource.get("subscriptionId") or "").casefold(), "")}
                for resource in resources
            ] if tenant_map else resources
            telemetry, telemetry_warnings = self._collect_telemetry(telemetry_resources)
            payload = {
                "configuration_scope": scope,
                "source": "azure",
                "warning": _combined_warnings(
                    "Azure inventory collection is incomplete." if inventory_warnings else None,
                    *inventory_warnings,
                    "Azure inventory retained; telemetry collection is incomplete."
                    if telemetry_warnings else None,
                    *telemetry_warnings,
                ),
                "subscriptions": sorted(set(subscription_ids)),
                "resource_groups": groups,
                "inventory_complete": not inventory_warnings,
                "resources": resources,
                "telemetry": telemetry,
                "collected_at": _utc_now(),
            }
            self.store.upsert_prompt_records(
                folder, telemetry.get("prompt_records", [])
            )
            self.store.save_snapshot(folder, "azure", payload, payload["collected_at"])
            return payload
        except AzureCollectionError as exc:
            return self._fallback(folder, str(exc), scope)

    def _scoped_snapshot(self, folder: str, scope: dict[str, Any]) -> dict[str, Any] | None:
        cached = self.store.latest_snapshot(folder, ("azure",))
        if cached and cached["payload"].get("configuration_scope") == scope:
            return cached
        return None

    @staticmethod
    def _cached_inventory(cached: dict[str, Any], warning: str) -> dict[str, Any]:
        payload = copy.deepcopy(cached["payload"])
        payload.update({
            "source": "cached",
            "warning": _combined_warnings(warning, payload.get("warning")),
            "cached_at": cached["created_at"],
        })
        telemetry = payload.get("telemetry") or {}
        for row in telemetry.get("prompt_records", []):
            if row.get("source") == "azure":
                row["source"] = "cached"
        for point in telemetry.get("cognitive_metric_points", []):
            point["source"] = "cached"
        return payload

    def _fallback(self, folder: str, warning: str, scope: dict[str, Any]) -> dict[str, Any]:
        cached = self._scoped_snapshot(folder, scope)
        if cached:
            return self._cached_inventory(
                cached, f"Azure refresh failed; retained cached inventory. {warning}"
            )
        return {
            "source": "unavailable",
            "warning": f"Azure inventory unavailable; no cached snapshot. {warning}",
            "subscriptions": [], "resource_groups": [], "resources": [],
            "telemetry": {}, "collected_at": None,
        }

    def _collect_telemetry(
        self, resources: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], list[str]]:
        workspaces = [
            item for item in resources
            if str(item.get("type", "")).casefold()
            == "microsoft.operationalinsights/workspaces"
        ]
        cognitive = [
            item for item in resources
            if str(item.get("type", "")).casefold()
            == "microsoft.cognitiveservices/accounts"
        ]
        app_insights = [
            item for item in resources
            if str(item.get("type", "")).casefold()
            == "microsoft.insights/components"
        ]
        successful_workspace_ids: set[str] = set()
        successful_prompt_queries = 0
        records: list[dict[str, Any]] = []
        metric_points: list[dict[str, Any]] = []
        warnings: list[str] = []
        collection_errors: list[dict[str, str]] = []

        def record_error(resource: dict[str, Any], error: AzureCollectionError) -> None:
            warnings.append(_collection_warning(resource, error))
            collection_errors.append({
                "resource_id": str(resource.get("id") or resource.get("name") or ""),
                "detail": str(error),
            })

        for workspace in workspaces:
            try:
                customer_id = (
                    (workspace.get("properties") or {}).get("customerId")
                    or self._workspace_customer_id(workspace)
                )
                if customer_id:
                    records.extend(self._query_workspace(str(customer_id), workspace))
                    successful_prompt_queries += 1
                    if workspace.get("id"):
                        successful_workspace_ids.add(str(workspace["id"]).casefold())
                else:
                    raise AzureCollectionError("Workspace customer ID was not returned.")
            except AzureCollectionError as exc:
                record_error(workspace, exc)
        for component in app_insights:
            if str(
                (component.get("properties") or {}).get("WorkspaceResourceId") or ""
            ).casefold() in successful_workspace_ids:
                continue
            try:
                records.extend(self._query_app_insights(component, successful_workspace_ids))
                successful_prompt_queries += 1
            except AzureCollectionError as exc:
                record_error(component, exc)
        for resource in cognitive:
            try:
                metric_points.extend(self._query_cognitive_metrics(resource))
            except AzureCollectionError as exc:
                record_error(resource, exc)
        return {
            "prompt_records": records,
            "cognitive_metric_points": metric_points,
            "workspace_count": len(workspaces),
            "app_insights_count": len(app_insights),
            "cognitive_account_count": len(cognitive),
            "collection_errors": collection_errors,
            "successful_prompt_queries": successful_prompt_queries,
        }, warnings

    def _query_app_insights(
        self, component: dict[str, Any], queried_workspaces: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        properties = component.get("properties") or {}
        app_id = properties.get("AppId") or properties.get("appId")
        if not app_id:
            shown = self._run_resource_json(component, [
                "resource", "show", "--ids", str(component.get("id") or ""),
            ])
            if isinstance(shown, dict):
                shown_properties = shown.get("properties") or {}
                app_id = shown_properties.get("AppId") or shown_properties.get("appId")
                properties = shown_properties
        linked_workspace = str(properties.get("WorkspaceResourceId") or "").casefold()
        if linked_workspace and linked_workspace in (queried_workspaces or set()):
            # Generic ARM inventory omits these properties. Once expanded, reuse
            # the successful workspace query rather than hitting the legacy app API.
            return []
        if not app_id:
            raise AzureCollectionError("Application Insights AppId was not returned.")
        payload = self._telemetry_post(component, app_id, application_insights=True)
        defaults = {
            "region": component.get("location"),
            "source": "azure",
            "environment": _environment_from_name(
                str(component.get("resourceGroup") or "")
            ),
            "project_number": parse_resource_group_name(
                str(component.get("resourceGroup") or "")
            )["project_number"],
        }
        return self.parse_telemetry_rows(self._tabular_rows(payload), defaults)

    def _workspace_customer_id(self, workspace: dict[str, Any]) -> str | None:
        value = self._run_resource_json(workspace, [
            "monitor", "log-analytics", "workspace", "show",
            "--ids", str(workspace.get("id") or ""),
        ])
        if isinstance(value, dict):
            return _nullable_text(value.get("customerId"))
        return None

    def _query_workspace(
        self, customer_id: str, workspace: dict[str, Any],
    ) -> list[dict[str, Any]]:
        payload = self._telemetry_post(workspace, customer_id)
        rows = self._tabular_rows(payload)
        defaults = {
            "region": workspace.get("location"),
            "source": "azure",
            "environment": _environment_from_name(
                str(workspace.get("resourceGroup") or "")
            ),
            "project_number": (
                parse_resource_group_name(
                    str(workspace.get("resourceGroup") or "")
                )["project_number"]
            ),
        }
        return self.parse_telemetry_rows(rows, defaults)

    @staticmethod
    def _tabular_rows(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if not isinstance(payload, dict):
            raise AzureCollectionError("Telemetry response was not a JSON object or array.")
        if payload.get("error"):
            raise AzureCollectionError(
                f"Telemetry query failed: {_telemetry_error_detail(payload['error'])}"
            )
        if isinstance(payload.get("value"), list):
            return [row for row in payload["value"] if isinstance(row, dict)]
        tables = payload.get("tables")
        if not isinstance(tables, list):
            raise AzureCollectionError("Telemetry response did not contain query tables.")
        result: list[dict[str, Any]] = []
        for table in tables:
            if (not isinstance(table, dict) or not isinstance(table.get("columns"), list)
                    or not isinstance(table.get("rows"), list)):
                raise AzureCollectionError("Telemetry response contained an invalid query table.")
            columns = []
            for column in table["columns"]:
                if not isinstance(column, dict) or not isinstance(column.get("name"), str):
                    raise AzureCollectionError("Telemetry response contained an invalid query column.")
                columns.append(column["name"])
            if len(set(columns)) != len(columns):
                raise AzureCollectionError("Telemetry response contained duplicate query columns.")
            for values in table["rows"]:
                if not isinstance(values, list) or len(values) != len(columns):
                    raise AzureCollectionError("Telemetry response contained an invalid query row.")
                result.append(dict(zip(columns, values)))
        return result

    @classmethod
    def parse_telemetry_rows(
        cls, rows: Iterable[dict[str, Any]],
        defaults: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        defaults = defaults or {}
        categorizer = PromptCategorizer()
        result = []
        for raw in rows:
            dimensions = _dynamic_dict(
                raw.get("customDimensions")
                or raw.get("Properties")
                or raw.get("properties")
            )
            measurements = _dynamic_dict(
                raw.get("customMeasurements")
                or raw.get("Measurements")
                or raw.get("measurements")
            )

            def first(*names: str, default: Any = None) -> Any:
                for name in names:
                    for source in (raw, dimensions, measurements):
                        value = source.get(name)
                        if value is not None and value != "":
                            return value
                return default

            prompt = _message_text(first(
                "prompt", "input_messages", "gen_ai.input.messages",
                "gen_ai.prompt", "request_body",
            ))
            response = _message_text(first(
                "response", "output_messages", "gen_ai.output.messages",
                "gen_ai.completion", "response_body",
            ))
            categorization = categorizer.categorize(prompt)
            duration = first("latency_ms", "duration_ms", "DurationMs", "duration")
            if hasattr(duration, "total_seconds"):
                duration = duration.total_seconds() * 1000
            success = first("success", "Success", default=True)
            status = first("resultCode", "ResultCode", "status_code")
            if status is not None:
                try:
                    success = bool(success) and int(status) < 400
                except (TypeError, ValueError):
                    pass
            record = _normalize_prompt_record({
                "operation_id": first(
                    "operation_id", "OperationId", "operation_Id",
                    "gen_ai.operation.id", "id",
                ),
                "conversation_id": first(
                    "conversation_id", "gen_ai.conversation.id",
                    "openai.conversation.id",
                ),
                "response_id": first(
                    "response_id", "gen_ai.response.id", "openai.response.id"
                ),
                "timestamp": first(
                    "timestamp", "TimeGenerated", "timeGenerated", "Timestamp"
                ),
                "project_number": first(
                    "project_number", default=defaults.get("project_number")
                ),
                "environment": first(
                    "environment", "deployment.environment",
                    default=defaults.get("environment"),
                ),
                "region": first(
                    "region", "cloud.region", default=defaults.get("region")
                ),
                "model": first(
                    "model", "gen_ai.request.model", "gen_ai.response.model",
                    "openai.request.model", "azure.openai.deployment.name",
                    default="unknown",
                ),
                "category": first("category", default=categorization["category"]),
                "prompt": prompt,
                "response": response,
                "input_tokens": first(
                    "input_tokens", "gen_ai.usage.input_tokens",
                    "openai.usage.prompt_tokens", "azure.openai.usage.prompt_tokens",
                ),
                "cached_input_tokens": first(
                    "cached_input_tokens", "gen_ai.usage.cached_input_tokens",
                    "gen_ai.usage.cache_read.input_tokens",
                    "gen_ai.usage.input_tokens.cache_read",
                    "openai.usage.prompt_tokens_details.cached_tokens",
                    "azure.openai.usage.cached_prompt_tokens",
                ),
                "output_tokens": first(
                    "output_tokens", "gen_ai.usage.output_tokens",
                    "openai.usage.completion_tokens",
                    "azure.openai.usage.completion_tokens",
                ),
                "total_tokens": first(
                    "total_tokens", "gen_ai.usage.total_tokens",
                    "openai.usage.total_tokens",
                ),
                "latency_ms": duration,
                "success": success,
                "error_type": first(
                    "error_type", "error.type",
                    default=None if success else str(status or "request_error"),
                ),
                "source": defaults.get("source", "azure"),
            })
            result.append(record)
        return result

    def _query_cognitive_metrics(
        self, resource: dict[str, Any],
    ) -> list[dict[str, Any]]:
        resource_id = str(resource.get("id") or "")
        definitions = self._run_resource_json(resource, [
            "monitor", "metrics", "list-definitions", "--resource", resource_id,
        ])
        wanted = {
            "azureopenairequests", "processedprompttokens", "generatedtokens",
            "tokentransaction",
        }
        available = []
        for definition in definitions if isinstance(definitions, list) else []:
            metric_name = (
                (definition.get("name") or {}).get("value")
                if isinstance(definition, dict) else None
            )
            if metric_name and metric_name.casefold() in wanted:
                available.append(metric_name)
        if not available:
            return []
        start = (datetime.now(timezone.utc) - timedelta(days=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        payload = self._run_resource_json(resource, [
            "monitor", "metrics", "list", "--resource", resource_id,
            "--metric", ",".join(available), "--interval", "P1D",
            "--start-time", start, "--aggregation", "Total",
        ])
        points: list[dict[str, Any]] = []
        for metric in payload.get("value", []) if isinstance(payload, dict) else []:
            name = ((metric.get("name") or {}).get("value") or "unknown")
            for series in metric.get("timeseries", []):
                for point in series.get("data", []):
                    points.append({
                        "timestamp": point.get("timeStamp"),
                        "metric": name,
                        "value": point.get("total", 0),
                        "resource_id": resource_id,
                        "model": (
                            next((
                                item.get("value")
                                for item in series.get("metadatavalues", [])
                                if str((item.get("name") or {}).get("value", "")).casefold()
                                in {"modeldeploymentname", "modelname"}
                            ), None)
                        ),
                        "source": "azure",
                    })
        return points


def _seeded_inventory() -> dict[str, Any]:
    groups = [
        {"name": "aif-project001-dev-rg", "location": "swedencentral", "subscriptionId": "demo"},
        {"name": "aif-project001-test-rg", "location": "swedencentral", "subscriptionId": "demo"},
        {"name": "aif-project001-prod-rg", "location": "westeurope", "subscriptionId": "demo"},
        {"name": "aif-common-rg", "location": "swedencentral", "subscriptionId": "demo"},
    ]
    specs = [
        ("dev", "swedencentral", "Microsoft.Storage/storageAccounts", "Succeeded"),
        ("dev", "swedencentral", "Microsoft.CognitiveServices/accounts", "Succeeded"),
        ("dev", "swedencentral", "Microsoft.Search/searchServices", "Succeeded"),
        ("stage", "swedencentral", "Microsoft.Storage/storageAccounts", "Succeeded"),
        ("stage", "swedencentral", "Microsoft.MachineLearningServices/workspaces", "Succeeded"),
        ("prod", "westeurope", "Microsoft.Storage/storageAccounts", "Succeeded"),
        ("prod", "westeurope", "Microsoft.CognitiveServices/accounts", "Succeeded"),
        ("prod", "westeurope", "Microsoft.Search/searchServices", "Updating"),
    ]
    env_rg = {
        "dev": groups[0]["name"], "stage": groups[1]["name"], "prod": groups[2]["name"]
    }
    resources = [
        {
            "name": f"demo-{index}",
            "type": service,
            "location": location,
            "resourceGroup": env_rg[environment],
            "subscriptionId": "demo",
            "provisioningState": state,
        }
        for index, (environment, location, service, state) in enumerate(specs, 1)
    ]
    return {
        "source": "seeded",
        "warning": None,
        "subscriptions": [],
        "resource_groups": groups,
        "resources": resources,
        "telemetry": {
            "prompt_records": _seeded_prompt_records(),
            "cognitive_metric_points": [],
            "workspace_count": 0,
            "cognitive_account_count": 2,
        },
        "collected_at": _utc_now(),
    }


def _seeded_prompt_records() -> list[dict[str, Any]]:
    anchor = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    models = ("gpt-4.1-mini", "gpt-4o", "text-embedding-3-large")
    prompts = (
        ("Refactor this Python API and add unit tests.", "Coding"),
        ("Build a grounded vector search query for product documents.", "Search/RAG"),
        ("Summarize the telemetry incident for the operations team.", "Operations"),
        ("Plan a secure model deployment with least privilege.", "Security/Governance"),
        ("Analyze this SQL dataset for weekly trends.", "Data/Analytics"),
        ("Create a retraining plan for model drift.", "MLOps"),
    )
    records = []
    for index in range(30):
        prompt, category = prompts[index % len(prompts)]
        input_tokens = 180 + index * 13
        cached = 0 if index % 3 else 60 + index
        output = 70 + index * 7
        records.append(_normalize_prompt_record({
            "operation_id": f"seed-operation-{index:03d}",
            "conversation_id": f"seed-conversation-{index // 3:03d}",
            "response_id": f"seed-response-{index:03d}",
            "timestamp": (
                anchor - timedelta(days=29 - index)
            ).isoformat().replace("+00:00", "Z"),
            "project_number": "001",
            "environment": ("dev", "stage", "prod")[index % 3],
            "region": ("swedencentral", "westeurope")[index % 2],
            "model": models[index % len(models)],
            "category": category,
            "prompt": prompt,
            "response": "Seeded demonstration response.",
            "input_tokens": input_tokens,
            "cached_input_tokens": cached,
            "output_tokens": output,
            "latency_ms": 420 + index * 23,
            "success": index % 9 != 0,
            "error_type": "rate_limit" if index % 9 == 0 else None,
            "source": "seeded",
        }))
    return records


def _mock_prompt_records() -> list[dict[str, Any]]:
    return [{**row, "source": "mock", "response": "Mock demonstration response."}
            for row in _seeded_prompt_records()]


def _filter_prompt_rows(
    rows: list[dict[str, Any]], project_number: str | None = None,
    environment: str | None = None, model: str | None = None,
    category: str | None = None, search: str | None = None,
    success: bool | None = None,
) -> list[dict[str, Any]]:
    result = []
    needle = search.casefold() if search else None
    for row in rows:
        if project_number is not None and row.get("project_number") != project_number:
            continue
        if environment is not None and row.get("environment") != environment:
            continue
        if model is not None and row.get("model") != model:
            continue
        if category is not None and row.get("category") != category:
            continue
        if success is not None and bool(row.get("success")) is not success:
            continue
        if needle and needle not in (
            f"{row.get('prompt', '')} {row.get('response', '')} "
            f"{row.get('operation_id', '')}"
        ).casefold():
            continue
        result.append(row)
    return result


def _prompt_metadata(rows: list[dict[str, Any]]) -> dict[str, list[Any]]:
    return {
        "project_numbers": sorted({
            row["project_number"] for row in rows if row.get("project_number")
        }),
        "environments": sorted({
            row["environment"] for row in rows if row.get("environment")
        }),
        "models": sorted({row["model"] for row in rows if row.get("model")}),
        "categories": sorted({
            row["category"] for row in rows if row.get("category")
        }),
        "success_values": [True, False],
    }


class OperationsService:
    """Compose local discovery, Azure inventory, and persisted operations data."""

    def __init__(
        self, store: OperationsStore | None = None,
        discovery: LocalFactoryDiscovery | None = None,
        inventory: AzureInventoryProvider | None = None,
    ):
        self.store = store or OperationsStore()
        self.discovery = discovery or LocalFactoryDiscovery()
        self.inventory = inventory or AzureInventoryProvider(self.store)

    def overview(
        self, aifactory_folder: str, include_azure: bool = True,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        local = self.discovery.discover(aifactory_folder)
        if include_azure:
            inventory = self.inventory.get_inventory(
                local["folder"], local["subscription_ids"], force_refresh, local
            )
        else:
            inventory = {
                "source": "local",
                "warning": None,
                "subscriptions": local["subscription_ids"],
                "resource_groups": [],
                "resources": [],
                "collected_at": _utc_now(),
            }
        groups = inventory["resource_groups"]
        resources = inventory["resources"]
        discovered_resources = self.discovery.annotate_with_inventory(
            local, groups, resources
        )
        stored_prompts = self.store.query_prompt_records(
            local["folder"], limit=5000
        )["rows"]
        telemetry = inventory.get("telemetry") or {}
        fresh_ids = {
            row.get("operation_id") for row in telemetry.get("prompt_records", [])
        } if inventory["source"] == "azure" else set()
        prompt_rows = [
            {
                **row,
                "source": "cached" if row.get("source") == "azure"
                and row.get("operation_id") not in fresh_ids else row.get("source", "local"),
            }
            for row in (stored_prompts or telemetry.get("prompt_records") or [])
        ]
        prompt_source = _records_source(prompt_rows)
        charts = self._charts(
            local["folder"], resources, inventory["source"], prompt_rows,
            telemetry.get("cognitive_metric_points") or [],
            inventory.get("configuration_scope"),
        )
        mock_charts = []
        if not prompt_rows or not resources:
            mock_rows = _mock_prompt_records()
            mock_resources = _seeded_inventory()["resources"]
            demonstration = self._charts(local["folder"], mock_resources, "mock", mock_rows, [])
            # Replace only missing chart series, never actual inventory/identity evidence.
            for key, chart in charts.items():
                if key != "snapshot_history" and not chart.get("labels"):
                    charts[key] = demonstration[key]
                    mock_charts.append(key)
            if not prompt_rows:
                prompt_rows = mock_rows
                prompt_source = "mock"
        regions = self._regions(local, groups, resources, discovered_resources["projects"], inventory)
        try:
            findings_warnings = RegionFindingsStore(self.store.db_path).overlay(
                local["folder"], regions
            )
        except (OSError, sqlite3.Error):
            for region in regions:
                region["pipeline_findings"] = []
            findings_warnings = [
                "Historical region findings unavailable; no success is inferred."
            ]
        factory = {
            key: local[key] for key in (
                "folder", "name", "orchestrator", "active_regions", "primary_region", "subscriptions",
                "subscription_ids", "project_numbers", "prefix_rg", "suffix_rg",
                "variables_found", "dashboard_url", "monitoring_regions",
            )
        }
        factory["project_count"] = len(discovered_resources["projects"])
        factory["resource_group_count"] = len(groups)
        factory["resource_count"] = len(resources)
        overall_source = inventory["source"]
        warning = _combined_warnings(inventory.get("warning"), *findings_warnings)
        if prompt_source != inventory["source"] and inventory["source"] not in {"seeded", "local"}:
            overall_source = "mixed"
        if prompt_source == "mock" or mock_charts:
            warning = _combined_warnings(warning,
                "Source: Mock for unavailable monitoring data. Demonstration values are not actual "
                "factory usage or deployment evidence. Available real data keeps its own source label.")
            if not resources and not telemetry.get("cognitive_metric_points"):
                overall_source = "mock" if prompt_source == "mock" else "mixed"
        return {
            "generated_at": _utc_now(),
            "source": overall_source,
            "warning": warning,
            "factory": factory,
            "regions": regions,
            "projects": discovered_resources["projects"],
            "common_resource_groups": discovered_resources["common_resource_groups"],
            "resource_inventory": self._resource_summary(groups, resources, inventory),
            "monitoring": charts,
            "operation_configs": self.store.list_configs(local["folder"]),
            "factory_action_requests": self.store.list_action_requests(local["folder"]),
            "prompt_summary": self._prompt_summary(prompt_rows, prompt_source),
        }

    def report_region_findings(self, folder: str, report: dict[str, Any]) -> dict[str, Any]:
        return RegionFindingsStore(self.store.db_path).record_report(folder, report)

    def import_region_findings(self, folder: str, content: str) -> dict[str, Any]:
        return RegionFindingsStore(self.store.db_path).import_content(folder, content)

    def load_config(
        self, folder: str, project_number: str, environment: str, kind: str,
    ) -> dict[str, Any]:
        return self.store.load_config(folder, project_number, environment, kind)

    def save_config(
        self, folder: str, project_number: str, environment: str,
        kind: str, config: dict[str, Any],
    ) -> dict[str, Any]:
        return self.store.save_config(
            folder, project_number, environment, kind, copy.deepcopy(config)
        )

    def create_factory_action(
        self, folder: str, action: str, target_region: str,
        source_region: str | None = None,
    ) -> dict[str, Any]:
        return self.store.create_action_request(
            folder, action, target_region, source_region
        )

    def create_project_action(
        self, folder: str, project_number: str, source_environment: str,
        target_environment: str, action: str,
    ) -> dict[str, Any]:
        return self.store.create_project_action(
            folder, project_number, source_environment, target_environment, action
        )

    def prompts(
        self, aifactory_folder: str, project_number: str | None = None,
        environment: str | None = None, model: str | None = None,
        category: str | None = None, search: str | None = None,
        success: bool | None = None, limit: int = 100, offset: int = 0,
    ) -> dict[str, Any]:
        result = self.store.query_prompt_records(
            aifactory_folder, project_number, environment, model, category,
            search, success, limit, offset,
        )
        source = "local"
        warning = None
        if not result["rows"] and result["total"] == 0 and not self.store.query_prompt_records(
            aifactory_folder, limit=1
        )["total"]:
            seeded = _filter_prompt_rows(
                _mock_prompt_records(), project_number, environment, model,
                category, search, success,
            )
            result = {
                "rows": seeded[offset:offset + limit],
                "total": len(seeded), "limit": limit, "offset": offset,
            }
            source = "mock"
            warning = (
                "Source: Mock. No actual GenAI prompt telemetry is available; "
                "these rows are demonstration data, not live usage."
            )
            metadata = _prompt_metadata(seeded)
        else:
            metadata = self.store.prompt_filter_metadata(aifactory_folder)
            sources = {row.get("source", "local") for row in result["rows"]}
            source = next(iter(sources)) if len(sources) == 1 else "mixed"
        return {
            **result, "source": source, "warning": warning,
            "filters": metadata,
            "summary": self._prompt_summary(result["rows"], source),
        }

    @staticmethod
    def _resource_summary(
        groups: list[dict[str, Any]], resources: list[dict[str, Any]],
        inventory: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "source": inventory["source"],
            "collected_at": inventory.get("collected_at"),
            "is_complete": inventory.get("inventory_complete") is True,
            "subscriptions": inventory.get("subscriptions", []),
            "subscription_count": len(inventory.get("subscriptions", [])),
            "resource_group_count": len(groups),
            "resource_count": len(resources),
            "resource_groups": groups,
            "resources": resources,
        }

    def _charts(
        self, folder: str, resources: list[dict[str, Any]], source: str,
        prompt_rows: list[dict[str, Any]],
        metric_points: list[dict[str, Any]],
        configuration_scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        def chart(
            counter: Counter[str], chart_source: str = source,
            chart_type: str = "column",
        ) -> dict[str, Any]:
            pairs = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
            return {
                "labels": [item[0] for item in pairs],
                "values": [item[1] for item in pairs],
                "source": chart_source,
                "chart_type": chart_type,
            }

        by_service = Counter(str(item.get("type") or "Unknown") for item in resources)
        by_environment = Counter(
            _environment_from_name(str(item.get("resourceGroup", ""))) or "common"
            for item in resources
        )
        by_region = Counter(str(item.get("location") or "unknown") for item in resources)
        by_group = Counter(str(item.get("resourceGroup") or "unknown") for item in resources)
        by_state = Counter(
            str(
                item.get("provisioningState")
                or (item.get("properties") or {}).get("provisioningState")
                or "Unknown"
            )
            for item in resources
        )
        top_groups = Counter(dict(by_group.most_common(10)))
        current_timestamp = _utc_now()
        snapshots = self.store.list_snapshots(folder)
        history = [
            {
                "timestamp": item["created_at"],
                "value": len(item["payload"].get("resources", [])),
                "source": item["source"],
            }
            for item in snapshots
            if isinstance(item["payload"].get("resources"), list)
            and (configuration_scope is None or item["payload"].get("configuration_scope") == configuration_scope)
        ]
        if source == "azure" and not any(
            point["timestamp"] == current_timestamp for point in history
        ):
            # The provider's just-saved point is already represented by its own
            # collection timestamp; only append when a custom provider was used.
            newest_count = history[-1]["value"] if history else None
            if newest_count != len(resources):
                history.append({
                    "timestamp": current_timestamp,
                    "value": len(resources),
                    "source": "azure",
                })
        real_points = [item for item in history if item["source"] == "azure"]
        if len(real_points) < 2 and source != "unavailable":
            anchor = datetime.now(timezone.utc)
            seeded_values = [5, 6, 6, 7, 8, 8]
            seeded_history = [
                {
                    "timestamp": (anchor - timedelta(days=7 - index)).isoformat().replace(
                        "+00:00", "Z"
                    ),
                    "value": value,
                    "source": "seeded",
                }
                for index, value in enumerate(seeded_values)
            ]
            history = seeded_history + history
        telemetry_source = _records_source(prompt_rows)
        by_day: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "requests": 0, "success": 0, "errors": 0, "latency_total": 0.0,
                "latency_count": 0, "input": 0, "cached": 0, "output": 0,
            }
        )
        by_model_requests: Counter[str] = Counter()
        by_model_tokens: Counter[str] = Counter()
        for row in prompt_rows:
            day = str(row.get("timestamp") or "")[:10] or "unknown"
            point = by_day[day]
            point["requests"] += 1
            point["success" if row.get("success", True) else "errors"] += 1
            latency = _float(row.get("latency_ms"))
            if latency is not None:
                point["latency_total"] += latency
                point["latency_count"] += 1
            point["input"] += _integer(row.get("input_tokens"))
            point["cached"] += _integer(row.get("cached_input_tokens"))
            point["output"] += _integer(row.get("output_tokens"))
            model = str(row.get("model") or "unknown")
            by_model_requests[model] += 1
            by_model_tokens[model] += (
                _integer(row.get("input_tokens"))
                + _integer(row.get("output_tokens"))
            )
        usage_by_day = copy.deepcopy(by_day)
        for metric in metric_points:
            day = str(metric.get("timestamp") or "")[:10]
            name = str(metric.get("metric") or "").casefold()
            amount = _integer(metric.get("value"))
            if "request" in name:
                usage_by_day[day]["requests"] = max(usage_by_day[day]["requests"], amount)
            elif "prompt" in name:
                usage_by_day[day]["input"] = max(usage_by_day[day]["input"], amount)
            elif "generated" in name:
                usage_by_day[day]["output"] = max(usage_by_day[day]["output"], amount)
        days = sorted(by_day)
        usage_days = sorted(usage_by_day)
        usage_source = _records_source(prompt_rows + [
            {**point, "source": point.get("source") or source} for point in metric_points
        ])
        requests = [usage_by_day[day]["requests"] for day in usage_days]
        successes = [by_day[day]["success"] for day in days]
        errors = [by_day[day]["errors"] for day in days]
        latency = [
            round(by_day[day]["latency_total"] / by_day[day]["latency_count"], 2)
            if by_day[day]["latency_count"] else 0.0 for day in days
        ]
        return {
            "resources_by_service_type": chart(by_service, chart_type="pie"),
            "resources_by_environment": chart(by_environment, chart_type="column"),
            "resources_by_region": chart(by_region, chart_type="column"),
            "top_resource_groups": chart(top_groups, chart_type="bar"),
            "provisioning_state": chart(by_state, chart_type="pie"),
            "snapshot_history": {
                "labels": [item["timestamp"] for item in history],
                "values": [item["value"] for item in history],
                "sources": [item["source"] for item in history],
                "points": history,
            },
            "requests_over_time": {
                "labels": usage_days, "values": requests, "source": usage_source,
                "chart_type": "line",
            },
            "tokens_over_time": {
                "labels": usage_days,
                "series": {
                    "input": [usage_by_day[day]["input"] for day in usage_days],
                    "cached_input": [usage_by_day[day]["cached"] for day in usage_days],
                    "output": [usage_by_day[day]["output"] for day in usage_days],
                },
                "source": usage_source,
                "chart_type": "line",
                "stacked": True,
            },
            "requests_by_model": chart(
                by_model_requests, telemetry_source, "bar"
            ),
            "tokens_by_model": chart(by_model_tokens, telemetry_source, "bar"),
            "success_error_rate": {
                "labels": days,
                "series": {"success": successes, "error": errors},
                "success_rate": round(
                    100 * sum(successes) / max(1, sum(successes) + sum(errors)), 2
                ),
                "error_rate": round(
                    100 * sum(errors) / max(1, sum(successes) + sum(errors)), 2
                ),
                "source": telemetry_source,
                "chart_type": "line",
            },
            "latency_trend": {
                "labels": days, "values": latency, "unit": "ms",
                "source": telemetry_source, "chart_type": "line",
            },
        }

    @staticmethod
    def _prompt_summary(
        rows: list[dict[str, Any]], source: str,
    ) -> dict[str, Any]:
        total = len(rows)
        errors = sum(1 for row in rows if not row.get("success", True))
        return {
            "source": source,
            "record_count": total,
            "success_count": total - errors,
            "error_count": errors,
            "input_tokens": sum(_integer(row.get("input_tokens")) for row in rows),
            "cached_input_tokens": sum(
                _integer(row.get("cached_input_tokens")) for row in rows
            ),
            "output_tokens": sum(_integer(row.get("output_tokens")) for row in rows),
            "models": sorted({
                str(row.get("model")) for row in rows if row.get("model")
            }),
            "categories": sorted({
                str(row.get("category")) for row in rows if row.get("category")
            }),
        }

    @staticmethod
    def _regions(
        local: dict[str, Any], groups: list[dict[str, Any]],
        resources: list[dict[str, Any]], projects: list[dict[str, Any]],
        inventory: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        resource_counts = Counter(
            str(item.get("location", "")).lower() for item in resources
        )
        group_counts = Counter(
            str(item.get("location", "")).lower() for item in groups
        )
        projects_by_region: dict[str, set[str]] = defaultdict(set)
        for project in projects:
            for environment in project["environments"]:
                for region in environment.get("regions") or [environment.get("region")]:
                    if region:
                        projects_by_region[str(region).lower()].add(project["project_number"])
        configured = {str(item).lower() for item in local["active_regions"]}
        result = []
        known = set()
        for region in azure_region_catalog():
            name = region["name"]
            known.add(name)
            count = resource_counts[name]
            has_factory = bool(count or group_counts[name] or name in configured)
            region.update({
                "has_factory": has_factory,
                "factory_count": 1 if has_factory else 0,
                "project_count": len(projects_by_region[name]),
                "resource_count": count,
                "status": "active" if count else (
                    "configured" if name in configured else "available"
                ),
            })
            result.append(region)
        # Azure occasionally introduces a region before the checked-in catalog is
        # updated. Preserve such real inventory instead of silently dropping it.
        for name in sorted((set(resource_counts) | set(group_counts)) - known - {""}):
            result.append({
                "name": name,
                "display_name": name,
                "geography": "Unknown",
                "physical_location": "Unknown",
                "latitude": 0.0,
                "longitude": 0.0,
                "normalized_latitude": 0.0,
                "normalized_longitude": 0.0,
                "has_factory": True,
                "factory_count": 1,
                "project_count": len(projects_by_region[name]),
                "resource_count": resource_counts[name],
                "status": "active" if resource_counts[name] else "configured",
            })
        inventory = inventory or {}
        scope = {str(name).lower() for name in local.get("monitoring_regions", [])}
        for region in result:
            observed = region["resource_count"] > 0 or group_counts[region["name"]] > 0
            if region["name"] not in scope and not observed:
                count_status = "out_of_scope"
                detail = (
                    "Not checked: this region is outside the current factory's inventory scope "
                    f"({', '.join(sorted(scope)) or 'not configured'}). The factory marker can come "
                    "from a saved configuration. Load the matching AI Factory folder and refresh "
                    "to see its projects and resources; these are not confirmed zero counts."
                )
            elif inventory.get("source") not in ("azure", "cached"):
                count_status = "not_collected"
                detail = "Resource inventory has not been collected for this factory; counts are not confirmed."
            elif inventory.get("inventory_complete") is not True:
                count_status = "partial"
                detail = "Partial inventory: displayed nonzero counts are a lower bound; zero is not confirmed."
            else:
                count_status = "complete"
                detail = (
                    f"Source: {inventory['source']}; collected {inventory.get('collected_at') or 'at an unknown time'}. "
                    "Counts cover only the selected factory. Resources are grouped by their Azure location; "
                    "global or other-region dependencies are counted separately."
                )
            region["count_status"] = count_status
            region["count_details"] = detail
        return result
