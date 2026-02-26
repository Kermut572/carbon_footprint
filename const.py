"""Constants for the Carbon Footprint integration."""

import json
import pathlib

DOMAIN = "carbon_footprint"

# ============================================================================
# TEST MODE - FOR TESTING SENSORS WITHOUT ELECTRICITY MAPS INTEGRATION
# ============================================================================
# Change to False to use real data from Electricity Maps
# See TESTING.md for detailed instructions on how to remove fake data
# when integrating with real data sources
# ============================================================================
TEST_MODE = True

bf_file = pathlib.Path(__file__).parent / "www/blocks_footprints.json"
with bf_file.open(encoding="utf-8") as file:
    BLOCKS_FOOTPRINTS = json.load(file)

