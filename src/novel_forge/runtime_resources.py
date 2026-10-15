from pathlib import Path
import sysconfig


def runtime_resource(relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Runtime resources require a relative package path")
    roots = (Path(__file__).resolve().parents[2], Path(sysconfig.get_path("data")) / "share" / "novel-forge")
    for root in roots:
        candidate = root / relative
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Runtime resource unavailable: {relative_path}")
