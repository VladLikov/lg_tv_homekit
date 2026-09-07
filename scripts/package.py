"""Build only integration code into a HACS release ZIP; no config or secrets."""
from pathlib import Path
import hashlib
import json
import zipfile

root = Path(__file__).resolve().parents[1]
components = root / "custom_components"
domains = [p for p in components.iterdir() if (p / "manifest.json").is_file()]
assert len(domains) == 1
component = domains[0]
manifest = json.loads((component / "manifest.json").read_text())
output = root / "dist"
output.mkdir(exist_ok=True)
archive = output / (component.name + ".zip")
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
    license_info = zipfile.ZipInfo("LICENSE", (2026, 1, 1, 0, 0, 0))
    z.writestr(license_info, (root / "LICENSE").read_bytes())
    for path in sorted(component.rglob("*")):
        if not path.is_file() or any(part.startswith(".") or part == "__pycache__" for part in path.relative_to(component).parts):
            continue
        if path.suffix == ".pyc":
            continue
        info = zipfile.ZipInfo(path.relative_to(component).as_posix(), (2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, path.read_bytes())
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
(output / (archive.name + ".sha256")).write_text(f"{digest}  {archive.name}\n")
print(f"{manifest['domain']} {manifest['version']}: {archive}")
