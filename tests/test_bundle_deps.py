import os
import subprocess
import struct
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / "tools" / "check_bundle_deps.py"


def _write_toc(tmp_path, app, entries):
    toc = tmp_path / "build" / app / "PKG-00.toc"
    toc.parent.mkdir(parents=True)
    toc.write_text(repr((None, None, entries)), encoding="utf-8")


def _run_checker(tmp_path, *apps):
    return subprocess.run(
        [sys.executable, str(CHECKER), *apps],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        encoding="utf-8",
        errors="strict",
        check=False,
    )


def _minimal_pe(*, magic=0x10B, import_rva=0, section_data=b"",
                virtual_size=None):
    """建立只含 checker 所需欄位的手工 PE fixture。"""
    optional_size = 224 if magic == 0x10B else 240
    section_count = int(bool(section_data))
    e_lfanew = 0x80
    optional_offset = e_lfanew + 24
    section_offset = optional_offset + optional_size
    raw_offset = 0x200
    size = raw_offset + len(section_data) if section_data else section_offset
    data = bytearray(size)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, e_lfanew)
    data[e_lfanew:e_lfanew + 4] = b"PE\0\0"
    struct.pack_into("<H", data, e_lfanew + 6, section_count)
    struct.pack_into("<H", data, e_lfanew + 20, optional_size)
    struct.pack_into("<H", data, optional_offset, magic)
    data_directory_offset = optional_offset + (96 if magic == 0x10B else 112)
    struct.pack_into("<I", data, data_directory_offset + 8, import_rva)
    if section_data:
        virtual_size = len(section_data) if virtual_size is None else virtual_size
        struct.pack_into("<I", data, section_offset + 8, virtual_size)
        struct.pack_into("<I", data, section_offset + 12, 0x1000)
        struct.pack_into("<I", data, section_offset + 16, len(section_data))
        struct.pack_into("<I", data, section_offset + 20, raw_offset)
        data[raw_offset:] = section_data
    return bytes(data)


def _import_section(name_bytes=b"kernel32.dll\0"):
    descriptor = bytearray(20)
    struct.pack_into("<I", descriptor, 12, 0x1000 + 40)
    return bytes(descriptor) + b"\0" * 20 + name_bytes


def test_main_fails_when_any_requested_build_is_missing(tmp_path):
    _write_toc(tmp_path, "present", [])

    result = _run_checker(tmp_path, "present", "missing")

    assert result.returncode != 0
    assert "[present] OK" in result.stdout
    assert "[missing]" in result.stdout


def test_main_fails_when_pe_import_parsing_fails(tmp_path):
    malformed = tmp_path / "malformed.dll"
    malformed.write_bytes(b"MZ")
    _write_toc(tmp_path, "broken", [("malformed.dll", str(malformed), "BINARY")])

    result = _run_checker(tmp_path, "broken")

    assert result.returncode != 0
    assert "!" in result.stdout
    assert "[broken] OK" not in result.stdout


def test_main_fails_when_candidate_pe_source_is_missing(tmp_path):
    missing = tmp_path / "absent.dll"
    _write_toc(tmp_path, "missing-source", [("absent.dll", str(missing), "BINARY")])

    result = _run_checker(tmp_path, "missing-source")

    assert result.returncode != 0
    assert str(missing) in result.stdout
    assert "[missing-source] OK" not in result.stdout


@pytest.mark.parametrize(
    ("case_name", "payload"),
    [
        ("plain", b"not-a-pe"),
        ("invalid-pe-signature", _minimal_pe().replace(b"PE\0\0", b"PX\0\0", 1)),
        ("unsupported-optional-magic", _minimal_pe(magic=0x999)),
        ("unmapped-import-rva", _minimal_pe(import_rva=0x1000)),
        (
            "truncated-import-descriptor",
            _minimal_pe(import_rva=0x1000, section_data=b"\1" * 10),
        ),
        (
            "missing-import-name-rva",
            _minimal_pe(
                import_rva=0x1000,
                section_data=b"\1" * 12 + b"\0" * 4 + b"\1" * 4 + b"\0" * 20,
            ),
        ),
        (
            "truncated-import-name",
            _minimal_pe(import_rva=0x1000,
                        section_data=_import_section(b"kernel32.dll")),
        ),
        (
            "invalid-import-name",
            _minimal_pe(import_rva=0x1000,
                        section_data=_import_section(b"not-a-library\0")),
        ),
    ],
)
def test_main_fails_closed_for_malformed_candidate_pe(
        tmp_path, case_name, payload):
    candidate = tmp_path / f"{case_name}.dll"
    candidate.write_bytes(payload)
    _write_toc(
        tmp_path,
        case_name,
        [(candidate.name, str(candidate), "BINARY")],
    )

    result = _run_checker(tmp_path, case_name)

    assert result.returncode != 0
    assert "PE 解析失敗" in result.stdout
    assert f"[{case_name}] OK" not in result.stdout


@pytest.mark.parametrize("import_name", [
    b"kernel32.dll\0",
    # PE 的 import 名稱不限 .dll：Qt6PrintSupport 匯入 `WINSPOOL.DRV`，
    # 舊版正規式只認 .dll 而把它判成非法，整支產品的檢查因此 fail-closed 誤報。
    b"WINSPOOL.DRV\0",
    b"hal.sys\0",
    b"host.exe\0",
])
def test_pe_imports_accepts_non_dll_module_extensions(tmp_path, import_name):
    sys.path.insert(0, str(ROOT))
    try:
        from tools.check_bundle_deps import pe_imports
    finally:
        sys.path.remove(str(ROOT))
    candidate = tmp_path / "with-import.dll"
    candidate.write_bytes(
        _minimal_pe(import_rva=0x1000,
                    section_data=_import_section(import_name)))

    assert pe_imports(str(candidate)) == [import_name.rstrip(b"\0").decode()]


def test_main_accepts_valid_pe_with_no_imports(tmp_path):
    candidate = tmp_path / "no-imports.dll"
    candidate.write_bytes(_minimal_pe())
    _write_toc(
        tmp_path,
        "no-imports",
        [(candidate.name, str(candidate), "BINARY")],
    )

    result = _run_checker(tmp_path, "no-imports")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[no-imports] OK" in result.stdout
