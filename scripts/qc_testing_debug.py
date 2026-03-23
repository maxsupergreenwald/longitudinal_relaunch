#!/usr/bin/env python3
"""QC Testing and Debugging Script for quickQC_api_calling_v7_relaunch.py

Manages the test roundtrip for verifying QC script behavior:
  1. setup         -- One-time mock shared drive creation
  2. snapshot      -- Export and save record_id=1 as clean baseline
  3. apply <ID>    -- Set up REDCap state for a specific test scenario
  4. [Manually run: python3 quickQC_api_calling_v7_relaunch.py]
  5. verify <ID>   -- Check that expected REDCap fields were set correctly
  6. restore       -- Restore clean snapshot to REDCap

Usage:
  python3 qc_testing_debug.py setup
  python3 qc_testing_debug.py snapshot
  python3 qc_testing_debug.py list
  python3 qc_testing_debug.py show <SCENARIO_ID>
  python3 qc_testing_debug.py apply <SCENARIO_ID>
  python3 qc_testing_debug.py verify <SCENARIO_ID>
  python3 qc_testing_debug.py restore
  python3 qc_testing_debug.py load-payloads

Prerequisites:
  pip install pycap pandas
  Run once: python3 qc_testing_debug.py setup
  Run once: python3 qc_testing_debug.py snapshot (after record_id=1 is ready)
  Before BL-17,BL-19,BL-21,BL-22,BL-25: run load-payloads
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from redcap import Project


# ============================================================================
# SECTION 1: Constants
# ============================================================================

REDCAP_API_URL = os.getenv("AIM8_REDCAP_API_URL", "https://redcap.research.yale.edu/api/")
RELAUNCH_API_TOKEN = "64C5D967CBEB77335224862283A74F4D"

SCRIPT_DIR = Path(__file__).parent
MOCK_DRIVE_ROOT = SCRIPT_DIR / "qc_test_drive"
MOCK_IP_PATH = MOCK_DRIVE_ROOT / "ips" / "ips_full.csv"
MOCK_JSON_PATH = MOCK_DRIVE_ROOT / "jsons" / "failed_task_jsons_baseline.csv"
MOCK_QC_TODO_PATH = MOCK_DRIVE_ROOT / "qc_to_dos"
SNAPSHOT_PATH           = SCRIPT_DIR / "qc_test_snapshot.json"
SCREENING_SNAPSHOT_PATH = SCRIPT_DIR / "qc_test_snapshot_screening.json"
BASELINE_SNAPSHOT_PATH  = SCRIPT_DIR / "qc_test_snapshot_baseline.json"
TASK_PAYLOADS_PATH = SCRIPT_DIR / "qc_task_payloads.json"
FAILED_TASK_EXAMPLES_PATH = SCRIPT_DIR.parent / "resources" / "failed_task_examples.csv"

TEST_RECORD_ID = 1
# DUPE_RECORD_ID is used ONLY for copy-paste detection and SCR-12/SCR-15 scenarios.
# Confirm this ID does not conflict with real study participants before first use.
DUPE_RECORD_ID = 9998

ACH_FIELD = "task_data_ach_task_short_baseline"
VCH_FIELD = "task_data_vch_short_psychedelic_bl"
PRL_FIELD = "task_data_prltask"

# IP configuration presets
_IP_BASE = {
    "ip": "1.2.3.4", "org": "AS15169 Google LLC", "country_name": "United States",
    "city": "Mountain View", "region": "California", "postal": "94035",
    "timezone": "America/Los_Angeles", "hostname": "google.com",
    "latitude": "37.4223", "longitude": "-122.0847",
}
IP_CLEAN = {**_IP_BASE, "record_id": TEST_RECORD_ID}
IP_FORBIDDEN_ORG = {**_IP_BASE, "record_id": TEST_RECORD_ID,
                    "org": "AS174 Cogent Communications", "ip": "38.140.0.1"}
IP_FORBIDDEN_COUNTRY = {**_IP_BASE, "record_id": TEST_RECORD_ID,
                         "country_name": "Nigeria", "org": "AS37153 MTN Nigeria", "ip": "41.58.0.1"}
# IP_PRIOR_BAD: record 1 shares IP 5.5.5.5 with a prior reviewed record (9998)
IP_PRIOR_BAD = {**_IP_BASE, "record_id": TEST_RECORD_ID, "ip": "5.5.5.5"}

_IP_MISSING = "MISSING"  # sentinel: delete row for TEST_RECORD_ID

_IP_COLUMNS = ["record_id", "ip", "org", "country_name", "city", "region",
               "postal", "timezone", "hostname", "latitude", "longitude"]


# ============================================================================
# SECTION 2: REDCap Helpers
# ============================================================================

def _get_project() -> Project:
    return Project(REDCAP_API_URL, RELAUNCH_API_TOKEN)


def redcap_export_record(record_id: int) -> dict[str, Any]:
    project = _get_project()
    df = project.export_records(records=[record_id], format_type="df")
    if df.empty:
        raise RuntimeError(f"Record {record_id} not found in REDCap.")
    row = df.iloc[0]
    return {k: (None if pd.isna(v) else v) for k, v in row.items()}


def redcap_import_fields(record_id: int, fields: dict[str, Any]) -> None:
    project = _get_project()
    import_row = {"record_id": record_id, **fields}
    df = pd.DataFrame([import_row])
    project.import_records(to_import=df, import_format="df", overwrite="overwrite")
    print(f"  Imported {len(fields)} field(s) to record {record_id}.")


def redcap_clear_fields(record_id: int, fields: list[str]) -> None:
    redcap_import_fields(record_id, {f: "" for f in fields})


# ============================================================================
# SECTION 3: Task Payload Management
# ============================================================================

# Maps (task, fail_reason) from failed_task_examples.csv -> payload key
_CSV_PAYLOAD_MAP: dict[tuple[str, str], str] = {
    ("auditory_ch_task", "Zero"): "ach_zero",
    ("visual_ch_task", "Negative"): "vch_negative",
    ("prl_task", "Worse Than Chance"): "prl_worse_than_chance",
    ("prl_task", "Non Responders"): "prl_non_responders",
}


def _load_csv_payloads() -> dict[str, str]:
    payloads: dict[str, str] = {}
    if not FAILED_TASK_EXAMPLES_PATH.exists():
        return payloads
    with open(FAILED_TASK_EXAMPLES_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = _CSV_PAYLOAD_MAP.get((row.get("task", ""), row.get("fail_reason", "")))
            if key and row.get("json_string"):
                payloads[key] = row["json_string"]
    return payloads


def _load_saved_payloads() -> dict[str, str]:
    if not TASK_PAYLOADS_PATH.exists():
        return {}
    with open(TASK_PAYLOADS_PATH) as f:
        return json.load(f)


def load_payload(name: str) -> str:
    all_payloads = {**_load_csv_payloads(), **_load_saved_payloads()}
    if name not in all_payloads:
        available = sorted(all_payloads.keys())
        raise RuntimeError(
            f"Payload '{name}' not found.\n"
            f"Available: {available or '(none)'}\n"
            f"Run: python3 qc_testing_debug.py load-payloads"
        )
    return all_payloads[name]


def cmd_load_payloads() -> None:
    """Interactive wizard: save additional failure-type task payloads."""
    NEEDED = [
        ("ach_negative",        "ACH (auditory_ch_task) — NEGATIVE SLOPE"),
        ("ach_fail_first_fifteen", "ACH (auditory_ch_task) — FAIL FIRST FIFTEEN"),
        ("vch_zero",            "VCH (visual_ch_task) — ZERO / NON-SIGNIFICANT SLOPE"),
        ("vch_fail_first_fifteen", "VCH (visual_ch_task) — FAIL FIRST FIFTEEN"),
        ("prl_no_lose_stay",    "PRL (prl_task) — NO LOSE-STAY (<1%)"),
    ]
    csv_payloads = _load_csv_payloads()
    saved = _load_saved_payloads()

    print("\nTask Payload Loader")
    print("=" * 60)
    print("Pre-loaded from resources/failed_task_examples.csv:")
    for key in sorted(csv_payloads.keys()):
        print(f"  [x] {key}")

    new_payloads = dict(saved)
    for payload_key, description in NEEDED:
        if payload_key in csv_payloads or payload_key in saved:
            print(f"\n  [x] {payload_key} — already saved, skipping")
            continue
        print(f"\n{description}")
        print("Paste the compressed JSON string (single line from the json_string column).")
        print("Press Enter twice when done, or type 'skip':")
        lines: list[str] = []
        while True:
            line = input()
            if line.strip().lower() == "skip":
                print(f"  Skipped {payload_key}.")
                break
            if line == "" and lines:
                payload_str = "".join(lines).strip()
                new_payloads[payload_key] = payload_str
                print(f"  Saved {payload_key} ({len(payload_str)} chars).")
                break
            lines.append(line)

    with open(TASK_PAYLOADS_PATH, "w") as f:
        json.dump(new_payloads, f, indent=2)
    print(f"\nSaved {len(new_payloads)} additional payload(s) to {TASK_PAYLOADS_PATH}")


# ============================================================================
# SECTION 4: Mock Drive Setup
# ============================================================================

def _write_ip_csv(rows: list[dict]) -> None:
    MOCK_IP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MOCK_IP_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_IP_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_ip_rows() -> list[dict]:
    if not MOCK_IP_PATH.exists():
        return []
    with open(MOCK_IP_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _update_ip_row(record_id: int, ip_config: dict) -> None:
    rows = [r for r in _read_ip_rows() if _safe_int(r.get("record_id")) != record_id]
    rows.append({**ip_config, "record_id": record_id})
    _write_ip_csv(rows)


def _delete_ip_row(record_id: int) -> None:
    rows = [r for r in _read_ip_rows() if _safe_int(r.get("record_id")) != record_id]
    _write_ip_csv(rows)


def _safe_int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def reset_ips_to_clean() -> None:
    rows = [r for r in _read_ip_rows()
            if _safe_int(r.get("record_id")) not in {TEST_RECORD_ID, DUPE_RECORD_ID}]
    rows.append(IP_CLEAN)
    _write_ip_csv(rows)


def cmd_setup() -> None:
    MOCK_DRIVE_ROOT.mkdir(parents=True, exist_ok=True)
    (MOCK_DRIVE_ROOT / "ips").mkdir(exist_ok=True)
    (MOCK_DRIVE_ROOT / "jsons").mkdir(exist_ok=True)
    MOCK_QC_TODO_PATH.mkdir(exist_ok=True)

    _write_ip_csv([IP_CLEAN])

    json_headers = ["record_id", "task", "fail_reason", "fail_attempt", "json_string"]
    with open(MOCK_JSON_PATH, "w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=json_headers).writeheader()

    print("Mock shared drive created at:", MOCK_DRIVE_ROOT)
    print()
    print("Before running the QC script, export this env variable:")
    print(f"  export AIM8_SHAREDDRIVE_PATH={MOCK_DRIVE_ROOT}")
    print()
    print("Next: python3 qc_testing_debug.py snapshot   (after record_id=1 is ready)")


# ============================================================================
# SECTION 5: Snapshot Management
# ============================================================================

def _snapshot_path(stage: str | None) -> Path:
    return {
        "screening": SCREENING_SNAPSHOT_PATH,
        "baseline":  BASELINE_SNAPSHOT_PATH,
    }.get(stage or "", SNAPSHOT_PATH)


def cmd_snapshot(stage: str | None = None) -> None:
    path = _snapshot_path(stage)
    print(f"Exporting record {TEST_RECORD_ID} from REDCap...")
    record = redcap_export_record(TEST_RECORD_ID)
    with open(path, "w") as f:
        json.dump(record, f, indent=2)
    label = f" ({stage})" if stage else ""
    print(f"Snapshot{label} saved to {path} ({len(record)} fields).")


def cmd_restore(stage: str | None = None) -> None:
    path = _snapshot_path(stage)
    if not path.exists():
        label = f" ({stage})" if stage else ""
        hint = f"snapshot {stage}" if stage else "snapshot"
        print(f"ERROR: Snapshot{label} not found at {path}")
        print(f"Run: python3 qc_testing_debug.py {hint}")
        sys.exit(1)

    with open(path) as f:
        snapshot = json.load(f)

    print(f"Restoring record {TEST_RECORD_ID} from snapshot ({len(snapshot)} fields)...")
    redcap_import_fields(TEST_RECORD_ID, snapshot)

    # Clear dupe record fields
    dupe_clear = [
        ACH_FIELD, VCH_FIELD, PRL_FIELD,
        "qc_passed", "qc_notes", "screening_pass", "race_qc",
        "email_rpt", "datedone_screening_survey",
        "task_data_ach_bl_retrieved", "task_data_vch_bl_retrieved", "task_data_prl_bl_retrieved",
    ]
    print(f"Clearing dupe record {DUPE_RECORD_ID}...")
    try:
        redcap_clear_fields(DUPE_RECORD_ID, dupe_clear)
    except Exception as exc:
        print(f"  (dupe record clear: {exc} — may not exist yet, continuing)")

    reset_ips_to_clean()
    print("IP file reset.")

    _clear_incomplete_flags()
    print("Restore complete.")


def _clear_incomplete_flags() -> None:
    if not MOCK_QC_TODO_PATH.exists():
        return
    removed = 0
    for date_dir in MOCK_QC_TODO_PATH.iterdir():
        if not date_dir.is_dir():
            continue
        for flag in date_dir.iterdir():
            if "INCOMPLETE" in flag.name:
                flag.unlink()
                removed += 1
    if removed:
        print(f"Cleared {removed} INCOMPLETE flag file(s).")


# ============================================================================
# SECTION 6: ScenarioSpec and Registry
# ============================================================================

@dataclass
class ScenarioSpec:
    scenario_id: str
    name: str
    category: str               # "screening" or "baseline"
    description: str
    field_overrides: dict       # REDCap fields to set on TEST_RECORD_ID before test
    ip_config: Any              # IP_CLEAN / IP_FORBIDDEN_ORG / IP_PRIOR_BAD / _IP_MISSING / None
    task_data_payload: str | None   # key in payload store
    task_data_field: str | None     # REDCap field to write payload into
    uses_dupe_record: bool      # True = scenario requires DUPE_RECORD_ID
    dupe_task_field: str | None # Which task field to copy to dupe (BL-16x only)
    prompts: list[str]          # User inputs needed at QC script prompts
    expected_fields: dict       # field -> value on TEST_RECORD_ID after QC run
    expected_fields_dupe: dict  # field -> value on DUPE_RECORD_ID after QC run
    notes: str


SCENARIOS: dict[str, ScenarioSpec] = {

# ---------------------------------------------------------------------------
# SCREENING SCENARIOS
# ---------------------------------------------------------------------------
# All require: submit_screen_v3 present, screening_pass/qc_passed null,
# phone_number present, ip_zoom_invite null.

"SCR-00": ScenarioSpec(
    "SCR-00", "Passes screening", "screening",
    "Reference case — user provides clean passing record. No overrides needed.",
    field_overrides={}, ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Phone verdict: n (clear)", "Import: yes"],
    expected_fields={"screening_pass": "1", "eligible_notify": "1"},
    expected_fields_dupe={},
    notes="No setup needed. Record_id=1 should already have clean screening data.",
),

"SCR-01": ScenarioSpec(
    "SCR-01", "Age too old", "screening",
    "age_v2=70 triggers 'Age above 65' hard fail.",
    field_overrides={"age_v2": "70"}, ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"screening_pass": "0", "qc_passed": "0", "ineligibile_fraud": "1"},
    expected_fields_dupe={},
    notes="Hard fail before phone review — no phone verdict prompt.",
),

"SCR-02": ScenarioSpec(
    "SCR-02", "Age too young", "screening",
    "age_v2=16 triggers 'Age below 18' hard fail.",
    field_overrides={"age_v2": "16"}, ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"screening_pass": "0", "qc_passed": "0", "ineligibile_fraud": "1"},
    expected_fields_dupe={}, notes="",
),

"SCR-03": ScenarioSpec(
    "SCR-03", "Cognition screener failed", "screening",
    "cognition_screener_v2=1 triggers hard fail.",
    field_overrides={"cognition_screener_v2": "1"}, ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"screening_pass": "0", "qc_passed": "0", "ineligibile_fraud": "1"},
    expected_fields_dupe={}, notes="",
),

"SCR-04": ScenarioSpec(
    "SCR-04", "Seizure history", "screening",
    "seizure_hx_v2=1 triggers hard fail.",
    field_overrides={"seizure_hx_v2": "1"}, ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"screening_pass": "0", "qc_passed": "0", "ineligibile_fraud": "1"},
    expected_fields_dupe={}, notes="",
),

"SCR-05": ScenarioSpec(
    "SCR-05", "Intoxication at intake", "screening",
    "intox_screen_v2=1 triggers hard fail.",
    field_overrides={"intox_screen_v2": "1"}, ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"screening_pass": "0", "qc_passed": "0", "ineligibile_fraud": "1"},
    expected_fields_dupe={}, notes="",
),

"SCR-06": ScenarioSpec(
    "SCR-06", "No psychedelic use", "screening",
    "psycheduse_yn=2 triggers 'Did not endorse serotonergic psychedelic use' hard fail.",
    field_overrides={"psycheduse_yn": "2"}, ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"screening_pass": "0", "qc_passed": "0", "ineligibile_fraud": "1"},
    expected_fields_dupe={}, notes="",
),

"SCR-07": ScenarioSpec(
    "SCR-07", "Raven score too low", "screening",
    "raven_total_score_v2=0 triggers 'Raven score below minimum' hard fail.",
    field_overrides={"raven_total_score_v2": "0"}, ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"screening_pass": "0", "qc_passed": "0", "ineligibile_fraud": "1"},
    expected_fields_dupe={}, notes="",
),

"SCR-08": ScenarioSpec(
    "SCR-08", "No computer access", "screening",
    "no_computer=1 triggers hard fail.",
    field_overrides={"no_computer": "1"}, ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"screening_pass": "0", "qc_passed": "0", "ineligibile_fraud": "1"},
    expected_fields_dupe={}, notes="",
),

"SCR-09": ScenarioSpec(
    "SCR-09", "English fluency not met", "screening",
    "english_fluency=0 triggers hard fail.",
    field_overrides={"english_fluency": "0"}, ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"screening_pass": "0", "qc_passed": "0", "ineligibile_fraud": "1"},
    expected_fields_dupe={}, notes="",
),

"SCR-10": ScenarioSpec(
    "SCR-10", "Geographic fraud flag", "screening",
    "Clears geo_crit — pd.isna() check in script fires 'Geographic fraud flag' hard fail.",
    field_overrides={"geo_crit": ""}, ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"screening_pass": "0", "qc_passed": "0", "ineligibile_fraud": "1"},
    expected_fields_dupe={},
    notes="Script checks pd.isna(row.get('geo_crit', np.nan)). Blank string in REDCap exports as NaN.",
),

"SCR-11": ScenarioSpec(
    "SCR-11", "Recent SP use (within 42 days)", "screening",
    "sp_lastuse_days_screen=30 triggers 'Reported SP/atypical use within the last 42 days' hard fail.",
    field_overrides={"sp_lastuse_days_screen": "30"}, ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"screening_pass": "0", "qc_passed": "0", "ineligibile_fraud": "1"},
    expected_fields_dupe={}, notes="",
),

"SCR-11b": ScenarioSpec(
    "SCR-11b", "Recent SP use, willing to wait (clean)", "screening",
    "sp_dayslastuse=30 AND psychedelic_abstinence_yn=1 AND clean IP/phone -> sp_wait path -> "
    "screening_pass=1, eligible_afterwait_notify=1 (NOT eligible_notify).",
    field_overrides={"sp_dayslastuse": "30", "psychedelic_abstinence_yn": "1"}, ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Phone verdict: n (clear)", "Import: yes"],
    expected_fields={"screening_pass": "1", "eligible_afterwait_notify": "1", "eligible_notify": None},
    expected_fields_dupe={},
    notes="eligible_notify must remain blank. eligible_afterwait_notify=1 sends the deferred invitation.",
),

"SCR-11c": ScenarioSpec(
    "SCR-11c", "Recent SP use, willing to wait, fraudulent phone", "screening",
    "sp_dayslastuse=30, psychedelic_abstinence_yn=1 (willing to wait), but user enters 'y' at "
    "phone verdict -> normal fraud path. sp_wait does NOT protect against explicit phone fraud.",
    field_overrides={"sp_dayslastuse": "30", "psychedelic_abstinence_yn": "1"}, ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Phone verdict: y (fraudulent/VOIP)", "Import: yes"],
    expected_fields={
        "screening_pass": "0", "qc_passed": "0", "ineligibile_fraud": "1",
        "eligible_afterwait_notify": None,
    },
    expected_fields_dupe={},
    notes="eligible_afterwait_notify must remain blank — phone fraud overrides the wait path.",
),

"SCR-11d": ScenarioSpec(
    "SCR-11d", "Recent atypical use, willing to wait (clean)", "screening",
    "SP dayslastuse is fine (>42) but mdma_dayslastuse=10 triggers atypical_recentuse calc -> "
    "sp_wait path. psychedelic_abstinence_yn=1 -> screening_pass=1, eligible_afterwait_notify=1.",
    field_overrides={"mdma_lifetime": "1", "mdma_dayslastuse": "10", "psychedelic_abstinence_yn": "1"},
    ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Phone verdict: n (clear)", "Import: yes"],
    expected_fields={"screening_pass": "1", "eligible_afterwait_notify": "1", "eligible_notify": None},
    expected_fields_dupe={},
    notes=(
        "atypical_recentuse is a REDCap calc field that fires when atypical substance use is "
        "recent. If the calc doesn't update from just setting mdma_dayslastuse, set "
        "atypical_recentuse=1 directly in field_overrides as a fallback."
    ),
),

"SCR-12": ScenarioSpec(
    "SCR-12", "Duplicate email", "screening",
    "email_rpt on record 1 matches a prior record's email (record 9998). "
    "apply() injects record 9998 with the same email and datedone_screening_survey set.",
    field_overrides={"email_rpt": "dupe_test@example.com"}, ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=True, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"screening_pass": "0", "qc_passed": "0", "ineligibile_fraud": "1"},
    expected_fields_dupe={},
    notes=(
        "HOW IT WORKS: apply() imports email_rpt=dupe_test@example.com to record 1. "
        "It also imports to record 9998: email_rpt=dupe_test@example.com + "
        "datedone_screening_survey=2025-01-01 (marks it as a 'prior screened' record). "
        "_apply_duplicate_identity_checks() finds the email match in historic records -> hard fail."
    ),
),

"SCR-13": ScenarioSpec(
    "SCR-13", "Forbidden IP org", "screening",
    "IP org is AS174 Cogent Communications — in FORBIDDEN_IP_ORGS set.",
    field_overrides={}, ip_config=IP_FORBIDDEN_ORG,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"screening_pass": "0", "qc_passed": "0", "ineligibile_fraud": "1"},
    expected_fields_dupe={},
    notes="Only ips_full.csv is modified. No REDCap field overrides needed.",
),

"SCR-14": ScenarioSpec(
    "SCR-14", "Forbidden IP country", "screening",
    "IP country_name=Nigeria — in FORBIDDEN_IP_COUNTRIES set.",
    field_overrides={}, ip_config=IP_FORBIDDEN_COUNTRY,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"screening_pass": "0", "qc_passed": "0", "ineligibile_fraud": "1"},
    expected_fields_dupe={},
    notes="Only ips_full.csv is modified.",
),

"SCR-15": ScenarioSpec(
    "SCR-15", "Suspicious duplicate IP", "screening",
    "Record 1 and prior record 9998 share IP 5.5.5.5 (non-safe org). "
    "Record passes automated checks but ip_zoom_invite=1 is set alongside screening_pass=1.",
    field_overrides={}, ip_config=IP_PRIOR_BAD,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=True, dupe_task_field=None,
    prompts=["User code: m", "Phone verdict: n (clear)", "Import: yes"],
    expected_fields={"screening_pass": "1", "eligible_notify": "1", "ip_zoom_invite": "1"},
    expected_fields_dupe={},
    notes=(
        "HOW IT WORKS: apply() sets record 1 IP to 5.5.5.5 (AS15169 Google — not safe-duplicate). "
        "It also adds record 9998 to ips_full.csv with IP=5.5.5.5 and imports "
        "datedone_screening_survey=2025-01-01 + qc_passed=0 to record 9998 (marks it as "
        "'already reviewed ineligible'). prior_bad_ips now includes 5.5.5.5 -> suspicious IP flag."
    ),
),

"SCR-16": ScenarioSpec(
    "SCR-16", "Phone verdict: VOIP/fraudulent", "screening",
    "Record passes automated checks. User enters 'y' at phone verdict prompt -> hard fail.",
    field_overrides={}, ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Phone verdict: y (fraudulent/VOIP)", "Import: yes"],
    expected_fields={"screening_pass": "0", "qc_passed": "0", "ineligibile_fraud": "1"},
    expected_fields_dupe={},
    notes="No field overrides — only the 'y' phone verdict causes the fail.",
),

"SCR-17": ScenarioSpec(
    "SCR-17", "Phone verdict: manual follow-up", "screening",
    "Record passes automated checks. User enters '?' -> max_number_followup=1. NOT a fail.",
    field_overrides={}, ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Phone verdict: ? (needs Max review)", "Import: yes"],
    expected_fields={"max_number_followup": "1"},
    expected_fields_dupe={},
    notes="screening_pass and qc_passed should remain blank — verify they are NOT set.",
),

"SCR-18": ScenarioSpec(
    "SCR-18", "Missing IP metadata", "screening",
    "IP row for record 1 deleted from ips_full.csv. Record goes to manual_followup.",
    field_overrides={}, ip_config=_IP_MISSING,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m",
             "When prompted for REDCap PDF archive rows: type 'no ip' and press Enter",
             "Import: yes"],
    expected_fields={"max_number_followup": "1"},
    expected_fields_dupe={},
    notes="screening_pass and qc_passed should remain blank.",
),

"SCR-19": ScenarioSpec(
    "SCR-19", "Fake drug endorsed at screening (kaopectamine)", "screening",
    "kaopectamine_lifetime=1 triggers 'Endorsed fake drug (kaopectamine) during screening' hard fail "
    "in _apply_screening_eligibility_rules. Distinct from BL-03 (same trap caught at baseline QC).",
    field_overrides={"kaopectamine_lifetime": "1"}, ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={
        "screening_pass": "0", "qc_passed": "0", "ineligibile_fraud": "1",
        "qc_notes": "CONTAINS:kaopectamine",
    },
    expected_fields_dupe={},
    notes="Hard fail before phone verdict — no phone verdict prompt.",
),

"SCR-20": ScenarioSpec(
    "SCR-20", "AI prompt injection field filled (flexibility_yn)", "screening",
    "flexibility_yn='ok' — the @HIDDEN-SURVEY honeypot field was filled in. "
    "Normal participants never see it; AI agents parsing raw HTML may follow the embedded instruction.",
    field_overrides={"flexibility_yn": "ok"}, ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={
        "screening_pass": "0", "qc_passed": "0", "ineligibile_fraud": "1",
        "qc_notes": "CONTAINS:flexibility_yn",
    },
    expected_fields_dupe={},
    notes="Hard fail before phone verdict — no phone verdict prompt.",
),

"SCR-21": ScenarioSpec(
    "SCR-21", "Screening completed too quickly (screen_seconds_taken < 90)", "screening",
    "screen_seconds_taken=45 triggers 'Completed screening suspiciously fast' hard fail.",
    field_overrides={"screen_seconds_taken": "45"}, ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={
        "screening_pass": "0", "qc_passed": "0", "ineligibile_fraud": "1",
        "qc_notes": "CONTAINS:screen_seconds_taken",
    },
    expected_fields_dupe={},
    notes="Hard fail before phone verdict — no phone verdict prompt.",
),

"SCR-22": ScenarioSpec(
    "SCR-22", "screen_motive exactly 500 characters (length heuristic only)", "screening",
    "screen_motive is exactly 500 characters but does NOT begin with the AI template phrase. "
    "Fires heuristic 1 only: 'response is exactly 500 characters'.",
    field_overrides={"screen_motive": "a" * 500}, ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={
        "screening_pass": "0", "qc_passed": "0", "ineligibile_fraud": "1",
        "qc_notes": "CONTAINS:exactly 500 characters",
    },
    expected_fields_dupe={},
    notes="Hard fail before phone verdict. Confirm qc_notes does NOT mention 'AI template phrase'.",
),

"SCR-23": ScenarioSpec(
    "SCR-23", "screen_motive AI template phrase — 490 chars (phrase heuristic only)", "screening",
    "screen_motive starts with 'I would describe my personal motivation' and is 490 chars (in "
    "476–524 range) but NOT exactly 500. Fires heuristic 2 only: 'begins with AI template phrase'.",
    field_overrides={"screen_motive": "I would describe my personal motivation" + "x" * 452},
    ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={
        "screening_pass": "0", "qc_passed": "0", "ineligibile_fraud": "1",
        "qc_notes": "CONTAINS:AI template phrase",
    },
    expected_fields_dupe={},
    notes=(
        "Hard fail before phone verdict. screen_motive value is 490 chars (38 + 452). "
        "Confirm qc_notes does NOT mention 'exactly 500 characters'."
    ),
),

"SCR-24": ScenarioSpec(
    "SCR-24", "screen_motive both AI flags (500 chars + template phrase)", "screening",
    "screen_motive starts with 'I would describe my personal motivation' AND is exactly 500 chars. "
    "Both heuristics fire; both reasons are semicolon-joined in qc_notes.",
    field_overrides={"screen_motive": "I would describe my personal motivation" + "x" * 462},
    ip_config=IP_CLEAN,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={
        "screening_pass": "0", "qc_passed": "0", "ineligibile_fraud": "1",
        "qc_notes": "CONTAINS:AI template phrase",
    },
    expected_fields_dupe={},
    notes=(
        "Hard fail before phone verdict. screen_motive value is exactly 500 chars (38 + 462). "
        "qc_notes should contain both 'exactly 500 characters' AND 'AI template phrase' "
        "semicolon-joined."
    ),
),

# ---------------------------------------------------------------------------
# BASELINE QC SCENARIOS
# ---------------------------------------------------------------------------
# All require: qc_passed null, screening_pass > 0, race_qc present, all task data present.

"BL-00": ScenarioSpec(
    "BL-00", "Passes QC", "baseline",
    "Reference case — user provides clean record with all passing data.",
    field_overrides={}, ip_config=None,
    task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"qc_passed": "1", "send_pay_confirm": "1", "employee_name": "NOT_EMPTY"},
    expected_fields_dupe={},
    notes="No setup needed. An expense sheet should be generated in qc_test_drive/qc_to_dos/.",
),

"BL-01": ScenarioSpec(
    "BL-01", "Attention check fail", "baseline",
    "All attn_check_surveybl fields set to 0. Sum < count-of-fields -> failedAttnCheck.",
    field_overrides={"attn_check_surveybl": "0", "attn_check_surveybl2": "0",
                     "attn_check_surveybl3": "0", "attn_check_surveybl4": "0"},
    ip_config=None, task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"qc_passed": "0", "qc_notes": "NOT_EMPTY"},
    expected_fields_dupe={},
    notes="qc_notes contains 'Failed attention check'. fraudulent_email_inconsistentanswers=1.",
),

"BL-02": ScenarioSpec(
    "BL-02", "Race/age mismatch", "baseline",
    "race_qc != race_v2 AND age_qc != age_v2 -> failed_new_qc critical fail.",
    field_overrides={"race_qc": "3", "race_v2": "1", "age_qc": "35", "age_v2": "25"},
    ip_config=None, task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"qc_passed": "0", "qc_notes": "NOT_EMPTY"},
    expected_fields_dupe={},
    notes="racediff=2 > 1 alone triggers the fail. qc_notes contains 'race/age consistency QC'.",
),

"BL-03": ScenarioSpec(
    "BL-03", "Fake drug endorsed (kaopectamine)", "baseline",
    "kaopectamine_lifetime='1' (radio Yes) -> failed_trap_questions critical fail.",
    field_overrides={"kaopectamine_lifetime": "1"},
    ip_config=None, task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"qc_passed": "0", "qc_notes": "NOT_EMPTY"},
    expected_fields_dupe={},
    notes="qc_notes contains 'trap/fraud-detection'. This is a critical fail -> qc_passed=0.",
),

"BL-04": ScenarioSpec(
    "BL-04", "Dose mismatch trap (fraud_recent_dose)", "baseline",
    "fraud_recent_dose=1 -> calculated dose mismatch trap -> critical fail.",
    field_overrides={"fraud_recent_dose": "1"},
    ip_config=None, task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"qc_passed": "0", "qc_notes": "NOT_EMPTY"},
    expected_fields_dupe={}, notes="",
),

"BL-05": ScenarioSpec(
    "BL-05", "CAPS attention check fail (fraud_caps='0')", "baseline",
    "fraud_caps='0' (answered No to embedded CAPS item, correct=Yes) -> critical fail.",
    field_overrides={"fraud_caps": "0"},
    ip_config=None, task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"qc_passed": "0", "qc_notes": "NOT_EMPTY"},
    expected_fields_dupe={},
    notes="Script checks: fraud_caps.astype(str).strip() == '0'",
),

"BL-06": ScenarioSpec(
    "BL-06", "PDI attention check fail (fraud_pdi='0')", "baseline",
    "fraud_pdi='0' (answered No to embedded PDI item, correct=Yes) -> critical fail.",
    field_overrides={"fraud_pdi": "0"},
    ip_config=None, task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"qc_passed": "0", "qc_notes": "NOT_EMPTY"},
    expected_fields_dupe={}, notes="",
),

"BL-07": ScenarioSpec(
    "BL-07", "No SP use in main survey", "baseline",
    "psycheduse_yn=1 but life/total SP use = 0 in survey -> absurd SP response critical fail.",
    field_overrides={"psycheduse_yn": "1", "psycheduse_life_nomic": "0",
                     "psychedelicuse_lifetimetot": "0"},
    ip_config=None, task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"qc_passed": "0", "qc_notes": "NOT_EMPTY"},
    expected_fields_dupe={},
    notes="qc_notes contains 'no SP use in main survey despite saying they used SPs in screening'.",
),

"BL-08": ScenarioSpec(
    "BL-08", "Non-SP effects endorsed (sp_fraud_aes)", "baseline",
    "sp_fraud_aes___1=1 -> endorsed non-SP effects from SP use -> critical fail.",
    field_overrides={"psycheduse_yn": "1", "sp_fraud_aes___1": "1"},
    ip_config=None, task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"qc_passed": "0", "qc_notes": "NOT_EMPTY"},
    expected_fields_dupe={},
    notes="qc_notes contains 'Reported non-SP effects from SPs'.",
),

"BL-09": ScenarioSpec(
    "BL-09", "Bizarre route of administration", "baseline",
    "sp_fraud_psi=3 (<6 threshold) -> bizarre ROA for psilocybin -> critical fail.",
    field_overrides={"psycheduse_yn": "1", "sp_fraud_psi": "3"},
    ip_config=None, task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"qc_passed": "0", "qc_notes": "NOT_EMPTY"},
    expected_fields_dupe={},
    notes="Other sp_fraud_* fields should be at or above thresholds in clean snapshot. "
          "qc_notes contains 'bizarre route of administration'.",
),

"BL-10": ScenarioSpec(
    "BL-10", "Twice-inconsistent SP (post-verification fail)", "baseline",
    "verify_emailed=1 + sp_verify_pass=0 -> gave inconsistent SP answers twice -> critical fail.",
    field_overrides={"verify_emailed": "1", "sp_verify_pass": "0"},
    ip_config=None, task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"qc_passed": "0", "qc_notes": "NOT_EMPTY"},
    expected_fields_dupe={},
    notes="qc_notes contains 'inconsistent answers about SP use twice'. Critical fail.",
),

"BL-11": ScenarioSpec(
    "BL-11", "SP nanresponses (verify path only)", "baseline",
    "sp_type_recent and sp_dayslastuse blank -> nanresponses -> verify_emailed path (NOT qc fail).",
    field_overrides={"psycheduse_life_nomic": "3", "sp_type_recent": "", "sp_dayslastuse": ""},
    ip_config=None, task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"verify_emailed": "1", "inconsistent_sp_answers": "1"},
    expected_fields_dupe={},
    notes="qc_passed should remain blank — this is verify-only, NOT a critical fail.",
),

"BL-12": ScenarioSpec(
    "BL-12", "Illogical year SP use (verify path only)", "baseline",
    "psycheduse_year_nomic(2) < psycheduse_6month_nomic(3) -> illogical_year -> verify path.",
    field_overrides={"psycheduse_yn": "1", "psycheduse_life_nomic": "5",
                     "sp_type_recent": "psilocybin", "sp_dayslastuse": "200",
                     "sp_lastuse_days_screen": "200",
                     "psycheduse_year_nomic": "2", "psycheduse_6month_nomic": "3"},
    ip_config=None, task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"verify_emailed": "1"},
    expected_fields_dupe={},
    notes="qc_passed remains blank.",
),

"BL-13": ScenarioSpec(
    "BL-13", "Illogical lifetime SP use (verify path only)", "baseline",
    "psycheduse_life_nomic(2) < psycheduse_6month_nomic(3) -> illogical_life -> verify path.",
    field_overrides={"psycheduse_yn": "1", "sp_type_recent": "psilocybin",
                     "sp_dayslastuse": "200", "sp_lastuse_days_screen": "200",
                     "psycheduse_life_nomic": "2", "psycheduse_year_nomic": "1",
                     "psycheduse_6month_nomic": "3"},
    ip_config=None, task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"verify_emailed": "1"},
    expected_fields_dupe={},
    notes="qc_passed remains blank.",
),

"BL-14": ScenarioSpec(
    "BL-14", "Wrong recent SP type (verify path only)", "baseline",
    "sp_type_recent != sp_type_recent_qc -> wrong_recent -> verify path.",
    field_overrides={"psycheduse_yn": "1", "psycheduse_life_nomic": "5",
                     "sp_type_recent": "psilocybin", "sp_type_recent_qc": "lsd",
                     "sp_dayslastuse": "200", "sp_lastuse_days_screen": "200"},
    ip_config=None, task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"verify_emailed": "1"},
    expected_fields_dupe={},
    notes="qc_passed remains blank.",
),

"BL-15": ScenarioSpec(
    "BL-15", "Inconsistent SP usetime 6-month window (verify path only)", "baseline",
    "sp_dayslastuse=100 (<180) but psycheduse_6month_nomic=0 -> failed_usetime_qc -> verify path.",
    field_overrides={"psycheduse_yn": "1", "psycheduse_life_nomic": "5",
                     "sp_type_recent": "psilocybin", "sp_lastuse_days_screen": "100",
                     "sp_dayslastuse": "100", "psycheduse_6month_nomic": "0",
                     "psycheduse_year_nomic": "1"},
    ip_config=None, task_data_payload=None, task_data_field=None,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"verify_emailed": "1"},
    expected_fields_dupe={},
    notes="qc_passed remains blank.",
),

"BL-16a": ScenarioSpec(
    "BL-16a", "Copy-paste ACH data", "baseline",
    "Injects identical ACH task data to record 9998. Both records in QC queue with same RT rows "
    "-> pivot duplicate detection fires -> fraud_copy_paste_ach -> qc_passed=0 on both.",
    field_overrides={}, ip_config=None,
    task_data_payload=None,  # payload comes from record 1's current ACH field at apply time
    task_data_field=ACH_FIELD,
    uses_dupe_record=True, dupe_task_field=ACH_FIELD,
    prompts=["User code: m",
             "NOTE: Both record 1 AND record 9998 will be in QC queue",
             "Import: yes"],
    expected_fields={"qc_passed": "0", "qc_notes": "NOT_EMPTY"},
    expected_fields_dupe={"qc_passed": "0", "qc_notes": "NOT_EMPTY"},
    notes=(
        "HOW IT WORKS: apply() exports ACH data from record 1, then imports the SAME string to "
        "record 9998 (with screening_pass=1, race_qc copied from record 1, qc_passed blank). "
        "_load_ach_trials() pivots on (record_id x trial) RT values and detects duplicate rows "
        "-> both records added to fraud_copy_paste_ach -> qc_passed=0. "
        "qc_notes should contain 'Copy pasted ACH data'."
    ),
),

"BL-16b": ScenarioSpec(
    "BL-16b", "Copy-paste VCH data", "baseline",
    "Injects identical VCH task data to record 9998 -> fraud_copy_paste_vch -> qc_passed=0 both.",
    field_overrides={}, ip_config=None,
    task_data_payload=None,
    task_data_field=VCH_FIELD,
    uses_dupe_record=True, dupe_task_field=VCH_FIELD,
    prompts=["User code: m", "NOTE: Both record 1 AND record 9998 in QC queue", "Import: yes"],
    expected_fields={"qc_passed": "0", "qc_notes": "NOT_EMPTY"},
    expected_fields_dupe={"qc_passed": "0", "qc_notes": "NOT_EMPTY"},
    notes="Same mechanism as BL-16a but for VCH. qc_notes contains 'Copy pasted VCH data'.",
),

"BL-16c": ScenarioSpec(
    "BL-16c", "Copy-paste PRL data", "baseline",
    "Injects identical PRL task data to record 9998 -> fraud_copy_paste_prl -> qc_passed=0 both.",
    field_overrides={}, ip_config=None,
    task_data_payload=None,
    task_data_field=PRL_FIELD,
    uses_dupe_record=True, dupe_task_field=PRL_FIELD,
    prompts=["User code: m", "NOTE: Both record 1 AND record 9998 in QC queue", "Import: yes"],
    expected_fields={"qc_passed": "0", "qc_notes": "NOT_EMPTY"},
    expected_fields_dupe={"qc_passed": "0", "qc_notes": "NOT_EMPTY"},
    notes="Same mechanism as BL-16a but for PRL. qc_notes contains 'Copy pasted PRL data'.",
),

"BL-17": ScenarioSpec(
    "BL-17", "ACH negative slope (task retry)", "baseline",
    "ACH data with negative detection slope -> task retry queued (NOT qc_passed=0 — see note).",
    field_overrides={}, ip_config=None,
    task_data_payload="ach_negative", task_data_field=ACH_FIELD,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"ach_replay": "1", "replay_links_ach": "1"},
    expected_fields_dupe={},
    notes=(
        "IMPORTANT: At baseline, negative slope routes through _task_failures_for_record() -> "
        "_queue_task_retry() and does NOT set qc_passed=0. Only questionnaire/fraud checks cause "
        "qc_passed=0. task_data_ach_task_short_baseline should be cleared after retry is queued. "
        "Requires 'ach_negative' payload from load-payloads."
    ),
),

"BL-18": ScenarioSpec(
    "BL-18", "ACH zero/non-significant slope (task retry)", "baseline",
    "ACH data with p>0.05 (non-significant) detection slope -> task retry queued.",
    field_overrides={}, ip_config=None,
    task_data_payload="ach_zero", task_data_field=ACH_FIELD,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"ach_replay": "1", "replay_links_ach": "1"},
    expected_fields_dupe={},
    notes="Payload 'ach_zero' auto-loaded from resources/failed_task_examples.csv.",
),

"BL-19": ScenarioSpec(
    "BL-19", "ACH fail-first-fifteen (task retry)", "baseline",
    "ACH data where mean response in first 15 trials < 0.5 -> task retry queued.",
    field_overrides={}, ip_config=None,
    task_data_payload="ach_fail_first_fifteen", task_data_field=ACH_FIELD,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"ach_replay": "1", "replay_links_ach": "1"},
    expected_fields_dupe={},
    notes="Requires 'ach_fail_first_fifteen' payload from load-payloads.",
),

"BL-20": ScenarioSpec(
    "BL-20", "VCH negative slope (task retry)", "baseline",
    "VCH data with negative detection slope -> task retry queued.",
    field_overrides={}, ip_config=None,
    task_data_payload="vch_negative", task_data_field=VCH_FIELD,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"vch_replay": "1", "replay_links_vch": "1"},
    expected_fields_dupe={},
    notes="Payload 'vch_negative' auto-loaded from resources/failed_task_examples.csv.",
),

"BL-21": ScenarioSpec(
    "BL-21", "VCH zero/non-significant slope (task retry)", "baseline",
    "VCH data with p>0.05 detection slope -> task retry queued.",
    field_overrides={}, ip_config=None,
    task_data_payload="vch_zero", task_data_field=VCH_FIELD,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"vch_replay": "1", "replay_links_vch": "1"},
    expected_fields_dupe={},
    notes="Requires 'vch_zero' payload from load-payloads.",
),

"BL-22": ScenarioSpec(
    "BL-22", "VCH fail-first-fifteen (task retry)", "baseline",
    "VCH data where mean response in first 15 trials < 0.5 -> task retry queued.",
    field_overrides={}, ip_config=None,
    task_data_payload="vch_fail_first_fifteen", task_data_field=VCH_FIELD,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"vch_replay": "1", "replay_links_vch": "1"},
    expected_fields_dupe={},
    notes="Requires 'vch_fail_first_fifteen' payload from load-payloads.",
),

"BL-23": ScenarioSpec(
    "BL-23", "PRL worse than chance (<34% correct)", "baseline",
    "PRL data where mean rewardProbChoice==0.85 rate < 34% -> task retry queued.",
    field_overrides={}, ip_config=None,
    task_data_payload="prl_worse_than_chance", task_data_field=PRL_FIELD,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"prl_replay": "1", "replay_links_prl": "1"},
    expected_fields_dupe={},
    notes="Payload 'prl_worse_than_chance' auto-loaded from resources/failed_task_examples.csv.",
),

"BL-24": ScenarioSpec(
    "BL-24", "PRL non-responders (>10% no response)", "baseline",
    "PRL data where >10% of trials have keyChoice==-999 -> task retry queued.",
    field_overrides={}, ip_config=None,
    task_data_payload="prl_non_responders", task_data_field=PRL_FIELD,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"prl_replay": "1", "replay_links_prl": "1"},
    expected_fields_dupe={},
    notes="Payload 'prl_non_responders' auto-loaded from resources/failed_task_examples.csv.",
),

"BL-25": ScenarioSpec(
    "BL-25", "PRL no lose-stay (<1%)", "baseline",
    "PRL data with <1% lose-stay rate -> task retry queued.",
    field_overrides={}, ip_config=None,
    task_data_payload="prl_no_lose_stay", task_data_field=PRL_FIELD,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"prl_replay": "1", "replay_links_prl": "1"},
    expected_fields_dupe={},
    notes="Requires 'prl_no_lose_stay' payload from load-payloads.",
),

"BL-26": ScenarioSpec(
    "BL-26", "Fourth task failure (fourth_fail=1)", "baseline",
    "All 4 ACH replay slots already set + failing ACH data -> fourth_fail=1 instead of new retry.",
    field_overrides={"ach_replay": "1", "ach_replay_2": "1",
                     "ach_replay_3": "1", "ach_replay_4": "1"},
    ip_config=None,
    task_data_payload="ach_zero", task_data_field=ACH_FIELD,
    uses_dupe_record=False, dupe_task_field=None,
    prompts=["User code: m", "Import: yes"],
    expected_fields={"fourth_fail": "1"},
    expected_fields_dupe={},
    notes=(
        "_replay_attempt_number() counts filled replay_fields. With all 4 filled, "
        "next_index=4 >= len(replay_fields)=4 -> fourth_fail set instead of another retry slot. "
        "Uses ach_zero as the failing ACH payload."
    ),
),

}  # end SCENARIOS


# ============================================================================
# SECTION 7: Apply Command
# ============================================================================

def cmd_apply(scenario_id: str) -> None:
    spec = _get_scenario(scenario_id)
    print(f"\nSetting up {scenario_id}: {spec.name}")
    print("=" * 60)

    if spec.field_overrides:
        print(f"Importing {len(spec.field_overrides)} field override(s) to record {TEST_RECORD_ID}...")
        redcap_import_fields(TEST_RECORD_ID, spec.field_overrides)

    # Update ips_full.csv
    if spec.ip_config is None:
        pass  # baseline scenarios don't need IP changes
    elif spec.ip_config == _IP_MISSING:
        _delete_ip_row(TEST_RECORD_ID)
        print(f"Deleted IP row for record {TEST_RECORD_ID} from ips_full.csv.")
    else:
        _update_ip_row(TEST_RECORD_ID, spec.ip_config)
        print(f"Set IP for record {TEST_RECORD_ID}: org={spec.ip_config.get('org')}")

    # Import task payload (non-copy-paste scenarios)
    if spec.task_data_payload and spec.task_data_field and not spec.uses_dupe_record:
        payload = load_payload(spec.task_data_payload)
        print(f"Importing payload '{spec.task_data_payload}' to '{spec.task_data_field}'...")
        redcap_import_fields(TEST_RECORD_ID, {spec.task_data_field: payload})

    # Dupe record setup
    if spec.uses_dupe_record:
        _setup_dupe_record(spec, scenario_id)

    print(f"\nSetup complete. Now run the QC script:")
    print(f"  export AIM8_SHAREDDRIVE_PATH={MOCK_DRIVE_ROOT}")
    print(f"  python3 quickQC_api_calling_v7_relaunch.py")
    print()
    for p in spec.prompts:
        print(f"  > {p}")
    print()
    print(f"Then: python3 qc_testing_debug.py verify {scenario_id}")


def _setup_dupe_record(spec: ScenarioSpec, scenario_id: str) -> None:
    if scenario_id == "SCR-12":
        # Inject a prior record matching the email on record 1
        print(f"Injecting prior record {DUPE_RECORD_ID} with duplicate email...")
        redcap_import_fields(DUPE_RECORD_ID, {
            "email_rpt": "dupe_test@example.com",
            "datedone_screening_survey": "2025-01-01",
            "screening_pass": "",
            "qc_passed": "",
        })
        return

    if scenario_id == "SCR-15":
        # Add a row to ips_full.csv for record 9998 with same IP, and mark it as reviewed
        print(f"Adding prior-reviewed record {DUPE_RECORD_ID} to ips_full.csv with IP=5.5.5.5...")
        _update_ip_row(DUPE_RECORD_ID, {**_IP_BASE, "record_id": DUPE_RECORD_ID, "ip": "5.5.5.5"})
        redcap_import_fields(DUPE_RECORD_ID, {
            "datedone_screening_survey": "2025-01-01",
            "qc_passed": "0",
        })
        return

    # BL-16a/b/c: copy task data from record 1 to record 9998
    if spec.dupe_task_field:
        print(f"Exporting '{spec.dupe_task_field}' from record {TEST_RECORD_ID}...")
        record_data = redcap_export_record(TEST_RECORD_ID)
        task_payload = record_data.get(spec.dupe_task_field)
        if not task_payload:
            print(f"WARNING: '{spec.dupe_task_field}' is empty on record {TEST_RECORD_ID}.")
            print("Ensure record_id=1 has valid task data before running BL-16x scenarios.")
        else:
            print(f"  Got {len(str(task_payload))} chars of task data.")

        dupe_race_qc = record_data.get("race_qc", "1")
        redcap_import_fields(DUPE_RECORD_ID, {
            spec.dupe_task_field: task_payload,
            "screening_pass": "1",
            "race_qc": dupe_race_qc,
            "qc_passed": "",
        })
        print(f"Record {DUPE_RECORD_ID} configured with identical {spec.dupe_task_field}.")
        print(f"Both records {TEST_RECORD_ID} and {DUPE_RECORD_ID} will appear in QC queue.")


# ============================================================================
# SECTION 8: Verify Command
# ============================================================================

def cmd_verify(scenario_id: str) -> None:
    spec = _get_scenario(scenario_id)
    print(f"\nVerifying {scenario_id}: {spec.name}")
    print("=" * 60)

    record = redcap_export_record(TEST_RECORD_ID)
    all_pass = _check_fields(record, spec.expected_fields, TEST_RECORD_ID)

    if spec.uses_dupe_record and spec.expected_fields_dupe:
        try:
            dupe_record = redcap_export_record(DUPE_RECORD_ID)
            dupe_pass = _check_fields(dupe_record, spec.expected_fields_dupe, DUPE_RECORD_ID)
            all_pass = all_pass and dupe_pass
        except RuntimeError as exc:
            print(f"Could not export record {DUPE_RECORD_ID}: {exc}")
            all_pass = False

    print()
    if all_pass:
        print(f"RESULT: PASS — all expected fields verified for {scenario_id}")
    else:
        print(f"RESULT: FAIL — one or more fields did not match for {scenario_id}")
        sys.exit(1)


def _check_fields(record: dict, expected: dict, record_id: int) -> bool:
    all_pass = True
    print(f"\nRecord {record_id}:")
    print(f"  {'Field':<48} {'Expected':<22} {'Actual':<22} Result")
    print(f"  {'-'*48} {'-'*22} {'-'*22} ------")
    for field_name, expected_value in expected.items():
        actual = record.get(field_name)
        actual_str = str(actual) if actual is not None else "(blank)"
        if expected_value is None:
            passed = actual is None or str(actual).strip() == ""
            exp_str = "(blank/null)"
        elif expected_value == "NOT_EMPTY":
            passed = actual is not None and str(actual).strip() != ""
            exp_str = "(not empty)"
        elif isinstance(expected_value, str) and expected_value.startswith("CONTAINS:"):
            needle = expected_value[len("CONTAINS:"):]
            passed = needle.lower() in str(actual or "").lower()
            exp_str = f"(contains '{needle}')"
        else:
            try:
                passed = float(str(actual).strip()) == float(str(expected_value).strip())
            except (ValueError, TypeError):
                passed = str(actual).strip() == str(expected_value).strip()
            exp_str = str(expected_value)
        result = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  {field_name:<48} {exp_str:<22} {actual_str:<22} {result}")
    return all_pass


# ============================================================================
# SECTION 9: List and Show Commands
# ============================================================================

def cmd_list() -> None:
    scr = [(sid, s) for sid, s in SCENARIOS.items() if s.category == "screening"]
    bl = [(sid, s) for sid, s in SCENARIOS.items() if s.category == "baseline"]

    avail = sorted(_load_csv_payloads().keys() | _load_saved_payloads().keys())
    missing_payloads = [
        s.task_data_payload for _, s in SCENARIOS.items()
        if s.task_data_payload and s.task_data_payload not in avail
    ]

    print("\nScreening Scenarios:")
    print(f"  {'ID':<10} {'Name':<48} Expected")
    for sid, s in scr:
        outcome = " | ".join(f"{k}={v}" for k, v in list(s.expected_fields.items())[:2])
        print(f"  {sid:<10} {s.name:<48} {outcome}")

    print("\nBaseline QC Scenarios:")
    print(f"  {'ID':<10} {'Name':<48} Expected")
    for sid, s in bl:
        outcome = " | ".join(f"{k}={v}" for k, v in list(s.expected_fields.items())[:2])
        status = " [needs payload]" if s.task_data_payload and s.task_data_payload not in avail else ""
        print(f"  {sid:<10} {s.name:<48} {outcome}{status}")

    print(f"\nTask payloads available: {avail or '(none)'}")
    if missing_payloads:
        print(f"Missing payloads needed: {sorted(set(missing_payloads))}")
        print("Run: python3 qc_testing_debug.py load-payloads")


def cmd_show(scenario_id: str) -> None:
    spec = _get_scenario(scenario_id)
    print(f"\n{spec.scenario_id}: {spec.name} [{spec.category.upper()}]")
    print(f"Description: {spec.description}")
    print(f"\nField overrides: {spec.field_overrides or '(none)'}")
    if spec.ip_config is not None:
        label = "(delete row)" if spec.ip_config == _IP_MISSING else spec.ip_config.get("org", "")
        print(f"IP config: {label}")
    if spec.task_data_payload:
        print(f"Task payload: '{spec.task_data_payload}' -> field '{spec.task_data_field}'")
    if spec.uses_dupe_record:
        print(f"Uses dupe record {DUPE_RECORD_ID}: yes")
    print(f"\nPrompts for QC script:")
    for p in spec.prompts:
        print(f"  > {p}")
    print(f"\nExpected fields (record {TEST_RECORD_ID}):")
    for k, v in spec.expected_fields.items():
        print(f"  {k} = {v}")
    if spec.expected_fields_dupe:
        print(f"\nExpected fields (record {DUPE_RECORD_ID}):")
        for k, v in spec.expected_fields_dupe.items():
            print(f"  {k} = {v}")
    if spec.notes:
        print(f"\nNotes:\n  {spec.notes}")


def _get_scenario(scenario_id: str) -> ScenarioSpec:
    sid = scenario_id.upper()
    if sid not in SCENARIOS:
        print(f"Unknown scenario '{scenario_id}'. Run 'list' to see available scenarios.")
        sys.exit(1)
    return SCENARIOS[sid]


# ============================================================================
# SECTION 10: CLI Entry Point
# ============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="QC testing helper for quickQC_api_calling_v7_relaunch.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Standard test cycle:
  1. python3 qc_testing_debug.py apply <ID>
  2. export AIM8_SHAREDDRIVE_PATH=./qc_test_drive
  3. python3 quickQC_api_calling_v7_relaunch.py   (enter prompts as shown by apply)
  4. python3 qc_testing_debug.py verify <ID>
  5. python3 qc_testing_debug.py restore

One-time setup:
  python3 qc_testing_debug.py setup
  python3 qc_testing_debug.py snapshot   (after record_id=1 exists in REDCap)

For task failure scenarios (BL-17,19,21,22,25):
  python3 qc_testing_debug.py load-payloads
        """,
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("setup")
    snap_p = sub.add_parser("snapshot")
    snap_p.add_argument("stage", nargs="?", choices=["screening", "baseline"], default=None,
                        help="Stage to snapshot: 'screening' or 'baseline' (omit for legacy single slot)")
    rest_p = sub.add_parser("restore")
    rest_p.add_argument("stage", nargs="?", choices=["screening", "baseline"], default=None,
                        help="Stage to restore: 'screening' or 'baseline' (omit for legacy single slot)")
    sub.add_parser("list")
    sub.add_parser("load-payloads")
    show_p = sub.add_parser("show")
    show_p.add_argument("scenario_id")
    apply_p = sub.add_parser("apply")
    apply_p.add_argument("scenario_id")
    verify_p = sub.add_parser("verify")
    verify_p.add_argument("scenario_id")

    args = parser.parse_args()
    dispatch = {
        "setup": cmd_setup,
        "list": cmd_list,
        "load-payloads": cmd_load_payloads,
    }
    if args.command in dispatch:
        dispatch[args.command]()
    elif args.command == "snapshot":
        cmd_snapshot(getattr(args, "stage", None))
    elif args.command == "restore":
        cmd_restore(getattr(args, "stage", None))
    elif args.command == "show":
        cmd_show(args.scenario_id)
    elif args.command == "apply":
        cmd_apply(args.scenario_id)
    elif args.command == "verify":
        cmd_verify(args.scenario_id)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
