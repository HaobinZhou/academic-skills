from pathlib import Path
import importlib.util


SOURCE = Path(__file__).parents[1] / "src" / "router.py"
SPEC = importlib.util.spec_from_file_location("router", SOURCE)
assert SPEC and SPEC.loader
router = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(router)

assert router.route_request(True) == "approval"
assert router.route_request(False) == "execution"
