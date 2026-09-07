"""Set publication metadata locally, without contacting GitHub."""
import argparse
import json
import re
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("owner")
args = parser.parse_args()
if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", args.owner):
    parser.error("Use a GitHub username or organization name")
root = Path(__file__).resolve().parents[1]
for manifest in (root / "custom_components").glob("*/manifest.json"):
    data = json.loads(manifest.read_text())
    url = f"https://github.com/{args.owner}/{root.name}"
    data.update(documentation=url, issue_tracker=url + "/issues", codeowners=["@" + args.owner])
    manifest.write_text(json.dumps(data, indent=2) + "\n")
