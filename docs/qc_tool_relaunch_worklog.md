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

---

## Testing Harness Build — 2026-03-24

Added `qc_testing_debug.py` and `qc_relaunch_testing.md` as the official roundtrip testing system for `quickQC_api_calling_v7_relaunch.py`.

### Files added / modified
- `scripts/qc_testing_debug.py` — new test helper script
- `scripts/qc_relaunch_testing.md` — new testing guide (all scenarios documented)

### Snapshot persistence (CSV, not JSON)
- Snapshot files are now CSV + pandas, not JSON.
  - `qc_test_snapshot_screening.csv` — saved before Stage 1; restored after each ELIG/SCR test
  - `qc_test_snapshot_baseline.csv` — saved before Stage 2; restored after each BL test
- `cmd_snapshot`: `project.export_records() → df.to_csv()`
- `cmd_restore`: `pd.read_csv(dtype=str, keep_default_na=False) → redcap_import_fields()`

### Local shared drive (no mount needed)
- `SHAREDDRIVE_NETWORK_PATH` now defaults to `scripts/qc_test_drive/` (created by `cmd_setup`).
- Production line (commented out): `/Volumes/psychedelics/online`
- `_check_incomplete_flags` auto-creates the folder instead of crashing when the drive is absent.

### Bug fixes in `quickQC_api_calling_v7_relaunch.py`
- `nonempty_task_series` lambda: wrapped return in `bool()` to prevent mixed str/bool Series that broke the `|` operator.
- FutureWarning on dtype-incompatible column assignment: cast `ineligibilty_reason` and `qc_notes` columns to `object` before setting string values.
- `parse_redcap_pdf_log` rewritten to handle both old (tab-delimited) and new (pid=936, `_id{N}_` filename, IP concatenated directly after `HH:MM`) REDCap PDF archive formats.

### Clickable hyperlinks in terminal output
- Added `hyperlink(url, text)` to `quickQC_api_calling_v7_relaunch.py` using OSC 8 escape sequences — renders as underlined clickable text in VS Code terminal.
- Used in `collect_phone_verdicts` (SpyDialer, IPQuality Score, IPInfo) and `_load_and_update_ip_database` (REDCap PDF archive link).
- `_hyperlink()` also added to `qc_testing_debug.py` for the REDCap record link printed in ELIG checklists.

### Rich `cmd_apply` output (`_print_scenario_checklist`)
- Prints the scenario header, all modifications applied (REDCap fields + IP config + dupe record), expected outcome (key fields, alerts triggered, other fields), prompts to enter during the QC script run, the exact commands to run next, and the NEXT UP scenario.
- ELIG scenarios show a different block: "WHAT TO CHECK IN REDCAP" with the scenario's `notes`, a clickable REDCap record link, and "Press Enter to auto-restore."
- SCR/BL scenarios now use `restore baseline` vs `restore screening` dynamically based on `spec.category`.

### IP CSV starts empty
- `cmd_setup` writes an empty `ips_full.csv` (no placeholder 1.2.3.4 row).
- Forces the full copy-paste IP flow to be exercised on first test run.

### Stage 0 — Eligibility Scenarios (ELIG-XX)
- **Key insight:** REDCap's eligibility formula gates `submit_screen_v3`. Participants failing eligibility never reach the QC queue. Eligibility testing is purely manual — the QC script has nothing to check.
- Added 16 ELIG scenarios (ELIG-00 through ELIG-15) with `category="eligibility"`, `expected_fields={}`, `ip_config=None`, `prompts=[]`.
  - ELIG-00 to ELIG-09: basic eligibility criteria (age, cognition, seizure, intox, computer, Raven, geo, SP use, English)
  - ELIG-10 to ELIG-15: SP / salvia / MDMA wait-path scenarios (used within 6 weeks × willing/not willing to wait)
- `cmd_apply` for ELIG: imports fields → `_print_scenario_checklist` (checklist-only block) → `input("Press Enter…")` → `cmd_restore("screening")`
- `cmd_verify` for ELIG: prints "manual verification only" and returns early — no field checks.
- `cmd_list`: new ELIG section (Stage 0) shown before SCR (Stage 1) and BL (Stage 2).

### SCR-XX renumbering
- Removed SCR-01 through SCR-11 (eligibility criteria that moved to ELIG).
- Renumbered remaining scenarios:

| New ID | Old ID | Scenario |
|---|---|---|
| SCR-00 | SCR-00 | Clean pass (unchanged) |
| SCR-01 | SCR-11b | SP wait, clean |
| SCR-02 | SCR-11c | SP wait, VOIP phone |
| SCR-03 | SCR-11d | MDMA wait, clean |
| SCR-04 | SCR-12 | Duplicate email |
| SCR-05 | SCR-13 | Forbidden IP org |
| SCR-06 | SCR-14 | Forbidden IP country |
| SCR-07 | SCR-15 | Suspicious duplicate IP |
| SCR-08 | SCR-16 | Phone verdict: VOIP |
| SCR-09 | SCR-17 | Phone verdict: manual follow-up |
| SCR-10 | SCR-18 | Missing IP metadata |
| SCR-11 | SCR-19 | Kaopectamine trap |
| SCR-12 | SCR-20 | Flexibility honeypot |
| SCR-13 | SCR-21 | Screen too fast |
| SCR-14 | SCR-22 | 500-char motive |
| SCR-15 | SCR-23 | AI template phrase |
| SCR-16 | SCR-24 | Both AI flags |

- Fixed `_setup_dupe_record` to use new IDs: `SCR-12` → `SCR-04`, `SCR-15` → `SCR-07`.
- Fixed `_REDCAP_RECORD_URL` constant placement (was inside `SCENARIOS` dict literal, causing `SyntaxError`; moved outside).

### `qc_relaunch_testing.md` restructure
- Replaced Overview with a three-stage table (ELIG / SCR / BL).
- Updated One-Time Setup: removed env var export step (path defaults locally); fixed `.json` → `.csv` snapshot filenames.
- Updated Standard Test Cycle: added Stage 0 cycle (apply-only, no QC script, no verify, auto-restore); removed `export AIM8_SHAREDDRIVE_PATH` lines from code blocks.
- Updated Important Notes: added ELIG auto-restore note; updated dupe-record scenario references (SCR-04/07 instead of SCR-12/15).
- Replaced the entire old Screening Scenarios section with:
  - Stage 0 (ELIG-00 through ELIG-15): field set + expected REDCap outcome per scenario
  - "Graduating from Stage 0 to Stage 1" bridge
  - Stage 1 (SCR-00 through SCR-16): full scenario documentation with new IDs
- Updated stale IP-scenario reference at bottom of doc (SCR-13/14/15/18 → SCR-05/06/07/10).
