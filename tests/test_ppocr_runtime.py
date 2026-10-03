"""CPU runtime regressions using the bundled ONNX models, without Paddle/CUDA.

Run with: python tests/test_ppocr_runtime.py
Install requirements-ov.txt to enable the real-model tests. No downloads or OCR
mocks are used; a missing optional dependency is reported as a skip.
"""
import importlib.util
import os
import pathlib
import re
import tempfile
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME_PATH = ROOT / "scripts" / "ppocr_openvino.py"
MISSING_DEPS = [name for name in ("numpy", "cv2", "pyclipper", "openvino")
                if importlib.util.find_spec(name) is None]


def setUpModule():
    # Use the upstream consent mechanism in an isolated test HOME before loading
    # any model. Do not send an opt-out transition event or touch user settings.
    if MISSING_DEPS:
        return
    global _test_home, _saved_environment
    _test_home = tempfile.TemporaryDirectory(prefix="readpdf-offline-home-")
    _saved_environment = {key: os.environ.get(key) for key in ("HOME", "LOCALAPPDATA")}
    os.environ.update(HOME=_test_home.name, LOCALAPPDATA=_test_home.name)
    from openvino_telemetry.utils.opt_in_checker import OptInChecker, ConsentCheckResult
    checker = OptInChecker()
    if not checker.update_result(ConsentCheckResult.DECLINED):
        raise RuntimeError("Cannot disable optional runtime telemetry for offline tests")
    assert checker.check(enable_opt_in_dialog=False) == ConsentCheckResult.DECLINED


def tearDownModule():
    if MISSING_DEPS:
        return
    for key, value in _saved_environment.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    _test_home.cleanup()


def load_runtime(base=""):
    # Only the environment is controlled: model loading and inference stay real.
    spec = importlib.util.spec_from_file_location("ppocr_runtime_test", RUNTIME_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, {"OCR_OV_DIR": str(base)}):
        spec.loader.exec_module(module)
    return module


class DependencyManifestTests(unittest.TestCase):
    def test_standalone_cpu_dependencies_are_declared(self):
        requirements = (ROOT / "requirements-ov.txt").read_text(encoding="utf-8")
        names = {re.split(r"[<>=!~;\[]", line.split("#", 1)[0].strip())[0].lower()
                 for line in requirements.splitlines()
                 if line.split("#", 1)[0].strip()}
        self.assertTrue({"openvino", "numpy", "opencv-python-headless", "pyclipper"}
                        .issubset(names))
        self.assertFalse(any("paddle" in name or "cuda" in name or "nvidia" in name
                             for name in names))


@unittest.skipIf(MISSING_DEPS, "optional CPU dependencies missing: " + ", ".join(MISSING_DEPS))
class PortableModelPathTests(unittest.TestCase):
    def test_bundled_paths_point_to_actual_files(self):
        runtime = load_runtime()
        self.assertEqual(pathlib.Path(runtime.BASE), ROOT / "models")
        for key in ("det", "rec", "dict"):
            path = pathlib.Path(runtime.MODELS["v6"][key])
            self.assertTrue(path.is_file(), f"missing bundled {key}: {path}")
            self.assertTrue(path.is_relative_to(ROOT / "models"))

    def test_environment_override_uses_native_separators(self):
        with tempfile.TemporaryDirectory(prefix="ocr models ") as directory:
            base = pathlib.Path(directory)
            runtime = load_runtime(base)
            cfg = runtime.MODELS["v6"]
            self.assertEqual(pathlib.Path(cfg["det"]),
                             base / "PP-OCRv6_small_det_onnx" / "inference.onnx")
            self.assertEqual(pathlib.Path(cfg["rec"]),
                             base / "PP-OCRv6_small_rec_onnx" / "inference.onnx")
            self.assertEqual(pathlib.Path(cfg["dict"]), base / "ppocr_keys_v6.txt")

    def test_blank_environment_uses_bundled_models(self):
        runtime = load_runtime("  ")
        self.assertEqual(pathlib.Path(runtime.BASE), ROOT / "models")


@unittest.skipIf(MISSING_DEPS, "optional CPU dependencies missing: " + ", ".join(MISSING_DEPS))
class RealModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = load_runtime()
        cls.cfg = cls.runtime.MODELS["v6"]
        cls.char_list = cls.runtime.load_char_dict(cls.cfg["dict"])
        core = cls.runtime.Core()
        detector = core.read_model(cls.cfg["det"])
        detector.reshape([1, 3, -1, -1])
        cls.detector = core.compile_model(detector, "CPU")
        recognizer = core.read_model(cls.cfg["rec"])
        recognizer.reshape([1, 3, cls.cfg["rec_height"], -1])
        cls.recognizer = core.compile_model(recognizer, "CPU")

    def test_real_detector_and_recognizer_read_generated_text(self):
        runtime = self.runtime
        image = runtime.np.full((400, 960, 3), 255, dtype=runtime.np.uint8)
        runtime.cv2.putText(image, "CPU TEXT 12345", (65, 180),
                            runtime.cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0),
                            3, runtime.cv2.LINE_AA)
        results = runtime.ocr_image(image, self.detector, self.recognizer, None,
                                    self.char_list, self.cfg, rotate=False)
        text = "".join(line["text"] for line in results)
        self.assertIn("CPUTEXT12345", re.sub(r"\s+", "", text).upper(), results)
        for line in results:
            self.assertGreater(line["conf"], 0.7)
            self.assertEqual(len(line["box"]), 4)
            for x, y in line["box"]:
                self.assertTrue(0 <= x < image.shape[1])
                self.assertTrue(0 <= y < image.shape[0])

    def test_real_detector_returns_no_text_for_blank_image(self):
        runtime = self.runtime
        image = runtime.np.full((400, 600, 3), 255, dtype=runtime.np.uint8)
        self.assertEqual(runtime.ocr_image(image, self.detector, self.recognizer,
                                          None, self.char_list, self.cfg,
                                          rotate=False), [])

    def test_dictionary_matches_real_recognizer_output(self):
        runtime = self.runtime
        tensor = runtime.np.zeros((1, 3, self.cfg["rec_height"], 320),
                                  dtype=runtime.np.float32)
        prediction = self.recognizer(tensor)[self.recognizer.output(0)]
        self.assertEqual(prediction.shape[-1], len(self.char_list))
        self.assertEqual(self.char_list[0], "blank")
        self.assertEqual(self.char_list[-1], " ")
        self.assertIn("🇩🇪", self.char_list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
