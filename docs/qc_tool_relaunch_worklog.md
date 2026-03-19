# QC Tool Relaunch Worklog

## Goal Of This Draft
- Replace the hard-to-edit baseline QC notebook with a more readable first-draft Python QC tool for the merged Aim 8 relaunch workflow.
- Keep two core jobs working:
  - new screening records that need fraud review before `screening_pass`
  - newly completed baseline records that need QC and payment export

## Files Added
- `quickQC_api_calling_v7_relaunch.py`
- `quickQC_rpt_relaunch.py`
- `run_all_qc_relaunch.py`
- `qc_tool_relaunch_worklog.md`

## Current Usage
- Default daily run from this folder:
  - `python3 run_all_qc_relaunch.py`
- Individual tools are still available when you only need one part:
  - `python3 quickQC_api_calling_v7_relaunch.py`
  - `python3 quickQC_rpt_relaunch.py`
- The suite / baseline script prompts for:
  - the staff member name code
  - pasted REDCap PDF-archive text for missing IPs
  - phone / VOIP verdicts for screening records
  - confirmation before REDCap imports
- The repeated-measures script prompts for:
  - the staff member name code
  - confirmation before REDCap imports

## Files Left Untouched On Purpose
- `quickQC_api_calling_v6_OnlyLongitudinal.ipynb`
  - kept as the behavior reference while building the new draft
- `quickQC_rpt_apicalls.ipynb`
  - kept as the behavior reference while building the follow-up-session draft
- the merged REDCap XML draft
  - this pass only touched the QC tool layer

## What The New Script Does

### Screening path
- Loads the baseline/merged project through the existing REDCap API token.
- Identifies records that have:
  - `submit_screen_v3` present
  - `screening_pass` missing
  - `qc_passed` missing
  - `phone_number` present
- Pulls / updates the IP metadata database from `ips_full.csv`.
- Parses pasted REDCap PDF-archive text for missing IPs.
- Flags screening records for:
  - forbidden IP org / country
  - duplicate screening/payment/contact emails
  - duplicate IPs already associated with reviewed / ineligible records
  - basic eligibility failures still relevant to the amended project
- Prompts the user for phone/VOIP review only after the automated checks.
- Builds a REDCap screening update dataframe with:
  - `screening_pass`
  - `qc_passed`
  - `eligible_notify`
  - `ineligibile_fraud`
  - `ip_zoom_invite`
  - `max_number_followup`
  - `ineligibilty_reason`

### Completed-baseline QC path
- Identifies completed baseline records more cleanly than the old notebook:
  - `qc_passed` missing
  - `screening_pass == 1`
  - `race_qc` present
  - ACH, VCH, and PRL task data present either in main task-data fields or retrieved backup fields
- Preserves the old notebook’s main baseline QC logic for:
  - attention checks
  - race/age mismatch
  - absurd / inconsistent SP response checks
  - ACH slope / first-15 checks
  - VCH slope / first-15 checks
  - PRL worse-than-chance / non-response / lose-stay checks
  - duplicate copy-paste task-data checks
- Reorganizes that logic into named sections and helper functions so specific areas are easier to edit.

### Payment path
- Simplifies payment export to the amended workflow:
  - Amazon.com US electronic gift card only
  - `$50`
  - Aim 8 baseline session wording
- Removes the old US Bank / physical VISA / Yale credit branching from the payment export logic.
- Writes the expense sheet CSV into the dated QC folder.

### Output / flags
- Writes summary markdown files into the dated QC folder:
  - `screening_review_summary.md`
  - `completion_qc_summary.md`
- The repeated-measures tool also writes:
  - `repeated_measures_qc_summary.md`
- The wrapper prints the paths for any generated summaries / expense sheets at the end.
- Writes the same flag-file family the old process depended on:
  - `REDCAP_SCREENS_*`
  - `REDCAP_FULLRECORDS_*`
  - `PAYMENTS_FULLRECORDS_*`
  - `TASKS_FULLRECORDS_*`

## New Follow-Up Tool

### Architecture choice
- I kept the relaunch QC as:
  - one baseline/screening tool
  - one repeated-measures follow-up tool
  - one run-all wrapper
- I did **not** merge everything into one massive script.
  - this keeps the screening/baseline workflow safer to edit
  - it also makes the follow-up timepoint logic easier to debug without touching fraud-screening code

### What `quickQC_rpt_relaunch.py` does
- Loads the repeated-measures REDCap project using a dedicated token:
  - `AIM8_RPT_API_TOKEN`
- Loads the randomization decoder spreadsheet:
  - `AIM8_RPT_DECODER_PATH`
- Reconstructs internal per-timepoint task payload columns:
  - `ach_payload_hyp/acu/sub/pers`
  - `vch_payload_hyp/acu/sub/pers`
  - `prl_payload_hyp/acu/sub/pers`
- Uses retrieved-task backups if the randomized raw task slot is missing.
- Reviews completed timepoints that still have no payment date and were not already QC-failed.
  - important implementation detail:
    - follow-up queueing now ignores records where `qc_passed_<tp> == 0`
    - this prevents the same failed timepoint from resurfacing forever just because `payment_date_<tp>` is blank

### Follow-up QC logic preserved from the old notebook
- ACH / VCH:
  - negative slope
  - zero slope
  - first-15-trials `<50%` detection
  - duplicate RT rows across participants
- PRL:
  - `<34%` correct
  - `>10%` no response
  - `<1%` lose-stay
  - duplicate decision-time rows across participants
- Timing anomalies are still warnings only:
  - acute too early / too late relative to hyperacute
  - subacute too late relative to hyperacute / acute
  - persisting too late relative to hyperacute / acute

### Follow-up auto-block rule preserved from the old notebook
- The old notebook only withheld auto-payment for:
  - ACH negative slope
  - VCH negative slope
  - PRL non-responders
  - PRL worse-than-chance
- I preserved that narrow blocker rule.
- I also added payload parse failures as blockers.
  - reason: in the notebook these cases would usually just crash or require manual intervention anyway

### Old notebook overrides preserved
- Record `1570`
  - still removed from the subacute ACH fail lists
- Record `1307`
  - still removed from the hyperacute **auto-block** list
  - I preserved it as a warning note rather than a payment-blocking failure

### Follow-up payment behavior changed for the amendment
- All follow-up payments are now:
  - Amazon.com US electronic gift card
  - `$50`
- Removed old branches for:
  - Amazon physical VISA
  - digital US Bank prepaid cards
  - mailed physical VISA cards
- On auto-pass, the follow-up tool writes:
  - `payment_date_<tp>`
  - `payment_type_<tp>`
  - `payment_amount_<tp>`
  - `qc_passed_<tp>`
  - `send_pay_confirm_<tp>`
- On auto-fail, the follow-up tool writes:
  - `qc_passed_<tp> = 0`
  - `qc_bad_data_<tp> = 1`
  - `qc_bad_reason_<tp>`

### Readability / editability improvements in the follow-up tool
- Split the repeated-measures code into explicit sections:
  - project configuration
  - queue detection
  - per-timepoint payload reconstruction
  - task parsers
  - blocker rules
  - warning rules
  - payment export
  - summary writing
- The part you are likely to tweak later is now easy to find:
  - `_blocking_reasons_for_record`
  - `_warning_notes_for_record`
  - `_apply_manual_overrides`

## New Run-All Wrapper

### What `run_all_qc_relaunch.py` does
- Prompts once for the staff member code.
- Runs, in order:
  - screening fraud review
  - baseline completion QC/payment
  - repeated-measures QC/payment
- Prompts separately before each REDCap import.
- Prints the paths for:
  - baseline summary markdown
  - repeated-measures summary markdown
  - any baseline expense sheet
  - any follow-up expense sheet
  - the SharePoint payment upload target

### Why I used a CLI wrapper instead of another notebook
- The notebook logic had become very hard to edit safely.
- The CLI wrapper still supports the interactive parts that matter:
  - pasting REDCap PDF archive text
  - entering phone / VOIP judgments
  - confirming REDCap imports
- It is much easier to maintain than pushing the logic back into a notebook cell.

## Readability / Editability Changes
- Split the old monolithic notebook logic into explicit sections:
  - project configuration
  - screening fraud review
  - absurd SP response checks
  - task parsers
  - task QC metrics
  - completion update assembly
  - payment export
  - flag files
- Added `TaskConfig` to group replay/template/reset behavior per task.
- Made the “absurd SP responses” logic a dedicated method:
  - `_evaluate_absurd_sp_responses`
- Moved recurring small operations into helpers:
  - numeric coercion
  - latest completion date
  - parsed email cleanup
  - REDCap PDF log parsing
  - task payload decoding

## Important Behavior Changes From The Old Notebook
- Removed Yale-specific routing and assumptions.
- Removed cannabis-specific routing and exclusions.
- Removed the old longitudinal waiting path from QC logic.
- Removed the old “invite to separate longitudinal project” logic.
- Removed non-Amazon payment branches.
- Updated payment amount from `$40` to `$50`.
- Updated follow-up payment amount from `$60` to `$50`.
- Added `fail_first_fifteen` and `fail_first_fifteen_vch` to task retry routing.
  - the old notebook built those fail lists but did not clearly route them through the replay/template update block
- Fixed the old mismatch where manual phone follow-up was written to `email_max` in one place but the import field list expected `max_number_followup`.

## Deliberate Scope Limits In This Draft
- I did not create a new notebook wrapper.
  - the new wrapper is CLI-based rather than notebook-based
- I kept some legacy REDCap admin fields in the baseline script if they still help the current workflow.
  - example: `ip_zoom_invite`, `verify_emailed`, replay email fields
- The repeated-measures script does not yet create its own flag-file family.
  - it currently relies on markdown summaries plus console output instead
- The follow-up parser assumes retrieved PRL backups still deserialize into the same basic row-wise structure as the old notebook expected.
  - that should be smoke-tested on a few known records

## Validation Done
- `python3 -m py_compile quickQC_api_calling_v7_relaunch.py`
- `python3 -m py_compile quickQC_rpt_relaunch.py`
- `python3 -m py_compile run_all_qc_relaunch.py`
- I did not run the script end-to-end against live REDCap or the mounted share drive in this environment.

## Main Risks / Things To Check Next
- The live merged REDCap project may not keep every legacy admin field that the old notebook used.
  - the new script already filters update columns to fields that actually exist in the exported dataframe, but the live project should still be checked once the XML is imported
- The screening duplicate-IP branch still uses `ip_zoom_invite`.
  - if the new streamlined workflow should replace that with a different manual-review field, change it in `build_screening_updates`
- The script still assumes the same shared-drive layout:
  - `/Volumes/psychedelics/online`
  - `ips/ips_full.csv`
  - `jsons/failed_task_jsons_baseline.csv`
- The scripts still assume the REDCap API tokens and IPInfo token currently used by the old notebooks unless overridden with environment variables.
- The follow-up queue logic intentionally treats `qc_passed_<tp> = 0` as “already reviewed, withhold payment”.
  - if you would rather keep failed timepoints reappearing until manually cleared, that rule would need to be changed
- The repeated-measures payment script now uses `payment_email_rpt`, then falls back to `payment_email_bl`, then `email_rpt`.
  - that fallback order should be confirmed against current payment expectations
- I did not live-test the wrapper prompts or REDCap imports against production data.

## Suggested Next Pass
1. Smoke-test `quickQC_api_calling_v7_relaunch.py` against a mounted drive and a safe batch of known records.
2. Smoke-test `quickQC_rpt_relaunch.py` on a few known hyperacute / acute / subacute / persisting records, especially ones with retrieved backups.
3. Confirm which legacy admin/email fields still exist after the merged XML is imported to REDCap.
4. Decide whether the repeated-measures script should also write dedicated flag files, or whether the markdown summary is sufficient.
5. If desired, add a thin notebook launcher that simply shells out to `run_all_qc_relaunch.py` without moving logic back into notebook cells.
