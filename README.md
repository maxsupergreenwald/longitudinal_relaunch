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

| File | Description |
|------|-------------|
| `run_all_qc_relaunch.py` | **Daily wrapper** — runs screening, baseline, and follow-up QC in one pass |
| `quickQC_api_calling_v7_relaunch.py` | Baseline and screening QC/payment tool |
| `quickQC_rpt_relaunch.py` | Repeated-measures (follow-up) QC/payment tool |
| `merge_redcap_projects.py` | One-time script used to generate the merged draft — reference only |
| `quickQC_api_calling_v6_OnlyLongitudinal.ipynb` | Old baseline QC notebook — reference only |
| `quickQC_rpt_apicalls.ipynb` | Old follow-up QC notebook — reference only |

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
REDCap project exports used for reference during the merge and QC build:
- Alerts export
- Data dictionary export
- Survey queue export
- ASI export (pid 606)

## Quick Start (Daily QC Run)
```bash
cd scripts/
python3 run_all_qc_relaunch.py
```

See `docs/qc_tools_protocol.md` for full instructions.
