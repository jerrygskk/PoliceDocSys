"""把 pytest collection/run JSON 組成可追加、可比較的趨勢紀錄。"""
from __future__ import annotations

import argparse
import json
import unittest
from pathlib import Path


def compare_node_ids(expected, actual):
    expected_set = set(expected)
    actual_set = set(actual)
    return {
        "matches": expected_set == actual_set,
        "missing": sorted(expected_set - actual_set),
        "extra": sorted(actual_set - expected_set),
    }


def unittest_id_to_pytest(test_id):
    parts = test_id.split(".")
    module_parts = parts[:-2]
    if module_parts and module_parts[0] == "tests":
        module_parts = module_parts[1:]
    module_path = "/".join(module_parts)
    return f"tests/{module_path}.py::{parts[-2]}::{parts[-1]}"


def _iter_unittest_cases(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from _iter_unittest_cases(test)
        else:
            yield test


def write_collection_relationship(pytest_collection_path, output_path):
    pytest_nodes = _read_json(pytest_collection_path)["node_ids"]
    suite = unittest.defaultTestLoader.discover("tests")
    unittest_nodes = sorted(
        unittest_id_to_pytest(test.id()) for test in _iter_unittest_cases(suite)
    )
    comparison = compare_node_ids(unittest_nodes, pytest_nodes)
    payload = {
        "unittest_count": len(unittest_nodes),
        "pytest_count": len(pytest_nodes),
        "unittest_node_ids": unittest_nodes,
        "pytest_node_ids": pytest_nodes,
        "unittest_missing_from_pytest": comparison["missing"],
        "pytest_only_node_ids": comparison["extra"],
    }
    Path(output_path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def build_trend_record(*, collection_node_ids, layers, durations, previous=None):
    record = {
        "collection_count": len(collection_node_ids),
        "layers": {
            name: {
                "count": len(data["node_ids"]),
                "elapsed_seconds": data["elapsed_seconds"],
            }
            for name, data in layers.items()
        },
        "durations": durations[:20],
    }
    if previous is not None:
        previous_layers = previous.get("layers", {})
        record["delta"] = {
            "collection_count": (
                record["collection_count"] - previous.get("collection_count", 0)
            ),
            "layers": {
                name: {
                    "count": values["count"] - previous_layers.get(name, {}).get("count", 0),
                    "elapsed_seconds": round(
                        values["elapsed_seconds"]
                        - previous_layers.get(name, {}).get("elapsed_seconds", 0.0),
                        6,
                    ),
                }
                for name, values in record["layers"].items()
            },
        }
    return record


def write_trend_record(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection",
                        help="含 node_ids 陣列的 collection JSON")
    parser.add_argument("--layer", action="append", default=[], metavar="NAME=RUN_JSON")
    parser.add_argument("--previous", help="前次 JSON 或 JSONL 趨勢紀錄")
    parser.add_argument("--output", required=True, help="追加寫入的 JSONL")
    parser.add_argument("--unittest-proof", action="store_true",
                        help="輸出 unittest nodes 是 pytest collection 子集的完整證據")
    args = parser.parse_args(argv)

    if args.unittest_proof:
        if not args.collection:
            parser.error("--unittest-proof 需要 --collection")
        write_collection_relationship(args.collection, args.output)
        return 0
    if not args.collection:
        parser.error("需要 --collection")

    collection = _read_json(args.collection)
    layers = {}
    durations = []
    for value in args.layer:
        name, path = value.split("=", 1)
        run = _read_json(path)
        layers[name] = {
            "node_ids": run["node_ids"],
            "elapsed_seconds": run["elapsed_seconds"],
        }
        durations.extend(run.get("durations", []))
    previous = None
    if args.previous:
        lines = Path(args.previous).read_text(encoding="utf-8").splitlines()
        previous = json.loads(lines[-1])
    durations.sort(key=lambda row: (-row["seconds"], row["node_id"]))
    record = build_trend_record(
        collection_node_ids=collection["node_ids"], layers=layers,
        durations=durations, previous=previous)
    write_trend_record(args.output, record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
