from pathlib import Path
import importlib.util


SOURCE = Path(__file__).parents[1] / "src" / "editor_state.py"
SPEC = importlib.util.spec_from_file_location("editor_state", SOURCE)
assert SPEC and SPEC.loader
editor_state = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(editor_state)

assert editor_state.may_generate("ready", True) is True
assert editor_state.may_generate("ready", False) is False
assert editor_state.may_generate("draft", True) is False
