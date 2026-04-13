#!/usr/bin/env python3
"""Evaluate Home Assistant LLM device detection over repeated websocket runs."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import json
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import websockets
except ModuleNotFoundError as exc:  # pragma: no cover - import guard
    raise SystemExit(
        "Missing dependency 'websockets'. Install it with: pip install websockets"
    ) from exc

try:
    from tqdm import tqdm
except ModuleNotFoundError as exc:  # pragma: no cover - import guard
    raise SystemExit(
        "Missing dependency 'tqdm'. Install it with: pip install tqdm"
    ) from exc


DEFAULT_DEVICE_KEY = "test_device"


@dataclass(slots=True)
class InputDevice:
    device_index: int
    manufacturer: str
    model: str
    true_type: str


@dataclass(slots=True)
class RequestTracker:
    """Tracks messages for a single websocket request id."""

    request_id: int
    future: asyncio.Future[str | None]
    first_result_payload: str | None = None
    first_error: dict[str, Any] | None = None
    all_messages: list[dict[str, Any]] = field(default_factory=list)

    def record_message(self, message: dict[str, Any]) -> None:
        self.all_messages.append(message)

    def resolve_success(self, payload: str) -> None:
        if self.first_result_payload is None:
            self.first_result_payload = payload
        if not self.future.done():
            self.future.set_result(RequestOutcome(raw_response=payload))

    def resolve_failure(self, error: dict[str, Any]) -> None:
        if self.first_error is None:
            self.first_error = error
        if self.first_result_payload is not None:
            return
        if not self.future.done():
            self.future.set_result(
                RequestOutcome(
                    raw_response=None,
                    failure_reason=build_error_reason(error),
                )
            )


@dataclass(slots=True)
class RequestOutcome:
    raw_response: str | None
    failure_reason: str | None = None


def build_error_reason(error_message: dict[str, Any]) -> str:
    error = error_message.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        message = error.get("message")
        if code and message:
            return f"error_before_result:{code}:{message}"
        if code:
            return f"error_before_result:{code}"
        if message:
            return f"error_before_result:{message}"
    return "error_before_result"


class HAWebSocketClient:
    """Minimal Home Assistant websocket client with per-request tracking."""

    def __init__(self, ws_url: str, access_token: str, command_type: str) -> None:
        self.ws_url = ws_url
        self.access_token = access_token
        self.command_type = command_type
        self.websocket: Any | None = None
        self.receiver_task: asyncio.Task[None] | None = None
        self.next_request_id = 1
        self.trackers: dict[int, RequestTracker] = {}

    async def connect(self) -> None:
        self.websocket = await websockets.connect(self.ws_url)
        auth_message = await self._recv_json()
        if auth_message.get("type") != "auth_required":
            raise RuntimeError(
                f"Expected auth_required, got: {json.dumps(auth_message)}"
            )

        await self.websocket.send(
            json.dumps({"type": "auth", "access_token": self.access_token})
        )

        auth_result = await self._recv_json()
        if auth_result.get("type") != "auth_ok":
            raise RuntimeError(f"Authentication failed: {json.dumps(auth_result)}")

        self.receiver_task = asyncio.create_task(self._receiver_loop())

    async def close(self) -> None:
        if self.receiver_task is not None:
            self.receiver_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.receiver_task
        if self.websocket is not None:
            await self.websocket.close()

    async def classify_devices(
        self, devices: dict[str, dict[str, str]], timeout_seconds: float
    ) -> RequestOutcome:
        if self.websocket is None:
            raise RuntimeError("Websocket is not connected")

        request_id = self.next_request_id
        self.next_request_id += 1

        loop = asyncio.get_running_loop()
        tracker = RequestTracker(request_id=request_id, future=loop.create_future())
        self.trackers[request_id] = tracker

        message = {
            "id": request_id,
            "type": self.command_type,
            "devices": devices,
        }
        await self.websocket.send(json.dumps(message))

        try:
            return await asyncio.wait_for(tracker.future, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return RequestOutcome(raw_response=None, failure_reason="timeout")

    async def _recv_json(self) -> dict[str, Any]:
        if self.websocket is None:
            raise RuntimeError("Websocket is not connected")
        raw_message = await self.websocket.recv()
        return json.loads(raw_message)

    async def _receiver_loop(self) -> None:
        if self.websocket is None:
            raise RuntimeError("Websocket is not connected")

        try:
            async for raw_message in self.websocket:
                message = json.loads(raw_message)
                request_id = message.get("id")
                if request_id is None:
                    continue

                tracker = self.trackers.get(request_id)
                if tracker is None:
                    continue

                tracker.record_message(message)
                if tracker.first_result_payload is not None:
                    continue

                message_type = message.get("type")
                if message_type == "result":
                    if message.get("success") is False or "error" in message:
                        tracker.resolve_failure(message)
                        continue

                    result = message.get("result")
                    if not isinstance(result, dict):
                        continue
                    payload = result.get("device_types")
                    if isinstance(payload, str):
                        tracker.resolve_success(payload)
                elif message_type == "error":
                    tracker.resolve_failure(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            for tracker in self.trackers.values():
                if not tracker.future.done():
                    tracker.future.set_exception(exc)


@dataclass(slots=True)
class RawPrediction:
    device_index: int
    manufacturer: str
    model: str
    true_type: str
    run_index: int
    predicted_type: str | None
    success: bool
    raw_response: str | None
    failure_reason: str | None


class RequestPacer:
    """Keeps outgoing requests under a configured requests-per-minute ceiling."""

    def __init__(self, max_requests_per_minute: float | None) -> None:
        self.max_requests_per_minute = max_requests_per_minute
        self.min_interval_seconds = (
            60.0 / max_requests_per_minute if max_requests_per_minute else 0.0
        )
        self.last_request_started_at: float | None = None

    async def wait_for_slot(self) -> None:
        if self.min_interval_seconds <= 0:
            return

        now = time.monotonic()
        if self.last_request_started_at is None:
            self.last_request_started_at = now
            return

        elapsed = now - self.last_request_started_at
        remaining = self.min_interval_seconds - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)

        self.last_request_started_at = time.monotonic()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate Home Assistant LLM device detection over websocket."
    )
    parser.add_argument("--input-csv", required=True, help="CSV with device rows")
    parser.add_argument(
        "--ws-url",
        default="ws://localhost:8123/api/websocket",
        help="Home Assistant websocket URL",
    )
    parser.add_argument(
        "--access-token", required=True, help="Home Assistant long-lived access token"
    )
    parser.add_argument(
        "--command-type",
        default="carbon_footprint/llm_detection",
        help="Websocket command type to call",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=10,
        help="Number of repeated runs per device",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where evaluation outputs will be written",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=1,
        help="1-based device index to start from within the input CSV",
    )
    parser.add_argument(
        "--end-index",
        type=int,
        default=None,
        help="1-based device index to stop at within the input CSV (inclusive)",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=90.0,
        help="Seconds to wait for the first valid result for one request",
    )
    parser.add_argument(
        "--max-requests-per-minute",
        type=float,
        default=20.0,
        help="Maximum number of outgoing websocket requests per minute",
    )
    parser.add_argument(
        "--device-key",
        default=DEFAULT_DEVICE_KEY,
        help="Device key used inside the request payload",
    )
    parser.add_argument(
        "--write-confusion-matrix",
        action="store_true",
        help="Also write confusion_matrix.csv",
    )
    return parser.parse_args()


def load_input_rows(csv_path: Path) -> list[InputDevice]:
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("Input CSV has no header row")

        missing = {"manufacturer", "model"} - set(reader.fieldnames)
        if missing:
            raise ValueError(f"Input CSV is missing required columns: {sorted(missing)}")

        true_type_column = None
        for candidate in ("true_type", "expected_type"):
            if candidate in reader.fieldnames:
                true_type_column = candidate
                break
        if true_type_column is None:
            raise ValueError("Input CSV must contain either 'true_type' or 'expected_type'")

        rows: list[InputDevice] = []
        for index, row in enumerate(reader, start=1):
            rows.append(
                InputDevice(
                    device_index=index,
                    manufacturer=(row.get("manufacturer") or "").strip(),
                    model=(row.get("model") or "").strip(),
                    true_type=(row.get(true_type_column) or "").strip(),
                )
            )
        return rows


def extract_predicted_type(device_types_json: str, device_key: str) -> str | None:
    parsed = json.loads(device_types_json)
    if not isinstance(parsed, dict):
        return None

    predicted = parsed.get(device_key)
    if isinstance(predicted, str):
        value = predicted.strip()
        return value or None
    return None


class RawPredictionWriter:
    """Streams per-run results directly to CSV while the benchmark is running."""

    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.handle: Any | None = None
        self.writer: csv.DictWriter[str] | None = None

    def __enter__(self) -> "RawPredictionWriter":
        self.handle = self.output_path.open("w", encoding="utf-8", newline="")
        self.writer = csv.DictWriter(
            self.handle,
            fieldnames=[
                "device_index",
                "manufacturer",
                "model",
                "true_type",
                "run_index",
                "predicted_type",
                "success",
                "raw_response",
                "failure_reason",
            ],
        )
        self.writer.writeheader()
        self.handle.flush()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.handle is not None:
            self.handle.close()

    def write(self, result: RawPrediction) -> None:
        if self.writer is None or self.handle is None:
            raise RuntimeError("RawPredictionWriter is not opened")

        self.writer.writerow(
            {
                "device_index": result.device_index,
                "manufacturer": result.manufacturer,
                "model": result.model,
                "true_type": result.true_type,
                "run_index": result.run_index,
                "predicted_type": result.predicted_type,
                "success": result.success,
                "raw_response": result.raw_response,
                "failure_reason": result.failure_reason,
            }
        )
        self.handle.flush()


async def evaluate_devices(
    args: argparse.Namespace, output_dir: Path
) -> tuple[list[RawPrediction], dict[str, Any]]:
    all_rows = load_input_rows(Path(args.input_csv))
    if args.start_index < 1:
        raise ValueError("--start-index must be 1 or greater")
    if args.end_index is not None and args.end_index < args.start_index:
        raise ValueError("--end-index must be greater than or equal to --start-index")

    rows = [
        row
        for row in all_rows
        if row.device_index >= args.start_index
        and (args.end_index is None or row.device_index <= args.end_index)
    ]
    client = HAWebSocketClient(
        ws_url=args.ws_url,
        access_token=args.access_token,
        command_type=args.command_type,
    )
    pacer = RequestPacer(args.max_requests_per_minute)

    results: list[RawPrediction] = []
    stop_info: dict[str, Any] = {
        "stopped_early": False,
        "stop_reason": None,
        "last_completed_device_index": None,
        "next_start_index": None,
    }
    total_runs = len(rows) * args.runs

    await client.connect()
    try:
        with RawPredictionWriter(output_dir / "raw_predictions.csv") as raw_writer:
            with tqdm(
                total=total_runs,
                desc="Evaluating devices",
                unit="run",
                file=sys.stdout,
            ) as progress:
                for device_position, row in enumerate(rows, start=1):
                    devices_payload = {
                        args.device_key: {
                            "manufacturer": row.manufacturer,
                            "model": row.model,
                        }
                    }
                    for run_index in range(args.runs):
                        predicted_type: str | None = None
                        success = False
                        raw_response: str | None = None
                        failure_reason: str | None = None

                        try:
                            await pacer.wait_for_slot()
                            outcome = await client.classify_devices(
                                devices=devices_payload,
                                timeout_seconds=args.request_timeout,
                            )
                            raw_response = outcome.raw_response
                            failure_reason = outcome.failure_reason
                            if raw_response is not None:
                                predicted_type = extract_predicted_type(
                                    raw_response, args.device_key
                                )
                                success = predicted_type is not None
                                if not success:
                                    failure_reason = "missing_device_key_or_empty_prediction"
                        except json.JSONDecodeError:
                            predicted_type = None
                            success = False
                            failure_reason = "invalid_json_response"
                        except Exception:
                            predicted_type = None
                            success = False
                            failure_reason = "unexpected_exception"

                        result = RawPrediction(
                            device_index=row.device_index,
                            manufacturer=row.manufacturer,
                            model=row.model,
                            true_type=row.true_type,
                            run_index=run_index,
                            predicted_type=predicted_type,
                            success=success,
                            raw_response=raw_response,
                            failure_reason=failure_reason,
                        )
                        results.append(result)
                        raw_writer.write(result)

                        progress.update(1)
                        progress.set_postfix_str(
                            (
                                f"device {row.device_index}/{len(all_rows)} "
                                f"({device_position}/{len(rows)}) | "
                                f"{row.manufacturer} {row.model} | "
                                f"run {run_index + 1}/{args.runs} | "
                                f"{'ok' if success else 'failed'}"
                            ),
                            refresh=False,
                        )

                        if failure_reason and "TooManyRequests" in failure_reason:
                            stop_info = {
                                "stopped_early": True,
                                "stop_reason": failure_reason,
                                "last_completed_device_index": row.device_index - 1,
                                "next_start_index": row.device_index,
                            }
                            progress.write(
                                "Stopping early due to rate limiting. "
                                f"Resume with --start-index {row.device_index} "
                                "after switching API keys."
                            )
                            return results, stop_info
    finally:
        await client.close()

    if results:
        stop_info["last_completed_device_index"] = results[-1].device_index
        stop_info["next_start_index"] = results[-1].device_index + 1

    return results, stop_info


def summarize_predictions(
    results: list[RawPrediction],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    grouped: dict[tuple[int, str, str, str], list[RawPrediction]] = defaultdict(list)
    for result in results:
        grouped[
            (
                result.device_index,
                result.manufacturer,
                result.model,
                result.true_type,
            )
        ].append(result)

    summary_rows: list[dict[str, Any]] = []
    majority_correct = 0
    confidence_values: list[float] = []
    success_rate_values: list[float] = []

    for (device_index, manufacturer, model, true_type), device_runs in grouped.items():
        total_runs = len(device_runs)
        successful_runs = [run for run in device_runs if run.success and run.predicted_type]
        success_rate = len(successful_runs) / total_runs if total_runs else 0.0

        majority_vote: str | None = None
        confidence = 0.0
        uncertainty = 1.0

        if successful_runs:
            counts = Counter(run.predicted_type for run in successful_runs if run.predicted_type)
            majority_vote, majority_count = counts.most_common(1)[0]
            confidence = majority_count / len(successful_runs)
            uncertainty = 1.0 - confidence

        if majority_vote == true_type:
            majority_correct += 1

        confidence_values.append(confidence)
        success_rate_values.append(success_rate)

        summary_rows.append(
            {
                "manufacturer": manufacturer,
                "model": model,
                "true_type": true_type,
                "device_index": device_index,
                "majority_vote": majority_vote,
                "confidence": confidence,
                "uncertainty": uncertainty,
                "success_rate": success_rate,
                "successful_runs": len(successful_runs),
                "total_runs": total_runs,
            }
        )

    device_count = len(summary_rows)
    metrics = {
        "accuracy": (majority_correct / device_count) if device_count else 0.0,
        "average_confidence": (
            sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
        ),
        "average_success_rate": (
            sum(success_rate_values) / len(success_rate_values)
            if success_rate_values
            else 0.0
        ),
        "num_devices": device_count,
        "num_runs": len(results),
    }

    return summary_rows, metrics


def write_device_summary(output_dir: Path, summary_rows: list[dict[str, Any]]) -> None:
    summary_path = output_dir / "device_summary.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "manufacturer",
                "model",
                "true_type",
                "device_index",
                "majority_vote",
                "confidence",
                "uncertainty",
                "success_rate",
                "successful_runs",
                "total_runs",
            ],
        )
        writer.writeheader()
        for row in summary_rows:
            writer.writerow(row)


def write_metrics(output_dir: Path, metrics: dict[str, Any]) -> None:
    metrics_path = output_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")


def write_confusion_matrix(output_dir: Path, summary_rows: list[dict[str, Any]]) -> None:
    labels = sorted(
        {
            row["true_type"]
            for row in summary_rows
            if row["true_type"]
        }
        | {
            row["majority_vote"]
            for row in summary_rows
            if row["majority_vote"]
        }
    )
    matrix: dict[str, Counter[str]] = {label: Counter() for label in labels}

    for row in summary_rows:
        true_type = row["true_type"]
        predicted = row["majority_vote"] or "__FAILED__"
        if true_type not in matrix:
            matrix[true_type] = Counter()
        matrix[true_type][predicted] += 1

    predicted_labels = sorted({label for counts in matrix.values() for label in counts})
    if "__FAILED__" in predicted_labels:
        predicted_labels.remove("__FAILED__")
        predicted_labels.append("__FAILED__")

    matrix_path = output_dir / "confusion_matrix.csv"
    with matrix_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["true_type", *predicted_labels])
        for true_label in sorted(matrix):
            writer.writerow(
                [true_label, *[matrix[true_label].get(pred, 0) for pred in predicted_labels]]
            )


async def async_main(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results, stop_info = await evaluate_devices(args, output_dir)
    summary_rows, metrics = summarize_predictions(results)
    metrics.update(stop_info)
    metrics["start_index"] = args.start_index

    write_device_summary(output_dir, summary_rows)
    write_metrics(output_dir, metrics)
    if args.write_confusion_matrix:
        write_confusion_matrix(output_dir, summary_rows)


def main() -> None:
    args = parse_args()
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
