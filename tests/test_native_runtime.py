import unittest

from mosaic_lab.native_runtime import _is_native_file, _manifest_digest, _parse_ldd, _parse_proc_status


class NativeRuntimeTests(unittest.TestCase):
    def test_native_file_detection_is_platform_aware_without_path_execution(self):
        for path in (
            "river/_rust_stats.cpython-313-x86_64-linux-gnu.so",
            "numpy.libs/libopenblas.so.0",
            "pkg/module.pyd",
            "pkg/library.dll",
            "pkg/library.dylib",
        ):
            with self.subTest(path=path):
                self.assertTrue(_is_native_file(path))
        self.assertFalse(_is_native_file("pkg/module.py"))
        self.assertFalse(_is_native_file("pkg/data.json"))

    def test_ldd_parser_tracks_sonames_and_missing_libraries(self):
        deps, missing = _parse_ldd(
            "libpython3.13.so.1.0 => /usr/lib/libpython3.13.so.1.0 (0x1)\n"
            "libmissing.so.1 => not found\n"
            "linux-vdso.so.1 (0x2)\n"
        )
        self.assertEqual(deps, ["libmissing.so.1", "libpython3.13.so.1.0", "linux-vdso.so.1"])
        self.assertEqual(missing, ["libmissing.so.1"])

    def test_proc_status_parser_fails_closed(self):
        self.assertEqual(_parse_proc_status("Name:\tpython\nVmRSS:\t12345 kB\n"), 12345)
        for text in ("Name:\tpython\n", "VmRSS: 12 MB\n", "VmRSS: -1 kB\n"):
            with self.subTest(text=text):
                with self.assertRaises((RuntimeError, ValueError)):
                    _parse_proc_status(text)

    def test_manifest_digest_is_deterministic_and_sensitive(self):
        items = [{"path": "a.so", "size": 2, "sha256": "a" * 64}]
        self.assertEqual(_manifest_digest(items), _manifest_digest(items))
        changed = [{"path": "a.so", "size": 3, "sha256": "a" * 64}]
        self.assertNotEqual(_manifest_digest(items), _manifest_digest(changed))


if __name__ == "__main__":
    unittest.main()
