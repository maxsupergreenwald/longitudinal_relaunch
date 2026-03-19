#!/usr/bin/env python3
"""Repeated-measures follow-up QC/payment tool for the Aim 8 relaunch project.

This script is a readable replacement for the old
`quickQC_rpt_apicalls.ipynb` repeated-measures notebook.

Scope of this draft:
- handle completed hyperacute / acute / subacute / persisting sessions
- preserve the notebook's main task QC logic for ACH, VCH, and PRL
- preserve the notebook's narrow auto-block rules for follow-up payments
- convert follow-up payments to Amazon-only $50 exports
- write a markdown summary that makes manual follow-up steps obvious
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from redcap import Project

from quickQC_api_calling_v7_relaunch import (
    QC_TODO_PATH,
    REDCAP_API_URL,
    SHAREPOINT_PAYMENT_UPLOAD_URL,
    USER_NAMES,
    ask_yes_no,
    clean_email,
    decode_compressed_json,
    ensure_directory,
    field_exists,
    string_value,
    to_int_list,
)


# ============================================================================
# SECTION 1: Project Configuration
# ============================================================================

RPT_API_TOKEN = os.getenv("AIM8_RPT_API_TOKEN", "66785AFE5341D3F73B4F518339C60186")
RPT_DECODER_PATH = Path(
    os.getenv(
        "AIM8_RPT_DECODER_PATH",
        "/Users/msg74/Desktop/powers_lab/Analysis/Aim1_rpt/data/resources/"
        "RptRandomizationDecoder_transformed_intNotString.xlsx",
    )
)

PAYMENT_AMOUNT = "$50"
PAYMENT_TYPE = "Amazon.com US electronic gift card"

TIMEPOINT_ORDER = ["hyp", "acu", "sub", "pers"]
TIMEPOINT_INFO = {
    "hyp": {
        "label": "Hyperacute",
        "timepoint_number": 1,
        "browser_field": "browser_hyp",
        "payment_date_field": "payment_date_hyp",
        "payment_type_field": "payment_type_hyp",
        "payment_amount_field": "payment_amount_hyp",
        "payment_url_field": "payment_url_hyp",
        "timestamp_field": "timestamp_hyp_post",
        "qc_pass_field": "qc_passed_hyp",
        "qc_bad_data_field": "qc_bad_data_hyp",
        "qc_bad_reason_field": "qc_bad_reason_hyp",
        "send_pay_confirm_field": "send_pay_confirm_hyp",
        "event_label": "Completion of Aim 8; hyperacute timepoint",
    },
    "acu": {
        "label": "Acute",
        "timepoint_number": 2,
        "browser_field": "browser_acu",
        "payment_date_field": "payment_date_acu",
        "payment_type_field": "payment_type_acu",
        "payment_amount_field": "payment_amount_acu",
        "payment_url_field": "payment_url_acu",
        "timestamp_field": "timestamp_acu_post",
        "qc_pass_field": "qc_passed_acu",
        "qc_bad_data_field": "qc_bad_data_acu",
        "qc_bad_reason_field": "qc_bad_reason_acu",
        "send_pay_confirm_field": "send_pay_confirm_acu",
        "event_label": "Completion of Aim 8; acute timepoint",
    },
    "sub": {
        "label": "Subacute",
        "timepoint_number": 3,
        "browser_field": "browser_sub",
        "payment_date_field": "payment_date_sub",
        "payment_type_field": "payment_type_sub",
        "payment_amount_field": "payment_amount_sub",
        "payment_url_field": "payment_url_sub",
        "timestamp_field": "timestamp_sub_post",
        "qc_pass_field": "qc_passed_sub",
        "qc_bad_data_field": "qc_bad_data_sub",
        "qc_bad_reason_field": "qc_bad_reason_sub",
        "send_pay_confirm_field": "send_pay_confirm_sub",
        "event_label": "Completion of Aim 8; subacute timepoint",
    },
    "pers": {
        "label": "Persisting",
        "timepoint_number": 4,
        "browser_field": "browser_pers",
        "payment_date_field": "payment_date_pers",
        "payment_type_field": "payment_type_pers",
        "payment_amount_field": "payment_amount_pers",
        "payment_url_field": "payment_url_pers",
        "timestamp_field": "timestamp_pers_post",
        "qc_pass_field": "qc_passed_pers",
        "qc_bad_data_field": "qc_bad_data_pers",
        "qc_bad_reason_field": "qc_bad_reason_pers",
        "send_pay_confirm_field": "send_pay_confirm_pers",
        "event_label": "Completion of Aim 8; persisting timepoint",
    },
}

RETRIEVED_FIELD_PATTERNS = {
    "ach": "task_data_ach_retrieved_{slot}_{timepoint}",
    "vch": "task_data_vch_retrieved_{slot}_{timepoint}",
    "prl": "task_data_prl_retrieved_{slot}_{timepoint}",
}


# ============================================================================
# SECTION 2: Data Containers
# ============================================================================


@dataclass
class TimepointReview:
    pending_records: list[int] = field(default_factory=list)
    ready_for_payment: list[int] = field(default_factory=list)
    qc_failed: list[int] = field(default_factory=list)
    missing_payment_email: list[int] = field(default_factory=list)
    blocking_reasons: dict[int, list[str]] = field(default_factory=dict)
    warning_notes: dict[int, list[str]] = field(default_factory=dict)
    qc_lists: dict[str, list[int]] = field(default_factory=dict)


@dataclass
class RepeatedMeasuresReview:
    results_by_timepoint: dict[str, TimepointReview]
    update_df: pd.DataFrame
    update_fields: list[str]
    expensesheet_path: Path | None
    summary_path: Path | None


# ============================================================================
# SECTION 3: Small Utility Helpers
# ============================================================================


def nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and value.strip() not in {"", "testing", "TESTING", "EXCUSED"}


def first_nonempty_value(values: list[Any]) -> str | None:
    for value in values:
        if nonempty_text(value):
            return str(value)
    return None


def extract_redcap_date(date_string: str) -> str:
    if not date_string:
        return datetime.now().strftime("%m/%d/%Y")
    clean_string = str(date_string).split(" ", 1)[0]
    try:
        return datetime.strptime(clean_string, "%Y-%m-%d").strftime("%m/%d/%Y")
    except ValueError:
        return datetime.now().strftime("%m/%d/%Y")


# ============================================================================
# SECTION 4: Main Tool Class
# ============================================================================


class RepeatedMeasuresQuickQC:
    def __init__(self, user_code: str):
        user_key = user_code.strip().lower()
        if user_key not in USER_NAMES:
            allowed = ", ".join(USER_NAMES)
            raise ValueError(f"Unrecognized user '{user_code}'. Allowed values: {allowed}")

        self.user_code = user_key
        self.user_name = USER_NAMES[user_key]
        self.project: Project | None = None
        self.df: pd.DataFrame | None = None
        self.decoder_map: dict[int, dict[int, str]] = {}
        self.pending_by_timepoint: dict[str, list[int]] = {timepoint: [] for timepoint in TIMEPOINT_ORDER}
        self.date_directory = QC_TODO_PATH / datetime.now().strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # SECTION 4A: Project loading and queue detection
    # ------------------------------------------------------------------

    def load(self) -> "RepeatedMeasuresQuickQC":
        ensure_directory(self.date_directory)

        self.project = Project(REDCAP_API_URL, RPT_API_TOKEN)
        raw_df = self.project.export_records(format_type="df").reset_index(names="record_id")
        self.df = self._clean_export(raw_df)
        self.decoder_map = self._load_decoder()
        self.df = self._materialize_timepoint_task_payloads(self.df)
        self.pending_by_timepoint = self._identify_pending_records()
        return self

    def print_dashboard(self) -> None:
        assert self.df is not None

        total_pending = sum(len(records) for records in self.pending_by_timepoint.values())
        print(f"Loaded Aim 8 repeated-measures QC as {self.user_name}")
        print(f"Follow-up session reviews waiting for QC/payment: {total_pending}")
        for timepoint in TIMEPOINT_ORDER:
            print(f"  {TIMEPOINT_INFO[timepoint]['label']}: {len(self.pending_by_timepoint[timepoint])}")
        if total_pending == 0:
            print("No repeated-measures sessions are waiting for QC/payment.")

    def _clean_export(self, raw_df: pd.DataFrame) -> pd.DataFrame:
        df = raw_df.copy()
        df["record_id"] = pd.to_numeric(df["record_id"], errors="coerce")
        df = df.loc[df["record_id"].notna()].copy()
        df["record_id"] = df["record_id"].astype(int)
        df = df.loc[df["record_id"] > 67].copy()
        df = df.replace({"EXCUSED": np.nan}, regex=True)
        df = df.drop(columns=[column for column in df.columns if "fisher" in column], errors="ignore")
        return df.reset_index(drop=True)

    def _load_decoder(self) -> dict[int, dict[int, str]]:
        if not RPT_DECODER_PATH.exists():
            raise RuntimeError(f"Randomization decoder not found at {RPT_DECODER_PATH}")

        decoder = pd.read_excel(RPT_DECODER_PATH)
        needed_columns = {"random_rpt", 2, 3, 4, 5}
        missing = needed_columns - set(decoder.columns)
        if missing:
            raise RuntimeError(f"Decoder is missing required columns: {sorted(missing)}")

        decoder[[2, 3, 4, 5]] = decoder[[2, 3, 4, 5]].replace({2: "hyp", 3: "acu", 4: "sub", 5: "pers"})
        decoder_map: dict[int, dict[int, str]] = {}
        for _, row in decoder.iterrows():
            decoder_map[int(row["random_rpt"])] = {
                2: str(row[2]),
                3: str(row[3]),
                4: str(row[4]),
                5: str(row[5]),
            }
        return decoder_map

    def _materialize_timepoint_task_payloads(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        for timepoint in TIMEPOINT_ORDER:
            for task_prefix in ["ach", "vch", "prl"]:
                df[f"{task_prefix}_payload_{timepoint}"] = np.nan

        for index, row in df.iterrows():
            random_rpt = pd.to_numeric(row.get("random_rpt", np.nan), errors="coerce")
            if pd.isna(random_rpt):
                continue

            decoder_row = self.decoder_map.get(int(random_rpt))
            if not decoder_row:
                continue

            for slot in range(2, 6):
                timepoint = decoder_row.get(slot)
                if timepoint not in TIMEPOINT_ORDER:
                    continue

                ach_value = row.get(f"task_data_ach_task_short_psychedelic{slot}", np.nan)
                vch_value = row.get(f"task_data_vch_short_psychedelic_{slot}", np.nan)
                prl_value = row.get(f"task_data_prltask{slot - 1}", np.nan)

                if nonempty_text(ach_value):
                    df.at[index, f"ach_payload_{timepoint}"] = ach_value
                if nonempty_text(vch_value):
                    df.at[index, f"vch_payload_{timepoint}"] = vch_value
                if nonempty_text(prl_value):
                    df.at[index, f"prl_payload_{timepoint}"] = prl_value

        for index, row in df.iterrows():
            for timepoint in TIMEPOINT_ORDER:
                for task_prefix in ["ach", "vch", "prl"]:
                    payload_field = f"{task_prefix}_payload_{timepoint}"
                    if nonempty_text(row.get(payload_field, np.nan)):
                        continue
                    fallback = first_nonempty_value(
                        [
                            row.get(RETRIEVED_FIELD_PATTERNS[task_prefix].format(slot=slot, timepoint=timepoint), np.nan)
                            for slot in range(2, 6)
                        ]
                    )
                    if fallback:
                        df.at[index, payload_field] = fallback

        return df

    def _identify_pending_records(self) -> dict[str, list[int]]:
        assert self.df is not None
        pending: dict[str, list[int]] = {}

        for timepoint in TIMEPOINT_ORDER:
            info = TIMEPOINT_INFO[timepoint]
            browser_field = info["browser_field"]
            payment_date_field = info["payment_date_field"]
            qc_pass_field = info["qc_pass_field"]

            browser_complete = self.df[browser_field].notna() if field_exists(self.df, browser_field) else pd.Series(False, index=self.df.index)
            payment_missing = self.df[payment_date_field].isna() if field_exists(self.df, payment_date_field) else pd.Series(True, index=self.df.index)
            qc_pass = (
                pd.to_numeric(self.df[qc_pass_field], errors="coerce")
                if field_exists(self.df, qc_pass_field)
                else pd.Series(np.nan, index=self.df.index)
            )
            not_already_failed = qc_pass.ne(0) | qc_pass.isna()

            mask = browser_complete & payment_missing & not_already_failed
            pending[timepoint] = to_int_list(self.df.loc[mask, "record_id"].tolist())

        return pending

    # ------------------------------------------------------------------
    # SECTION 4B: Follow-up QC, warnings, and payment assembly
    # ------------------------------------------------------------------

    def run_followup_qc(self) -> RepeatedMeasuresReview:
        assert self.df is not None

        record_ids = sorted(set(sum(self.pending_by_timepoint.values(), [])))
        update_df = self._blank_update_frame(record_ids)
        results_by_timepoint: dict[str, TimepointReview] = {}
        expense_rows: list[pd.DataFrame] = []

        for timepoint in TIMEPOINT_ORDER:
            pending_records = self.pending_by_timepoint[timepoint]
            result = TimepointReview(pending_records=pending_records)
            results_by_timepoint[timepoint] = result

            if not pending_records:
                continue

            timepoint_df = self.df.loc[self.df["record_id"].isin(pending_records)].copy().reset_index(drop=True)
            qc_lists = self._run_timepoint_task_qc(timepoint_df, timepoint)
            self._apply_manual_overrides(timepoint, qc_lists)
            result.qc_lists = qc_lists

            for record_id in pending_records:
                row = self.df.loc[self.df["record_id"] == record_id].reset_index(drop=True)
                if row.empty:
                    continue
                current = row.iloc[0]

                blocking = self._blocking_reasons_for_record(timepoint, record_id, qc_lists)
                warnings = self._warning_notes_for_record(timepoint, record_id, qc_lists, current)

                if warnings:
                    result.warning_notes[record_id] = warnings

                if blocking:
                    result.qc_failed.append(record_id)
                    result.blocking_reasons[record_id] = blocking
                    self._apply_updates(
                        update_df,
                        record_id,
                        {
                            TIMEPOINT_INFO[timepoint]["qc_pass_field"]: 0,
                            TIMEPOINT_INFO[timepoint]["qc_bad_data_field"]: 1,
                            TIMEPOINT_INFO[timepoint]["qc_bad_reason_field"]: "; ".join(blocking),
                        },
                    )
                    continue

                payment_email = self._payment_email_for_record(current)
                self._apply_updates(
                    update_df,
                    record_id,
                    {
                        TIMEPOINT_INFO[timepoint]["qc_pass_field"]: 1,
                    },
                )

                if not payment_email:
                    result.missing_payment_email.append(record_id)
                    continue

                result.ready_for_payment.append(record_id)
                expense_rows.append(self._expense_row(current, timepoint, payment_email))
                self._apply_updates(
                    update_df,
                    record_id,
                    {
                        TIMEPOINT_INFO[timepoint]["payment_date_field"]: datetime.now().strftime("%m/%d/%Y"),
                        TIMEPOINT_INFO[timepoint]["payment_type_field"]: PAYMENT_TYPE,
                        TIMEPOINT_INFO[timepoint]["payment_amount_field"]: PAYMENT_AMOUNT,
                        TIMEPOINT_INFO[timepoint]["send_pay_confirm_field"]: 1,
                    },
                )

            self._print_timepoint_review(timepoint, result)

        expensesheet_path = self._build_expensesheet(expense_rows)
        summary_path = self._write_summary(results_by_timepoint, update_df, expensesheet_path)

        return RepeatedMeasuresReview(
            results_by_timepoint=results_by_timepoint,
            update_df=update_df,
            update_fields=[field for field in update_df.columns if field != "record_id"],
            expensesheet_path=expensesheet_path,
            summary_path=summary_path,
        )

    def import_followup_updates(self, review: RepeatedMeasuresReview) -> None:
        assert self.project is not None

        updates = review.update_df.copy()
        if updates.empty:
            print("No repeated-measures updates to import.")
            return

        real_updates = updates.loc[updates.drop(columns=["record_id"]).notna().any(axis=1)].copy()
        if real_updates.empty:
            print("No repeated-measures updates to import.")
            return

        integer_fields = [
            field
            for field in real_updates.columns
            if field.startswith("qc_passed_") or field.startswith("qc_bad_data_") or field.startswith("send_pay_confirm_")
        ]
        for field in integer_fields:
            if field in real_updates.columns:
                real_updates[field] = pd.to_numeric(real_updates[field], errors="coerce").astype("Int64")

        self.project.import_records(to_import=real_updates, import_format="df")
        print(f"Imported repeated-measures updates for {len(real_updates)} records.")

    # ------------------------------------------------------------------
    # SECTION 4C: Timepoint task parsing and QC metrics
    # ------------------------------------------------------------------

    def _run_timepoint_task_qc(self, timepoint_df: pd.DataFrame, timepoint: str) -> dict[str, list[int]]:
        ach_master, ach_parse_errors, ach_duplicates = self._load_ch_trials(timepoint_df, f"ach_payload_{timepoint}", "decibels")
        vch_master, vch_parse_errors, vch_duplicates = self._load_ch_trials(timepoint_df, f"vch_payload_{timepoint}", "contrasts")
        prl_master, prl_parse_errors, prl_duplicates = self._load_prl_trials(timepoint_df, f"prl_payload_{timepoint}")

        ach_qc = self._evaluate_ch_task(ach_master, "decibels")
        vch_qc = self._evaluate_ch_task(vch_master, "contrasts")
        prl_qc = self._evaluate_prl(prl_master)

        return {
            "ach_negative": to_int_list(ach_qc["negative"]),
            "ach_zero": to_int_list(ach_qc["zero"]),
            "ach_fail_first_fifteen": to_int_list(ach_qc["fail_first_fifteen"]),
            "ach_fraud_copy_paste": to_int_list(ach_duplicates),
            "ach_parse_error": to_int_list(ach_parse_errors),
            "vch_negative": to_int_list(vch_qc["negative"]),
            "vch_zero": to_int_list(vch_qc["zero"]),
            "vch_fail_first_fifteen": to_int_list(vch_qc["fail_first_fifteen"]),
            "vch_fraud_copy_paste": to_int_list(vch_duplicates),
            "vch_parse_error": to_int_list(vch_parse_errors),
            "prl_worse_than_chance": to_int_list(prl_qc["worse_than_chance"]),
            "prl_non_responders": to_int_list(prl_qc["non_responders"]),
            "prl_no_lose_stay": to_int_list(prl_qc["no_lose_stay"]),
            "prl_fraud_copy_paste": to_int_list(prl_duplicates),
            "prl_parse_error": to_int_list(prl_parse_errors),
        }

    def _decode_task_payload(self, payload: str) -> Any:
        try:
            return decode_compressed_json(payload)
        except Exception:
            pass

        try:
            return json.loads(payload)
        except Exception:
            return None

    def _load_ch_trials(
        self,
        dataframe: pd.DataFrame,
        payload_field: str,
        level_field: str,
    ) -> tuple[pd.DataFrame, list[int], list[int]]:
        participant_dfs: list[pd.DataFrame] = []
        parse_errors: list[int] = []

        for _, row in dataframe.iterrows():
            record_id = int(row["record_id"])
            payload = row.get(payload_field, np.nan)
            if not nonempty_text(payload):
                continue

            decoded = self._decode_task_payload(str(payload))
            if not isinstance(decoded, dict):
                parse_errors.append(record_id)
                continue

            try:
                participant_dfs.append(self._ch_components_to_dataframe(decoded, record_id, level_field))
            except Exception:
                parse_errors.append(record_id)

        if not participant_dfs:
            empty = pd.DataFrame(columns=["response", "rt", level_field, "component", "record_id", "trial"])
            return empty, sorted(set(parse_errors)), []

        task_df = pd.concat(participant_dfs, ignore_index=True)
        task_df["record_id"] = pd.to_numeric(task_df["record_id"], errors="coerce").astype(int)
        task_df["trial"] = task_df.groupby("record_id").cumcount() + 1

        pivoted = task_df.pivot(index="record_id", columns="trial", values="rt")
        duplicates = pivoted[pivoted.duplicated(keep=False)].index.tolist()
        return task_df, sorted(set(parse_errors)), sorted(set(to_int_list(duplicates)))

    def _ch_components_to_dataframe(self, data: dict[str, Any], record_id: int, level_field: str) -> pd.DataFrame:
        blocks = ["component_1", "component_2", "component_3", "component_4"]
        block_dfs: list[pd.DataFrame] = []

        for block_number, block in enumerate(blocks, start=1):
            block_payload = data.get(block)
            if not isinstance(block_payload, dict):
                raise ValueError(f"Missing block `{block}`")

            frame = pd.DataFrame(
                {
                    "response": block_payload["response"],
                    "rt": block_payload["responseTime"],
                    level_field: block_payload[level_field],
                    "component": block_number,
                    "record_id": record_id,
                }
            )
            block_dfs.append(frame)

        participant_df = pd.concat(block_dfs, ignore_index=True)
        participant_df[level_field] = pd.to_numeric(participant_df[level_field], errors="coerce").round(5)
        return participant_df

    def _evaluate_ch_task(self, task_df: pd.DataFrame, intensity_field: str) -> dict[str, list[int]]:
        if task_df.empty:
            return {"negative": [], "zero": [], "fail_first_fifteen": []}

        detections = task_df[["record_id", intensity_field, "response"]].dropna()
        if detections.empty:
            return {"negative": [], "zero": [], "fail_first_fifteen": []}

        detection_slopes = self._test_detection_probability(detections, intensity_field)
        first_fifteen = task_df.loc[task_df["trial"] < 16].groupby("record_id").mean(numeric_only=True).reset_index()

        return {
            "negative": to_int_list(detection_slopes.loc[detection_slopes["beta_coefficient"] < 0, "record_id"].tolist()),
            "zero": to_int_list(detection_slopes.loc[detection_slopes["p_value"] > 0.05, "record_id"].tolist()),
            "fail_first_fifteen": to_int_list(first_fifteen.loc[first_fifteen["response"] < 0.5, "record_id"].tolist()),
        }

    def _test_detection_probability(self, detections: pd.DataFrame, intensity_field: str) -> pd.DataFrame:
        results: list[dict[str, Any]] = []
        for record_id, group in detections.groupby("record_id"):
            try:
                model = smf.logit(formula=f"response ~ {intensity_field}", data=group).fit(disp=0)
                p_value = float(model.pvalues.get(intensity_field, 1.0))
                beta = float(model.params.get(intensity_field, 0.0))
            except Exception:
                p_value = 1.0
                beta = 0.0
            results.append({"record_id": int(record_id), "p_value": p_value, "beta_coefficient": beta})
        return pd.DataFrame(results)

    def _load_prl_trials(
        self,
        dataframe: pd.DataFrame,
        payload_field: str,
    ) -> tuple[pd.DataFrame, list[int], list[int]]:
        prl_frames: list[pd.DataFrame] = []
        parse_errors: list[int] = []

        for _, row in dataframe.iterrows():
            record_id = int(row["record_id"])
            payload = row.get(payload_field, np.nan)
            if not nonempty_text(payload):
                continue

            decoded = self._decode_task_payload(str(payload))
            prl_rows = self._prl_rows_from_payload(decoded, record_id)
            if prl_rows is None:
                parse_errors.append(record_id)
                continue

            prl_frames.append(pd.DataFrame(prl_rows))

        if not prl_frames:
            empty = pd.DataFrame(columns=["record_id", "trial", "decisionTime", "rewardProbChoice", "keyChoice", "outcome"])
            return empty, sorted(set(parse_errors)), []

        df_prl = pd.concat(prl_frames, ignore_index=True)
        df_prl = df_prl.replace({"fractal1": 1, "fractal2": 2, "fractal3": 3})
        if "choice" in df_prl.columns:
            df_prl["choice"] = pd.to_numeric(df_prl["choice"], errors="coerce")
        df_prl["record_id"] = pd.to_numeric(df_prl["record_id"], errors="coerce").astype(int)
        df_prl = df_prl.reset_index(drop=True)

        try:
            pivoted = df_prl.pivot(index="record_id", columns="trial", values="decisionTime")
            duplicates = pivoted[pivoted.duplicated(keep=False)].index.tolist()
        except Exception:
            duplicates = []

        return df_prl, sorted(set(parse_errors)), sorted(set(to_int_list(duplicates)))

    def _prl_rows_from_payload(self, decoded: Any, fallback_record_id: int) -> list[dict[str, Any]] | None:
        if isinstance(decoded, dict) and isinstance(decoded.get("data"), list):
            rows = decoded.get("data", [])
            record_id = decoded.get("recordId", fallback_record_id)
            project_id = decoded.get("projectId", np.nan)
            for row in rows:
                row["record_id"] = record_id
                row["projectId"] = project_id
            return rows

        if isinstance(decoded, list):
            rows: list[dict[str, Any]] = []
            for item in decoded:
                if not isinstance(item, dict):
                    return None
                item = item.copy()
                item["record_id"] = item.get("record_id", fallback_record_id)
                rows.append(item)
            return rows

        return None

    def _evaluate_prl(self, df_prl: pd.DataFrame) -> dict[str, list[int]]:
        if df_prl.empty:
            return {"worse_than_chance": [], "non_responders": [], "no_lose_stay": []}

        percent_correct = self._append_percent(df_prl, "rewardProbChoice", 0.85, "%Correct")
        worse_than_chance = to_int_list(
            percent_correct.groupby("record_id")["%Correct"].mean().reset_index().loc[lambda data: data["%Correct"] < 34, "record_id"].tolist()
        )

        percent_no_response = self._append_percent(percent_correct, "keyChoice", -999, "%NoResponse")
        non_responders = to_int_list(
            percent_no_response.groupby("record_id")["%NoResponse"].mean().reset_index().loc[lambda data: data["%NoResponse"] > 10, "record_id"].tolist()
        )

        percent_no_response = percent_no_response.reset_index(drop=True)
        win_stay_lose_stay: list[str | float] = []
        for row_index in range(len(percent_no_response)):
            current = percent_no_response.loc[row_index]
            if (
                row_index == 0
                or current["record_id"] != percent_no_response.loc[row_index - 1, "record_id"]
                or pd.isna(current["outcome"])
                or percent_no_response.loc[row_index - 1, "outcome"] == -999
            ):
                win_stay_lose_stay.append(np.nan)
                continue

            previous = percent_no_response.loc[row_index - 1]
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
            percent_no_response.groupby("record_id")["lose_stay_percent"].mean().reset_index().loc[lambda data: data["lose_stay_percent"] < 1, "record_id"].tolist()
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

    # ------------------------------------------------------------------
    # SECTION 4D: Blocker rules, warnings, and manual overrides
    # ------------------------------------------------------------------

    def _apply_manual_overrides(self, timepoint: str, qc_lists: dict[str, list[int]]) -> None:
        if timepoint == "sub":
            for key in ["ach_negative", "ach_zero", "ach_fail_first_fifteen", "ach_fraud_copy_paste"]:
                qc_lists[key] = [record_id for record_id in qc_lists.get(key, []) if record_id != 1570]

    def _blocking_reasons_for_record(self, timepoint: str, record_id: int, qc_lists: dict[str, list[int]]) -> list[str]:
        blocker_map = {
            "ach_negative": "ACH negative slope",
            "vch_negative": "VCH negative slope",
            "prl_non_responders": "PRL >10% no-response rate",
            "prl_worse_than_chance": "PRL <34% correct responses",
            "ach_parse_error": "ACH payload could not be parsed",
            "vch_parse_error": "VCH payload could not be parsed",
            "prl_parse_error": "PRL payload could not be parsed",
        }

        reasons = [label for key, label in blocker_map.items() if record_id in qc_lists.get(key, [])]

        # Preserve the old notebook's explicit hyperacute exception.
        if timepoint == "hyp" and record_id == 1307:
            blocker_reason_set = {
                "ACH negative slope",
                "VCH negative slope",
                "PRL >10% no-response rate",
                "PRL <34% correct responses",
            }
            reasons = [reason for reason in reasons if reason not in blocker_reason_set]

        return sorted(set(reasons))

    def _warning_notes_for_record(
        self,
        timepoint: str,
        record_id: int,
        qc_lists: dict[str, list[int]],
        row: pd.Series,
    ) -> list[str]:
        warnings: list[str] = []

        warning_map = {
            "ach_zero": "ACH slope not significantly different from zero",
            "ach_fail_first_fifteen": "ACH first 15 trials had <50% detection",
            "ach_fraud_copy_paste": "ACH reaction times match another record",
            "vch_zero": "VCH slope not significantly different from zero",
            "vch_fail_first_fifteen": "VCH first 15 trials had <50% detection",
            "vch_fraud_copy_paste": "VCH reaction times match another record",
            "prl_no_lose_stay": "PRL lose-stay behavior was <1%",
            "prl_fraud_copy_paste": "PRL decision times match another record",
        }
        warnings.extend(label for key, label in warning_map.items() if record_id in qc_lists.get(key, []))

        if timepoint == "hyp" and record_id == 1307:
            override_warning_map = {
                "ach_negative": "ACH negative slope",
                "vch_negative": "VCH negative slope",
                "prl_non_responders": "PRL >10% no-response rate",
                "prl_worse_than_chance": "PRL <34% correct responses",
            }
            warnings.extend(label for key, label in override_warning_map.items() if record_id in qc_lists.get(key, []))
            if any(record_id in qc_lists.get(key, []) for key in override_warning_map):
                warnings.append("Manual notebook override preserved for record 1307 at hyperacute")

        timing_warnings = {
            "acu": [
                ("less_sixhr_sincehyp_acu", "Acute session was completed <6 hours after hyperacute"),
                ("over_1day_sincehyp_acu", "Acute session was completed >24 hours after hyperacute"),
            ],
            "sub": [
                ("days_sincehyp_sub", "Subacute session was completed >14 days after hyperacute"),
                ("days_since_acu_sub", "Subacute session was completed >13 days after acute"),
            ],
            "pers": [
                ("days_sincehyp_pers", "Persisting session was completed >180 days after hyperacute"),
                ("days_since_acu_pers", "Persisting session was completed >179 days after acute"),
            ],
        }
        for field, label in timing_warnings.get(timepoint, []):
            value = pd.to_numeric(row.get(field, np.nan), errors="coerce")
            if pd.notna(value) and value > 0:
                warnings.append(f"{label} ({int(value)} day(s)/flag units)")

        return sorted(set(warnings))

    # ------------------------------------------------------------------
    # SECTION 4E: REDCap updates, expense-sheet rows, and reporting
    # ------------------------------------------------------------------

    def _blank_update_frame(self, record_ids: list[int]) -> pd.DataFrame:
        fields = ["record_id"]
        for timepoint in TIMEPOINT_ORDER:
            info = TIMEPOINT_INFO[timepoint]
            fields.extend(
                [
                    info["payment_date_field"],
                    info["payment_type_field"],
                    info["payment_amount_field"],
                    info["qc_pass_field"],
                    info["qc_bad_data_field"],
                    info["qc_bad_reason_field"],
                    info["send_pay_confirm_field"],
                ]
            )

        update_df = pd.DataFrame({"record_id": record_ids})
        for field in fields[1:]:
            update_df[field] = pd.NA
        return update_df

    def _apply_updates(self, update_df: pd.DataFrame, record_id: int, updates: dict[str, Any]) -> None:
        for field, value in updates.items():
            if field in update_df.columns:
                update_df.loc[update_df["record_id"] == record_id, field] = value

    def _payment_email_for_record(self, row: pd.Series) -> str | None:
        for field in ["payment_email_rpt", "payment_email_bl", "email_rpt"]:
            email = clean_email(row.get(field, np.nan))
            if email:
                return email
        return None

    def _expense_row(self, row: pd.Series, timepoint: str, payment_email: str) -> pd.DataFrame:
        info = TIMEPOINT_INFO[timepoint]
        return pd.DataFrame(
            {
                "Date of Participation:  (month/day/year)": [extract_redcap_date(string_value(row, info["timestamp_field"]))],
                "Date of Payment:          (month/day/year)": [""],
                "Name of Yale Researcher requesting payment:": [self.user_name],
                "Name of Yale Researcher providing payment:": ["Catalina Mourgues"],
                "Amount of Payment:      (in USD)": [PAYMENT_AMOUNT],
                "Subject ID #:": [int(row["record_id"])],
                "Type of Participation or Assessment Point:            **Use the same verbiage as referenced in the HIC Economic Considerations**                                                           List all activities separately, including parking, miles, food or incidentals.": [
                    info["event_label"]
                ],
                "Type of Payment:      (Cash, Gift Card, etc.)": [PAYMENT_TYPE],
                "Delivery Detail (email, address)": [payment_email],
                "Payment Instrument Link": [string_value(row, info["payment_url_field"])],
                "Comments /Confirmation": [np.nan],
            }
        )

    def _build_expensesheet(self, expense_rows: list[pd.DataFrame]) -> Path | None:
        if not expense_rows:
            return None

        expensesheet = pd.concat(expense_rows, ignore_index=True)
        path = self.date_directory / f"expense_sheet_rpt_{datetime.now().strftime('%Y-%m-%d')}.csv"
        expensesheet.to_csv(path, index=False)
        return path

    def _print_timepoint_review(self, timepoint: str, result: TimepointReview) -> None:
        label = TIMEPOINT_INFO[timepoint]["label"]
        if not result.pending_records:
            return

        print(f"\n{label}: {len(result.pending_records)} record(s) need review")
        print(f"  Ready for payment: {len(result.ready_for_payment)}")
        print(f"  QC failed / payment withheld: {len(result.qc_failed)}")
        print(f"  Missing payment email: {len(result.missing_payment_email)}")

        for record_id in result.pending_records:
            status_parts: list[str] = []
            if record_id in result.ready_for_payment:
                status_parts.append("ready for payment")
            if record_id in result.qc_failed:
                status_parts.append("payment withheld")
            if record_id in result.missing_payment_email:
                status_parts.append("missing payment email")
            status_text = ", ".join(status_parts) if status_parts else "manual review"

            print(f"  Record {record_id}: {status_text}")
            for reason in result.blocking_reasons.get(record_id, []):
                print(f"    BLOCK: {reason}")
            for note in result.warning_notes.get(record_id, []):
                print(f"    NOTE: {note}")

    def _write_summary(
        self,
        results_by_timepoint: dict[str, TimepointReview],
        update_df: pd.DataFrame,
        expensesheet_path: Path | None,
    ) -> Path:
        summary_path = self.date_directory / "repeated_measures_qc_summary.md"
        lines = [
            "# Repeated-Measures QC Summary",
            "",
            f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
            f"- Staff member: {self.user_name}",
            f"- Expensesheet: {expensesheet_path if expensesheet_path else 'none'}",
            f"- SharePoint upload target: {SHAREPOINT_PAYMENT_UPLOAD_URL}",
            "",
            "## REDCap Update Snapshot",
        ]

        non_null_updates = update_df.loc[update_df.drop(columns=["record_id"]).notna().any(axis=1)].copy()
        if non_null_updates.empty:
            lines.append("- No REDCap updates queued.")
        else:
            lines.append(f"- Records with queued updates: {sorted(to_int_list(non_null_updates['record_id'].tolist()))}")

        for timepoint in TIMEPOINT_ORDER:
            label = TIMEPOINT_INFO[timepoint]["label"]
            result = results_by_timepoint[timepoint]

            lines.extend(
                [
                    "",
                    f"## {label}",
                    f"- Pending review: {result.pending_records}",
                    f"- Ready for payment: {result.ready_for_payment}",
                    f"- QC failed / payment withheld: {result.qc_failed}",
                    f"- Missing payment email: {result.missing_payment_email}",
                    "",
                    "### Blocking Reasons",
                ]
            )
            if result.blocking_reasons:
                for record_id in sorted(result.blocking_reasons):
                    lines.append(f"- {record_id}: {'; '.join(result.blocking_reasons[record_id])}")
            else:
                lines.append("- none")

            lines.extend(["", "### Warning Notes"])
            if result.warning_notes:
                for record_id in sorted(result.warning_notes):
                    lines.append(f"- {record_id}: {'; '.join(result.warning_notes[record_id])}")
            else:
                lines.append("- none")

            lines.extend(["", "### Raw QC Lists"])
            if result.qc_lists:
                for key, values in sorted(result.qc_lists.items()):
                    if values:
                        lines.append(f"- {key}: {sorted(set(values))}")
                if lines[-1] == "### Raw QC Lists":
                    lines.append("- none")
            else:
                lines.append("- none")

        summary_path.write_text("\n".join(lines))
        return summary_path


# ============================================================================
# SECTION 5: Simple CLI Entry Point
# ============================================================================


def main() -> None:
    user_code = input("Who is using the script? m, kayla, or gabby? ").strip().lower()
    tool = RepeatedMeasuresQuickQC(user_code).load()
    tool.print_dashboard()

    review = tool.run_followup_qc()
    if review.summary_path:
        print(f"\nSummary written to: {review.summary_path}")
    if review.expensesheet_path:
        print(f"Expense sheet written to: {review.expensesheet_path}")

    if ask_yes_no("Import repeated-measures QC/payment updates to REDCap? Type 'yes' to confirm: "):
        tool.import_followup_updates(review)
    else:
        print("Skipped REDCap repeated-measures import.")


if __name__ == "__main__":
    main()
