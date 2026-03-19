#!/usr/bin/env python3
"""Baseline + screening QC tool for the Aim 8 relaunch project.

This script is a readable replacement for the old
`quickQC_api_calling_v6_OnlyLongitudinal.ipynb` baseline notebook.

Scope of this draft:
- handle new screening records that need fraud review before `screening_pass`
- handle newly completed baseline records that need QC and payment export
- preserve the baseline ACH / VCH / PRL QC logic from the old notebook
- remove Yale, cannabis, old longitudinal-waiting, and non-Amazon payment paths

Still intentionally out of scope for this draft:
- per-timepoint follow-up QC/payment after hyperacute / acute / subacute / persisting
- full replacement of every legacy admin alert/template field
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
BASELINE_API_TOKEN = os.getenv("AIM8_BASELINE_API_TOKEN", "1D481003114ECDA8E4077078E0D08D0A")
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
    "payment_email_bl",
    "payment_email_bl_2",
    "email_addtl_contact",
    "email_rpt",
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
    records_to_screen: list[int]
    screen_df: pd.DataFrame
    ip_df: pd.DataFrame
    hard_fail: list[int] = field(default_factory=list)
    suspicious_ip: list[int] = field(default_factory=list)
    phone_review: list[int] = field(default_factory=list)
    manual_followup: list[int] = field(default_factory=list)
    ineligibility_notes: dict[int, str] = field(default_factory=dict)


@dataclass
class CompletionReview:
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
    return input(prompt).strip().lower() == "yes"


def clean_email(value: Any) -> str | None:
    if pd.isna(value):
        return None
    email = str(value).strip().lower()
    return email or None


def numeric_value(row: pd.Series, field: str) -> float:
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
    if field not in row.index or pd.isna(row[field]):
        return ""
    return str(row[field]).strip()


def add_reason(reason_map: dict[int, str], record_id: int, reason: str) -> None:
    existing = reason_map.get(record_id, "")
    combined = f"{existing}; {reason}" if existing else reason
    reason_map[record_id] = combined


def field_exists(df: pd.DataFrame, field: str) -> bool:
    return field in df.columns


def to_int_list(values: list[Any]) -> list[int]:
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
    if primary_field in row.index and isinstance(row[primary_field], str) and row[primary_field].strip():
        return True
    if backup_field and backup_field in row.index and isinstance(row[backup_field], str) and row[backup_field].strip():
        return True
    return False


def latest_completion_date(row: pd.Series, date_fields: list[str]) -> str:
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
    decoded = base64.b64decode(compressed_string)
    decompressed = gzip.decompress(decoded).decode("utf-8")
    return json.loads(decompressed)


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


# ============================================================================
# SECTION 4: Task QC Configuration
# ============================================================================


@dataclass
class TaskConfig:
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
        self._check_incomplete_flags(QC_TODO_PATH)
        ensure_directory(self.date_directory)

        self.project = Project(REDCAP_API_URL, BASELINE_API_TOKEN)
        raw_df = self.project.export_records(format_type="df").reset_index(names="record_id")
        self.metadata = self.project.export_metadata(format_type="df")
        self.df = self._clean_export(raw_df)
        self.df_og = self.df.copy()

        self.records_to_screen = self._identify_screening_records()
        self.records_to_check = self._identify_completed_baseline_records()
        return self

    def print_dashboard(self) -> None:
        print(f"Loaded Aim 8 relaunch QC as {self.user_name}")
        print(f"Screening records waiting for fraud review: {len(self.records_to_screen)}")
        print(f"Completed baseline records waiting for QC/payment: {len(self.records_to_check)}")
        if not self.records_to_screen and not self.records_to_check:
            print("Nothing to do today.")

    def _clean_export(self, raw_df: pd.DataFrame) -> pd.DataFrame:
        df = raw_df.copy()

        if df["record_id"].dtype == object:
            test_mask = df["record_id"].isin(TEST_RECORDS)
            df = df.loc[~test_mask].copy()

        df["record_id"] = pd.to_numeric(df["record_id"], errors="coerce")
        df = df.loc[df["record_id"].notna()].copy()
        df["record_id"] = df["record_id"].astype(int)

        if "replay_email" in df.columns:
            df["replay_email"] = df["replay_email"].fillna("NO EMAIL GIVEN")

        if "student_yn" in df.columns:
            df["student_yn"] = pd.to_numeric(df["student_yn"], errors="coerce").fillna(0).astype(int)

        # Old hard-coded exclusions carried over from the notebook reference.
        df = df.loc[~df["record_id"].isin({456, 654})].copy()

        return df.reset_index(drop=True)

    def _identify_screening_records(self) -> list[int]:
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

        self._write_screening_summary(review)
        return review

    def collect_phone_verdicts(self, review: ScreeningReview) -> dict[int, str]:
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

            while True:
                prompt = (
                    f"Record {record_id}\n"
                    f"Phone: {phone}\n"
                    f"IP: {ip_text}\n"
                    "Enter 'y' if fraudulent/VOIP, 'n' if clear, '?' if Max should review: "
                )
                verdict = input(prompt).strip().lower()
                if verdict in {"y", "n", "?"}:
                    verdicts[record_id] = verdict
                    break
                print("Please enter only 'y', 'n', or '?'.")

        return verdicts

    def build_screening_updates(self, review: ScreeningReview, phone_verdicts: dict[int, str]) -> pd.DataFrame:
        assert self.df is not None

        updates = self.df.loc[self.df["record_id"].isin(review.records_to_screen)].copy()
        if updates.empty:
            return updates

        pass_go = [record_id for record_id, verdict in phone_verdicts.items() if verdict == "n"]
        hard_fail = set(review.hard_fail)
        hard_fail.update(record_id for record_id, verdict in phone_verdicts.items() if verdict == "y")
        manual_followup = set(review.manual_followup)
        manual_followup.update(record_id for record_id, verdict in phone_verdicts.items() if verdict == "?")

        updates.loc[updates["record_id"].isin(hard_fail), ["screening_pass", "qc_passed"]] = 0
        if "ineligibile_fraud" in updates.columns:
            updates.loc[updates["record_id"].isin(hard_fail), "ineligibile_fraud"] = 1

        updates.loc[updates["record_id"].isin(pass_go), "screening_pass"] = 1
        if "eligible_notify" in updates.columns:
            updates.loc[updates["record_id"].isin(pass_go), "eligible_notify"] = 1
        if "ip_zoom_invite" in updates.columns:
            updates.loc[updates["record_id"].isin(review.suspicious_ip), "ip_zoom_invite"] = 1
        if "max_number_followup" in updates.columns:
            updates.loc[updates["record_id"].isin(manual_followup), "max_number_followup"] = 1

        if "ineligibilty_reason" in updates.columns:
            for record_id, reason in review.ineligibility_notes.items():
                updates.loc[updates["record_id"] == record_id, "ineligibilty_reason"] = reason

        desired_fields = [
            "screening_pass",
            "qc_passed",
            "eligible_notify",
            "ineligibile_fraud",
            "ip_zoom_invite",
            "max_number_followup",
            "ineligibilty_reason",
            "record_id",
        ]
        desired_fields = [field for field in desired_fields if field in updates.columns]
        updates = updates[desired_fields].copy()

        for field in ["screening_pass", "qc_passed", "eligible_notify", "ineligibile_fraud", "ip_zoom_invite", "max_number_followup"]:
            if field in updates.columns:
                updates[field] = pd.to_numeric(updates[field], errors="coerce").astype("Int64")

        return updates

    def import_screening_updates(self, updates: pd.DataFrame) -> None:
        assert self.project is not None
        if updates.empty:
            print("No screening updates to import.")
            return
        self.project.import_records(to_import=updates, import_format="df")
        self._update_redcap_flag("REDCAP_SCREENS_INCOMPLETE")
        print(f"Imported screening updates for {len(updates)} records.")

    def _load_and_update_ip_database(self, records_to_screen: list[int]) -> pd.DataFrame:
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
            ]

            if not pd.isna(numeric_value(row, "sp_lastuse_days_screen")) and numeric_value(row, "sp_lastuse_days_screen") < 42:
                checks.append((True, "Reported SP/atypical use within the last 42 days"))

            for failed, reason in checks:
                if failed:
                    add_reason(review.ineligibility_notes, record_id, reason)
                    review.hard_fail.append(record_id)

    def _apply_duplicate_identity_checks(self, review: ScreeningReview) -> None:
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
            "failed_sp_qc": to_int_list(sp_findings["failed_sp_qc"]),
            "failed_usetime_qc": to_int_list(sp_findings["failed_usetime_qc"]),
            "illogical_year": to_int_list(sp_findings["illogical_year"]),
            "illogical_life": to_int_list(sp_findings["illogical_life"]),
            "wrong_recent": to_int_list(sp_findings["wrong_recent"]),
            "nanresponses": to_int_list(sp_findings["nanresponses"]),
            "nanresponses_screen": to_int_list(sp_findings["nanresponses_screen"]),
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
        attn_fields = ["attn_check_surveybl", "attn_check_surveybl2", "attn_check_surveybl3", "attn_check_surveybl4"]
        existing = [field for field in attn_fields if field in df_raw.columns]
        if not existing:
            return []
        totals = df_raw[existing].apply(pd.to_numeric, errors="coerce").sum(axis=1)
        return to_int_list(df_raw.loc[totals < len(existing), "record_id"].tolist())

    def _find_race_age_mismatch(self, df_raw: pd.DataFrame) -> list[int]:
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
        findings = {
            "failed_sp_qc": [],
            "failed_usetime_qc": [],
            "illogical_year": [],
            "illogical_life": [],
            "wrong_recent": [],
            "nanresponses": [],
            "nanresponses_screen": [],
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
        findings["nanresponses_screen"] = to_int_list(df_finished.loc[df_finished["sp_lastuse_days_screen"].isna(), "record_id"].tolist())

        df_finished = df_finished.loc[
            ~df_finished["record_id"].isin(findings["nanresponses"] + findings["nanresponses_screen"])
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
        data = decode_compressed_json(compressed_string)
        rows = data.get("data", [])
        record_id = data.get("recordId")
        project_id = data.get("projectId")
        for row in rows:
            row["record_id"] = record_id
            row["projectId"] = project_id
        return rows

    def _evaluate_prl(self, df_prl: pd.DataFrame) -> dict[str, list[int]]:
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
        matching = dataframe.loc[dataframe[column] == value].groupby("record_id").size()
        total = dataframe.groupby("record_id").size()
        percent = (matching / total) * 100
        return dataframe.merge(percent.reset_index(name=new_column), on="record_id", how="left")

    def _load_spacejunk_trials(self, df_raw: pd.DataFrame, fraud_list: list[int]) -> pd.DataFrame:
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
        note_map = {
            "failedAttnCheck": "Failed attention check",
            "failed_new_qc": "Failed race/age consistency QC",
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
        verification_keys = [
            "failed_usetime_qc",
            "illogical_life",
            "illogical_year",
            "wrong_recent",
            "nanresponses",
            "nanresponses_screen",
        ]
        for key in verification_keys:
            if record_id in qc_lists.get(key, []):
                return absurdity_reasons.get(record_id, key.replace("_", " "))
        return None

    def _task_failures_for_record(self, record_id: int, qc_lists: dict[str, list[int]]) -> list[tuple[str, str]]:
        failures: list[tuple[str, str]] = []
        for task_name, config in TASK_CONFIGS.items():
            for condition in config.failure_conditions:
                if record_id in qc_lists.get(condition, []):
                    failures.append((task_name, condition.replace("_", " ")))
                    break
        return failures

    def _replay_attempt_number(self, row: pd.Series, replay_fields: list[str]) -> int:
        count = 1
        for field in replay_fields:
            if field in row.index and pd.notna(row[field]):
                count += 1
        return count

    def _queue_task_retry(self, update_df: pd.DataFrame, record_id: int, config: TaskConfig) -> None:
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
        primary = row.get(config.task_col, np.nan)
        if isinstance(primary, str):
            return primary
        backup = row.get(config.backup_col, np.nan)
        if isinstance(backup, str):
            return backup
        return ""

    def _apply_record_updates(self, update_df: pd.DataFrame, record_id: int, updates: dict[str, Any]) -> None:
        for field, value in updates.items():
            if field in update_df.columns:
                update_df.loc[update_df["record_id"] == record_id, field] = value

    def _append_failed_json_rows(self, rows: list[dict[str, Any]]) -> int:
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

            payment_email = clean_email(row.get("payment_email_bl", np.nan))
            if not payment_email:
                print(f"Record {record_id} passed QC but is missing payment_email_bl.")
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
