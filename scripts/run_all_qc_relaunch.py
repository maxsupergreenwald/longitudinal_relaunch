#!/usr/bin/env python3
"""Daily wrapper that runs the full Aim 8 QC suite in one pass.

PURPOSE
-------
This is the script you run every day.  It calls both QC engines in sequence:
  1. quickQC_api_calling_v7_relaunch.py  — screening fraud review + baseline completion
  2. quickQC_rpt_relaunch.py             — repeated-measures follow-up (hyp/acu/sub/pers)

HOW TO RUN
----------
From within the scripts/ directory:
    python3 run_all_qc_relaunch.py

You will be asked for your user code (m, kayla, or gabby) and then walked through
each step interactively.  All steps that require REDCap imports prompt for confirmation
before pushing data.  You can skip any import without losing the local summary files.

WHAT IT DOES (IN ORDER)
------------------------
1. Load both tools (pulls all REDCap data, checks shared-drive flags).
2. Print a dashboard showing how many records are in each queue.
3. Screening fraud review (if any records are waiting):
   - Runs IP/eligibility checks automatically.
   - Prompts for phone/VOIP verdict on each record.
   - Offers to push screening updates to REDCap.
4. Baseline completion QC (if any records are waiting):
   - Runs all task and questionnaire QC automatically.
   - Offers to push completion updates (replay links, payments, etc.) to REDCap.
5. Repeated-measures follow-up QC (always runs):
   - QC's all pending hyp/acu/sub/pers sessions automatically.
   - Offers to push follow-up updates (qc_passed, payment dates, etc.) to REDCap.
6. Prints paths to all generated files and the SharePoint payment upload URL.

OUTPUT FILES (in /Volumes/psychedelics/online/qc_to_dos/YYYY-MM-DD/)
----------------------------------------------------------------------
  screening_review_summary.md        — screening fraud review results
  completion_qc_summary.md           — baseline QC results
  repeated_measures_qc_summary.md    — follow-up QC results
  expensesheet_YYYY-MM-DD.csv        — baseline payments (upload to SharePoint)
  expense_sheet_rpt_YYYY-MM-DD.csv   — follow-up payments (upload to SharePoint)
  *_INCOMPLETE.txt / *_COMPLETE.txt  — flag files tracking step completion
"""

from __future__ import annotations

from quickQC_api_calling_v7_relaunch import (
    SHAREPOINT_PAYMENT_UPLOAD_URL,
    RelaunchQuickQC,
    ask_yes_no,
)
from quickQC_rpt_relaunch import RepeatedMeasuresQuickQC


def print_suite_dashboard(baseline_tool: RelaunchQuickQC, rpt_tool: RepeatedMeasuresQuickQC) -> None:
    """Print a high-level count of records in all three queues across both tools."""
    print("\nAim 8 QC suite overview")
    print(f"  Screening fraud reviews: {len(baseline_tool.records_to_screen)}")
    print(f"  Baseline completions waiting for QC/payment: {len(baseline_tool.records_to_check)}")
    total_followup = sum(len(records) for records in rpt_tool.pending_by_timepoint.values())
    print(f"  Follow-up sessions waiting for QC/payment: {total_followup}")
    for timepoint in ["hyp", "acu", "sub", "pers"]:
        print(f"    {timepoint}: {len(rpt_tool.pending_by_timepoint[timepoint])}")


def main() -> None:
    """Entry point for the daily QC run.  Runs screening, baseline, and follow-up in order."""
    user_code = input("Who is using the QC suite? m, kayla, or gabby? ").strip().lower()

    baseline_tool = RelaunchQuickQC(user_code).load()
    rpt_tool = RepeatedMeasuresQuickQC(user_code).load()
    print_suite_dashboard(baseline_tool, rpt_tool)

    screening_summary = None
    baseline_completion_review = None
    followup_review = None
    baseline_summary_path = baseline_tool.date_directory / "completion_qc_summary.md"

    if baseline_tool.records_to_screen:
        print("\nRunning screening fraud review...")
        screening_review = baseline_tool.prepare_screening_review()
        screening_summary = baseline_tool.date_directory / "screening_review_summary.md"
        verdicts = baseline_tool.collect_phone_verdicts(screening_review)
        screening_updates = baseline_tool.build_screening_updates(screening_review, verdicts)
        if ask_yes_no("Import screening updates to REDCap? Type 'yes' to confirm: "):
            baseline_tool.import_screening_updates(screening_updates)
        else:
            print("Skipped REDCap screening import.")

    if baseline_tool.records_to_check:
        print("\nRunning baseline completion QC...")
    baseline_completion_review = baseline_tool.run_completion_qc()
    if baseline_completion_review.records_to_check:
        if baseline_completion_review.expensesheet_path:
            print(f"Baseline expense sheet written to: {baseline_completion_review.expensesheet_path}")
        if ask_yes_no("Import baseline completion QC updates to REDCap? Type 'yes' to confirm: "):
            baseline_tool.import_completion_updates(baseline_completion_review)
        else:
            print("Skipped REDCap baseline completion import.")

    print("\nRunning repeated-measures follow-up QC...")
    followup_review = rpt_tool.run_followup_qc()
    if followup_review.summary_path:
        print(f"Repeated-measures summary written to: {followup_review.summary_path}")
    if followup_review.expensesheet_path:
        print(f"Repeated-measures expense sheet written to: {followup_review.expensesheet_path}")

    followup_updates_queued = False
    if followup_review.update_df is not None and not followup_review.update_df.empty:
        followup_updates_queued = bool(followup_review.update_df.drop(columns=["record_id"]).notna().any(axis=1).any())

    if followup_updates_queued and ask_yes_no("Import repeated-measures QC/payment updates to REDCap? Type 'yes' to confirm: "):
        rpt_tool.import_followup_updates(followup_review)
    elif followup_updates_queued:
        print("Skipped REDCap repeated-measures import.")
    else:
        print("No repeated-measures REDCap updates were queued.")

    print("\nManual follow-up items")
    if screening_summary:
        print(f"  Screening summary: {screening_summary}")
    if baseline_summary_path.exists():
        print(f"  Baseline completion summary: {baseline_summary_path}")
    if followup_review and followup_review.summary_path:
        print(f"  Repeated-measures summary: {followup_review.summary_path}")
    if baseline_completion_review and baseline_completion_review.expensesheet_path:
        print(f"  Upload baseline payments: {baseline_completion_review.expensesheet_path}")
    if followup_review and followup_review.expensesheet_path:
        print(f"  Upload follow-up payments: {followup_review.expensesheet_path}")
    print(f"  SharePoint upload target: {SHAREPOINT_PAYMENT_UPLOAD_URL}")


if __name__ == "__main__":
    main()
