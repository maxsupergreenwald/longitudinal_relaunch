# REDCap Merge Worklog

## Directory Structure

```
Longitudinal_Relaunch/
├── xml/                              # REDCap XML exports
│   ├── PsychedelicsAim1Repe_2026-03-17_1912_merged_draft.REDCap.xml   ← ACTIVE DRAFT
│   ├── PsychedelicsAim1Repe_2026-03-17_1912.REDCap.xml                ← original baseline (do not edit)
│   ├── PsychedelicsAim1Repe_2026-03-17_1656.REDCap.xml                ← original longitudinal (do not edit)
│   └── PsychedelicsAim1Onli_2026-03-17_1420.REDCap.xml                ← spare original export
├── scripts/                          # Python QC scripts and old notebooks
│   ├── run_all_qc_relaunch.py        ← daily CLI wrapper (run this from scripts/)
│   ├── quickQC_api_calling_v7_relaunch.py   ← new baseline/screening QC
│   ├── quickQC_rpt_relaunch.py       ← new repeated-measures QC
│   ├── merge_redcap_projects.py      ← one-time merge script (reference only)
│   ├── quickQC_api_calling_v6_OnlyLongitudinal.ipynb   ← OLD notebook (reference)
│   └── quickQC_rpt_apicalls.ipynb    ← OLD notebook (reference)
├── docs/                             # Protocol docs, consent, and worklogs
│   ├── Aim8_RepeatedMeasuresConsent_3.3.26.pdf / .docx
│   ├── summary_2.26.26.docx
│   ├── redcap_merge_worklog.md       ← this file
│   ├── qc_tool_relaunch_worklog.md
│   └── qc_tools_protocol.md
└── csvs/                             # REDCap CSV exports (alerts, data dictionary, survey queue)
```

## Sources Reviewed
- `docs/summary_2.26.26.docx`
- `docs/Aim8_RepeatedMeasuresConsent_3.3.26.pdf` and `.docx`
- `xml/PsychedelicsAim1Repe_2026-03-17_1912.REDCap.xml`
- `xml/PsychedelicsAim1Repe_2026-03-17_1656.REDCap.xml`
- `csvs/Psychedelics1BLongitudinalRela_DataDictionary_2026-03-19.csv`
- `scripts/quickQC_api_calling_v6_OnlyLongitudinal.ipynb`

## Protocol / Consent Deltas
- Direct enrollment into the Aim 8 serotonergic psychedelic repeated-measures subgroup is now allowed.
- The repeated-measures schedule is baseline plus up to four follow-up opportunities: during use, day after use, 1-2 weeks after use, and 1-6 months after use.
- Screening happens immediately after consent.
- For the serotonergic subgroup, baseline requires at least 6 weeks since the most recent serotonergic or atypical psychedelic use.
- Cannabis exclusion is not supposed to block Aim 8 enrollment.
- The "more recent atypical psychedelic than serotonergic psychedelic" exclusion was removed.
- Participants should not use additional serotonergic or atypical psychedelics between the planned use event and the final follow-up.
- Compensation is now fixed at `$50` per completed session, maximum `$250`.
- Payment method should be standardized to Amazon.com US electronic gift cards.

## Prior Structure

### Former baseline project: `1912`
- Purpose: former first-contact project for both cross-sectional and longitudinal recruitment.
- Core participant path in survey queue:
  1. `consent_baseline`
  2. `screening_survey`
  3. `sms_verification`
  4. `screening_result`
  5. `eligibile`
  6. `survey_perception_substance_use`
  7. `family_history_and_asi`
  8. `visual_ch_task`
  9. `prl_task`
  10. `auditory_ch_task`
  11. `spacejunk_game`
  12. `validity_checks`
- Additional forms existed outside the main path:
  - `payment_form`
  - `clarification_survey`
  - `answer_checks`
  - `longitudinal_study_waiting`
  - `prolific_screening_result`
  - `visual_ch_task_shortened_dlb`
  - `extra_questions`
  - `add_on_questions`
  - `add_on_questions_yale`
  - `payment_confirmation`
  - `delayed_payment_confirmation`
  - `participation_resume`
  - `new_payment`
  - `email_alerts`
  - `reconsent_baseline`
- Screening gate:
  - Participants could not reach `eligibile` unless `screening_pass='1'`.
  - `screening_pass` was hidden on the consent instrument and set after semi-automatic / semi-manual QC review.
  - The queue logic used `screening_pass`, `student_yn`, `eligible_click`, and `sp_wait_pls`.
- Waiting path:
  - `screening_result` used `sp_wait_pls` plus a separate `longitudinal_study_waiting` instrument.
  - `continue_date` was calculated there and used by `longitudinal_continue_link` alerts.
  - The current waiting copy still references a 3-month or 6-month style wait and the older longitudinal setup.
- Payment structure:
  - Baseline project still contains Amazon, US Bank, Prolific, MTurk, physical card, and Yale-credit pathways.
  - Participant-facing text still references `$40`, US Bank gift cards, VISA cards, Prolific/MTurk, and Yale course credit.
- Yale-specific structure:
  - `student_yn`, `sona_id`, `study_summary_yale`, `screen_yaleemail`, Yale add-on forms, Yale QC alerts, and Yale-specific debrief fields remain in the export.
- Task data storage:
  - Baseline consent already stores baseline task payload fields such as `task_data_ach_task_short_baseline`, `task_data_vch_short_psychedelic_bl`, `task_data_prltask`, `task_data_spacejunk_bl`, and related retrieved / complete fields.

### Former longitudinal project: `1656`
- Purpose: separate repeated-measures project for invited longitudinal participants.
- Main instruments:
  - `consent_rpt`
  - `repeat_measures_study_instructions`
  - `hyperacute_presurvey` -> task chain -> `hyperacute_postsurvey`
  - `acute_presurvey` -> task chain -> `acute_postsurvey`
  - `subacute_presurvey` -> task chain -> `subacute_postsurvey`
  - `persisting_presurvey` -> task chain -> `persisting_postsurvey`
  - per-timepoint payment/admin instruments
- The repeated-measures export contains the follow-up questionnaires/tasks we need.
- The repeated-measures consent instrument also stores the longitudinal task payload fields and several follow-up admin fields including:
  - `random_rpt`
  - `email_rpt`
  - `include_hyp_measures`
  - many `task_data_*` fields for hyperacute / acute / subacute / persisting timepoints
- Existing longitudinal invitation logic is split between:
  - survey scheduler records
  - alerts
  - payment confirmation alerts
- The longitudinal export also still contains obsolete or draft material:
  - test scheduler emails for some task forms
  - Prolific / MTurk fields
  - `$40` payment text
  - Amazon + US Bank / VISA mixed payment wording

### QC notebook: `quickQC_api_calling_v6_OnlyLongitudinal.ipynb`
- Pulls records from the former baseline REDCap via API.
- Uses `screening_pass` and `qc_passed` as major gates.
- Screens for:
  - suspicious IP / geography
  - duplicate emails / identities
  - replay / fraudulent task payloads
  - suspicious phone numbers / VOIP
  - internal consistency problems
- Still includes logic for:
  - Yale students
  - control recruitment limits
  - cannabis zoom / cannabis wait path
  - longitudinal waiting path
  - recontact / reconsent remnants
- This means the current QC notebook is not yet aligned with the merged target structure.

### Likely redundant baseline content
- Clearly obsolete for the merged longitudinal-only flow:
  - `longitudinal_study_waiting`
  - `prolific_screening_result`
  - `visual_ch_task_shortened_dlb`
  - `extra_questions`
  - `add_on_questions`
  - `add_on_questions_yale`
  - `participation_resume`
  - `new_payment`
  - `reconsent_baseline`
- Likely admin-only and not participant path:
  - `payment_form`
  - `clarification_survey`
  - `answer_checks`
  - `payment_confirmation`
  - `delayed_payment_confirmation`

### Repeated / overlapping content
- `repeat_measures_study_instructions` duplicates baseline ASI and substance-use-history content in part.
- Some baseline ASI and lifetime substance-use material appears to overlap with follow-up instruments.
- Follow-up task payload fields are currently split across the two projects; the merged design should consolidate them into the first instrument.

## Unique Baseline Elements Likely Worth Preserving
- `screening_pass` gate and related QC review pause.
- `eligible_notify` style email-to-continue concept.
- Baseline questionnaires/tasks already wired to the fraud/QC process.
- Existing baseline task storage fields and `encrypted_metadata_uri`.
- Admin forms and fields currently used by the QC workflow:
  - `clarification_survey`
  - `answer_checks`
  - `verify_emailed`
  - `sp_tot_verify`
  - `sp_verify_pass`

## Questions / Ambiguities For User Input
1. ~~The consent amendment says the final follow-up opportunity is `1-6 months after use`, while some current project logic and text still concretely schedule the first persisting invitation at `30 days`. I am assuming the first invitation should go out at `30 days` and remain available / repeat thereafter unless you want a different first send date.~~ **RESOLVED (2026-03-18): First persisting invitation at 30 days, repeat monthly thereafter. Confirmed.**
2. ~~The former longitudinal build includes an `include_hyp_measures` flag that looks like an internal way to suppress the hyperacute timepoint. I am assuming the hyperacute timepoint remains available and optional by default.~~ **RESOLVED (2026-03-18): Available to all, not required. Confirmed.**
3. ~~The old QC workflow includes `clarification_survey` / `answer_checks` follow-up fields for inconsistent psychedelic answers. I am assuming those should stay as hidden admin tools for now rather than be deleted immediately.~~ **RESOLVED (2026-03-18): Keep them. Confirmed.**
4. ~~The merged project needs a single email field for follow-up invitations. I am assuming we should add / preserve a dedicated study-contact email (`email_rpt`) rather than rely only on the Amazon payment email.~~ **RESOLVED (2026-03-18): `email_rpt` confirmed.**
5. ~~I am assuming baseline should still be paid as its own completed session, bringing the total possible compensation to five paid sessions.~~ **RESOLVED (2026-03-18): Yes, 5 sessions × $50 = $250 max. Confirmed.**

## Assumptions I Am Proceeding With
- The merged project should be longitudinal SP-only from the participant-facing side.
- Cannabis-specific exclusion, zoom, and recontact paths should be removed from participant flow.
- Yale / SONA / Intro Psych / course-credit pathways should be removed from participant flow even if a few hidden backend compatibility fields remain temporarily.
- Amazon.com US electronic gift card is the only participant-facing payment path.
- The former baseline XML should remain preserved; edits should be written to a new draft XML so the original export stays available for reference.

## Decision Log
- Preserved the original baseline XML untouched and generated a separate draft output file for the merged build.
- Kept `clarification_survey` and `answer_checks` in the project for now because the current QC notebook still references the associated verification workflow.
- Kept many obsolete Yale / Prolific / MTurk / US Bank / VISA fields only as hidden compatibility remnants rather than deleting every underlying item definition immediately.
- Chose `email_rpt` as the dedicated study-contact / follow-up invitation field and set it as the project-level survey invitation email field.
- Replaced the old waiting instrument path with a screening-results-based 6-week hold / reminder pattern.
- Used REDCap alerts rather than the old longitudinal scheduler records for the new draft timepoint invitation flow.
- Interpreted the requested hidden `psyched_percent_*` compatibility fields literally as proportions (`count / total`, 0-1) rather than 0-100 manually entered percentages.
- Converted old redundant microdose compatibility fields (`microdose_yn`, `psycheduse_life_micro`, `psych_dayslastuse_micro`) into hidden derived fields instead of leaving them participant-facing.

## Changes Made
- Created this worklog and documented the current-state structure before editing the XML.
- Added `merge_redcap_projects.py` to generate a merged draft XML from the two REDCap exports.
- Generated `PsychedelicsAim1Repe_2026-03-17_1912_merged_draft.REDCap.xml`.
- Imported the longitudinal follow-up survey instruments into the baseline draft:
  - hyperacute
  - acute
  - subacute
  - persisting
  - per-timepoint payment confirmation / admin forms
- Added the follow-up task payload fields plus supporting longitudinal admin fields (`email_rpt`, `random_rpt`, `include_hyp_measures`, `prolific_yn_rpt`) into the first instrument (`consent_baseline`) where needed for task storage / follow-up logic.
- Set the project-level survey invitation email field to `email_rpt`.
- Removed obsolete form definitions from the active merged draft:
  - `longitudinal_study_waiting`
  - `prolific_screening_result`
  - `visual_ch_task_shortened_dlb`
  - `extra_questions`
  - `add_on_questions`
  - `add_on_questions_yale`
  - `payment_confirmation`
  - `delayed_payment_confirmation`
  - `participation_resume`
  - `new_payment`
  - `email_alerts`
  - `reconsent_baseline`
- Rebuilt the participant survey queue into a simple linear baseline path:
  1. consent
  2. screening
  3. SMS verification
  4. screening results
  5. eligible page after reviewer approval
  6. baseline questionnaires / tasks
  7. validity checks
- Updated participant-facing payment setup in the draft:
  - hidden legacy payment method choice
  - defaulted the backend payment method to Amazon gift card
  - updated the visible payment email prompt to Amazon.com US electronic gift card wording
- Updated screening logic in the draft:
  - `sp_lastuse_days_screen` now explicitly refers to serotonergic or atypical psychedelic use
  - `sp_wait_pls` now presents a 6-week hold/reminder option on screening results
  - `continue_date` now calculates from `timestamp_screen_day` and `sp_lastuse_days_screen` using a 42-day threshold
  - `submit_screen_v3` now only appears for likely-eligible participants who either have no prior SP use / only microdose history or are already at least 42 days from their last SP / atypical use
- Added new alert-driven invitation flow in the draft:
  - immediate confirmation that a recent-use participant will receive a reminder later
  - scheduled 6-week continuation email
  - post-baseline day-of / hyperacute invitation
  - post-baseline day-after / acute invitation
  - 1-2 week follow-up invitation
  - 1-6 month follow-up invitation
  - imported / adapted the 24-hour reminder alert
- Hid obvious Yale / SONA / Prolific / MTurk / US Bank / VISA legacy fields in the draft so they are not participant-facing even where item definitions remain in the XML.
- Updated the participant-facing `TLDR` study-description text on the `interested_spstudy_consent` checkbox prompt so it now describes the current longitudinal workflow:
  - consent
  - screening
  - baseline
  - brief pre-use surveys
  - follow-up sessions around the next planned SP use
  - 6-week lookback and no-additional-use expectation through final follow-up
- Replaced the old lifetime subjective-dose percentage workflow in the baseline SP-use module:
  - added a new participant-facing subjective dose guide using the threshold / light / common / strong / heavy framework
  - kept backward-compatible legacy suffix conventions (`_micro`, `_low`, `_medium`, `_heavy`, `_vheavy`)
  - replaced visible `% of uses` entry fields with visible count fields (`psyched_uses_*`)
  - made `psychedelicuse_lifetimetot` a hidden calc sum of all dose-count fields
  - made `psycheduse_life_nomic` a hidden calc sum excluding microdose / threshold counts
  - added a visible double-check descriptive field that displays the derived total and macrodose counts once all five dose-count fields are filled
  - added per-dose follow-ups for age first used and approximate last-use date for each dose bin
  - added hidden per-dose `datediff` fields (`psyched_dayslastuse_*`)
  - converted the legacy hidden compatibility fields `psyched_percent_*` to calculated values based on the new count fields
  - converted `microdose_yn`, `psycheduse_life_micro`, and `psych_dayslastuse_micro` into hidden compatibility fields derived from the new count/date fields
- Updated the participant-facing subjective-dose prompts and code lists across active baseline and follow-up instruments so they no longer reference the old HealingMaps / LSD-microgram guide:
  - `psyched_lastuse_dose`
  - `subjectivedose_hyp`
  - `subjectivedose_acu`
  - `subjectivedose_sub`
  - `subjectivedose_pers`
- Replaced SES money questions with the new ordinal household-money wording and response options in the active baseline, verification, and addon variants:
  - `ses_income`
  - `ses_income_parents`
  - `ses_income_verify`
  - `ses_income_parents_verify`
  - `ses_income_addon`

## Survey Settings Audit (2026-03-18)
Full audit of all 43 survey settings blocks in the merged draft. Key findings and fixes:

### Fixed
- `validity_checks` acknowledgement: updated to explain QC review, inform participant they will receive two emails (hyperacute + acute invitations) immediately after baseline, plus automated subacute and persisting invitations; includes $50 baseline payment info.
- `spacejunk_game` acknowledgement: was incorrectly saying "allow 10 business days for Amazon gift card; 20 for VISA" — spacejunk is not the final instrument. Replaced with "Almost there! Click to continue to the final set of questions."
- `persisting_presurvey` acknowledgement: was copy-pasted from `hyperacute_presurvey` ("set an alarm once you take your psychedelic"). Corrected to simple "Thank you! Next up: the games!"
- `subacute_postsurvey` acknowledgement: was generic "Thank you. Have a nice day." Updated to inform participant that a persisting invitation will arrive in ~1 month.
- `persisting_postsurvey` acknowledgement: was generic "Thank you. Have a nice day." Updated to thank participant for completing the full study and include $50 final payment info.

### Confirmed Correct
- `sms_verification`: auto-redirects to next survey when `[phone_number]<>""` ✓
- `eligibile`: `redirect_next_surv=1`, auto-advances after reviewer unlocks ✓
- All follow-up task chains (`*_hyp`, `*_acu`, `*_sub`, `*_pers`): `redirect_next_surv=1` ✓
- `space_junk_*` follow-up variants: `save_and_return=0` (correct for tasks) ✓
- `hyperacute_postsurvey` acknowledgement: correctly tells participant acute email is already in their inbox ✓
- `acute_postsurvey` acknowledgement: correctly describes subacute (1-2 weeks) and persisting (1-6 months) timing ✓

### Known Residual Issues
- `consent_baseline` acknowledgement: appears to contain old response-cap text ("survey temporarily closed for pay period"); this is non-critical because the survey queue auto-advances past consent and participants do not normally see this screen, but it should be cleaned up in a future pass.
- `payment_form_*` and `payment_confirmation_*` acknowledgements are all generic "Thank you. Have a nice day." — acceptable for admin-only forms but could be improved later.

## Remaining Risks / Follow-Up
- The e-consent payload itself has not yet been fully swapped to the new IRB-approved consent document inside the REDCap XML attachment / e-consent machinery. The draft currently updates surrounding participant-facing workflow text and structure, but the actual embedded e-consent artifact still needs a careful dedicated pass.
- The current QC notebook is still built around the older baseline schema and waiting / Yale / cannabis remnants. It should be revised after the XML structure is finalized.
- The merged draft still contains hidden legacy item definitions for compatibility; a later cleanup pass could remove unused underlying item / alert definitions more aggressively once the new workflow is confirmed.
- Any downstream code or analysis that assumed the legacy `psyched_percent_*` fields were stored as 0-100 values will need to be updated, because the new hidden compatibility fields now store proportions from 0 to 1.
