#!/usr/bin/env python3
"""Run the websocket LLM evaluator over a CSV in fixed-size batches.
    The arguments are:
    --input-csv: Path to the input CSV file containing the devices to evaluate. The CSV must have a header row, and the first device is considered to be at index 1.
    --ws-url: The URL of the Home Assistant websocket API to connect to. Default is ws://localhost:8123/api/websocket.
    --access-token: A long-lived access token for authenticating with the Home Assistant websocket API. This is required.
    --command-type: The type of websocket command to send for each device. Default is carbon_footprint/llm_detection.
    --batch-size: The number of devices to evaluate in each batch. Default is 10.
    --runs: The number of repeated runs to perform for each device. Default is 3.
    --request-timeout: The number of seconds to wait for the first valid result for one request before considering it a failure. Default is 400 seconds.
    --max-requests-per-minute: The maximum number of outgoing websocket requests to send per minute. Default is 15.
    --output-root: The root directory under which per-batch output folders will be created. This is required.
    --start-batch: The 1-based batch number to start from. Default is 1.
    --end-batch: The 1-based batch number to stop at. Default is None, which means to run until the last batch based on the number of devices in the input CSV.
"""
# this script was made using OpenAI's codex, with the prompt: help me make a script to evaluate the uncertainty of my llm's carbon footprint estimates in batches, so I can run it on a large dataset of devices. I want to specify the batch size, and the script should run the evaluation script multiple times with the right start and end indices for each batch. The evaluation script is called evaluate_ws_llm_uncertainty.py and it takes --start-index and --end-index arguments to specify which rows of the CSV to evaluate. I also want to be able to specify a range of batches to run, so I can run them in parallel on different machines if I want. The input CSV has a header row, so the first device is at index 1. The script should also create an output directory for each batch, like results_01, results_02, etc., under a specified output root directory.


from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run batched websocket LLM evaluation over an input CSV."
    )
    parser.add_argument("--input-csv", required=True, help="Full benchmark CSV")
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
        "--batch-size",
        type=int,
        default=10,
        help="Number of devices to evaluate per batch",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of repeated runs per device",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=400.0,
        help="Seconds to wait for the first valid result for one request",
    )
    parser.add_argument(
        "--max-requests-per-minute",
        type=float,
        default=15.0,
        help="Maximum number of outgoing websocket requests per minute",
    )
    parser.add_argument(
        "--output-root",
        required=True,
        help="Directory under which per-batch output folders will be created",
    )
    parser.add_argument(
        "--start-batch",
        type=int,
        default=1,
        help="1-based batch number to start from",
    )
    parser.add_argument(
        "--end-batch",
        type=int,
        default=None,
        help="1-based batch number to stop at",
    )
    return parser.parse_args()


def count_devices(csv_path: Path) -> int:
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return sum(1 for _ in reader)


def main() -> None:
    args = parse_args()
    input_csv = Path(args.input_csv)
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    total_devices = count_devices(input_csv)
    total_batches = (total_devices + args.batch_size - 1) // args.batch_size

    if args.start_batch < 1:
        raise SystemExit("--start-batch must be 1 or greater")
    if args.end_batch is not None and args.end_batch < args.start_batch:
        raise SystemExit("--end-batch must be greater than or equal to --start-batch")

    start_batch = args.start_batch
    end_batch = args.end_batch or total_batches

    if start_batch > total_batches:
        raise SystemExit(
            f"--start-batch {start_batch} is beyond the available {total_batches} batches"
        )

    script_path = Path(__file__).with_name("evaluate_ws_llm_uncertainty.py")

    for batch_number in range(start_batch, min(end_batch, total_batches) + 1):
        start_index = (batch_number - 1) * args.batch_size + 1
        end_index = min(batch_number * args.batch_size, total_devices)
        output_dir = output_root / f"results_{batch_number:02d}"

        print(
            f"\n=== Batch {batch_number:02d}/{total_batches:02d} | "
            f"devices {start_index}-{end_index} -> {output_dir} ==="
        )

        command = [
            sys.executable,
            str(script_path),
            "--input-csv",
            str(input_csv),
            "--ws-url",
            args.ws_url,
            "--access-token",
            args.access_token,
            "--command-type",
            args.command_type,
            "--runs",
            str(args.runs),
            "--start-index",
            str(start_index),
            "--end-index",
            str(end_index),
            "--request-timeout",
            str(args.request_timeout),
            "--max-requests-per-minute",
            str(args.max_requests_per_minute),
            "--output-dir",
            str(output_dir),
        ]

        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            raise SystemExit(
                f"Batch {batch_number:02d} failed with exit code {completed.returncode}"
            )


if __name__ == "__main__":
    main()
