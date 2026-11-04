import json
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml_model_factory.inference import ModelScorer, EVENT_ID, EVENT_TIME, IMAGE_COLUMN, load_scorer, sample_requests
from ml_model_factory.streaming import (
    CheckpointStore, EventHubsSource, FileCheckpointStore, JsonlDirectorySource,
    ParquetDirectorySink, StreamProcessor,
)

SCENARIO = {
    "name": "fixture-stream", "task": "classification", "target": "label",
    "features": ["x"], "categorical_features": [],
    "dataset": {"provider": "kaggle", "kind": "dataset", "slug": "fixture/data", "version": 1},
}

class ConstantScorer(ModelScorer):
    def __init__(self, scenario=SCENARIO):
        super().__init__(scenario, "custom")
    def predict(self, features):
        return np.ones(len(features), dtype=int)

class FailsOnce(CheckpointStore):
    def __init__(self, inner):
        self.inner = inner
        self.failed = False
    def load(self):
        return self.inner.load()
    def commit(self, checkpoint):
        if not self.failed:
            self.failed = True
            raise RuntimeError("crash after sink")
        return self.inner.commit(checkpoint)

def write_events(path: Path, rows):
    path.mkdir()
    (path / "events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows) + "{bad json\n", encoding="utf-8")

def read_batch(out: Path, batch=0):
    root = out / f"batch-{batch:010d}"
    return pd.read_parquet(root / "predictions.parquet"), pd.read_parquet(root / "quarantine.parquet"), json.loads((root / "_SUCCESS.json").read_text())

def test_stream_processor_quarantines_malformed_late_labels_and_deduplicates_across_restart(tmp_path):
    now = datetime(2026, 10, 6, tzinfo=timezone.utc)
    events = [
        {EVENT_ID: "a", EVENT_TIME: now.isoformat(), "x": 1},
        {EVENT_ID: "b", EVENT_TIME: (now + timedelta(seconds=1)).isoformat(), "x": 2, "label": 1},
        {EVENT_ID: "a", EVENT_TIME: (now + timedelta(seconds=2)).isoformat(), "x": 3},
        {EVENT_ID: "old", EVENT_TIME: (now - timedelta(hours=1)).isoformat(), "x": 4},
        {EVENT_ID: "missing", EVENT_TIME: (now + timedelta(seconds=3)).isoformat()},
    ]
    write_events(tmp_path / "events", events)
    store = FileCheckpointStore(tmp_path / "checkpoint.json")
    processor = StreamProcessor(SCENARIO, ConstantScorer(), JsonlDirectorySource(tmp_path / "events"), store,
                                ParquetDirectorySink(tmp_path / "out"), watermark_seconds=10, max_events=10,
                                model_version="7")
    summary = processor.run(max_batches=1)
    pred, quarantine, receipt = read_batch(tmp_path / "out")
    assert summary["predictions"] == 1
    assert list(pred[EVENT_ID]) == ["a"]
    assert {"label_present", "duplicate_in_batch", "late", "missing_columns:x", "malformed_json"}.issubset(set(quarantine["reason"]))
    assert all(isinstance(item, dict) and {"event_id", "event_time"} <= set(item) for item in receipt["checkpoint"]["recent_event_ids"])
    assert receipt["checkpoint"]["next_batch_id"] == 1

    more = {EVENT_ID: "a", EVENT_TIME: (now + timedelta(seconds=3)).isoformat(), "x": 5}
    (tmp_path / "events" / "z.jsonl").write_text(json.dumps(more) + "\n", encoding="utf-8")
    summary = StreamProcessor(SCENARIO, ConstantScorer(), JsonlDirectorySource(tmp_path / "events"), store,
                              ParquetDirectorySink(tmp_path / "out"), model_version="7").run(max_batches=1)
    _, quarantine, _ = read_batch(tmp_path / "out", 1)
    assert summary["quarantine"] == 1 and list(quarantine["reason"]) == ["duplicate"]

def test_crash_after_sink_write_recovers_without_duplicate_output(tmp_path):
    now = datetime(2026, 10, 6, tzinfo=timezone.utc)
    write_events(tmp_path / "events", [{EVENT_ID: "a", EVENT_TIME: now.isoformat(), "x": 1}])
    inner = FileCheckpointStore(tmp_path / "checkpoint.json")
    with pytest.raises(RuntimeError, match="crash"):
        StreamProcessor(SCENARIO, ConstantScorer(), JsonlDirectorySource(tmp_path / "events"), FailsOnce(inner),
                        ParquetDirectorySink(tmp_path / "out"), model_version="7").run(max_batches=1)
    assert inner.load() is None
    summary = StreamProcessor(SCENARIO, ConstantScorer(), JsonlDirectorySource(tmp_path / "events"), inner,
                              ParquetDirectorySink(tmp_path / "out"), model_version="7").run(max_batches=1)
    assert summary["batches"] == 1 and inner.load().next_batch_id == 1
    assert len(list((tmp_path / "out").glob("batch-*"))) == 1

def test_checkpoint_identity_mismatch_is_refused(tmp_path):
    write_events(tmp_path / "events", [{EVENT_ID: "a", EVENT_TIME: datetime.now(timezone.utc).isoformat(), "x": 1}])
    source = JsonlDirectorySource(tmp_path / "events")
    sink = ParquetDirectorySink(tmp_path / "out")
    store = FileCheckpointStore(tmp_path / "checkpoint.json")
    StreamProcessor(SCENARIO, ConstantScorer(), source, store, sink, model_version="7").run(max_batches=1)
    with pytest.raises(ValueError, match="identity"):
        StreamProcessor(SCENARIO, ConstantScorer(), source, store, sink, model_version="8").run(max_batches=1)
    other = tmp_path / "other"
    write_events(other, [{EVENT_ID: "b", EVENT_TIME: datetime.now(timezone.utc).isoformat(), "x": 2}])
    with pytest.raises(ValueError, match="identity"):
        StreamProcessor(SCENARIO, ConstantScorer(), JsonlDirectorySource(other), store, sink, model_version="7").run(max_batches=1)

def test_eventhubs_source_uses_one_blocking_receive_call_and_closes_client():
    class Event:
        def __init__(self, body, sequence_number):
            self._body = body
            self.sequence_number = sequence_number
        def body_as_str(self, encoding="UTF-8"):
            return self._body
    class Context:
        def __init__(self, partition_id):
            self.partition_id = partition_id
    class Client:
        def __init__(self):
            self.calls = []
            self.closed = threading.Event()
        def get_partition_ids(self):
            return ["0", "1"]
        def get_partition_properties(self, partition_id):
            return {"is_empty": partition_id == "1", "last_enqueued_sequence_number": 100}
        def receive_batch(self, **kwargs):
            self.calls.append(kwargs)
            def callback():
                kwargs["on_event_batch"](Context("0"), [
                    Event('{"event_id":"e","event_time":"2026-10-06T00:00:00Z","x":1}', 42),
                    Event('bad', 43),
                ])
            threading.Thread(target=callback, daemon=True).start()
            while not self.closed.wait(0.01):
                pass
        def close(self):
            self.closed.set()
    client = Client()
    source = EventHubsSource("ns.servicebus.windows.net", "hub", "$Default", object(),
                             client_factory=lambda *args: client)
    started = time.monotonic()
    batch = source.read({"partitions": {"0": 41}}, max_events=10, timeout_seconds=0.2)
    assert time.monotonic() - started < 2
    assert client.closed.is_set()
    assert len(client.calls) == 1
    assert client.calls[0]["starting_position"] == {"0": 41, "1": -1}
    assert client.calls[0]["starting_position_inclusive"] == {"0": False, "1": False}
    assert batch.end_position == {"partitions": {"0": 43, "1": -1}}
    assert len(batch.events) == 1 and batch.malformed[0].reason == "malformed_json"


def test_eventhubs_idle_read_anchors_and_stream_processor_commits_position(tmp_path):
    class Client:
        def __init__(self, emit=False):
            self.closed = threading.Event()
            self.calls = []
            self.emit = emit
        def get_partition_ids(self):
            return ["0", "1"]
        def get_partition_properties(self, partition_id):
            return {"is_empty": partition_id == "1", "last_enqueued_sequence_number": 10}
        def receive_batch(self, **kwargs):
            self.calls.append(kwargs)
            while not self.closed.wait(0.01):
                pass
        def close(self):
            self.closed.set()
    client = Client()
    source = EventHubsSource("ns.servicebus.windows.net", "hub", "$Default", object(), client_factory=lambda *args: client)
    store = FileCheckpointStore(tmp_path / "checkpoint.json")
    summary = StreamProcessor(SCENARIO, ConstantScorer(), source, store, ParquetDirectorySink(tmp_path / "out"),
                              model_version="7").run(max_batches=1, timeout_seconds=0.1)
    assert summary["batches"] == 0 and summary["idle_batches"] == 1
    assert store.load().source_position == {"partitions": {"0": 10, "1": -1}}
    assert not (tmp_path / "out").exists()


def test_eventhubs_events_between_runs_resume_after_anchor(tmp_path):
    class Event:
        sequence_number = 11
        def body_as_str(self, encoding="UTF-8"):
            return '{"event_id":"later","event_time":"2026-10-06T00:00:00Z","x":1}'
    class Context:
        partition_id = "0"
    class Client:
        def __init__(self, emit=False):
            self.closed = threading.Event()
            self.calls = []
            self.emit = emit
        def get_partition_ids(self):
            return ["0"]
        def get_partition_properties(self, partition_id):
            return {"is_empty": False, "last_enqueued_sequence_number": 10}
        def receive_batch(self, **kwargs):
            self.calls.append(kwargs)
            if self.emit and kwargs["starting_position"] == {"0": 10}:
                kwargs["on_event_batch"](Context(), [Event()])
            while not self.closed.wait(0.01):
                pass
        def close(self):
            self.closed.set()
    first = Client()
    store = FileCheckpointStore(tmp_path / "checkpoint.json")
    StreamProcessor(SCENARIO, ConstantScorer(), EventHubsSource("ns.servicebus.windows.net", "hub", "$Default", object(), client_factory=lambda *args: first),
                    store, ParquetDirectorySink(tmp_path / "out"), model_version="7").run(max_batches=1, timeout_seconds=0.1)
    second = Client(emit=True)
    summary = StreamProcessor(SCENARIO, ConstantScorer(), EventHubsSource("ns.servicebus.windows.net", "hub", "$Default", object(), client_factory=lambda *args: second),
                              store, ParquetDirectorySink(tmp_path / "out"), model_version="7").run(max_batches=1, timeout_seconds=0.1)
    pred, _, _ = read_batch(tmp_path / "out")
    assert second.calls[0]["starting_position"] == {"0": 10}
    assert list(pred[EVENT_ID]) == ["later"] and summary["predictions"] == 1


def test_eventhubs_max_events_truncation_keeps_undelivered_partition_position():
    class Event:
        def __init__(self, sequence_number, event_id):
            self.sequence_number = sequence_number
            self.event_id = event_id
        def body_as_str(self, encoding="UTF-8"):
            return json.dumps({"event_id": self.event_id, "event_time": "2026-10-06T00:00:00Z", "x": 1})
    class Context:
        def __init__(self, partition_id):
            self.partition_id = partition_id
    class Client:
        def __init__(self):
            self.closed = threading.Event()
        def get_partition_ids(self):
            return ["0", "1"]
        def get_partition_properties(self, partition_id):
            return {"is_empty": False, "last_enqueued_sequence_number": 5 if partition_id == "0" else 8}
        def receive_batch(self, **kwargs):
            kwargs["on_event_batch"](Context("0"), [Event(6, "a")])
            kwargs["on_event_batch"](Context("1"), [Event(9, "b")])
            while not self.closed.wait(0.01):
                pass
        def close(self):
            self.closed.set()
    batch = EventHubsSource("ns.servicebus.windows.net", "hub", "$Default", object(), client_factory=lambda *args: Client()).read({}, 1, 0.1)
    assert [event.payload[EVENT_ID] for event in batch.events] == ["a"]
    assert batch.end_position == {"partitions": {"0": 6, "1": 8}}

def test_custom_seasonal_naive_forecast_streaming_end_to_end(tmp_path):
    from ml_model_factory.data import prepare
    from ml_model_factory.training import train
    forecast = {
        "name": "fixture-forecast", "task": "forecasting", "target": "sales", "features": ["date"],
        "dataset": {"provider": "kaggle", "kind": "dataset", "slug": "fixture/data", "version": 1},
        "forecast": {"time_column": "date", "series_columns": [], "frequency": "D", "horizon": 3},
        "custom": {"algorithm": "seasonal_naive", "seasonal_period": 7}, "quality": {},
    }
    dates = pd.date_range("2025-01-01", periods=60, freq="D")
    pd.DataFrame({"date": dates, "sales": np.arange(60) % 7 + 10.0}).to_csv(tmp_path / "series.csv", index=False)
    prepare(forecast, tmp_path / "series.csv", tmp_path / "prepared")
    train(forecast, tmp_path / "prepared", tmp_path / "model")
    sample_requests(forecast, tmp_path / "prepared", tmp_path / "requests", rows=3,
                    generated_at=datetime(2026, 10, 6, tzinfo=timezone.utc))
    summary = StreamProcessor(
        forecast, load_scorer(forecast, tmp_path / "model"), JsonlDirectorySource(tmp_path / "requests"),
        FileCheckpointStore(tmp_path / "checkpoint.json"), ParquetDirectorySink(tmp_path / "out"), model_version="1",
    ).run(max_batches=1)
    pred, quarantine, _ = read_batch(tmp_path / "out")
    truth = pd.read_parquet(tmp_path / "requests" / "labels.parquet")["sales"].to_numpy()
    np.testing.assert_allclose(pred["prediction"].to_numpy(), truth)
    assert summary["predictions"] == 3 and quarantine.empty

def test_vision_streaming_with_injected_fake_scorer(tmp_path):
    image = {"name": "fixture-image", "task": "image_classification", "dataset": SCENARIO["dataset"]}
    class ImageScorer(ModelScorer):
        def __init__(self):
            super().__init__(image, "custom")
        def predict(self, features):
            assert list(features.columns) == [IMAGE_COLUMN]
            return np.array(["cat"] * len(features), dtype=object)
    write_events(tmp_path / "events", [{EVENT_ID: "img1", EVENT_TIME: datetime.now(timezone.utc).isoformat(), IMAGE_COLUMN: "aW1hZ2U="}])
    summary = StreamProcessor(image, ImageScorer(), JsonlDirectorySource(tmp_path / "events"),
                              FileCheckpointStore(tmp_path / "checkpoint.json"), ParquetDirectorySink(tmp_path / "out"),
                              model_version="vision1").run(max_batches=1)
    pred, quarantine, _ = read_batch(tmp_path / "out")
    assert summary["predictions"] == 1 and list(pred["prediction"]) == ["cat"]
    assert list(quarantine["reason"]) == ["malformed_json"]
