"""Constants for the Carbon Footprint integration."""

import json
import pathlib

DOMAIN = "carbon_footprint"

bf_file = pathlib.Path(__file__).parent / "www/blocks_footprints.json"
with bf_file.open(encoding="utf-8") as file:
    BLOCKS_FOOTPRINTS = json.load(file)
