# Aim 8 QC Tools Protocol

## Default Daily Workflow
- Mount the shared drive expected by the tools:
  - `/Volumes/psychedelics/online`
- Open a terminal in:
  - `…/RedCapStuff/Longitudinal_Relaunch/scripts/`
- Run the full suite:
  - `python3 run_all_qc_relaunch.py`

## What The Wrapper Does
- Prompts once for the staff member code:
  - `m`
  - `kayla`
  - `gabby`
- Runs three stages in order:
  - screening fraud review
  - baseline completion QC/payment
  - repeated-measures follow-up QC/payment
- Prompts before each REDCap import.
- Prints the paths for any output files at the end.

## When To Use Each Script
All scripts live in `scripts/`. Run them from that directory.

- Use `python3 run_all_qc_relaunch.py`
  - default daily option
  - use this when you want one pass across everything
- Use `python3 quickQC_api_calling_v7_relaunch.py`
  - when you only need screening + baseline
  - especially useful if you are focused on fraud review / replay links / baseline payments
- Use `python3 quickQC_rpt_relaunch.py`
  - when you only need hyperacute / acute / subacute / persisting review and payment

## Interactive Steps During A Typical Run

### Screening stage
- If there are screening records missing IP metadata, paste the REDCap PDF archive text when prompted.
- For records needing phone review, enter:
  - `y` for fraudulent / VOIP
  - `n` for clear
  - `?` for Max manual follow-up
- Confirm whether to import screening updates into REDCap.

### Baseline completion stage
- Review the console output and the generated markdown summary.
- Confirm whether to import baseline completion updates into REDCap.
- If an expense sheet is generated, upload it after the run.

### Repeated-measures stage
- Review the console output and the generated markdown summary.
- Confirm whether to import repeated-measures updates into REDCap.
- If an expense sheet is generated, upload it after the run.

## Output Files
- All QC outputs are written into the dated shared-drive folder:
  - `/Volumes/psychedelics/online/qc_to_dos/YYYY-MM-DD/`
- Baseline / screening outputs:
  - `screening_review_summary.md`
  - `completion_qc_summary.md`
  - `expensesheet_YYYY-MM-DD.csv` if baseline payments were queued
- Repeated-measures outputs:
  - `repeated_measures_qc_summary.md`
  - `expense_sheet_rpt_YYYY-MM-DD.csv` if follow-up payments were queued
- Baseline flag files:
  - `REDCAP_SCREENS_*`
  - `REDCAP_FULLRECORDS_*`
  - `PAYMENTS_FULLRECORDS_*`
  - `TASKS_FULLRECORDS_*`

## Payment Handling
- Current amendment-compliant payment mode in both tools:
  - Amazon.com US electronic gift card only
  - `$50`
- SharePoint upload target is printed by the wrapper and is also configurable by env var:
  - `AIM8_SHAREPOINT_PAYMENT_URL`

## REDCap Update Rules To Know

### Baseline tool
- Screening updates modify fields like:
  - `screening_pass`
  - `qc_passed`
  - `eligible_notify`
  - `ineligibile_fraud`
- Baseline completion updates modify fields like:
  - `qc_passed`
  - `qc_notes`
  - replay fields
  - payment confirmation trigger fields

### Repeated-measures tool
- Auto-passed follow-up sessions update:
  - `payment_date_<tp>`
  - `payment_type_<tp>`
  - `payment_amount_<tp>`
  - `qc_passed_<tp>`
  - `send_pay_confirm_<tp>`
- Auto-failed follow-up sessions update:
  - `qc_passed_<tp> = 0`
  - `qc_bad_data_<tp> = 1`
  - `qc_bad_reason_<tp>`
- Important queueing rule:
  - follow-up sessions with `qc_passed_<tp> = 0` are treated as already reviewed failures and do not keep resurfacing just because `payment_date_<tp>` is blank

## Current Follow-Up QC Policy
- Auto-block follow-up payment for:
  - ACH negative slope
  - VCH negative slope
  - PRL `>10%` no-response rate
  - PRL `<34%` correct
  - task payload parse failures
- Keep as warnings only:
  - zero slopes
  - first-15-trial failures
  - PRL lose-stay `<1%`
  - duplicated RT / decision-time patterns
  - timing anomalies between timepoints
- Preserved notebook overrides:
  - record `1570` is removed from subacute ACH fail lists
  - record `1307` is removed from hyperacute auto-blocking but still surfaced as a warning

## Environment Variables
- `AIM8_REDCAP_API_URL`
  - defaults to the Yale REDCap API URL
- `AIM8_BASELINE_API_TOKEN`
  - baseline / screening project token
- `AIM8_RPT_API_TOKEN`
  - repeated-measures project token
- `AIM8_IPINFO_TOKEN`
  - IP metadata lookup token for screening review
- `AIM8_SHAREDDRIVE_PATH`
  - defaults to `/Volumes/psychedelics/online`
- `AIM8_SHAREPOINT_PAYMENT_URL`
  - SharePoint sheet URL printed at the end of the run
- `AIM8_RPT_DECODER_PATH`
  - path to the repeated-measures randomization decoder Excel file

## If The Two REDCap Projects Become One Live Project
- Keep using the same scripts if that is convenient.
- Point both tools at the merged live project by setting:
  - `AIM8_BASELINE_API_TOKEN=<merged token>`
  - `AIM8_RPT_API_TOKEN=<merged token>`
- The wrapper will still work; both sub-tools will just talk to the same REDCap project.

## Recommended Smoke Test Before First Live Use
From `scripts/`:
1. Run `python3 quickQC_api_calling_v7_relaunch.py` on a day with a small known screening/baseline batch.
2. Run `python3 quickQC_rpt_relaunch.py` on a few known follow-up records, especially one with retrieved task backups.
3. Confirm the generated CSVs and markdown summaries match expectations.
4. Confirm the REDCap import rows look correct before answering `yes` at the import prompts.
