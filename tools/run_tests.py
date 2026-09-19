from pathlib import Path
import importlib.util
import inspect
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TESTS))


def load_module(path: Path):
    name = f"_k5_test_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load test module: {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def build_suite():
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    class_cases = 0
    function_cases = 0
    unsupported = []
    for path in sorted(TESTS.glob("test_*.py")):
        module = load_module(path)
        module_suite = loader.loadTestsFromModule(module)
        class_cases += module_suite.countTestCases()
        suite.addTests(module_suite)
        for name, value in sorted(vars(module).items()):
            if not name.startswith("test_") or not inspect.isfunction(value) or value.__module__ != module.__name__:
                continue
            if inspect.signature(value).parameters:
                unsupported.append(f"{path.name}:{name}")
                continue
            suite.addTest(unittest.FunctionTestCase(value, description=f"{path.name}:{name}"))
            function_cases += 1
    if unsupported:
        raise RuntimeError("unsupported parameterized module-level tests: " + ", ".join(unsupported))
    return suite, class_cases, function_cases


if __name__ == "__main__":
    suite, class_cases, function_cases = build_suite()
    if suite.countTestCases() == 0:
        raise RuntimeError("no tests discovered")
    print(f"discovered {class_cases} unittest cases + {function_cases} module-level cases")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful())
