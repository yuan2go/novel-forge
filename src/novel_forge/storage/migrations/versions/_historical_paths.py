from pathlib import Path
import sys

# COMPATIBILITY: Frozen craft modules retain their original imports and bytes outside the active migration registry.
package = sys.modules[__package__]
for lineage in ("craft_16291555", "craft_2eb0e685", "craft_f06f4dac"):
    package.__path__.append(str(Path(__file__).resolve().parent.parent / "historical" / lineage))
