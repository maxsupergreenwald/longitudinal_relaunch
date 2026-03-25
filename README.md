# Longitudinal_Relaunch

REDCap project rebuild for the Aim 8 serotonergic psychedelics (SP) longitudinal study (Powers Lab, Yale).

The two former REDCap projects — a baseline/screening project and a separate repeated-measures follow-up project — have been merged into a single streamlined project per the IRB amendment (March 2026).

## Directory Layout

```
Longitudinal_Relaunch/
├── xml/          REDCap XML exports
├── scripts/      Python QC scripts (run from this folder)
├── docs/         Protocol docs, consent forms, worklogs
└── csvs/         REDCap CSV exports (alerts, data dictionary, survey queue)
```

### xml/
| File | Description |
|------|-------------|
| `PsychedelicsAim1Repe_2026-03-17_1912_merged_draft.REDCap.xml` | **Active working draft** — import this into REDCap |
| `PsychedelicsAim1Repe_2026-03-17_1912.REDCap.xml` | Original baseline project export — do not edit |
| `PsychedelicsAim1Repe_2026-03-17_1656.REDCap.xml` | Original longitudinal follow-up project export — do not edit |
| `PsychedelicsAim1Onli_2026-03-17_1420.REDCap.xml` | Spare original export |

### scripts/
Run all scripts from within the `scripts/` directory.

**Active scripts:**

| File | Description |
|------|-------------|
| `run_all_qc_relaunch.py` | **Daily wrapper** — runs screening, baseline, and follow-up QC in one pass |
| `quickQC_api_calling_v7_relaunch.py` | Baseline and screening QC/payment tool |
| `quickQC_rpt_relaunch.py` | Repeated-measures (follow-up) QC/payment tool |
| `qc_testing_debug.py` | QC test helper — manages REDCap state for roundtrip scenario testing |
| `qc_relaunch_testing.md` | Testing guide — all ~63 test scenarios (ELIG-00–15, SCR-00–16, BL-00–27+) with instructions |

**Legacy scripts** (moved to `scripts/legacy/` — reference only, no longer in active use):

| File | Description |
|------|-------------|
| `legacy/quickQC_api_calling_v6_OnlyLongitudinal.ipynb` | Old baseline QC notebook — superseded by v7 |
| `legacy/quickQC_rpt_apicalls.ipynb` | Old follow-up QC notebook — superseded by `quickQC_rpt_relaunch.py` |
| `legacy/merge_redcap_projects.py` | One-time script used to generate the merged draft |
| `legacy/restructure_drug_questions.py` | One-time drug question migration utility |

### docs/
| File | Description |
|------|-------------|
| `Aim8_RepeatedMeasuresConsent_3.3.26.pdf` | IRB-approved consent form for Aim 8 |
| `Aim8_RepeatedMeasuresConsent_3.3.26.docx` | Consent form source |
| `summary_2.26.26.docx` | Protocol amendment summary |
| `redcap_merge_worklog.md` | Full worklog for the XML merge — prior structure, changes, decisions, open questions |
| `qc_tool_relaunch_worklog.md` | Worklog for new QC script development |
| `qc_tools_protocol.md` | Operational SOP for running the QC tools |

### csvs/
Working REDCap CSV exports — **these are the live working copies, not just references.**

| File | Description |
|------|-------------|
| `Psychedelics1BLongitudinalRela_DataDictionary_2026-03-20.csv` | **Active data dictionary** — import into REDCap to update fields |
| `Psychedelics1BLongitudinalRela_Alerts_2026-03-20.csv` | **Active alerts** — 68 alerts total (60 original + 8 new follow-up payment alerts A-1399–A-1406) |
| `PsychedelicsAim1RepeatedMeasur_Alerts_2026-03-20.csv` | Reference alerts from old repeated-measures project — do not edit |

#### Data Dictionary key changes (as of 2026-03-20)
- `email_rpt` replaces `payment_email_bl` — single field for study comms + Amazon gift cards
- `kaopectamine_lifetime` — fake drug trap question (radio, `lifetime_use` matrix, after salvia)
- `fraud_caps`, `fraud_pdi` — attention check fields (yesno; correct = Yes; No flagged by QC)
- `validity_sp_dose` + `sp_most_recent_dose` + `fraud_recent_dose` — dose self-report validity system
- 21 `@HIDDEN-SURVEY` ineligibility reason descriptives at top of `screening_result`
- Dose bins renamed: threshold / light / common / strong / heavy

#### Alerts key changes (as of 2026-03-20)
- All participant-facing alerts now send from `maximillian.greenwald@yale.edu` (`Powers Lab @ Yale University`) to `[email_rpt]`
- Payment Confirmation Receipt alerts A-1399/1401/1403/1405 (Hyp/Acu/Sub/Pers): 21-day lag, triggered by `qc_passed_X=1 AND send_pay_confirm_X=1` — **start deactivated, activate when follow-up collection begins**
- Payment Late researcher alerts A-1400/1402/1404/1406 (Hyp/Acu/Sub/Pers): triggered by `payment_confirm_X=0` — **start deactivated**

## Quick Start (Daily QC Run)
```bash
cd scripts/
python3 run_all_qc_relaunch.py
```

See `docs/qc_tools_protocol.md` for full instructions.
