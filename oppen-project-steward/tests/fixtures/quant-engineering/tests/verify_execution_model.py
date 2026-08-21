from pathlib import Path
import importlib.util


SOURCE = Path(__file__).parents[1] / "src" / "execution.py"
SPEC = importlib.util.spec_from_file_location("execution", SOURCE)
assert SPEC and SPEC.loader
execution = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(execution)

assert execution.execution_bar(0) == 1
assert execution.execution_bar(19) == 20
