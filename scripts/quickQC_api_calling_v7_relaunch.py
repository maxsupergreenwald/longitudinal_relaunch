#!/usr/bin/env python3
"""Baseline + screening QC tool for the Aim 8 serotonergic psychedelics relaunch project.

PURPOSE
-------
This script handles two distinct review queues that arise during daily data collection:

1. SCREENING FRAUD REVIEW
   New participants complete the screening survey (consent → screening_survey →
   screening_result) and submit via `submit_screen_v3`.  Before we can call them
   eligible and invite them to the baseline session, we need to verify they are real,
   US-based people who are not duplicating a prior attempt.  This script:
     - Checks hard exclusion criteria (age, cognition, seizure history, etc.)
     - Checks for fake-drug endorsement (kaopectamine trap question)
     - Checks for SP/atypical use within 42 days and routes willing-to-wait participants
       to the `eligible_afterwait_notify` path instead of immediate `eligible_notify`
     - Cross-references IP address against a curated blocklist and prior-record history
     - Prompts the researcher to manually verify each phone number / VOIP check
     - Writes screening_pass, eligible_notify (or eligible_afterwait_notify), and
       ineligibile_fraud back to REDCap

2. BASELINE COMPLETION QC
   Participants who have passed screening and completed all baseline instruments
   (surveys + ACH + VCH + PRL tasks) land in a second queue.  This script:
     - Runs task-level QC on ACH, VCH, and PRL data (slope, zero-detection,
       first-15-trial, copy-paste duplicate checks)
     - Checks attention checks, race/age consistency, and trap/fraud questions
       (kaopectamine, fraud_caps, fraud_pdi, fraud_recent_dose)
     - Evaluates SP use responses for internal consistency (illogical counts,
       wrong most-recent type, implausible routes of administration)
     - Routes failed-task records into replay slots (up to 4 per task) rather than
       rejecting them outright
     - Routes suspicious-SP records to a manual verification email flow
       (verify_emailed=1) and re-evaluates them once sp_verify_pass is set
     - Writes qc_passed, qc_notes, replay_links_*, and payment info to REDCap
     - Generates an expense-sheet CSV ready for SharePoint upload

TYPICAL DAILY WORKFLOW
----------------------
Run this from within the scripts/ directory via `run_all_qc_relaunch.py`, which
calls both this script and quickQC_rpt_relaunch.py in one pass.  You can also
run this file directly:

    python3 quickQC_api_calling_v7_relaunch.py

Or import the class in a Jupyter notebook / the testing helper:

    from quickQC_api_calling_v7_relaunch import RelaunchQuickQC
    tool = RelaunchQuickQC("m").load()

METHOD CALL ORDER
-----------------
Screening path:
    tool.load()
    review  = tool.prepare_screening_review()   # builds ScreeningReview
    verdicts = tool.collect_phone_verdicts(review)
    updates  = tool.build_screening_updates(review, verdicts)
    tool.import_screening_updates(updates)      # pushes to REDCap

Baseline completion path:
    completion = tool.run_completion_qc()       # builds CompletionReview
    tool.import_completion_updates(completion)  # pushes to REDCap

KEY CONFIGURATION (top of this file)
--------------------------------------
    RELAUNCH_API_TOKEN      — REDCap API token for the merged Aim 8 project
    IPINFO_TOKEN            — ipinfo.io token for IP geolocation lookups
    SHAREDDRIVE_NETWORK_PATH — mount point for /Volumes/psychedelics/online
    IP_DATABASE_PATH        — ips/ips_full.csv on the shared drive
    FAILED_JSON_PATH        — jsons/failed_task_jsons_baseline.csv
    FORBIDDEN_IP_ORGS/COUNTRIES — automatic hard-fail IP blocklist
    SCREENING_EMAIL_FIELDS  — fields checked for duplicate email addresses
    BASELINE_DATE_FIELDS    — fields used to pick the latest completion date

KEY REDCAP FIELDS WRITTEN BY THIS SCRIPT
-----------------------------------------
Screening:
    screening_pass          — 1 = cleared fraud review; 0 = ineligible
    qc_passed               — 0 = hard fail; blank = not yet reviewed
    eligible_notify         — 1 = triggers immediate baseline invitation alert
    eligible_afterwait_notify — 1 = triggers invitation alert at continue_date
                               (for participants who used SP within last 42 days
                                but are willing to wait)
    ineligibile_fraud       — 1 = flagged as fraudulent
    ip_zoom_invite          — 1 = suspicious IP, needs Zoom verification
    max_number_followup     — 1 = needs manual follow-up by Max
    qc_notes                — free-text reason for ineligibility
    ineligibilty_reason     — free-text reason (separate legacy field)

Baseline completion:
    qc_passed               — 1 = passed; 0 = failed
    qc_notes                — failure or verification reason
    verify_emailed          — 1 = sent SP verification survey
    inconsistent_sp_answers — 1 = flagged for inconsistent SP responses
    fraudulent_email        — 1 = copy-paste fraud detected
    fraudulent_email_inconsistentanswers — 1 = absurd SP responses
    replay_links_ach/vch/prl     — 1 = triggers replay invitation alert (slot 1)
    replay_links_ach_2/3/4  — slots 2–4 for subsequent replay attempts
    fourth_fail             — 1 = all 4 replay slots exhausted
    send_pay_confirm        — 1 = triggers payment confirmation alert
    employee_name           — staff member who ran QC
    pay_day_ofweek          — day of week (1=Mon…7=Sun) payment was queued
"""

from __future__ import annotations

import base64
import csv
import gzip
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from redcap import Project


# ============================================================================
# SECTION 1: Project Configuration
# ============================================================================

USER_NAMES = {
    "m": "Maximillian S. Greenwald",
    "kayla": "Kayla Morgan",
    "gabby": "Gabriela Hernandez",
}

REDCAP_API_URL = os.getenv("AIM8_REDCAP_API_URL", "https://redcap.research.yale.edu/api/")
RELAUNCH_API_TOKEN = "64C5D967CBEB77335224862283A74F4D"
IPINFO_TOKEN = os.getenv("AIM8_IPINFO_TOKEN", "20f981656f0139")
SHAREPOINT_PAYMENT_UPLOAD_URL = os.getenv(
    "AIM8_SHAREPOINT_PAYMENT_URL",
    "https://yaleedu-my.sharepoint.com/:x:/r/personal/silmilly_toribio_yale_edu/_layouts/15/Doc.aspx"
    "?sourcedoc=%7B989CA093-98FB-412F-A0BA-F99D26B72AAF%7D&file=Participant%20Payment%20Request%20Psychedelics%20MSG.xlsx"
    "&action=default&mobileredirect=true&DefaultItemOpen=1",
)

SHAREDDRIVE_NETWORK_PATH = Path(os.getenv("AIM8_SHAREDDRIVE_PATH", "/Volumes/psychedelics/online"))
IP_DATABASE_PATH = SHAREDDRIVE_NETWORK_PATH / "ips" / "ips_full.csv"
FAILED_JSON_PATH = SHAREDDRIVE_NETWORK_PATH / "jsons" / "failed_task_jsons_baseline.csv"
QC_TODO_PATH = SHAREDDRIVE_NETWORK_PATH / "qc_to_dos"

TEST_RECORDS = {
    "BlueLightTesting_1",
    "r/Drugs Testing",
    "TESTING",
    "TESTING2",
    "TESTING3",
    "TESTING4",
    "TESTING5",
    "TESTING6",
    "test_rec_w_realdata_ithink",
    "testing_before_newqc",
    "testing_max_prerelaunch",
    "testing_pre_yale_relaunch",
}

FORBIDDEN_IP_ORGS = {
    "AS14061 DigitalOcean, LLC",
    "AS396356 Latitude.sh",
    "AS5650 Frontier Communications of America, Inc.",
    "AS25769 Garden Valley Telephone Company",
    "AS21859 Zenlayer Inc",
    "AS22200 Bloomingdale Communications Inc.",
    "AS8167 V tal",
    "AS11878 tzulo, inc.",
    "AS393398 1515 ROUNDTABLE DR PROPERTY, LLC",
    "AS396956 Meriwether Lewis Electric Cooperative",
    "AS9009 M247 Europe SRL",
    "AS16276 OVH SAS",
    "AS136787 PacketHub S.A.",
    "AS62240 Clouvider",
    "AS60068 Datacamp Limited",
    "AS6079 RCN",
    "AS13285 TalkTalk Communications Limited",
    "AS6461 Zayo Bandwidth",
    "AS174 Cogent Communications",
    "AS212238 Datacamp Limited",
    "AS6300 Consolidated Communications, Inc.",
}

FORBIDDEN_IP_COUNTRIES = {"Nigeria", "Ghana"}
SAFE_DUPLICATE_IP_ORGS = {"AS14550 Middlebury College", "AS29 Yale University"}

SCREENING_EMAIL_FIELDS = [
    "email_rpt",
    "email_rpt_2",
    "email_addtl_contact",
    "interested_spstudy",
]

BASELINE_DATE_FIELDS = [
    "datedone_consent_baseline",
    "datedone_screening_survey",
    "datedone_sms_verification",
    "datedone_screening_result",
    "datedone_eligibile",
    "datedone_survey_perception_substance_use",
    "datedone_family_history_and_asi",
    "datedone_visual_ch_task",
    "datedone_prl_task",
    "datedone_auditory_ch_task",
    "datedone_spacejunk_game",
    "datedone_validity_checks",
    "datedone_clarification_survey",
    "datedone_answer_checks",
]


# ============================================================================
# SECTION 2: Data Containers
# ============================================================================


@dataclass
class ScreeningReview:
    """All data and categorised record lists produced by prepare_screening_review().

    After prepare_screening_review() runs, every record in records_to_screen will
    appear in exactly one of: hard_fail, phone_review, or sp_wait.
    Records may additionally appear in suspicious_ip or manual_followup.

    Attributes
    ----------
    records_to_screen   : record IDs pulled from the screening queue (submit_screen_v3
                          filled, screening_pass blank, qc_passed blank).
    screen_df           : REDCap data subset for just these records.
    ip_df               : IP-address metadata from ips_full.csv, one row per record.
    hard_fail           : Records that failed an automatic rule (age, cognition, fake
                          drug, forbidden IP, duplicate email, etc.).  Will receive
                          screening_pass=0 and ineligibile_fraud=1.
    suspicious_ip       : Records whose IP matches a previously-reviewed / ineligible
                          record.  Will receive ip_zoom_invite=1 for Zoom verification.
    phone_review        : Records that passed all automatic checks and need a human
                          to look up the phone number for VOIP detection.
    manual_followup     : Records that could not be auto-resolved (e.g. missing IP).
                          Will receive max_number_followup=1.
    sp_wait             : Records that used SP/atypical psychedelics within 42 days but
                          answered psychedelic_abstinence_yn='1' (willing to wait).
                          These go through the normal phone review; if cleared they get
                          screening_pass=1 and eligible_afterwait_notify=1 (not
                          eligible_notify), deferring the invitation to continue_date.
    ineligibility_notes : {record_id: reason string} for every record with a failure
                          reason.  Written to qc_notes on hard-fail records.
    """

    records_to_screen: list[int]
    screen_df: pd.DataFrame
    ip_df: pd.DataFrame
    hard_fail: list[int] = field(default_factory=list)
    suspicious_ip: list[int] = field(default_factory=list)
    phone_review: list[int] = field(default_factory=list)
    manual_followup: list[int] = field(default_factory=list)
    sp_wait: list[int] = field(default_factory=list)
    ineligibility_notes: dict[int, str] = field(default_factory=dict)


@dataclass
class CompletionReview:
    """All data and results produced by run_completion_qc().

    Attributes
    ----------
    records_to_check        : Record IDs that were reviewed in this run.
    update_df               : DataFrame of REDCap field updates ready to import.
                              One row per record; columns are the fields to write.
    update_fields           : Column names in update_df (excluding record_id).
    expensesheet_path       : Path to the generated expense-sheet CSV, or None if no
                              records passed QC and needed payment.
    failed_json_append_count: Number of failed-task JSON rows appended to
                              FAILED_JSON_PATH on the shared drive.
    qc_lists                : Dict of named lists identifying which records triggered
                              each QC flag (e.g. 'zero', 'negative', 'failed_sp_qc').
                              Printed to the completion summary markdown.
    """

    records_to_check: list[int]
    update_df: pd.DataFrame
    update_fields: list[str]
    expensesheet_path: Path | None
    failed_json_append_count: int
    qc_lists: dict[str, list[int]]


# ============================================================================
# SECTION 3: Small Utility Helpers
# ============================================================================


def ask_yes_no(prompt: str) -> bool:
    """Prompt the researcher with a yes/no question; return True only if they type 'yes'."""
    return input(prompt).strip().lower() == "yes"


def clean_email(value: Any) -> str | None:
    """Normalise an email value from a REDCap cell to a lowercase string, or None if blank."""
    if pd.isna(value):
        return None
    email = str(value).strip().lower()
    return email or None


def numeric_value(row: pd.Series, field: str) -> float:
    """Safely read a numeric field from a DataFrame row.

    Returns np.nan if the field is absent, NaN, or cannot be cast to float.
    This prevents KeyErrors and type errors when a REDCap field may not be
    present in the export (e.g. if it was added after an older export was cached).
    """
    if field not in row.index:
        return np.nan
    value = row[field]
    if pd.isna(value):
        return np.nan
    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def string_value(row: pd.Series, field: str) -> str:
    """Safely read a string field from a DataFrame row.

    Returns an empty string if the field is absent or NaN, so callers can do
    simple equality checks (e.g. string_value(row, 'x') == '1') without
    special-casing missing data.
    """
    if field not in row.index or pd.isna(row[field]):
        return ""
    return str(row[field]).strip()


def add_reason(reason_map: dict[int, str], record_id: int, reason: str) -> None:
    """Append a human-readable ineligibility reason to the running notes for a record.

    Reasons are semicolon-separated so that a record with multiple failures has a
    single, legible string written to qc_notes.
    """
    existing = reason_map.get(record_id, "")
    combined = f"{existing}; {reason}" if existing else reason
    reason_map[record_id] = combined


def field_exists(df: pd.DataFrame, field: str) -> bool:
    """Return True if `field` is a column in `df`.

    Used as a lightweight guard before writing to optional REDCap fields that may
    not be present in older project exports.
    """
    return field in df.columns


def to_int_list(values: list[Any]) -> list[int]:
    """Convert a list of possibly-NaN / mixed-type values to a clean list of ints.

    NaN values and anything that can't be cast to int are silently dropped.
    Used throughout to sanitise record_id columns from pandas Series.
    """
    cleaned: list[int] = []
    for value in values:
        if pd.isna(value):
            continue
        try:
            cleaned.append(int(value))
        except (TypeError, ValueError):
            continue
    return cleaned


def nonempty_task_value(row: pd.Series, primary_field: str, backup_field: str | None = None) -> bool:
    """Return True if a task payload field contains a non-empty string.

    Checks primary_field first; falls back to backup_field (the manually-retrieved
    JSON field, e.g. task_data_ach_bl_retrieved) if the primary is empty.
    Used to test whether a task record has usable data before running QC.
    """
    if primary_field in row.index and isinstance(row[primary_field], str) and row[primary_field].strip():
        return True
    if backup_field and backup_field in row.index and isinstance(row[backup_field], str) and row[backup_field].strip():
        return True
    return False


def latest_completion_date(row: pd.Series, date_fields: list[str]) -> str:
    """Return the most recent non-empty date among a list of REDCap date fields.

    Used to find the 'Date of Participation' for the expense sheet — we pick the
    latest instrument completion date rather than a single hard-coded field.
    Returns today's date (MM/DD/YYYY) if no valid date is found.
    """
    parsed_dates: list[datetime] = []
    for field in date_fields:
        value = string_value(row, field)
        if not value:
            continue
        try:
            parsed_dates.append(datetime.strptime(value, "%Y-%m-%d"))
        except ValueError:
            continue
    if not parsed_dates:
        return datetime.now().strftime("%m/%d/%Y")
    parsed_dates.sort(reverse=True)
    return parsed_dates[0].strftime("%m/%d/%Y")


def parse_redcap_pdf_log(log_string: str) -> pd.DataFrame:
    """Parse the REDCap PDF archive log text into a DataFrame of (record_id, ip) pairs.

    The researcher pastes rows from the REDCap Logging page (PDF archive view).
    Each row contains a record ID and the IP address used to submit the e-Consent.
    Returns a DataFrame with columns ['record_id', 'ip'].
    Raises ValueError if record/IP counts don't align (malformed paste).
    """
    record_matches = re.findall(r"(\d+)\s*\t(?:Consent|e-Consent)", log_string)
    ip_matches = re.findall(
        r"\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}(?::\d{2})?\s+(\d{1,3}(?:\.\d{1,3}){3})\s*\t1\t\s*e-Consent",
        log_string,
    )

    if not record_matches or not ip_matches or len(record_matches) != len(ip_matches):
        raise ValueError(
            f"Could not align record IDs and IPs in pasted REDCap log "
            f"(records={len(record_matches)}, ips={len(ip_matches)})."
        )

    pairs = [{"record_id": int(record_id), "ip": ip} for record_id, ip in zip(record_matches, ip_matches)]
    return pd.DataFrame(pairs)


def decode_compressed_json(compressed_string: str) -> dict[str, Any]:
    """Decompress and parse a gzip+base64 encoded JSON string.

    The ACH, VCH, and PRL task payloads are stored in REDCap as base64-encoded
    gzip-compressed JSON strings to fit within REDCap's field size limits.
    This function reverses that encoding to get back the raw task data dict.
    """
    decoded = base64.b64decode(compressed_string)
    decompressed = gzip.decompress(decoded).decode("utf-8")
    return json.loads(decompressed)


def ensure_directory(path: Path) -> None:
    """Create a directory (and any missing parents) if it does not already exist."""
    path.mkdir(parents=True, exist_ok=True)


# ============================================================================
# SECTION 4: Task QC Configuration
# ============================================================================


@dataclass
class TaskConfig:
    """Static configuration for one of the three baseline tasks (ACH, VCH, PRL).

    One instance of this class lives in TASK_CONFIGS for each task.  The QC engine
    reads these to know which REDCap fields to inspect, reset, and write back.

    Attributes
    ----------
    task_col            : Primary REDCap field that holds the compressed task payload
                          (e.g. 'task_data_ach_task_short_baseline').
    backup_col          : Fallback field holding a manually-retrieved JSON string if the
                          primary field is empty (e.g. 'task_data_ach_bl_retrieved').
    qualifying_cols     : Fields that get stamped with an HTML 'Incomplete' message when
                          a task fails, prompting the participant to redo the task.
    replay_fields       : REDCap yesno fields that track how many replay attempts have
                          been issued ('ach_replay', 'ach_replay_2', …, 'ach_replay_4').
                          The first unfilled slot is set to 1 on each failure.
    template_fields     : Parallel list of fields that trigger the replay invitation
                          alert for each slot ('replay_links_ach', 'replay_links_ach_2',
                          …).  Set to 1 alongside the matching replay_field.
    failure_conditions  : Names of qc_lists keys (from _evaluate_ch_task /
                          _evaluate_prl) that count as a failure requiring replay.
    reset_cols          : Fields to clear (set to NaN) when queuing a replay, so the
                          participant can re-do the headphone/browser checks and submit
                          a fresh payload.
    """

    task_col: str
    backup_col: str
    qualifying_cols: list[str]
    replay_fields: list[str]
    template_fields: list[str]
    failure_conditions: list[str]
    reset_cols: list[str]


TASK_CONFIGS = {
    "auditory_ch_task": TaskConfig(
        task_col="task_data_ach_task_short_baseline",
        backup_col="task_data_ach_bl_retrieved",
        qualifying_cols=[
            "task_data_ach_task_short_baseline_complete",
            "task_data_auditory_qualifying_task_2",
            "task_data_visual_qualifying_task_2",
        ],
        replay_fields=["ach_replay", "ach_replay_2", "ach_replay_3", "ach_replay_4"],
        template_fields=["replay_links_ach", "replay_links_ach_2", "replay_links_ach_3", "replay_links_ach_4"],
        failure_conditions=["zero", "negative", "fail_first_fifteen"],
        reset_cols=[
            "headphones_recheck_ah",
            "headphones_type_ah",
            "monitor_recheck_ah",
            "monitor_type_ah",
            "browser_ach",
            "ach_vol_adj_yn",
            "ach_vol_adj_amnt",
            "task_nosave_yn_ach_bl",
            "task_nosave_opt_ach_bl",
            "task_nosave_ach_bl",
            "task_data_ach_bl_retrieved",
            "confirm_ach_tasks",
        ],
    ),
    "visual_ch_task": TaskConfig(
        task_col="task_data_vch_short_psychedelic_bl",
        backup_col="task_data_vch_bl_retrieved",
        qualifying_cols=[
            "task_data_auditory_qualifying",
            "task_data_visual_qualifying",
            "task_data_vch_short_psychedelic_bl_complete",
        ],
        replay_fields=["vch_replay", "vch_replay_2", "vch_replay_3", "vch_replay_4"],
        template_fields=["replay_links_vch", "replay_links_vch_2", "replay_links_vch_3", "replay_links_vch_4"],
        failure_conditions=["zero_vch", "negative_vch", "fail_first_fifteen_vch"],
        reset_cols=[
            "headphones_check",
            "monitor_check",
            "browser_vch",
            "private_place_vch",
            "task_nosave_yn_vch_bl",
            "task_nosave_opt_vch_bl",
            "task_nosave_vch_bl",
            "task_data_vch_bl_retrieved",
            "confirm_vch_tasks",
        ],
    ),
    "prl_task": TaskConfig(
        task_col="task_data_prltask",
        backup_col="task_data_prl_bl_retrieved",
        qualifying_cols=["task_data_prltask_complete"],
        replay_fields=["prl_replay", "prl_replay_2", "prl_replay_3", "prl_replay_4"],
        template_fields=["replay_links_prl", "replay_links_prl_2", "replay_links_prl_3", "replay_links_prl_4"],
        failure_conditions=["no_lose_stay", "non_responders", "worse_than_chance"],
        reset_cols=[
            "browser_prl",
            "full_screen",
            "task_nosave_yn_prlbl",
            "task_nosave_opt_prlbl",
            "task_nosave_prlbl",
            "task_data_prl_bl_retrieved",
            "confirm_prl_complete",
        ],
    ),
}


# ============================================================================
# SECTION 5: Main Tool Class
# ============================================================================


class RelaunchQuickQC:
    """Main QC engine for the Aim 8 baseline and screening review workflow.

    Instantiate with the researcher's user code, call load() to pull data from
    REDCap, then run the screening and/or completion review.  See module docstring
    for the full call sequence.

    Instance attributes set by load():
        project         — PyCap Project object (authenticated REDCap connection)
        df              — Full REDCap export as a cleaned DataFrame
        df_og           — Copy of df at load time, used as a clean base for updates
        metadata        — REDCap metadata (field labels, types) — currently unused
        records_to_screen — IDs in the screening fraud queue
        records_to_check  — IDs in the baseline completion queue
        date_directory  — Path to today's QC_TODO_PATH/YYYY-MM-DD subfolder
    """

    def __init__(self, user_code: str):
        user_key = user_code.strip().lower()
        if user_key not in USER_NAMES:
            allowed = ", ".join(USER_NAMES)
            raise ValueError(f"Unrecognized user '{user_code}'. Allowed values: {allowed}")

        self.user_code = user_key
        self.user_name = USER_NAMES[user_key]
        self.project: Project | None = None
        self.df: pd.DataFrame | None = None
        self.df_og: pd.DataFrame | None = None
        self.metadata: pd.DataFrame | None = None
        self.records_to_screen: list[int] = []
        self.records_to_check: list[int] = []
        self.date_directory = QC_TODO_PATH / datetime.now().strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # SECTION 5A: Project loading and queue detection
    # ------------------------------------------------------------------

    def load(self) -> "RelaunchQuickQC":
        """Pull data from REDCap, populate both review queues, and return self.

        Steps:
        1. Abort if the shared drive has any unresolved INCOMPLETE flag files from
           a prior QC session (prevents concurrent / double-processing).
        2. Export all records from REDCap and clean the DataFrame.
        3. Identify which records need screening review vs. baseline completion review.

        Must be called before any other method.  Returns self for chaining:
            tool = RelaunchQuickQC("m").load()
        """
        self._check_incomplete_flags(QC_TODO_PATH)
        ensure_directory(self.date_directory)

        self.project = Project(REDCAP_API_URL, RELAUNCH_API_TOKEN)
        raw_df = self.project.export_records(format_type="df").reset_index(names="record_id")
        self.metadata = self.project.export_metadata(format_type="df")
        self.df = self._clean_export(raw_df)
        self.df_og = self.df.copy()

        self.records_to_screen = self._identify_screening_records()
        self.records_to_check = self._identify_completed_baseline_records()
        return self

    def print_dashboard(self) -> None:
        """Print a one-line summary of how many records are in each queue."""
        print(f"Loaded Aim 8 relaunch QC as {self.user_name}")
        print(f"Screening records waiting for fraud review: {len(self.records_to_screen)}")
        print(f"Completed baseline records waiting for QC/payment: {len(self.records_to_check)}")
        if not self.records_to_screen and not self.records_to_check:
            print("Nothing to do today.")

    def _clean_export(self, raw_df: pd.DataFrame) -> pd.DataFrame:
        """Standardise the raw REDCap export before any QC logic runs.

        - Drops string-based test records (BlueLightTesting_1, TESTING, etc.)
        - Coerces record_id to integer and drops non-numeric rows
        - Drops two specific legacy records hard-coded to exclude (IDs 456 and 654)
        """
        df = raw_df.copy()

        if df["record_id"].dtype == object:
            test_mask = df["record_id"].isin(TEST_RECORDS)
            df = df.loc[~test_mask].copy()

        df["record_id"] = pd.to_numeric(df["record_id"], errors="coerce")
        df = df.loc[df["record_id"].notna()].copy()
        df["record_id"] = df["record_id"].astype(int)

        # Old hard-coded exclusions carried over from the notebook reference.
        df = df.loc[~df["record_id"].isin({456, 654})].copy()

        return df.reset_index(drop=True)

    def _identify_screening_records(self) -> list[int]:
        """Return record IDs that are ready for the screening fraud review queue.

        A record enters the screening queue when ALL of the following are true:
          - submit_screen_v3 is filled (participant submitted the screening survey)
          - screening_pass is blank (not yet reviewed)
          - qc_passed is blank (not previously hard-failed at baseline)
          - phone_number is filled (we have a number to look up)
          - ip_zoom_invite is blank (not already flagged for Zoom verification)
        """
        assert self.df is not None
        df = self.df

        needed = (
            df["submit_screen_v3"].notna()
            & df["screening_pass"].isna()
            & df["qc_passed"].isna()
            & df["phone_number"].notna()
        )

        if field_exists(df, "ip_zoom_invite"):
            needed &= df["ip_zoom_invite"].isna()

        return to_int_list(df.loc[needed, "record_id"].tolist())

    def _identify_completed_baseline_records(self) -> list[int]:
        """Return record IDs that are ready for baseline completion QC and payment.

        A record enters this queue when ALL of the following are true:
          - qc_passed is blank (not yet reviewed or hard-failed)
          - screening_pass > 0 (cleared the fraud review)
          - race_qc is filled (the second-pass demographics survey is done)
          - ACH, VCH, and PRL task fields are non-empty (tasks were submitted)
          - NOT currently waiting for SP verification
            (verify_emailed=1 AND sp_verify_pass blank means we're waiting on the
             participant to fill out the clarification survey; we skip them until
             sp_verify_pass is set by the researcher)
        """
        assert self.df is not None
        df = self.df.copy()

        ready_mask = (
            df["qc_passed"].isna()
            & (pd.to_numeric(df["screening_pass"], errors="coerce") > 0)
            & df["race_qc"].notna()
            & nonempty_task_series(df, "task_data_ach_task_short_baseline", "task_data_ach_bl_retrieved")
            & nonempty_task_series(df, "task_data_vch_short_psychedelic_bl", "task_data_vch_bl_retrieved")
            & nonempty_task_series(df, "task_data_prltask", "task_data_prl_bl_retrieved")
        )

        if field_exists(df, "verify_emailed") and field_exists(df, "sp_tot_verify"):
            pending_verify = (pd.to_numeric(df["verify_emailed"], errors="coerce") == 1) & df["sp_tot_verify"].isna()
            ready_mask &= ~pending_verify

        if field_exists(df, "verify_emailed") and field_exists(df, "sp_verify_pass"):
            pending_max_review = (pd.to_numeric(df["verify_emailed"], errors="coerce") == 1) & df["sp_verify_pass"].isna()
            ready_mask &= ~pending_max_review

        return to_int_list(df.loc[ready_mask, "record_id"].tolist())

    def _check_incomplete_flags(self, base_path: Path) -> None:
        """Block the QC run if there are unresolved INCOMPLETE flags from a prior session.

        After each QC run, flag files are written to QC_TODO_PATH/YYYY-MM-DD/ to track
        whether expense sheets have been uploaded and whether manual tasks (replay emails,
        fraud follow-ups) have been completed.  If a previous session left behind an
        INCOMPLETE flag, we must not run a new QC pass until that session is resolved —
        otherwise we risk double-paying or missing a manual step.
        Raises RuntimeError listing the unresolved flags and who left them.
        """
        if not base_path.exists():
            raise RuntimeError(
                "The shared drive QC folder was not found. Mount "
                "`/Volumes/psychedelics/online` before running this tool."
            )

        date_dirs = sorted([path for path in base_path.iterdir() if path.is_dir() and path.name.startswith("2")], reverse=True)
        if not date_dirs:
            return

        latest_dir = date_dirs[0]
        incomplete_flags = sorted([path for path in latest_dir.iterdir() if "INCOMPLETE" in path.name])
        if not incomplete_flags:
            return

        messages = []
        for flag_path in incomplete_flags:
            try:
                owner = flag_path.read_text().strip()
            except OSError:
                owner = "unknown user"
            messages.append(f"{flag_path.name} (left by {owner})")

        joined = "\n".join(messages)
        raise RuntimeError(
            f"Unresolved QC flags were found in {latest_dir}.\n"
            f"Resolve them before running a new QC pass:\n{joined}"
        )

    # ------------------------------------------------------------------
    # SECTION 5B: Screening fraud review
    # ------------------------------------------------------------------

    def prepare_screening_review(self) -> ScreeningReview:
        """Build a ScreeningReview for all records currently in the screening queue.

        Loads the IP database, then runs two passes over the screening records:
          1. _apply_screening_eligibility_rules — checks hard exclusion criteria and the
             SP/atypical washout period; populates hard_fail and sp_wait.
          2. _apply_duplicate_identity_checks — cross-references IPs and emails against
             historical records; populates hard_fail, suspicious_ip, and manual_followup.

        All remaining records (not in hard_fail) are added to phone_review.
        Writes a markdown summary to today's date directory and returns the review object.
        """
        assert self.df is not None
        records = self.records_to_screen
        if not records:
            return ScreeningReview(records_to_screen=[], screen_df=self.df.iloc[0:0].copy(), ip_df=pd.DataFrame())

        ip_df = self._load_and_update_ip_database(records)
        screen_df = self.df.loc[self.df["record_id"].isin(records)].copy().reset_index(drop=True)

        review = ScreeningReview(
            records_to_screen=records,
            screen_df=screen_df,
            ip_df=ip_df,
        )

        self._apply_screening_eligibility_rules(review)
        self._apply_duplicate_identity_checks(review)

        for record_id in records:
            if record_id in review.hard_fail:
                continue
            review.phone_review.append(record_id)

        review.phone_review = sorted(set(review.phone_review))
        review.hard_fail = sorted(set(review.hard_fail))
        review.suspicious_ip = sorted(set(review.suspicious_ip))
        review.manual_followup = sorted(set(review.manual_followup))
        review.sp_wait = sorted(set(review.sp_wait))

        self._write_screening_summary(review)
        return review

    def collect_phone_verdicts(self, review: ScreeningReview) -> dict[int, str]:
        """Interactively prompt the researcher to judge each phone number in the review.

        For each record in review.phone_review, prints the phone number, IP address,
        and the participant's full screen_motive answer so the reviewer can read it
        while checking the phone number.  If the screen_motive text triggers any of
        the AI-generation heuristics (_screen_motive_fraud_reason), a bold red
        ALL-CAPS warning is printed along with a link to NoGPT for paste-in detection.

        Asks the researcher to enter one of:
          'y' — fraudulent or VOIP (will hard-fail the record)
          'n' — looks legitimate (will pass the record through)
          '?' — uncertain, needs Max to review (will set max_number_followup=1)

        Returns a dict of {record_id: verdict} for all reviewed records.
        Records in hard_fail are skipped — they already have a verdict.
        """
        assert self.df is not None

        verdicts: dict[int, str] = {}
        if not review.phone_review:
            return verdicts

        print("\nPhone / VOIP review needed for the following records:")
        print(review.phone_review)

        for record_id in review.phone_review:
            row = self.df.loc[self.df["record_id"] == record_id].reset_index(drop=True).iloc[0]
            phone = string_value(row, "phone_number")
            ip_series = review.ip_df.loc[review.ip_df["record_id"] == record_id, "ip"]
            ip_text = ip_series.iloc[0] if not ip_series.empty else "IP not found"

            motive_text = string_value(row, "screen_motive").strip()
            motive_display = motive_text if motive_text else "(no response)"
            motive_flag = self._screen_motive_fraud_reason(motive_text)

            print(f"\nRecord {record_id}")
            print(f"  Phone:      {phone}")
            print(f"  IP:         {ip_text}")
            print(f"  Motivation: {motive_display}")

            if motive_flag:
                print(f"\033[1;31m  *** AI FLAG: {motive_flag.upper()} ***\033[0m")
                print(f"\033[1;31m  *** CHECK FOR AI-GENERATED TEXT: https://www.nogpt.com ***\033[0m")

            while True:
                verdict = input("  Enter 'y' if fraudulent/VOIP, 'n' if clear, '?' if Max should review: ").strip().lower()
                if verdict in {"y", "n", "?"}:
                    verdicts[record_id] = verdict
                    break
                print("  Please enter only 'y', 'n', or '?'.")

        return verdicts

    def build_screening_updates(self, review: ScreeningReview, phone_verdicts: dict[int, str]) -> pd.DataFrame:
        """Translate the ScreeningReview and phone verdicts into a REDCap update DataFrame.

        Routing logic:
          hard_fail / phone verdict 'y' → screening_pass=0, qc_passed=0,
                                          ineligibile_fraud=1, qc_notes=reason
          sp_wait + phone verdict 'n'   → screening_pass=1,
                                          eligible_afterwait_notify=1
                                          (invitation scheduled at continue_date)
          normal pass (phone verdict 'n', not sp_wait) → screening_pass=1,
                                          eligible_notify=1
                                          (invitation sent immediately)
          suspicious_ip                 → ip_zoom_invite=1 (Zoom call required)
          phone verdict '?' or no IP    → max_number_followup=1

        Returns a filtered DataFrame containing only the fields that exist in the
        REDCap export, ready to pass to import_screening_updates().
        """
        assert self.df is not None

        updates = self.df.loc[self.df["record_id"].isin(review.records_to_screen)].copy()
        if updates.empty:
            return updates

        pass_go = [record_id for record_id, verdict in phone_verdicts.items() if verdict == "n"]
        hard_fail = set(review.hard_fail)
        # Merge phone-verdict 'y' into ineligibility_notes before updating hard_fail
        for record_id, verdict in phone_verdicts.items():
            if verdict == "y":
                if record_id not in review.ineligibility_notes:
                    add_reason(review.ineligibility_notes, record_id, "Flagged as fraudulent/VOIP by phone review")
                hard_fail.add(record_id)
        manual_followup = set(review.manual_followup)
        manual_followup.update(record_id for record_id, verdict in phone_verdicts.items() if verdict == "?")

        # sp_wait records that fail phone/IP review fall back to the normal fraud path.
        sp_wait_set = set(review.sp_wait)
        sp_wait_cleared = [rid for rid in pass_go if rid in sp_wait_set]
        normal_pass = [rid for rid in pass_go if rid not in sp_wait_set]

        updates.loc[updates["record_id"].isin(hard_fail), ["screening_pass", "qc_passed"]] = 0
        if "ineligibile_fraud" in updates.columns:
            updates.loc[updates["record_id"].isin(hard_fail), "ineligibile_fraud"] = 1

        # Normal pass: immediately eligible, send eligible_notify.
        updates.loc[updates["record_id"].isin(normal_pass), "screening_pass"] = 1
        if "eligible_notify" in updates.columns:
            updates.loc[updates["record_id"].isin(normal_pass), "eligible_notify"] = 1

        # SP-wait pass: passed phone/IP check but must wait out the washout period.
        # screening_pass=1 so they leave the screening queue; eligible_afterwait_notify
        # triggers the continue_date-scheduled email instead of the immediate eligible_notify.
        updates.loc[updates["record_id"].isin(sp_wait_cleared), "screening_pass"] = 1
        if "eligible_afterwait_notify" in updates.columns:
            updates.loc[updates["record_id"].isin(sp_wait_cleared), "eligible_afterwait_notify"] = 1

        if "ip_zoom_invite" in updates.columns:
            updates.loc[updates["record_id"].isin(review.suspicious_ip), "ip_zoom_invite"] = 1
        if "max_number_followup" in updates.columns:
            updates.loc[updates["record_id"].isin(manual_followup), "max_number_followup"] = 1

        if "ineligibilty_reason" in updates.columns:
            for record_id, reason in review.ineligibility_notes.items():
                updates.loc[updates["record_id"] == record_id, "ineligibilty_reason"] = reason

        # Write rejection reason into qc_notes for all hard-fail records
        if "qc_notes" in updates.columns:
            for record_id, reason in review.ineligibility_notes.items():
                if record_id in hard_fail:
                    updates.loc[updates["record_id"] == record_id, "qc_notes"] = reason

        desired_fields = [
            "screening_pass",
            "qc_passed",
            "qc_notes",
            "eligible_notify",
            "eligible_afterwait_notify",
            "ineligibile_fraud",
            "ip_zoom_invite",
            "max_number_followup",
            "ineligibilty_reason",
            "record_id",
        ]
        desired_fields = [field for field in desired_fields if field in updates.columns]
        updates = updates[desired_fields].copy()

        for field in ["screening_pass", "qc_passed", "eligible_notify", "eligible_afterwait_notify", "ineligibile_fraud", "ip_zoom_invite", "max_number_followup"]:
            if field in updates.columns:
                updates[field] = pd.to_numeric(updates[field], errors="coerce").astype("Int64")

        return updates

    def import_screening_updates(self, updates: pd.DataFrame) -> None:
        """Push the screening update DataFrame to REDCap and mark the flag as complete.

        Imports the update DataFrame produced by build_screening_updates().
        After a successful import, converts the REDCAP_SCREENS_INCOMPLETE flag file to
        REDCAP_SCREENS_COMPLETE so the shared-drive flag system reflects completion.
        """
        assert self.project is not None
        if updates.empty:
            print("No screening updates to import.")
            return
        self.project.import_records(to_import=updates, import_format="df")
        self._update_redcap_flag("REDCAP_SCREENS_INCOMPLETE")
        print(f"Imported screening updates for {len(updates)} records.")

    def _load_and_update_ip_database(self, records_to_screen: list[int]) -> pd.DataFrame:
        """Load ips_full.csv from the shared drive; fetch metadata for any new records.

        For each record that is not yet in the IP database, prompts the researcher to
        paste the REDCap PDF archive rows containing the IP address, then queries
        ipinfo.io for geolocation and ISP metadata and appends to the CSV.
        Returns the full (updated) ip_df with all screening records present.
        Raises RuntimeError if the shared drive is not mounted.
        """
        if not IP_DATABASE_PATH.exists():
            raise RuntimeError(f"IP database was not found at {IP_DATABASE_PATH}")

        ip_df = pd.read_csv(IP_DATABASE_PATH)
        if "record_id" not in ip_df.columns:
            raise RuntimeError(f"`{IP_DATABASE_PATH}` is missing a `record_id` column.")
        ip_df = ip_df.drop(columns=[col for col in ip_df.columns if "dumb" in col], errors="ignore")
        ip_df["record_id"] = pd.to_numeric(ip_df["record_id"], errors="coerce").astype("Int64")
        ip_df = ip_df.loc[ip_df["record_id"].notna()].copy()
        ip_df["record_id"] = ip_df["record_id"].astype(int)

        missing_records = [record_id for record_id in records_to_screen if record_id not in ip_df["record_id"].tolist()]
        if not missing_records:
            return ip_df

        print(
            f"\n{len(missing_records)} screening records are missing IP metadata.\n"
            "Paste the PDF archive rows covering those records, or type `no ip` to skip."
        )
        pasted = input("Paste REDCap PDF archive rows here: ").strip()
        if pasted.lower() == "no ip":
            return ip_df

        new_ip_rows = parse_redcap_pdf_log(pasted)
        new_ip_rows = new_ip_rows.loc[new_ip_rows["record_id"].isin(missing_records)].copy()
        if new_ip_rows.empty:
            raise RuntimeError("No usable record/IP pairs were found in the pasted REDCap archive text.")

        try:
            import ipinfo
        except ImportError as exc:
            raise RuntimeError("The `ipinfo` package is required for screening review.") from exc

        handler = ipinfo.getHandler(IPINFO_TOKEN)
        ip_details: list[pd.DataFrame] = []
        for _, row in new_ip_rows.iterrows():
            details = handler.getDetails(row["ip"])
            detail_df = pd.DataFrame(details.all, index=[0])
            detail_df["record_id"] = int(row["record_id"])
            detail_df["ip"] = row["ip"]
            ip_details.append(detail_df)

        appended = pd.concat(ip_details, ignore_index=True)
        merged = pd.concat([ip_df, appended], ignore_index=True)
        merged.to_csv(IP_DATABASE_PATH, index=False)
        return merged

    def _apply_screening_eligibility_rules(self, review: ScreeningReview) -> None:
        """Apply hard exclusion criteria and SP washout logic to each screening record.

        For each record, evaluates a list of boolean exclusion checks.  Any that fire
        add a human-readable reason to review.ineligibility_notes and append the record
        to review.hard_fail.

        Hard exclusion checks (all lead to hard_fail regardless of willingness to wait):
          - Age < 18 or > 65
          - Cognitive screener failed (cognition_screener_v2 > 0)
          - Seizure history (seizure_hx_v2 > 0)
          - Possible intoxication (intox_screen_v2 > 0)
          - Did not endorse SP use (psycheduse_yn > 1)
          - Raven score < 1
          - No computer access (no_computer > 0)
          - English fluency not met (english_fluency < 1)
          - Geographic fraud flag (geo_crit is NaN)
          - Endorsed kaopectamine (fake drug trap question; kaopectamine_lifetime == '1')
          - Filled in hidden AI prompt injection field (flexibility_yn non-blank)
          - screen_motive looks AI-generated (exactly 500 chars, or 476–524 chars with template phrase)
          - Completed screening in under 90 seconds (screen_seconds_taken < 90)

        SP/atypical washout check (handled separately to support willing-to-wait path):
          - sp_dayslastuse < 42 days OR atypical_recentuse == '1'
          → If psychedelic_abstinence_yn == '1' (willing to wait): added to sp_wait
          → Otherwise: added to hard_fail with a washout reason

        Mutates review in-place; does not return anything.
        """
        for _, row in review.screen_df.iterrows():
            record_id = int(row["record_id"])

            checks = [
                (numeric_value(row, "age_v2") > 65, "Age above 65"),
                (numeric_value(row, "age_v2") < 18, "Age below 18"),
                (numeric_value(row, "cognition_screener_v2") > 0, "Cognitive screener failed"),
                (numeric_value(row, "seizure_hx_v2") > 0, "Seizure history"),
                (numeric_value(row, "intox_screen_v2") > 0, "Possible intoxication at intake"),
                (numeric_value(row, "psycheduse_yn") > 1, "Did not endorse serotonergic psychedelic use"),
                (numeric_value(row, "raven_total_score_v2") < 1, "Raven score below minimum"),
                (numeric_value(row, "no_computer") > 0, "No computer access"),
                (numeric_value(row, "english_fluency") < 1, "English fluency not met"),
                (pd.isna(row.get("geo_crit", np.nan)), "Geographic fraud flag"),
                # Fake drug trap question checked at screening stage
                (string_value(row, "kaopectamine_lifetime").strip() == "1", "Endorsed fake drug (kaopectamine) during screening"),
                # Hidden AI prompt injection trap: @HIDDEN-SURVEY field that asks the
                # participant to type 'ok'; normal users never see it, AI agents may fill it
                (string_value(row, "flexibility_yn").strip() != "", "Responded to hidden AI prompt injection field (flexibility_yn)"),
                # Speed check: under 90 seconds is too fast for a human to read and answer
                (0 < numeric_value(row, "screen_seconds_taken") < 90, "Completed screening suspiciously fast (screen_seconds_taken < 90s)"),
            ]

            # SP/atypical use within the past 6 weeks — handle separately to support the
            # willing-to-wait path (psychedelic_abstinence_yn='1').
            sp_recent = (
                not pd.isna(numeric_value(row, "sp_dayslastuse"))
                and numeric_value(row, "sp_dayslastuse") < 42
            )
            atypical_recent = string_value(row, "atypical_recentuse").strip() == "1"
            willing_to_wait = string_value(row, "psychedelic_abstinence_yn").strip() == "1"

            if sp_recent or atypical_recent:
                if willing_to_wait:
                    # Participant acknowledged the washout requirement and agreed to wait.
                    # Subject them to the normal phone/IP review.  Eligibility and payment
                    # notification are deferred to continue_date via eligible_afterwait_notify.
                    review.sp_wait.append(record_id)
                else:
                    add_reason(review.ineligibility_notes, record_id, "Reported SP/atypical use within the last 42 days")
                    review.hard_fail.append(record_id)

            for failed, reason in checks:
                if failed:
                    add_reason(review.ineligibility_notes, record_id, reason)
                    review.hard_fail.append(record_id)

            # screen_motive: flag AI-generated motivational text responses.
            # Per-record reason is built by _screen_motive_fraud_reason (length/phrase heuristics).
            motive_reason = self._screen_motive_fraud_reason(string_value(row, "screen_motive").strip())
            if motive_reason:
                add_reason(review.ineligibility_notes, record_id, motive_reason)
                review.hard_fail.append(record_id)

    def _apply_duplicate_identity_checks(self, review: ScreeningReview) -> None:
        """Cross-reference new screening records against historical IPs and emails.

        Builds a set of 'historic' records — anyone who previously screened (whether
        eligible or not) — then checks each new record for:

          1. Forbidden IP org / country: IP is from FORBIDDEN_IP_ORGS or
             FORBIDDEN_IP_COUNTRIES → hard_fail.
          2. Duplicate email: any email field (SCREENING_EMAIL_FIELDS) matches an email
             in the historic record set → hard_fail.
          3. IP shared with a historic record: IP matches a prior record's IP (excluding
             known safe orgs like Yale and Middlebury) → suspicious_ip.
          4. Missing IP metadata: record is not in the IP database at all → manual_followup.

        Mutates review in-place.
        """
        assert self.df is not None
        df = self.df

        ineligible_mask = df["submit_screen_v3"].isna() & df["datedone_screening_survey"].notna()
        already_reviewed_mask = df["qc_passed"].notna()
        historic = df.loc[ineligible_mask | already_reviewed_mask].copy()

        historic_emails: dict[str, set[int]] = {}
        for _, row in historic.iterrows():
            record_id = int(row["record_id"])
            for field in SCREENING_EMAIL_FIELDS:
                email = clean_email(row[field]) if field in historic.columns else None
                if not email:
                    continue
                historic_emails.setdefault(email, set()).add(record_id)

        true_ips = review.ip_df.loc[~review.ip_df["org"].isin(SAFE_DUPLICATE_IP_ORGS)].copy()
        prior_bad_ips = set(true_ips.loc[true_ips["record_id"].isin(historic["record_id"]), "ip"].dropna().tolist())

        for _, row in review.screen_df.iterrows():
            record_id = int(row["record_id"])

            record_ip_rows = review.ip_df.loc[review.ip_df["record_id"] == record_id]
            if record_ip_rows.empty:
                review.manual_followup.append(record_id)
                add_reason(review.ineligibility_notes, record_id, "IP metadata missing")
                continue

            if record_ip_rows["org"].isin(FORBIDDEN_IP_ORGS).any() or record_ip_rows["country_name"].isin(FORBIDDEN_IP_COUNTRIES).any():
                review.hard_fail.append(record_id)
                add_reason(review.ineligibility_notes, record_id, "Forbidden IP organization/country")
                continue

            for field in SCREENING_EMAIL_FIELDS:
                if field not in row.index:
                    continue
                email = clean_email(row[field])
                if not email:
                    continue
                matching_records = historic_emails.get(email, set()) - {record_id}
                if matching_records:
                    review.hard_fail.append(record_id)
                    add_reason(review.ineligibility_notes, record_id, f"Email duplicates prior record(s): {sorted(matching_records)}")
                    break

            if record_id in review.hard_fail:
                continue

            record_ips = set(record_ip_rows["ip"].dropna().tolist())
            if record_ips & prior_bad_ips:
                review.suspicious_ip.append(record_id)
                add_reason(review.ineligibility_notes, record_id, "IP matches a previously reviewed/ineligible record")

    def _write_screening_summary(self, review: ScreeningReview) -> None:
        """Write a markdown summary of the screening review to today's date directory.

        Saved as screening_review_summary.md.  Lists counts for each category and
        all ineligibility reasons by record ID.  Useful for a paper trail and for
        anyone who needs to understand why a record was flagged without re-running
        the script.
        """
        summary_path = self.date_directory / "screening_review_summary.md"
        lines = [
            "# Screening Review Summary",
            "",
            f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
            f"- Records to screen: {len(review.records_to_screen)}",
            f"- Hard fail: {len(set(review.hard_fail))}",
            f"- Suspicious duplicate IP: {len(set(review.suspicious_ip))}",
            f"- Needs phone review: {len(set(review.phone_review))}",
            f"- Needs manual follow-up: {len(set(review.manual_followup))}",
            f"- SP wait path (willing to wait 6 weeks): {len(set(review.sp_wait))}",
            "",
            "## Record Notes",
        ]
        if review.ineligibility_notes:
            for record_id in sorted(review.ineligibility_notes):
                lines.append(f"- {record_id}: {review.ineligibility_notes[record_id]}")
        else:
            lines.append("- None")
        summary_path.write_text("\n".join(lines))

    # ------------------------------------------------------------------
    # SECTION 5C: Baseline completion QC and payment
    # ------------------------------------------------------------------

    def run_completion_qc(self) -> CompletionReview:
        """Run all baseline QC checks and build the REDCap update DataFrame.

        Processes every record in self.records_to_check through the following pipeline
        (in order of priority — the first applicable outcome wins for each record):

          1. Critical failure → qc_passed=0, qc_notes=reason
             Triggered by: failed attention check, race/age mismatch, failed trap
             questions (kaopectamine/dose/caps/pdi), copy-pasted task data, or
             confirmed absurd SP responses (sp_verify_pass set to 0 after verification).

          2. SP verification needed → verify_emailed=1, inconsistent_sp_answers=1
             Triggered by: internally inconsistent SP use responses that are suspicious
             but could be genuine errors.  Sends the clarification survey; record will
             be re-evaluated on the next QC run once sp_verify_pass is set.

          3. Task replay needed → ach/vch/prl_replay_N=1, replay_links_*=1
             Triggered by: task failure (zero/negative slope, first-15 failure for CH;
             worse-than-chance / non-responder for PRL).  Clears the task field and
             sends a replay invitation alert.  Up to 4 replay attempts per task.

          4. QC passed → qc_passed=1, expense sheet row generated

        Also appends failed task JSON payloads to FAILED_JSON_PATH on the shared drive
        for offline analysis.  Writes a completion_qc_summary.md.
        Returns a CompletionReview with the update DataFrame and expense sheet path.
        """
        assert self.df is not None and self.df_og is not None

        records = self.records_to_check
        empty_update = self.df_og.iloc[0:0].copy()
        if not records:
            return CompletionReview(
                records_to_check=[],
                update_df=empty_update,
                update_fields=[],
                expensesheet_path=None,
                failed_json_append_count=0,
                qc_lists={},
            )

        df_raw = self.df.loc[self.df["record_id"].isin(records)].copy().reset_index(drop=True)

        # -----------------------------
        # Baseline completeness checks
        # -----------------------------
        no_ach = df_raw.loc[
            ~df_raw.apply(
                lambda row: nonempty_task_value(row, "task_data_ach_task_short_baseline", "task_data_ach_bl_retrieved"),
                axis=1,
            ),
            "record_id",
        ].tolist()
        no_prl = df_raw.loc[
            ~df_raw.apply(lambda row: nonempty_task_value(row, "task_data_prltask", "task_data_prl_bl_retrieved"), axis=1),
            "record_id",
        ].tolist()
        no_vch = df_raw.loc[
            ~df_raw.apply(
                lambda row: nonempty_task_value(row, "task_data_vch_short_psychedelic_bl", "task_data_vch_bl_retrieved"),
                axis=1,
            ),
            "record_id",
        ].tolist()

        # --------------------------------------------
        # Baseline questionnaire / answer consistency
        # --------------------------------------------
        failed_attn_check = self._find_failed_attention_checks(df_raw)
        failed_new_qc = self._find_race_age_mismatch(df_raw)
        failed_trap_questions = self._find_trap_question_failures(df_raw)
        sp_findings = self._evaluate_absurd_sp_responses(df_raw)
        no_sms_verification = df_raw.loc[df_raw["phone_verified"].isna(), "record_id"].tolist()
        no_main_survey = df_raw.loc[df_raw["si_2_v2"].isna(), "record_id"].tolist()

        # -------------------
        # Task-level QC lists
        # -------------------
        fraud_copy_paste_ach: list[int] = []
        fraud_copy_paste_vch: list[int] = []
        fraud_copy_paste_prl: list[int] = []
        fraud_copy_paste_spacejunk: list[int] = []

        ach_master = self._load_ach_trials(df_raw, fraud_copy_paste_ach)
        ach_lists = self._evaluate_ch_task(ach_master, intensity_field="decibels", prefix="")

        vch_master = self._load_vch_trials(df_raw, fraud_copy_paste_vch)
        vch_lists = self._evaluate_ch_task(vch_master, intensity_field="contrasts", prefix="_vch")

        df_prl = self._load_prl_trials(df_raw, fraud_copy_paste_prl)
        prl_lists = self._evaluate_prl(df_prl)

        _spacejunk_df = self._load_spacejunk_trials(df_raw, fraud_copy_paste_spacejunk)

        qc_lists = {
            "failedAttnCheck": to_int_list(failed_attn_check),
            "failed_new_qc": to_int_list(failed_new_qc),
            "failed_trap_questions": to_int_list(failed_trap_questions),
            "failed_sp_qc": to_int_list(sp_findings["failed_sp_qc"]),
            "failed_usetime_qc": to_int_list(sp_findings["failed_usetime_qc"]),
            "illogical_year": to_int_list(sp_findings["illogical_year"]),
            "illogical_life": to_int_list(sp_findings["illogical_life"]),
            "wrong_recent": to_int_list(sp_findings["wrong_recent"]),
            "nanresponses": to_int_list(sp_findings["nanresponses"]),
            "no_sms_verification": to_int_list(no_sms_verification),
            "nosurvey1": to_int_list(no_main_survey),
            "no_ach": to_int_list(no_ach),
            "no_prl": to_int_list(no_prl),
            "no_vch": to_int_list(no_vch),
            "fraud_copy_paste_ach": to_int_list(fraud_copy_paste_ach),
            "fraud_copy_paste_vch": to_int_list(fraud_copy_paste_vch),
            "fraud_copy_paste_prl": to_int_list(fraud_copy_paste_prl),
            "fraud_copy_paste_spacejunk": to_int_list(fraud_copy_paste_spacejunk),
            "zero": to_int_list(ach_lists["zero"]),
            "negative": to_int_list(ach_lists["negative"]),
            "fail_first_fifteen": to_int_list(ach_lists["fail_first_fifteen"]),
            "zero_vch": to_int_list(vch_lists["zero_vch"]),
            "negative_vch": to_int_list(vch_lists["negative_vch"]),
            "fail_first_fifteen_vch": to_int_list(vch_lists["fail_first_fifteen_vch"]),
            "worse_than_chance": to_int_list(prl_lists["worse_than_chance"]),
            "non_responders": to_int_list(prl_lists["non_responders"]),
            "no_lose_stay": to_int_list(prl_lists["no_lose_stay"]),
        }

        update_fields = self._completion_update_fields()
        update_df = self.df_og.loc[self.df_og["record_id"].isin(records), [field for field in update_fields if field in self.df_og.columns]].copy()
        update_df = update_df.reset_index(drop=True)

        failed_json_append_count = 0
        failed_json_rows: list[dict[str, Any]] = []
        absurdity_reasons = sp_findings["absurdity_reasons"]

        for record_id in records:
            row = self.df.loc[self.df["record_id"] == record_id].reset_index(drop=True)
            if row.empty:
                continue
            current = row.iloc[0]
            record_updates: dict[str, Any] = {}

            critical_note = self._critical_failure_note(record_id, qc_lists, absurdity_reasons)
            if critical_note:
                record_updates["qc_passed"] = 0
                record_updates["qc_notes"] = critical_note
                if critical_note.startswith("Absurd psychedelics responses") and "fraudulent_email_inconsistentanswers" in update_df.columns:
                    record_updates["fraudulent_email_inconsistentanswers"] = 1
                elif "fraudulent_email" in update_df.columns and "copy pasted" in critical_note.lower():
                    record_updates["fraudulent_email"] = 1
                elif "fraudulent_email_inconsistentanswers" in update_df.columns:
                    record_updates["fraudulent_email_inconsistentanswers"] = 1
                self._apply_record_updates(update_df, record_id, record_updates)
                continue

            verification_note = self._verification_needed(record_id, qc_lists, absurdity_reasons)
            if verification_note:
                if "verify_emailed" in update_df.columns:
                    record_updates["verify_emailed"] = 1
                if "inconsistent_sp_answers" in update_df.columns:
                    record_updates["inconsistent_sp_answers"] = 1
                if "qc_notes" in update_df.columns:
                    record_updates["qc_notes"] = verification_note
                self._apply_record_updates(update_df, record_id, record_updates)
                continue

            task_failure_rows = self._task_failures_for_record(record_id, qc_lists)
            if task_failure_rows:
                for task_name, fail_reason in task_failure_rows:
                    config = TASK_CONFIGS[task_name]
                    self._queue_task_retry(update_df, record_id, config)
                    for field in config.qualifying_cols:
                        if field in update_df.columns:
                            update_df.loc[update_df["record_id"] == record_id, field] = '<font color="red">Incomplete</font>'

                    failed_json_rows.append(
                        {
                            "record_id": record_id,
                            "task": task_name,
                            "fail_reason": fail_reason,
                            "fail_attempt": self._replay_attempt_number(current, config.replay_fields),
                            "json_string": self._task_payload_for_export(current, config),
                        }
                    )
                    failed_json_append_count += 1
                continue

            # Default pass -> mark QC pass and prepare Amazon payment row.
            record_updates["qc_passed"] = 1
            if "employee_name" in update_df.columns:
                record_updates["employee_name"] = self.user_name
            if "pay_day_ofweek" in update_df.columns:
                record_updates["pay_day_ofweek"] = datetime.now().isoweekday()
            if "send_pay_confirm" in update_df.columns and clean_email(current.get("email_addtl_contact", np.nan)):
                record_updates["send_pay_confirm"] = 1
            self._apply_record_updates(update_df, record_id, record_updates)

        failed_json_count = self._append_failed_json_rows(failed_json_rows)
        expensesheet_path = self._build_baseline_expensesheet(update_df)
        manual_tasks_needed = self._manual_tasks_needed(update_df)
        self._write_completion_summary(qc_lists, update_df, expensesheet_path, failed_json_count)
        self._generate_flag_files(
            expensesheet_needed=expensesheet_path is not None,
            manual_tasks_needed=manual_tasks_needed,
        )

        return CompletionReview(
            records_to_check=records,
            update_df=update_df,
            update_fields=[field for field in update_df.columns if field != "record_id"],
            expensesheet_path=expensesheet_path,
            failed_json_append_count=failed_json_count,
            qc_lists=qc_lists,
        )

    def import_completion_updates(self, review: CompletionReview) -> None:
        """Push the baseline completion update DataFrame to REDCap.

        Coerces float columns that contain only whole numbers to Int64 before import
        (REDCap rejects floats like 1.0 for integer/yesno fields).
        Uses overwrite='overwrite' so task payload fields can be cleared for replays.
        Marks the REDCAP_FULLRECORDS_INCOMPLETE flag as complete after a successful push.
        """
        assert self.project is not None
        if review.update_df.empty:
            print("No completion updates to import.")
            return

        updates = review.update_df.copy()
        for field in updates.columns:
            if field == "record_id":
                continue
            if pd.api.types.is_float_dtype(updates[field]):
                non_null = updates[field].dropna()
                if not non_null.empty and (non_null % 1 == 0).all():
                    updates[field] = updates[field].astype("Int64")

        self.project.import_records(to_import=updates, import_format="df", overwrite="overwrite")
        self._update_redcap_flag("REDCAP_FULLRECORDS_INCOMPLETE")
        print(f"Imported completion updates for {len(updates)} records.")

    # ------------------------------------------------------------------
    # SECTION 5D: Baseline fraud / absurd-SP logic
    # ------------------------------------------------------------------

    def _find_failed_attention_checks(self, df_raw: pd.DataFrame) -> list[int]:
        """Return record IDs that failed one or more embedded attention checks.

        Checks attn_check_surveybl, attn_check_surveybl2, and attn_check_surveybl3.
        Each is a yesno field where the correct answer is 1 (Yes).  A record fails
        if the sum of existing checks is less than the number of existing check fields
        (i.e., they got at least one wrong).  Only checks fields present in the export
        to handle cases where a field does not yet exist in REDCap.
        """
        attn_fields = ["attn_check_surveybl", "attn_check_surveybl2", "attn_check_surveybl3"]
        existing = [field for field in attn_fields if field in df_raw.columns]
        if not existing:
            return []
        totals = df_raw[existing].apply(pd.to_numeric, errors="coerce").sum(axis=1)
        return to_int_list(df_raw.loc[totals < len(existing), "record_id"].tolist())

    def _screen_motive_fraud_reason(self, text: str) -> str | None:
        """Return a fraud reason if screen_motive looks AI-generated, else None.

        Two heuristics target AI agents that follow the prompt literally:
          1. Length is exactly 500 characters — AI commonly targets the exact count
             asked for when given a numeric target ("500 characters").
          2. Length is 476–524 characters AND begins with the template phrase
             "I would describe my personal motivation" — catches responses that
             echo the question wording back verbatim while hitting the ~500 target.

        Multiple matching reasons are semicolon-joined so both can appear in qc_notes.
        Returns None if no heuristic fires (i.e., the response looks human).
        """
        if not text:
            return None
        n = len(text)
        reasons: list[str] = []
        if n == 500:
            reasons.append("screen_motive: response is exactly 500 characters")
        if 476 <= n <= 524 and text.startswith("I would describe my personal motivation"):
            reasons.append(f"screen_motive: response is {n} chars and begins with AI template phrase")
        return "; ".join(reasons) if reasons else None

    def _find_trap_question_failures(self, df_raw: pd.DataFrame) -> list[int]:
        """Flag records that fail any of the embedded fraud/trap checks at baseline.

        This is distinct from the screening-stage kaopectamine check: here we check
        records that have already passed screening and completed the baseline battery.

        Checks (all lead to critical failure — qc_passed=0):
        - kaopectamine_lifetime == '1'  (fake drug endorsed — radio field, Yes=1)
        - fraud_recent_dose == '1'           (dose self-report doesn't match computed most-recent dose)
        - fraud_caps == '0'                  (missed embedded CAPS attention check — correct answer is Yes/1)
        - fraud_pdi == '0'                   (missed embedded PDI attention check — correct answer is Yes/1)
        - ai_copy_paste == '1' or '3'        (disagreed with no-copy-paste policy, or self-declared as AI)
        A record is flagged if any single check fires.
        """
        failures: set[int] = set()

        # kaopectamine_lifetime: radio field (1=Yes, 2=No)
        kao_field = "kaopectamine_lifetime"
        if kao_field in df_raw.columns:
            mask = df_raw[kao_field].astype(str).str.strip() == "1"
            failures.update(df_raw.loc[mask, "record_id"].astype(int).tolist())

        # fraud_recent_dose: calc returns 1 when dose report mismatches
        if "fraud_recent_dose" in df_raw.columns:
            mask = pd.to_numeric(df_raw["fraud_recent_dose"], errors="coerce") == 1
            failures.update(df_raw.loc[mask, "record_id"].astype(int).tolist())

        # fraud_caps: yesno — correct answer is Yes (1); flag if answered No (0)
        if "fraud_caps" in df_raw.columns:
            mask = df_raw["fraud_caps"].astype(str).str.strip() == "0"
            failures.update(df_raw.loc[mask, "record_id"].astype(int).tolist())

        # fraud_pdi: yesno — correct answer is Yes (1); flag if answered No (0)
        if "fraud_pdi" in df_raw.columns:
            mask = df_raw["fraud_pdi"].astype(str).str.strip() == "0"
            failures.update(df_raw.loc[mask, "record_id"].astype(int).tolist())

        # ai_copy_paste: radio — 2 (I agree) is the only valid response.
        # 1 = disagrees with no-copy-paste policy; 3 = self-declared AI agent.
        if "ai_copy_paste" in df_raw.columns:
            mask = df_raw["ai_copy_paste"].astype(str).str.strip().isin(["1", "3"])
            failures.update(df_raw.loc[mask, "record_id"].astype(int).tolist())

        return [int(r) for r in sorted(failures)]

    def _find_race_age_mismatch(self, df_raw: pd.DataFrame) -> list[int]:
        """Return record IDs where the race or age answer changed between screening and baseline.

        Participants report race (race_v2) and age (age_v2) during screening, then
        confirm them again in a later instrument (race_qc, age_qc).  Large discrepancies
        suggest the baseline was filled out by a different person than screening.
        A record fails if: |race_v2 - race_qc| > 1, OR |age_v2 - age_qc| > 1,
        OR both differ by any amount simultaneously.
        """
        required = {"race_qc", "race_v2", "age_qc", "age_v2"}
        if not required.issubset(df_raw.columns):
            return []

        df_finished = df_raw.loc[~(df_raw["race_qc"].isna() | df_raw["age_qc"].isna())].copy()
        df_finished.loc[df_finished["age_qc"] == "30yrs", "age_qc"] = 30
        df_finished["age_qc"] = pd.to_numeric(df_finished["age_qc"], errors="coerce")
        df_finished["age_v2"] = pd.to_numeric(df_finished["age_v2"], errors="coerce")

        failures: list[int] = []
        for _, row in df_finished.iterrows():
            racediff = abs(numeric_value(row, "race_qc") - numeric_value(row, "race_v2"))
            agediff = abs(numeric_value(row, "age_qc") - numeric_value(row, "age_v2"))
            if ((racediff > 0) and (agediff > 0)) or (racediff > 1) or (agediff > 1):
                failures.append(int(row["record_id"]))
        return failures

    def _evaluate_absurd_sp_responses(self, df_raw: pd.DataFrame) -> dict[str, Any]:
        """Evaluate the internal consistency and plausibility of SP use self-reports.

        Only runs on records with psycheduse_life_nomic > 0 (claimed SP use in their
        lifetime) and skips records where sp_type_recent or sp_dayslastuse is blank
        (added to 'nanresponses' and excluded from further checks).

        Verification flow:
          If verify_emailed=1 (we already sent the clarification survey):
            - sp_verify_pass > 0 → previously verified; skip (count as pass)
            - sp_verify_pass < 1 → gave inconsistent answers twice → failed_sp_qc
          Otherwise, runs consistency checks:

        Checks leading to 'failed_sp_qc' (critical failure):
          - psycheduse_life_nomic < 1 AND psychedelicuse_lifetimetot < 1
            (claimed SP use in screening but reports zero in main survey)
          - sp_fraud_aes___1–5: endorsed non-SP side effects as SP effects
          - sp_fraud_psi/lsd/mesc/dmt/5meo: reported an implausible route of
            administration (e.g. inhalation of psilocybin)

        Checks leading to 'failed_usetime_qc' (verification needed, not auto-fail):
          - sp_dayslastuse < 180 but psycheduse_6month_nomic < 1 (or vice versa)
          - sp_dayslastuse < 365 but psycheduse_year_nomic < 1 (or vice versa)

        Checks leading to 'illogical_year' / 'illogical_life' (verification needed):
          - Year count > lifetime count, or year count > lifetime count

        Checks leading to 'wrong_recent' (verification needed):
          - sp_type_recent (screening) != sp_type_recent_qc (baseline survey)

        Returns a dict with keys for each finding list plus 'absurdity_reasons'
        ({record_id: reason_string}).
        """
        findings = {
            "failed_sp_qc": [],
            "failed_usetime_qc": [],
            "illogical_year": [],
            "illogical_life": [],
            "wrong_recent": [],
            "nanresponses": [],
            "absurdity_reasons": {},
        }

        if "psycheduse_life_nomic" not in df_raw.columns:
            return findings

        df_finished = df_raw.loc[pd.to_numeric(df_raw["psycheduse_life_nomic"], errors="coerce") > 0].copy()
        if df_finished.empty:
            return findings

        nan_mask = (
            df_finished["sp_type_recent"].isna()
            | df_finished["sp_dayslastuse"].isna()
        )
        findings["nanresponses"] = to_int_list(df_finished.loc[nan_mask, "record_id"].tolist())

        df_finished = df_finished.loc[
            ~df_finished["record_id"].isin(findings["nanresponses"])
        ].copy()

        for _, row in df_finished.iterrows():
            record_id = int(row["record_id"])

            if numeric_value(row, "verify_emailed") == 1:
                if numeric_value(row, "sp_verify_pass") > 0:
                    continue
                if numeric_value(row, "sp_verify_pass") < 1:
                    findings["failed_sp_qc"].append(record_id)
                    findings["absurdity_reasons"][record_id] = (
                        "Gave inconsistent answers about SP use twice "
                        "(and/or answers were too different between the two surveys)"
                    )
                continue

            psycheduse_yn = numeric_value(row, "psycheduse_yn")
            if psycheduse_yn == 1:
                if numeric_value(row, "psycheduse_life_nomic") < 1 and numeric_value(row, "psychedelicuse_lifetimetot") < 1:
                    findings["failed_sp_qc"].append(record_id)
                    findings["absurdity_reasons"][record_id] = "Has no SP use in main survey despite saying they used SPs in screening"

                if string_value(row, "sp_type_recent") != string_value(row, "sp_type_recent_qc"):
                    findings["wrong_recent"].append(record_id)
                    findings["absurdity_reasons"][record_id] = "Has different answers for the most recent SP used in screening vs main survey"

                for idx in range(1, 6):
                    field = f"sp_fraud_aes___{idx}"
                    if field in row.index and numeric_value(row, field) > 0:
                        findings["failed_sp_qc"].append(record_id)
                        findings["absurdity_reasons"][record_id] = "Reported non-SP effects from SPs"
                        break

                weird_route = (
                    numeric_value(row, "sp_fraud_psi") < 6
                    or numeric_value(row, "sp_fraud_lsd") < 5
                    or numeric_value(row, "sp_fraud_mesc") < 6
                    or (1 < numeric_value(row, "sp_fraud_dmt") < 6)
                    or numeric_value(row, "sp_fraud_5meo") < 5
                )
                if weird_route:
                    findings["failed_sp_qc"].append(record_id)
                    findings["absurdity_reasons"][record_id] = "Reported a bizarre route of administration for SPs"

                if numeric_value(row, "psycheduse_year_nomic") < numeric_value(row, "psycheduse_6month_nomic"):
                    findings["illogical_year"].append(record_id)
                    findings["absurdity_reasons"][record_id] = "Has illogical answers for SP use in the past year"

                if (
                    numeric_value(row, "psycheduse_life_nomic") < numeric_value(row, "psycheduse_6month_nomic")
                    or numeric_value(row, "psycheduse_life_nomic") < numeric_value(row, "psycheduse_year_nomic")
                ):
                    findings["illogical_life"].append(record_id)
                    findings["absurdity_reasons"][record_id] = "Has illogical answers for SP use in their lifetime"

                if (
                    (numeric_value(row, "sp_dayslastuse") < 180 and numeric_value(row, "psycheduse_6month_nomic") < 1)
                    or (numeric_value(row, "sp_dayslastuse") > 185 and numeric_value(row, "psycheduse_6month_nomic") > 0)
                ):
                    findings["failed_usetime_qc"].append(record_id)
                    findings["absurdity_reasons"][record_id] = "Has inconsistent answers for SP use in the past 6 months"
                elif (
                    (numeric_value(row, "sp_dayslastuse") < 365 and numeric_value(row, "psycheduse_year_nomic") < 1)
                    or (numeric_value(row, "sp_dayslastuse") > 365 and numeric_value(row, "psycheduse_year_nomic") > 0)
                ):
                    findings["failed_usetime_qc"].append(record_id)
                    findings["absurdity_reasons"][record_id] = "Has inconsistent answers for SP use in the past year"

        for key, value in findings.items():
            if key == "absurdity_reasons":
                continue
            findings[key] = sorted(set(to_int_list(value)))

        return findings

    # ------------------------------------------------------------------
    # SECTION 5E: Task parsers and QC metrics
    # ------------------------------------------------------------------

    def _validate_retrieved_task_data(
        self,
        json_string: str,
        record_id: int,
        task_name: str,
        fraud_list: list[int],
    ) -> tuple[bool, bool]:
        """Validate a manually-retrieved (backup) task JSON string before parsing it.

        Returns (should_process, should_skip):
          (True, False)  — compressed payload detected; caller should decompress + parse
          (False, True)  — researcher said the string looks valid but unusual; skip for now
          (False, False) — invalid / fraudulent string; record added to fraud_list

        A compressed payload starts with 'H4sIAAAAA' (gzip+base64 prefix).
        Strings < 50 chars or obviously fake ('testing', '123') are auto-flagged.
        Anything else prompts the researcher to decide interactively.
        """
        if json_string.startswith("H4sIAAAAA"):
            return True, False

        if len(json_string) < 50 or json_string.lower() in {"testing", "test", "hello", "123"}:
            fraud_list.append(record_id)
            print(f"Record {record_id}: invalid retrieved {task_name} string -> marked as fraud")
            return False, False

        print(f"\nRecord {record_id} has questionable retrieved {task_name} data:")
        print(json_string[:150] + ("..." if len(json_string) > 150 else ""))
        while True:
            answer = input("Does this look like a valid JSON backup string? (yes/no): ").strip().lower()
            if answer in {"yes", "y"}:
                print(f"Skipping automated processing for record {record_id}; please review manually later.")
                return False, True
            if answer in {"no", "n"}:
                fraud_list.append(record_id)
                return False, False
            print("Please enter 'yes' or 'no'.")

    def _load_ach_trials(self, df_raw: pd.DataFrame, fraud_list: list[int]) -> pd.DataFrame:
        """Parse all ACH task payloads into a trial-level DataFrame.

        For each record, tries task_data_ach_task_short_baseline (compressed primary)
        then task_data_ach_bl_retrieved (manually-retrieved JSON backup).
        Parses the 4-block component structure via _ch_components_to_dataframe().
        After parsing, detects copy-paste fraud by pivoting on reaction time and
        flagging any two records with identical RT sequences.
        Returns a DataFrame with columns: response, rt, decibels, component,
        record_id, intensity, trial.
        """
        participant_dfs: list[pd.DataFrame] = []
        for _, row in df_raw.iterrows():
            record_id = int(row["record_id"])
            task_string = row.get("task_data_ach_task_short_baseline", np.nan)
            backup_string = row.get("task_data_ach_bl_retrieved", np.nan)

            if isinstance(task_string, str) and task_string != "testing":
                try:
                    data = decode_compressed_json(task_string)
                    participant_dfs.append(self._ch_components_to_dataframe(data, record_id, "decibels"))
                except Exception as exc:
                    print(f"Error decoding ACH for {record_id}: {exc}")
                    fraud_list.append(record_id)
            elif isinstance(backup_string, str):
                should_process, should_skip = self._validate_retrieved_task_data(backup_string, record_id, "ACH", fraud_list)
                if not should_process:
                    if should_skip:
                        continue
                    continue
                try:
                    data = json.loads(backup_string)
                    participant_dfs.append(self._ch_components_to_dataframe(data, record_id, "decibels"))
                except Exception as exc:
                    print(f"Error parsing retrieved ACH for {record_id}: {exc}")
                    fraud_list.append(record_id)

        if not participant_dfs:
            return pd.DataFrame(columns=["response", "rt", "decibels", "component", "record_id", "intensity", "trial"])

        ach_master = pd.concat(participant_dfs, ignore_index=True)
        ach_master["record_id"] = pd.to_numeric(ach_master["record_id"], errors="coerce").astype(int)
        ach_master["trial"] = ach_master.groupby("record_id").cumcount() + 1

        ach_pivot = ach_master.pivot(index="record_id", columns="trial", values="rt")
        duplicates = ach_pivot[ach_pivot.duplicated(keep=False)].index.tolist()
        fraud_list.extend(to_int_list(duplicates))
        return ach_master

    def _load_vch_trials(self, df_raw: pd.DataFrame, fraud_list: list[int]) -> pd.DataFrame:
        """Parse all VCH task payloads into a trial-level DataFrame.

        Identical in structure to _load_ach_trials but uses task_data_vch_short_psychedelic_bl
        / task_data_vch_bl_retrieved and the 'contrasts' intensity dimension.
        Returns a DataFrame with columns: response, rt, contrasts, component,
        record_id, intensity, trial.
        """
        participant_dfs: list[pd.DataFrame] = []
        for _, row in df_raw.iterrows():
            record_id = int(row["record_id"])
            task_string = row.get("task_data_vch_short_psychedelic_bl", np.nan)
            backup_string = row.get("task_data_vch_bl_retrieved", np.nan)

            if isinstance(task_string, str) and task_string != "testing":
                try:
                    data = decode_compressed_json(task_string)
                    participant_dfs.append(self._ch_components_to_dataframe(data, record_id, "contrasts"))
                except Exception as exc:
                    print(f"Error decoding VCH for {record_id}: {exc}")
                    fraud_list.append(record_id)
            elif isinstance(backup_string, str):
                should_process, should_skip = self._validate_retrieved_task_data(backup_string, record_id, "VCH", fraud_list)
                if not should_process:
                    if should_skip:
                        continue
                    continue
                try:
                    data = json.loads(backup_string)
                    participant_dfs.append(self._ch_components_to_dataframe(data, record_id, "contrasts"))
                except Exception as exc:
                    print(f"Error parsing retrieved VCH for {record_id}: {exc}")
                    fraud_list.append(record_id)

        if not participant_dfs:
            return pd.DataFrame(columns=["response", "rt", "contrasts", "component", "record_id", "intensity", "trial"])

        vch_master = pd.concat(participant_dfs, ignore_index=True)
        vch_master["record_id"] = pd.to_numeric(vch_master["record_id"], errors="coerce").astype(int)
        vch_master["trial"] = vch_master.groupby("record_id").cumcount() + 1

        vch_pivot = vch_master.pivot(index="record_id", columns="trial", values="rt")
        duplicates = vch_pivot[vch_pivot.duplicated(keep=False)].index.tolist()
        fraud_list.extend(to_int_list(duplicates))
        return vch_master

    def _ch_components_to_dataframe(self, data: dict[str, Any], record_id: int, level_field: str) -> pd.DataFrame:
        """Convert one participant's decoded ACH or VCH payload dict into a trial DataFrame.

        The payload is a dict with keys 'component_1' through 'component_4', each
        containing 'response', 'responseTime', and a level field ('decibels' or
        'contrasts').  Concatenates all 4 blocks into a single DataFrame and computes
        an 'intensity' column (25/50/75 percentile bins based on unique level values).
        """
        blocks = ["component_1", "component_2", "component_3", "component_4"]
        block_dfs: list[pd.DataFrame] = []
        for block_number, block in enumerate(blocks, start=1):
            frame = pd.DataFrame(
                {
                    "response": data[block]["response"],
                    "rt": data[block]["responseTime"],
                    level_field: data[block][level_field],
                    "component": block_number,
                    "record_id": record_id,
                }
            )
            block_dfs.append(frame)

        participant_df = pd.concat(block_dfs, ignore_index=True)
        participant_df[level_field] = pd.to_numeric(participant_df[level_field], errors="coerce").round(5)
        unique_values = sorted(participant_df[level_field].dropna().unique().tolist())
        if len(unique_values) >= 4:
            participant_df["intensity"] = participant_df[level_field].replace(
                {unique_values[1]: 25, unique_values[2]: 50, unique_values[3]: 75}
            )
        else:
            participant_df["intensity"] = np.nan
        return participant_df

    def _evaluate_ch_task(self, task_df: pd.DataFrame, intensity_field: str, prefix: str) -> dict[str, list[int]]:
        """Compute QC pass/fail lists for an ACH or VCH dataset.

        Runs a logistic regression of detection (response) ~ intensity for each
        participant.  A valid change-detection task should produce a positive slope
        (more intense stimulus → more detections).

        Returns a dict with three keys (prefix appended to each, e.g. '_vch'):
          'negative{prefix}' : β < 0 (worse detection at higher intensities — fraud)
          'zero{prefix}'     : p > 0.05 (slope not significantly different from zero)
          'fail_first_fifteen{prefix}': < 50% detection rate in first 15 trials
                                        (likely not wearing headphones / not watching)
        """
        if task_df.empty:
            suffix = prefix or ""
            return {
                f"negative{suffix}": [],
                f"zero{suffix}": [],
                f"fail_first_fifteen{suffix}": [],
            }

        detections = task_df[["record_id", intensity_field, "response"]].dropna()
        detection_slopes = self._test_detection_probability(detections, intensity_field)
        first_fifteen = task_df.loc[task_df["trial"] < 16].groupby("record_id").mean(numeric_only=True).reset_index()

        suffix = prefix or ""
        return {
            f"negative{suffix}": to_int_list(detection_slopes.loc[detection_slopes["beta_coefficient"] < 0, "record_id"].tolist()),
            f"zero{suffix}": to_int_list(detection_slopes.loc[detection_slopes["p_value"] > 0.05, "record_id"].tolist()),
            f"fail_first_fifteen{suffix}": to_int_list(first_fifteen.loc[first_fifteen["response"] < 0.5, "record_id"].tolist()),
        }

    def _test_detection_probability(self, detections: pd.DataFrame, intensity_field: str) -> pd.DataFrame:
        """Fit a logistic regression (response ~ intensity) per participant.

        Returns a DataFrame with columns [record_id, p_value, beta_coefficient].
        Records where the model fails to converge receive p_value=1.0 / beta=0.0
        (treated as zero slope — non-significant but not penalised as negative).
        """
        results: list[dict[str, Any]] = []
        for record_id, group in detections.groupby("record_id"):
            try:
                model = smf.logit(formula=f"response ~ {intensity_field}", data=group).fit(disp=0)
            except Exception:
                results.append({"record_id": int(record_id), "p_value": 1.0, "beta_coefficient": 0.0})
                continue
            results.append(
                {
                    "record_id": int(record_id),
                    "p_value": model.pvalues.get(intensity_field, 1.0),
                    "beta_coefficient": model.params.get(intensity_field, 0.0),
                }
            )
        return pd.DataFrame(results)

    def _load_prl_trials(self, df_raw: pd.DataFrame, fraud_list: list[int]) -> pd.DataFrame:
        """Parse all PRL task payloads into a trial-level DataFrame.

        PRL payloads are compressed JSON dicts with a 'data' list (each element is one
        trial row) plus 'recordId' and 'projectId'.  Also handles the older list-of-dicts
        format from early data collection.
        Detects copy-paste fraud via duplicate decision-time sequences across participants.
        Returns a DataFrame with columns: record_id, trial, decisionTime,
        rewardProbChoice, keyChoice, outcome (plus any additional fields in the payload).
        """
        frames: list[pd.DataFrame] = []
        for _, row in df_raw.iterrows():
            record_id = int(row["record_id"])
            task_string = row.get("task_data_prltask", np.nan)
            backup_string = row.get("task_data_prl_bl_retrieved", np.nan)

            if isinstance(task_string, str) and task_string != "testing":
                try:
                    data_array = self._process_prl_json(task_string)
                    frames.append(pd.DataFrame(data_array))
                except Exception as exc:
                    print(f"Error decoding PRL for {record_id}: {exc}")
                    fraud_list.append(record_id)
            elif isinstance(backup_string, str):
                should_process, should_skip = self._validate_retrieved_task_data(backup_string, record_id, "PRL", fraud_list)
                if not should_process:
                    if should_skip:
                        continue
                    continue
                try:
                    data = json.loads(backup_string)
                    if isinstance(data, dict):
                        data["record_id"] = record_id
                        frames.append(pd.DataFrame([data]))
                    elif isinstance(data, list):
                        frame = pd.DataFrame(data)
                        frame["record_id"] = record_id
                        frames.append(frame)
                    else:
                        fraud_list.append(record_id)
                except Exception as exc:
                    print(f"Error parsing retrieved PRL for {record_id}: {exc}")
                    fraud_list.append(record_id)

        if not frames:
            return pd.DataFrame(columns=["record_id", "trial", "decisionTime", "rewardProbChoice", "keyChoice", "outcome"])

        df_prl = pd.concat(frames, ignore_index=True)
        df_prl = df_prl.replace({"fractal1": 1, "fractal2": 2, "fractal3": 3})
        if "choice" in df_prl.columns:
            df_prl["choice"] = pd.to_numeric(df_prl["choice"], errors="coerce")
        df_prl["record_id"] = pd.to_numeric(df_prl["record_id"], errors="coerce").astype(int)
        df_prl = df_prl.reset_index(drop=True)

        try:
            prl_pivot = df_prl.pivot(index="record_id", columns="trial", values="decisionTime")
            duplicates = prl_pivot[prl_pivot.duplicated(keep=False)].index.tolist()
            fraud_list.extend(to_int_list(duplicates))
        except Exception as exc:
            print(f"Error in PRL duplicate-data screen: {exc}")

        return df_prl

    def _process_prl_json(self, compressed_string: str) -> list[dict[str, Any]]:
        """Decompress a PRL payload and return the flat list of trial dicts.

        Attaches 'record_id' and 'projectId' from the outer payload dict to each
        trial row so they are preserved through the concat step.
        """
        data = decode_compressed_json(compressed_string)
        rows = data.get("data", [])
        record_id = data.get("recordId")
        project_id = data.get("projectId")
        for row in rows:
            row["record_id"] = record_id
            row["projectId"] = project_id
        return rows

    def _evaluate_prl(self, df_prl: pd.DataFrame) -> dict[str, list[int]]:
        """Compute QC pass/fail lists for the PRL (Probabilistic Reward Learning) task.

        Returns a dict with three keys:
          'worse_than_chance' : < 34% correct responses (rewardProbChoice == 0.85)
                                (random guessing yields ~50% correct, so this is well
                                 below chance and indicates non-engagement or reversal)
          'non_responders'    : > 10% no-response trials (keyChoice == -999)
          'no_lose_stay'      : < 1% lose-stay behaviour
                                (a real learner should almost never stay after a loss;
                                 near-zero lose-stay means they never switched, i.e.
                                 ignored feedback entirely)
        """
        if df_prl.empty:
            return {"worse_than_chance": [], "non_responders": [], "no_lose_stay": []}

        percent_correct = self._append_percent(df_prl, "rewardProbChoice", 0.85, "%Correct")
        worse_than_chance = to_int_list(
            percent_correct.groupby("record_id")["%Correct"].mean().reset_index().loc[lambda d: d["%Correct"] < 34, "record_id"].tolist()
        )

        percent_no_response = self._append_percent(percent_correct, "keyChoice", -999, "%NoResponse")
        non_responders = to_int_list(
            percent_no_response.groupby("record_id")["%NoResponse"].mean().reset_index().loc[lambda d: d["%NoResponse"] > 10, "record_id"].tolist()
        )

        win_stay_lose_stay: list[str | float] = []
        percent_no_response = percent_no_response.reset_index(drop=True)
        for row_idx in range(len(percent_no_response)):
            current = percent_no_response.loc[row_idx]
            if (
                row_idx == 0
                or current["record_id"] != percent_no_response.loc[row_idx - 1, "record_id"]
                or pd.isna(current["outcome"])
                or percent_no_response.loc[row_idx - 1, "outcome"] == -999
            ):
                win_stay_lose_stay.append(np.nan)
                continue

            previous = percent_no_response.loc[row_idx - 1]
            if previous["outcome"] == 1 and current["rewardProbChoice"] == previous["rewardProbChoice"]:
                win_stay_lose_stay.append("win-stay")
            elif previous["outcome"] == 1 and current["rewardProbChoice"] != previous["rewardProbChoice"]:
                win_stay_lose_stay.append("win-switch")
            elif previous["outcome"] == 0 and current["rewardProbChoice"] != previous["rewardProbChoice"]:
                win_stay_lose_stay.append("lose-switch")
            elif previous["outcome"] == 0 and current["rewardProbChoice"] == previous["rewardProbChoice"]:
                win_stay_lose_stay.append("lose-stay")
            else:
                win_stay_lose_stay.append(np.nan)

        percent_no_response["win_stay_lose_switch"] = win_stay_lose_stay
        percent_no_response = self._append_percent(percent_no_response, "win_stay_lose_switch", "lose-stay", "lose_stay_percent")
        no_lose_stay = to_int_list(
            percent_no_response.groupby("record_id")["lose_stay_percent"].mean().reset_index().loc[lambda d: d["lose_stay_percent"] < 1, "record_id"].tolist()
        )

        return {
            "worse_than_chance": worse_than_chance,
            "non_responders": non_responders,
            "no_lose_stay": no_lose_stay,
        }

    def _append_percent(self, dataframe: pd.DataFrame, column: str, value: Any, new_column: str) -> pd.DataFrame:
        """Compute the per-participant percentage of rows where `column` equals `value`.

        Merges the result back onto the input DataFrame as a new column `new_column`.
        Used to compute %Correct, %NoResponse, and lose_stay_percent for PRL QC.
        """
        matching = dataframe.loc[dataframe[column] == value].groupby("record_id").size()
        total = dataframe.groupby("record_id").size()
        percent = (matching / total) * 100
        return dataframe.merge(percent.reset_index(name=new_column), on="record_id", how="left")

    def _load_spacejunk_trials(self, df_raw: pd.DataFrame, fraud_list: list[int]) -> pd.DataFrame:
        """Parse SpaceJunk game payloads and flag copy-paste duplicates.

        SpaceJunk is a secondary task whose data is collected for offline analysis but
        does not currently trigger any QC failures.  This method loads the data and
        adds any duplicate-reaction-time records to fraud_list for the copy-paste check.
        """
        frames: list[pd.DataFrame] = []
        for _, row in df_raw.iterrows():
            record_id = int(row["record_id"])
            task_string = row.get("task_data_spacejunk_bl", np.nan)
            backup_string = row.get("task_data_spacejunk_bl_retrieved", np.nan)

            if isinstance(task_string, str) and task_string != "testing":
                try:
                    data_array = self._process_prl_json(task_string)
                    frames.append(pd.DataFrame(data_array))
                except Exception as exc:
                    print(f"Error decoding SpaceJunk for {record_id}: {exc}")
                    fraud_list.append(record_id)
            elif isinstance(backup_string, str):
                should_process, should_skip = self._validate_retrieved_task_data(backup_string, record_id, "SpaceJunk", fraud_list)
                if not should_process:
                    if should_skip:
                        continue
                    continue
                try:
                    data = json.loads(backup_string)
                    if isinstance(data, dict):
                        data["record_id"] = record_id
                        frames.append(pd.DataFrame([data]))
                    elif isinstance(data, list):
                        frame = pd.DataFrame(data)
                        frame["record_id"] = record_id
                        frames.append(frame)
                except Exception as exc:
                    print(f"Error parsing retrieved SpaceJunk for {record_id}: {exc}")
                    fraud_list.append(record_id)

        if not frames:
            return pd.DataFrame(columns=["record_id", "trial", "timeToComplete"])

        df_spacejunk = pd.concat(frames, ignore_index=True)
        df_spacejunk["record_id"] = pd.to_numeric(df_spacejunk["record_id"], errors="coerce").astype(int)
        df_spacejunk["trial"] = df_spacejunk.groupby("record_id").cumcount() + 1
        if "level" in df_spacejunk.columns:
            df_spacejunk["trial_thislevel"] = df_spacejunk.groupby(["record_id", "level"]).cumcount() + 1

        try:
            pivoted = df_spacejunk.pivot(index="record_id", columns="trial", values="timeToComplete")
            duplicates = pivoted[pivoted.duplicated(keep=False)].index.tolist()
            fraud_list.extend(to_int_list(duplicates))
        except Exception as exc:
            print(f"Error in SpaceJunk duplicate-data screen: {exc}")

        return df_spacejunk

    # ------------------------------------------------------------------
    # SECTION 5F: Completion update assembly and payment exports
    # ------------------------------------------------------------------

    def _completion_update_fields(self) -> list[str]:
        """Return the list of REDCap field names that the completion QC may write.

        The update DataFrame is built from self.df_og filtered to only these columns.
        Fields that don't exist in the export are silently dropped, so this list can
        include fields that are present in some project versions but not others.
        Includes all replay, reset, and payment fields for all three tasks.
        """
        fields = [
            "record_id",
            "qc_passed",
            "qc_notes",
            "verify_emailed",
            "inconsistent_sp_answers",
            "send_pay_confirm",
            "pay_day_ofweek",
            "employee_name",
            "fraudulent_email_inconsistentanswers",
            "fraudulent_email",
            "fourth_fail",
            "replay_links_ach",
            "replay_links_ach_2",
            "replay_links_ach_3",
            "replay_links_ach_4",
            "replay_links_vch",
            "replay_links_vch_2",
            "replay_links_vch_3",
            "replay_links_vch_4",
            "replay_links_prl",
            "replay_links_prl_2",
            "replay_links_prl_3",
            "replay_links_prl_4",
            "task_data_ach_task_short_baseline",
            "task_data_vch_short_psychedelic_bl",
            "task_data_prltask",
            "task_data_ach_task_short_baseline_complete",
            "task_data_vch_short_psychedelic_bl_complete",
            "task_data_prltask_complete",
            "task_data_auditory_qualifying_task_2",
            "task_data_visual_qualifying_task_2",
            "task_data_auditory_qualifying",
            "task_data_visual_qualifying",
            "ach_replay",
            "ach_replay_2",
            "ach_replay_3",
            "ach_replay_4",
            "vch_replay",
            "vch_replay_2",
            "vch_replay_3",
            "vch_replay_4",
            "prl_replay",
            "prl_replay_2",
            "prl_replay_3",
            "prl_replay_4",
            "headphones_recheck_ah",
            "headphones_type_ah",
            "monitor_recheck_ah",
            "monitor_type_ah",
            "browser_ach",
            "ach_vol_adj_yn",
            "ach_vol_adj_amnt",
            "task_nosave_yn_ach_bl",
            "task_nosave_opt_ach_bl",
            "task_nosave_ach_bl",
            "task_data_ach_bl_retrieved",
            "confirm_ach_tasks",
            "headphones_check",
            "monitor_check",
            "browser_vch",
            "private_place_vch",
            "task_nosave_yn_vch_bl",
            "task_nosave_opt_vch_bl",
            "task_nosave_vch_bl",
            "task_data_vch_bl_retrieved",
            "confirm_vch_tasks",
            "browser_prl",
            "full_screen",
            "task_nosave_yn_prlbl",
            "task_nosave_opt_prlbl",
            "task_nosave_prlbl",
            "task_data_prl_bl_retrieved",
            "confirm_prl_complete",
        ]
        return fields

    def _critical_failure_note(
        self,
        record_id: int,
        qc_lists: dict[str, list[int]],
        absurdity_reasons: dict[int, str],
    ) -> str | None:
        """Return a failure reason string if this record should be hard-failed at baseline.

        Checks qc_lists for the critical failure categories (attention checks, race/age
        mismatch, trap questions, copy-paste fraud, and confirmed absurd SP responses).
        Returns the first matching reason string, or None if no critical failure found.
        The returned string is written to qc_notes and qc_passed is set to 0.
        """
        note_map = {
            "failedAttnCheck": "Failed attention check",
            "failed_new_qc": "Failed race/age consistency QC",
            "failed_trap_questions": "Failed trap/fraud-detection questions (fake drug, dose mismatch, AI copy-paste, or missed attention check)",
            "fraud_copy_paste_ach": "Copy pasted ACH data",
            "fraud_copy_paste_vch": "Copy pasted VCH data",
            "fraud_copy_paste_prl": "Copy pasted PRL data",
            "failed_sp_qc": "Absurd psychedelics responses",
        }
        for key, label in note_map.items():
            if record_id in qc_lists.get(key, []):
                if key == "failed_sp_qc" and record_id in absurdity_reasons:
                    return f"{label}: {absurdity_reasons[record_id]}"
                return label
        return None

    def _verification_needed(
        self,
        record_id: int,
        qc_lists: dict[str, list[int]],
        absurdity_reasons: dict[int, str],
    ) -> str | None:
        """Return a verification reason if this record needs the SP clarification survey.

        Checks for SP response patterns that are suspicious but could reflect genuine
        reporting errors rather than fraud: illogical timeline counts, wrong most-recent
        substance, or blank fields.  If triggered, verify_emailed=1 is set and the
        participant receives a clarification survey.  The record is skipped from future
        QC runs until sp_verify_pass is set by the researcher.
        Returns the first matching reason string, or None if verification is not needed.
        """
        verification_keys = [
            "failed_usetime_qc",
            "illogical_life",
            "illogical_year",
            "wrong_recent",
            "nanresponses",
        ]
        for key in verification_keys:
            if record_id in qc_lists.get(key, []):
                return absurdity_reasons.get(record_id, key.replace("_", " "))
        return None

    def _task_failures_for_record(self, record_id: int, qc_lists: dict[str, list[int]]) -> list[tuple[str, str]]:
        """Return a list of (task_name, fail_reason) for each task this record failed.

        Iterates over TASK_CONFIGS and checks each task's failure_conditions against
        qc_lists.  At most one failure reason is returned per task (the first match).
        Returns an empty list if the record passed all tasks.
        """
        failures: list[tuple[str, str]] = []
        for task_name, config in TASK_CONFIGS.items():
            for condition in config.failure_conditions:
                if record_id in qc_lists.get(condition, []):
                    failures.append((task_name, condition.replace("_", " ")))
                    break
        return failures

    def _replay_attempt_number(self, row: pd.Series, replay_fields: list[str]) -> int:
        """Return the attempt number (1-based) for the next replay of a failed task.

        Counts how many replay_fields are already filled (non-NaN) to determine which
        replay slot is next.  Used for the failed-task JSON log so we can track which
        attempt a given payload belongs to.
        """
        count = 1
        for field in replay_fields:
            if field in row.index and pd.notna(row[field]):
                count += 1
        return count

    def _queue_task_retry(self, update_df: pd.DataFrame, record_id: int, config: TaskConfig) -> None:
        """Set up the next replay attempt for a failed task in the update DataFrame.

        Finds the first unfilled replay slot (e.g. ach_replay_2 if ach_replay already=1)
        and sets both the replay flag and the matching replay_links field to 1.
        Then clears the task payload field and all reset_cols (headphone check, browser
        field, nosave fields, etc.) so the participant re-does the pre-task checklist.
        If all 4 slots are exhausted, sets fourth_fail=1 instead of a replay link.
        """
        row = update_df.loc[update_df["record_id"] == record_id].reset_index(drop=True)
        if row.empty:
            return
        current = row.iloc[0]
        next_index = 0
        for idx, field in enumerate(config.replay_fields):
            if field in current.index and pd.notna(current[field]):
                next_index = idx + 1

        if next_index < len(config.replay_fields):
            replay_field = config.replay_fields[next_index]
            if replay_field in update_df.columns:
                update_df.loc[update_df["record_id"] == record_id, replay_field] = 1

            template_field = config.template_fields[min(next_index, len(config.template_fields) - 1)]
            if template_field in update_df.columns:
                update_df.loc[update_df["record_id"] == record_id, template_field] = 1
        elif "fourth_fail" in update_df.columns:
            update_df.loc[update_df["record_id"] == record_id, "fourth_fail"] = 1

        if config.task_col in update_df.columns:
            update_df.loc[update_df["record_id"] == record_id, config.task_col] = np.nan
        if config.backup_col in update_df.columns:
            update_df.loc[update_df["record_id"] == record_id, config.backup_col] = np.nan

        for field in config.reset_cols:
            if field in update_df.columns:
                update_df.loc[update_df["record_id"] == record_id, field] = np.nan

    def _task_payload_for_export(self, row: pd.Series, config: TaskConfig) -> str:
        """Return the raw task payload string for a record (primary or backup field).

        Used when logging a failed task to FAILED_JSON_PATH so the raw data is
        preserved before the task field is cleared for replay.
        """
        primary = row.get(config.task_col, np.nan)
        if isinstance(primary, str):
            return primary
        backup = row.get(config.backup_col, np.nan)
        if isinstance(backup, str):
            return backup
        return ""

    def _apply_record_updates(self, update_df: pd.DataFrame, record_id: int, updates: dict[str, Any]) -> None:
        """Write a dict of {field: value} updates into the update DataFrame for one record.

        Silently skips fields that don't exist as columns in the DataFrame.
        """
        for field, value in updates.items():
            if field in update_df.columns:
                update_df.loc[update_df["record_id"] == record_id, field] = value

    def _append_failed_json_rows(self, rows: list[dict[str, Any]]) -> int:
        """Append failed-task records to the shared-drive CSV log and return the count.

        Creates the CSV if it doesn't exist.  Each row contains record_id, task name,
        fail reason, attempt number, and the raw JSON payload string for offline analysis.
        """
        if not rows:
            return 0

        if FAILED_JSON_PATH.exists():
            existing = pd.read_csv(FAILED_JSON_PATH)
        else:
            existing = pd.DataFrame(columns=["record_id", "task", "fail_reason", "fail_attempt", "json_string"])

        appended = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)
        appended.to_csv(FAILED_JSON_PATH, index=False)
        return len(rows)

    def _build_baseline_expensesheet(self, update_df: pd.DataFrame) -> Path | None:
        """Generate a CSV expense sheet for all baseline records that passed QC.

        Reads qc_passed from the update DataFrame and pulls participant details from
        self.df.  Each passing record becomes one row in the expense sheet with the
        date of participation (latest instrument completion date), payment amount ($50),
        payment type (Amazon gift card), and delivery email (email_rpt).
        Saves to today's date directory.  Returns the path, or None if no payments.
        """
        assert self.df is not None
        payment_rows: list[pd.DataFrame] = []

        for _, update_row in update_df.iterrows():
            record_id = int(update_row["record_id"])
            if numeric_value(update_row, "qc_passed") != 1:
                continue

            source = self.df.loc[self.df["record_id"] == record_id].reset_index(drop=True)
            if source.empty:
                continue
            row = source.iloc[0]

            payment_email = clean_email(row.get("email_rpt", np.nan))
            if not payment_email:
                print(f"Record {record_id} passed QC but is missing email_rpt.")
                continue

            payment_rows.append(
                pd.DataFrame(
                    {
                        "Date of Participation:  (month/day/year)": [latest_completion_date(row, BASELINE_DATE_FIELDS)],
                        "Date of Payment:          (month/day/year)": [""],
                        "Name of Yale Researcher requesting payment:": [self.user_name],
                        "Name of Yale Researcher providing payment:": ["Catalina Mourgues"],
                        "Amount of Payment:      (in USD)": ["$50"],
                        "Subject ID #:": [record_id],
                        "Type of Participation or Assessment Point:            **Use the same verbiage as referenced in the HIC Economic Considerations**                                                           List all activities separately, including parking, miles, food or incidentals.": [
                            "Completion of Aim 8; baseline session"
                        ],
                        "Type of Payment:      (Cash, Gift Card, etc.)": ["Amazon.com US electronic gift card"],
                        "Delivery Detail (email, address)": [payment_email],
                        "Payment Instrument Link": [string_value(row, "payment_url")],
                        "Comments /Confirmation": [np.nan],
                    }
                )
            )

        if not payment_rows:
            return None

        expensesheet = pd.concat(payment_rows, ignore_index=True)
        expensesheet_path = self.date_directory / f"expensesheet_{datetime.now().strftime('%Y-%m-%d')}.csv"
        expensesheet.to_csv(expensesheet_path, index=False)
        return expensesheet_path

    def _write_completion_summary(
        self,
        qc_lists: dict[str, list[int]],
        update_df: pd.DataFrame,
        expensesheet_path: Path | None,
        failed_json_count: int,
    ) -> None:
        """Write a markdown summary of the baseline completion QC to today's date directory.

        Saved as completion_qc_summary.md.  Lists record counts and all non-empty QC
        lists (zero, negative, failed_sp_qc, etc.) for a quick post-run audit.
        """
        summary_path = self.date_directory / "completion_qc_summary.md"
        lines = [
            "# Completion QC Summary",
            "",
            f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
            f"- Records reviewed: {len(self.records_to_check)}",
            f"- QC passed: {int((pd.to_numeric(update_df.get('qc_passed', pd.Series(dtype=float)), errors='coerce') == 1).sum())}",
            f"- Failed-task JSON rows appended: {failed_json_count}",
            f"- Expensesheet: {expensesheet_path if expensesheet_path else 'none'}",
            "",
            "## QC Lists",
        ]
        for key, values in sorted(qc_lists.items()):
            if values:
                lines.append(f"- {key}: {sorted(set(values))}")
        if lines[-1] == "## QC Lists":
            lines.append("- none")
        summary_path.write_text("\n".join(lines))

    # ------------------------------------------------------------------
    # SECTION 5G: Flag files
    # ------------------------------------------------------------------

    def _manual_tasks_needed(self, update_df: pd.DataFrame) -> bool:
        """Return True if any record in the update DataFrame has a manual follow-up action.

        Manual actions include: replay invitation links set, fraudulent flags set, or
        fourth_fail set.  Determines whether to create a TASKS_FULLRECORDS_INCOMPLETE
        flag that must be manually resolved before the next QC run.
        """
        manual_fields = [
            "fraudulent_email_inconsistentanswers",
            "fraudulent_email",
            "inconsistent_sp_answers",
            "fourth_fail",
            "replay_links_ach",
            "replay_links_ach_2",
            "replay_links_ach_3",
            "replay_links_ach_4",
            "replay_links_vch",
            "replay_links_vch_2",
            "replay_links_vch_3",
            "replay_links_vch_4",
            "replay_links_prl",
            "replay_links_prl_2",
            "replay_links_prl_3",
            "replay_links_prl_4",
        ]
        for field in manual_fields:
            if field in update_df.columns and pd.to_numeric(update_df[field], errors="coerce").fillna(0).gt(0).any():
                return True
        return False

    def _generate_flag_files(self, expensesheet_needed: bool, manual_tasks_needed: bool) -> None:
        """Write the initial set of flag files for today's QC run to the date directory.

        Flag files are plain text files whose names encode the state of each workflow
        step.  Another researcher (or a future QC run) checks these to know what is
        still outstanding.  Naming convention: <STEP>_INCOMPLETE.txt (needs action) or
        <STEP>_NA.txt (not applicable today).  Completed steps become <STEP>_COMPLETE.txt
        via _update_redcap_flag().

        Flags written:
          REDCAP_SCREENS_INCOMPLETE — screening imports need to be pushed to REDCap
          REDCAP_FULLRECORDS_INCOMPLETE — baseline imports need to be pushed to REDCap
          TASKS_FULLRECORDS_INCOMPLETE — replay emails / fraud follow-ups still pending
          PAYMENTS_FULLRECORDS_INCOMPLETE — expense sheet not yet uploaded to SharePoint
        """
        ensure_directory(self.date_directory)

        if self.records_to_screen:
            (self.date_directory / "REDCAP_SCREENS_INCOMPLETE.txt").write_text(self.user_name)
        else:
            (self.date_directory / "REDCAP_SCREENS_NA.txt").write_text(self.user_name)

        if self.records_to_check:
            (self.date_directory / "REDCAP_FULLRECORDS_INCOMPLETE.txt").write_text(self.user_name)
            if manual_tasks_needed:
                (self.date_directory / "TASKS_FULLRECORDS_INCOMPLETE.txt").write_text(self.user_name)
            else:
                (self.date_directory / "TASKS_FULLRECORDS_NA.txt").write_text(self.user_name)
            if expensesheet_needed:
                (self.date_directory / "PAYMENTS_FULLRECORDS_INCOMPLETE.txt").write_text(self.user_name)
            else:
                (self.date_directory / "PAYMENTS_FULLRECORDS_NA.txt").write_text(self.user_name)
        else:
            (self.date_directory / "TASKS_FULLRECORDS_NA.txt").write_text(self.user_name)
            (self.date_directory / "REDCAP_FULLRECORDS_NA.txt").write_text(self.user_name)
            (self.date_directory / "PAYMENTS_FULLRECORDS_NA.txt").write_text(self.user_name)

    def _update_redcap_flag(self, flag_name: str) -> None:
        """Rename an INCOMPLETE flag file to COMPLETE after its step is done.

        Called after import_screening_updates() and import_completion_updates() to
        signal that the REDCap push succeeded.  No-ops if the flag file doesn't exist.
        """
        incomplete_path = self.date_directory / f"{flag_name}.txt"
        if not incomplete_path.exists():
            return
        complete_path = self.date_directory / incomplete_path.name.replace("INCOMPLETE", "COMPLETE")
        incomplete_path.unlink()
        complete_path.write_text(self.user_name)

    def mark_payments_complete(self) -> None:
        self._complete_task_flag(
            "PAYMENTS_FULLRECORDS_INCOMPLETE",
            "Have you uploaded payments and emailed the payment contact? Type 'yes' to confirm: ",
        )

    def mark_tasks_complete(self) -> None:
        self._complete_task_flag(
            "TASKS_FULLRECORDS_INCOMPLETE",
            "Have you sent all non-payment follow-up emails and finished any manual QC tasks? Type 'yes' to confirm: ",
        )

    def _complete_task_flag(self, flag_name: str, prompt: str) -> None:
        incomplete_path = self.date_directory / f"{flag_name}.txt"
        if not incomplete_path.exists():
            print(f"No {flag_name} flag found.")
            return
        if not ask_yes_no(prompt):
            print(f"Leaving {flag_name} incomplete.")
            return
        complete_path = self.date_directory / incomplete_path.name.replace("INCOMPLETE", "COMPLETE")
        incomplete_path.unlink()
        complete_path.write_text(self.user_name)
        print(f"Marked {flag_name} complete.")


# ============================================================================
# SECTION 6: Pandas Helpers
# ============================================================================


def nonempty_task_series(df: pd.DataFrame, primary_field: str, backup_field: str | None = None) -> pd.Series:
    """Return a boolean Series indicating which rows have a non-empty task payload.

    Vectorised version of nonempty_task_value() for use in DataFrame masks.
    Used by _identify_completed_baseline_records() to check whether ACH/VCH/PRL
    data has been submitted before adding a record to the baseline review queue.
    """
    primary = df[primary_field].apply(lambda value: isinstance(value, str) and value.strip()) if primary_field in df.columns else pd.Series(False, index=df.index)
    if backup_field and backup_field in df.columns:
        backup = df[backup_field].apply(lambda value: isinstance(value, str) and value.strip())
        return primary | backup
    return primary


# ============================================================================
# SECTION 7: Simple CLI Entry Point
# ============================================================================


def main() -> None:
    user_code = input("Who is using the script? m, kayla, or gabby? ").strip().lower()
    tool = RelaunchQuickQC(user_code).load()
    tool.print_dashboard()

    if tool.records_to_screen:
        review = tool.prepare_screening_review()
        verdicts = tool.collect_phone_verdicts(review)
        screening_updates = tool.build_screening_updates(review, verdicts)
        if ask_yes_no("Import screening updates to REDCap? Type 'yes' to confirm: "):
            tool.import_screening_updates(screening_updates)
        else:
            print("Skipped REDCap screening import.")

    completion_review = tool.run_completion_qc()
    if completion_review.records_to_check:
        print(f"\nQC reviewed {len(completion_review.records_to_check)} completed baseline records.")
        if completion_review.expensesheet_path:
            print(f"Expensesheet written to: {completion_review.expensesheet_path}")
        if ask_yes_no("Import completion QC updates to REDCap? Type 'yes' to confirm: "):
            tool.import_completion_updates(completion_review)
        else:
            print("Skipped REDCap completion import.")


if __name__ == "__main__":
    main()
