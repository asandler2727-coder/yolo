#!/usr/bin/env python3
"""Advisory-mode apply step (spec §7): merge sentiment/cooling.json into the
paper config's pair_blacklist. Prints the diff; never touches anything else.
A pair listed in cooling.json stays blacklisted until removed manually."""
import json
from pathlib import Path

cfg_path = Path("config-paper.json")
cfg = json.loads(cfg_path.read_text())
cooling = json.loads(Path("sentiment/cooling.json").read_text())

blacklist = cfg["exchange"]["pair_blacklist"]
added = [p for p in cooling if p not in blacklist]
blacklist.extend(added)
cfg_path.write_text(json.dumps(cfg, indent=4) + "\n")
print(f"Added to blacklist: {added or 'nothing new'}")
print("Restart the bot (docker compose up -d --force-recreate) to apply.")
