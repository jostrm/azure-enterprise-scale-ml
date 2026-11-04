"""Deterministic micro-batch stream scoring with injectable sources and sinks."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import inference
from .config import load_json, validate_scenario, write_json


@dataclass(frozen=True)
class EventRecord:
    payload: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MalformedRecord:
    reason: str
    reference: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EventBatch:
    events: list[EventRecord]
    end_position: dict[str, Any]
    malformed: list[MalformedRecord] = field(default_factory=list)


@dataclass(frozen=True)
class Checkpoint:
    source_position: dict[str, Any]
    next_batch_id: int
    max_event_time: str | None
    recent_event_ids: list[str]
    model_identity: str
    source_identity: str


class EventSource(ABC):
    @property
    def identity(self) -> str:
        return type(self).__name__

    @abstractmethod
    def read(self, position: dict, max_events: int, timeout_seconds: float) -> EventBatch:
        """Read at most max_events starting after the committed position."""


class CheckpointStore(ABC):
    @abstractmethod
    def load(self) -> Checkpoint | None: ...

    @abstractmethod
    def commit(self, checkpoint: Checkpoint) -> None: ...


class PredictionSink(ABC):
    @abstractmethod
    def committed(self, batch_id: int) -> dict | None: ...

    @abstractmethod
    def write(self, batch_id: int, predictions, quarantine, metadata: dict) -> dict: ...


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode("utf-8")


def _hash_payload(predictions, quarantine, metadata: dict) -> str:
    return hashlib.sha256(_canonical({
        "predictions": predictions.to_dict("records"),
        "quarantine": quarantine.to_dict("records"),
        "metadata": {k: v for k, v in metadata.items() if k != "scored_at"},
    })).hexdigest()


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("event_time must be a timezone-aware ISO-8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("event_time must be timezone-aware")
    return parsed.astimezone(timezone.utc)


class JsonlDirectorySource(EventSource):
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    @property
    def identity(self) -> str:
        return "jsonl:" + str(self.directory.resolve())

    def _files(self) -> list[Path]:
        if not self.directory.is_dir():
            raise FileNotFoundError(f"Event directory not found: {self.directory}")
        return sorted(self.directory.glob("*.jsonl"), key=lambda p: p.name)

    def read(self, position: dict, max_events: int, timeout_seconds: float) -> EventBatch:
        if max_events < 1:
            raise ValueError("max_events must be positive")
        files = self._files()
        current = position.get("file")
        line = int(position.get("line", 0) or 0)
        start_index = 0
        if current:
            names = [p.name for p in files]
            start_index = names.index(current) if current in names else len(files)
        events: list[EventRecord] = []
        malformed: list[MalformedRecord] = []
        end = {"file": current, "line": line}
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        for file_index in range(start_index, len(files)):
            path = files[file_index]
            start_line = line if path.name == current else 0
            with path.open(encoding="utf-8") as stream:
                for number, raw in enumerate(stream):
                    if number < start_line:
                        continue
                    if time.monotonic() > deadline and events:
                        return EventBatch(events, end, malformed)
                    end = {"file": path.name, "line": number + 1}
                    raw = raw.rstrip("\n")
                    if not raw.strip():
                        continue
                    try:
                        payload = json.loads(raw)
                        if not isinstance(payload, dict):
                            raise ValueError("JSON event must be an object")
                        events.append(EventRecord(payload, {"file": path.name, "line": number + 1}))
                    except Exception as exc:
                        malformed.append(MalformedRecord("malformed_json", f"{path.name}:{number + 1}", {"error": str(exc)}))
                    if len(events) >= max_events:
                        return EventBatch(events, end, malformed)
            line = 0
        return EventBatch(events, end, malformed)


class FileCheckpointStore(CheckpointStore):
    def __init__(self, path: Path, *, scenario: str | None = None, model_identity: str | None = None,
                 source_identity: str | None = None, allow_identity_change: bool = False):
        self.path = Path(path)
        self.scenario = scenario
        self.model_identity = model_identity
        self.source_identity = source_identity
        self.allow_identity_change = allow_identity_change

    def load(self) -> Checkpoint | None:
        if not self.path.is_file():
            return None
        data = load_json(self.path)
        checkpoint = Checkpoint(**data)
        if not self.allow_identity_change:
            expected = {"model_identity": self.model_identity, "source_identity": self.source_identity}
            for key, value in expected.items():
                if value is not None and getattr(checkpoint, key) != value:
                    raise ValueError(f"Checkpoint {key} differs; refusing to resume another query/model")
        return checkpoint

    def commit(self, checkpoint: Checkpoint) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".staging")
        temporary.write_text(json.dumps(asdict(checkpoint), indent=2, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)


class ParquetDirectorySink(PredictionSink):
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def _batch_dir(self, batch_id: int) -> Path:
        return self.directory / f"batch-{batch_id:010d}"

    def committed(self, batch_id: int) -> dict | None:
        marker = self._batch_dir(batch_id) / "_SUCCESS.json"
        return load_json(marker) if marker.is_file() else None

    def write(self, batch_id: int, predictions, quarantine, metadata: dict) -> dict:
        import pandas as pd

        self.directory.mkdir(parents=True, exist_ok=True)
        receipt = {**metadata, "batch_id": batch_id, "prediction_rows": int(len(predictions)),
                   "quarantine_rows": int(len(quarantine)), "payload_sha256": _hash_payload(predictions, quarantine, metadata)}
        existing = self.committed(batch_id)
        if existing is not None:
            if existing.get("payload_sha256") != receipt["payload_sha256"]:
                raise ValueError(f"Committed batch {batch_id} has a different payload")
            return existing
        destination = self._batch_dir(batch_id)
        staging = self.directory / (destination.name + f".staging-{os.getpid()}-{time.time_ns()}")
        staging.mkdir(parents=True)
        try:
            predictions.to_parquet(staging / "predictions.parquet", index=False)
            quarantine.to_parquet(staging / "quarantine.parquet", index=False)
            write_json(staging / "_SUCCESS.json", receipt)
            staging.rename(destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return receipt


class EventHubsSource(EventSource):
    def __init__(self, fully_qualified_namespace: str, eventhub_name: str, consumer_group: str, credential, *,
                 client_factory=None, partition_ids: Iterable[str] | None = None, initial_position: str | int = "@latest"):
        if "Endpoint=" in fully_qualified_namespace or "SharedAccessKey" in fully_qualified_namespace:
            raise ValueError("EventHubsSource requires AAD namespace authentication, not connection strings or SAS")
        self.fully_qualified_namespace = fully_qualified_namespace
        self.eventhub_name = eventhub_name
        self.consumer_group = consumer_group
        self.credential = credential
        self.client_factory = client_factory
        self.partition_ids = list(partition_ids) if partition_ids is not None else None
        if initial_position not in ("@latest", "-1"):
            raise ValueError("initial_position must be @latest or -1")
        self.initial_position = initial_position

    @property
    def identity(self) -> str:
        return f"eventhubs://{self.fully_qualified_namespace}/{self.eventhub_name}/{self.consumer_group}"

    def _client(self):
        if self.client_factory is not None:
            return self.client_factory(self.fully_qualified_namespace, self.eventhub_name, self.consumer_group, self.credential)
        from azure.eventhub import EventHubConsumerClient
        return EventHubConsumerClient(
            fully_qualified_namespace=self.fully_qualified_namespace,
            eventhub_name=self.eventhub_name,
            consumer_group=self.consumer_group,
            credential=self.credential,
        )

    def read(self, position: dict, max_events: int, timeout_seconds: float) -> EventBatch:
        """Bound one receive_batch call with close(); initial_position='-1' replays retained history."""
        if max_events < 1:
            raise ValueError("max_events must be positive")
        client = self._client()
        events: list[EventRecord] = []
        malformed: list[MalformedRecord] = []
        sequences = {str(k): int(v) for k, v in dict((position or {}).get("partitions", {})).items()}
        lock = threading.Lock()
        stop = threading.Event()
        errors: list[BaseException] = []
        target = set(map(str, self.partition_ids)) if self.partition_ids is not None else None

        def body_text(event):
            if hasattr(event, "body_as_str"):
                return event.body_as_str(encoding="UTF-8")
            body = b"".join(event.body) if hasattr(event, "body") else bytes(event)
            return body.decode("utf-8")

        def on_event_batch(partition_context, event_batch):
            pid = str(getattr(partition_context, "partition_id", ""))
            if target is not None and pid not in target:
                return
            with lock:
                for event in event_batch:
                    if len(events) >= max_events:
                        stop.set()
                        break
                    seq = getattr(event, "sequence_number", None)
                    meta = {"partition_id": pid, "sequence_number": seq}
                    try:
                        payload = json.loads(body_text(event))
                        if not isinstance(payload, dict):
                            raise ValueError("JSON event must be an object")
                        events.append(EventRecord(payload, meta))
                    except Exception as exc:
                        malformed.append(MalformedRecord("malformed_json", f"partition {pid} sequence {seq}", {"error": str(exc)}))
                    if seq is not None:
                        sequences[pid] = int(seq)
                if len(events) >= max_events:
                    stop.set()

        def on_error(partition_context, error):
            pid = getattr(partition_context, "partition_id", None)
            errors.append(RuntimeError(f"Event Hubs receive failed on partition {pid}: {error}"))
            stop.set()

        def receive():
            try:
                partitions = list(map(str, self.partition_ids if self.partition_ids is not None else client.get_partition_ids()))
                starting = {}
                with lock:
                    for pid in partitions:
                        if pid in sequences:
                            starting[pid] = sequences[pid]
                        elif self.initial_position == "@latest":
                            props = client.get_partition_properties(pid)
                            anchor = -1 if props.get("is_empty") else int(props["last_enqueued_sequence_number"])
                            sequences[pid] = anchor
                            starting[pid] = anchor
                        else:
                            sequences[pid] = -1
                            starting[pid] = "-1"
                inclusive = {pid: False for pid in partitions}
                client.receive_batch(
                    on_event_batch=on_event_batch,
                    starting_position=starting,
                    starting_position_inclusive=inclusive,
                    max_batch_size=max_events,
                    max_wait_time=max(0.1, min(float(timeout_seconds), 5.0)),
                    on_error=on_error,
                )
            except BaseException as exc:
                errors.append(exc)
                stop.set()

        worker = threading.Thread(target=receive, name="eventhubs-receive-batch", daemon=True)
        worker.start()
        stop.wait(max(0.0, float(timeout_seconds)))
        client.close()
        worker.join(timeout=5.0)
        if worker.is_alive():
            raise TimeoutError("Event Hubs receive worker did not stop after client.close()")
        if errors:
            raise errors[0]
        with lock:
            return EventBatch(list(events), {"partitions": dict(sequences)}, list(malformed))

class StreamProcessor:
    def __init__(self, scenario: dict, scorer: inference.ModelScorer, source: EventSource, checkpoints: CheckpointStore,
                 sink: PredictionSink, *, watermark_seconds: int = 600, max_events: int = 1000,
                 dedup_capacity: int = 100000, model_version: str | None = None, clock=None):
        self.scenario = validate_scenario(scenario)
        self.scorer = scorer
        self.source = source
        self.checkpoints = checkpoints
        self.sink = sink
        self.watermark_seconds = int(watermark_seconds)
        self.max_events = int(max_events)
        self.dedup_capacity = int(dedup_capacity)
        self.model_version = model_version
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.model_identity = json.dumps({"model_version": model_version, **scorer.describe()}, sort_keys=True, default=str)
        self.source_identity = source.identity

    def _initial_checkpoint(self) -> Checkpoint:
        return Checkpoint({}, 0, None, [], self.model_identity, self.source_identity)

    def _quarantine(self, reason: str, reference: str, payload: dict | None = None, metadata: dict | None = None) -> dict:
        return {"reason": reason, "reference": reference, "event_id": (payload or {}).get(inference.EVENT_ID),
                "event_time": (payload or {}).get(inference.EVENT_TIME), "metadata": json.dumps(metadata or {}, sort_keys=True)}


    def _recent_pairs(self, checkpoint: Checkpoint, max_observed: datetime | None) -> list[dict[str, str]]:
        pairs: list[dict[str, str]] = []
        for item in checkpoint.recent_event_ids:
            if isinstance(item, dict):
                event_id, event_time = item.get("event_id"), item.get("event_time")
            else:
                event_id, event_time = item, checkpoint.max_event_time
            if isinstance(event_id, str) and event_id and isinstance(event_time, str):
                try:
                    parsed = _parse_time(event_time)
                except ValueError:
                    continue
                if max_observed is None or parsed.timestamp() >= max_observed.timestamp() - self.watermark_seconds:
                    pairs.append({"event_id": event_id, "event_time": parsed.isoformat()})
        return pairs[-self.dedup_capacity:]

    def _bounded_recent(self, checkpoint: Checkpoint, max_observed: datetime | None, valid: list[dict]) -> list[dict[str, str]]:
        pairs = self._recent_pairs(checkpoint, max_observed)
        for row in valid:
            pairs.append({"event_id": row[inference.EVENT_ID], "event_time": row[inference.EVENT_TIME]})
        if max_observed is not None:
            pairs = [p for p in pairs if _parse_time(p["event_time"]).timestamp() >= max_observed.timestamp() - self.watermark_seconds]
        return pairs[-self.dedup_capacity:]

    def _process_batch(self, checkpoint: Checkpoint, batch: EventBatch, timeout_seconds: float) -> tuple[Checkpoint, dict]:
        import pandas as pd

        batch_id = checkpoint.next_batch_id
        max_observed = _parse_time(checkpoint.max_event_time) if checkpoint.max_event_time else None
        recent_pairs = self._recent_pairs(checkpoint, max_observed)
        seen_recent = {item["event_id"] for item in recent_pairs}
        seen_batch: set[str] = set()
        valid: list[dict] = []
        quarantine = [self._quarantine(item.reason, item.reference, metadata=item.metadata) for item in batch.malformed]
        required = set(inference.model_columns(self.scenario))
        label = inference.label_column(self.scenario)
        for index, record in enumerate(batch.events):
            payload = record.payload
            reference = json.dumps(record.metadata, sort_keys=True) if record.metadata else str(index)
            event_id = payload.get(inference.EVENT_ID)
            try:
                if not isinstance(event_id, str) or not event_id.strip():
                    raise ValueError("invalid_event_id")
                event_time = _parse_time(payload.get(inference.EVENT_TIME))
                missing = required - set(payload)
                if missing:
                    raise ValueError("missing_columns:" + ",".join(sorted(missing)))
                if label in payload:
                    raise ValueError("label_present")
                if event_id in seen_batch:
                    raise ValueError("duplicate_in_batch")
                seen_batch.add(event_id)
                if event_id in seen_recent:
                    quarantine.append(self._quarantine("duplicate", reference, payload, record.metadata))
                    continue
                if max_observed is not None and event_time.timestamp() < max_observed.timestamp() - self.watermark_seconds:
                    quarantine.append(self._quarantine("late", reference, payload, record.metadata))
                    continue
                if max_observed is None or event_time > max_observed:
                    max_observed = event_time
                valid.append({**payload, inference.REQUEST_ID: event_id, inference.EVENT_TIME: event_time.isoformat()})
            except ValueError as exc:
                quarantine.append(self._quarantine(str(exc), reference, payload, record.metadata))
        if valid:
            frame = pd.DataFrame(valid)
            scored = inference.score_frame(self.scorer, frame, request_id_column=inference.REQUEST_ID,
                                           model_version=self.model_version)
            predictions = pd.DataFrame({
                inference.EVENT_ID: frame[inference.REQUEST_ID].to_numpy(),
                inference.EVENT_TIME: frame[inference.EVENT_TIME].to_numpy(),
                "prediction": scored["prediction"].to_numpy(),
                "model_version": scored.get("model_version", pd.Series([self.model_version] * len(scored))).astype(str).to_numpy(),
                "batch_id": batch_id,
            })
        else:
            predictions = pd.DataFrame(columns=[inference.EVENT_ID, inference.EVENT_TIME, "prediction", "model_version", "batch_id"])
        quarantine_frame = pd.DataFrame(quarantine, columns=["reason", "reference", "event_id", "event_time", "metadata"])
        recent = self._bounded_recent(checkpoint, max_observed, valid)
        new_checkpoint = Checkpoint(batch.end_position, batch_id + 1,
                                    max_observed.isoformat() if max_observed else checkpoint.max_event_time,
                                    recent, self.model_identity, self.source_identity)
        metadata = {"schema": "ml-model-factory-stream-batch/v1", "scenario": self.scenario["name"],
                    "batch_id": batch_id, "model_identity": self.model_identity, "source_identity": self.source_identity,
                    "input_events": len(batch.events), "malformed_events": len(batch.malformed),
                    "checkpoint": asdict(new_checkpoint),
                    "scored_at": self.clock().astimezone(timezone.utc).isoformat()}
        receipt = self.sink.write(batch_id, predictions, quarantine_frame, metadata)
        self.checkpoints.commit(new_checkpoint)
        return new_checkpoint, receipt

    def run(self, max_batches: int | None = None, idle_batches: int = 1, timeout_seconds: float = 5.0) -> dict:
        checkpoint = self.checkpoints.load() or self._initial_checkpoint()
        if checkpoint.model_identity != self.model_identity or checkpoint.source_identity != self.source_identity:
            raise ValueError("Checkpoint identity differs; use a new checkpoint for this source/model")
        completed = idle = read_events = quarantined = predicted = 0
        while max_batches is None or completed < max_batches:
            batch = self.source.read(checkpoint.source_position, self.max_events, timeout_seconds)
            if not batch.events and not batch.malformed:
                if batch.end_position != checkpoint.source_position:
                    checkpoint = Checkpoint(batch.end_position, checkpoint.next_batch_id, checkpoint.max_event_time,
                                            self._recent_pairs(checkpoint, _parse_time(checkpoint.max_event_time) if checkpoint.max_event_time else None),
                                            self.model_identity, self.source_identity)
                    self.checkpoints.commit(checkpoint)
                idle += 1
                if idle >= idle_batches:
                    break
                continue
            idle = 0
            existing = self.sink.committed(checkpoint.next_batch_id)
            if existing is not None:
                saved = existing.get("checkpoint")
                checkpoint = Checkpoint(**saved) if isinstance(saved, dict) else Checkpoint(
                    batch.end_position, checkpoint.next_batch_id + 1, checkpoint.max_event_time,
                    checkpoint.recent_event_ids, self.model_identity, self.source_identity)
                self.checkpoints.commit(checkpoint)
                completed += 1
                continue
            checkpoint, receipt = self._process_batch(checkpoint, batch, timeout_seconds)
            completed += 1
            read_events += len(batch.events)
            quarantined += int(receipt.get("quarantine_rows", 0))
            predicted += int(receipt.get("prediction_rows", 0))
        return {"batches": completed, "idle_batches": idle, "events": read_events,
                "predictions": predicted, "quarantine": quarantined, "next_batch_id": checkpoint.next_batch_id}


def _credential(args):
    from uuid import UUID
    if args.credential == "azure_cli":
        from azure.identity import AzureCliCredential
        return AzureCliCredential(tenant_id=str(UUID(args.tenant_id)) if args.tenant_id else None, process_timeout=60)
    from azure.identity import ManagedIdentityCredential
    return ManagedIdentityCredential(client_id=str(UUID(args.client_id)) if args.client_id else None)


def _stream_score_command(args):
    scenario = load_json(args.scenario)
    history = None
    if args.history is not None:
        from .data import read_frame
        history = read_frame(args.history)
    scorer = inference.load_scorer(scenario, args.model, mode=args.mode, history=history)
    if args.source == "jsonl":
        if args.events is None:
            raise ValueError("JSONL source requires --events")
        source = JsonlDirectorySource(args.events)
    else:
        if not (args.namespace and args.eventhub and args.consumer_group):
            raise ValueError("Event Hubs source requires --namespace, --eventhub and --consumer-group")
        source = EventHubsSource(args.namespace, args.eventhub, args.consumer_group, _credential(args),
                                initial_position="@latest" if args.initial_position == "latest" else "-1")
    checkpoint = FileCheckpointStore(args.checkpoint, model_identity=json.dumps({"model_version": args.model_version, **scorer.describe()}, sort_keys=True, default=str),
                                     source_identity=source.identity)
    processor = StreamProcessor(scenario, scorer, source, checkpoint, ParquetDirectorySink(args.output),
                                watermark_seconds=args.watermark_seconds, max_events=args.max_events,
                                model_version=args.model_version)
    return processor.run(max_batches=args.max_batches, timeout_seconds=args.timeout_seconds)


def add_commands(commands) -> None:
    parser = commands.add_parser("stream-score", help="Run bounded deterministic stream scoring micro-batches")
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--mode", choices=inference.MODES, default=None)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--source", required=True, choices=("jsonl", "eventhubs"))
    parser.add_argument("--events", type=Path)
    parser.add_argument("--namespace")
    parser.add_argument("--eventhub")
    parser.add_argument("--consumer-group")
    parser.add_argument("--credential", choices=("azure_cli", "managed_identity"), default="azure_cli")
    parser.add_argument("--tenant-id")
    parser.add_argument("--client-id")
    parser.add_argument("--initial-position", choices=("latest", "earliest"), default="latest",
                        help="Event Hubs bootstrap only: latest anchors the first run, earliest replays retained history")
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-batches", type=int)
    parser.add_argument("--max-events", type=int, default=1000)
    parser.add_argument("--watermark-seconds", type=int, default=600)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--model-version")
    parser.set_defaults(handler=_stream_score_command)
