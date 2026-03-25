# QC Testing Guide — Aim 8 Relaunch

Testing roundtrip for `quickQC_api_calling_v7_relaunch.py`. The companion script `qc_testing_debug.py` manages REDCap state before and after each scenario run so you can validate every QC code path against a single test record (record_id=1) without touching real participant data.

---

## Overview

Three stages of testing:

| Stage | ID prefix | How it works |
|---|---|---|
| 0 — Eligibility | ELIG-00 to ELIG-15 | `apply` imports fields → you check REDCap manually → press Enter → auto-restores |
| 1 — Screening fraud | SCR-00 to SCR-16 | `apply` → run QC script → `verify` → `restore screening` |
| 2 — Baseline QC | BL-00 to BL-27+ | `apply` → run QC script → `verify` → `restore baseline` |

**Total: 16 ELIG + 17 SCR + ~30 BL scenarios.**

---

## Prerequisites

**record_id=1 in REDCap must have:**
- A complete, passing screening survey (`submit_screen_v3` present, `screening_pass` and `qc_passed` null, `phone_number` present)
- Valid task data in all three task fields (`task_data_ach_task_short_baseline`, `task_data_vch_short_psychedelic_bl`, `task_data_prltask`)
- `race_qc` present (copy of `race_v2` from screening)
- All questionnaire fields filled in with plausible passing values

**record_id=9998 in REDCap** must exist as an empty test-only record. Confirm this ID does not conflict with any real study participant before first use.

**Python dependencies:** `pip install pycap pandas`

---

## One-Time Setup

**Step 1 — Create the mock shared drive:**
```bash
cd scripts/
python3 qc_testing_debug.py setup
```
This creates `scripts/qc_test_drive/` with the required directory structure and a stub `ips_full.csv` for record_id=1 (clean US IP).

**Step 2 — The shared drive path defaults to `scripts/qc_test_drive/` automatically** (no env var needed for local testing). The QC script picks it up via the modular path config in `quickQC_api_calling_v7_relaunch.py`.

**Step 3a — Save the screening snapshot** (run once record_id=1 has a submitted screening survey, `screening_pass` and `qc_passed` null, `phone_number` present — no task data needed yet):
```bash
python3 qc_testing_debug.py snapshot screening
```
Saves to `qc_test_snapshot_screening.csv`. Use `restore screening` between every ELIG-XX and SCR-XX test.

**Step 3b — Save the baseline snapshot** (run _after_ Stage 1 is complete and you have upgraded record_id=1: all task data present, `screening_pass=1`, `qc_passed` null):
```bash
python3 qc_testing_debug.py snapshot baseline
```
Saves to `qc_test_snapshot_baseline.csv`. Use `restore baseline` between every BL-XX test.

**Step 4 — Load task failure payloads** (required before BL-17, BL-19, BL-21, BL-22, BL-25):
```bash
python3 qc_testing_debug.py load-payloads
```
Four payloads are auto-loaded from `resources/failed_task_examples.csv` (`ach_zero`, `vch_negative`, `prl_worse_than_chance`, `prl_non_responders`). The wizard prompts you to paste the remaining five from your saved JSON strings document.

---

## Standard Test Cycle

### Stage 0 — Eligibility scenarios (ELIG-XX)
`apply` handles everything automatically: imports fields, prints what to check, waits for you to press Enter, then auto-restores. No QC script run needed.

```bash
# Just run apply — it will prompt you to check REDCap, then auto-restore
python3 qc_testing_debug.py apply ELIG-XX
```

Repeat for ELIG-00 through ELIG-15.

### Stage 1 — Screening fraud scenarios (SCR-XX)
Use `restore screening` after every run. Record_id=1 must be in the screening-ready state (screening snapshot taken via Step 3a above).

```bash
# 1. Apply the scenario (sets REDCap fields, updates ips_full.csv)
python3 qc_testing_debug.py apply SCR-XX

# 2. Run the QC script (follow the prompts printed by apply)
python3 quickQC_api_calling_v7_relaunch.py

# 3. Verify results
python3 qc_testing_debug.py verify SCR-XX

# 4. Restore the screening snapshot before the next scenario
python3 qc_testing_debug.py restore screening
```

### Stage 2 — Baseline scenarios (BL-XX)
Once all SCR scenarios pass: complete record_id=1 (add task data, confirm `screening_pass=1`, null `qc_passed`), take the baseline snapshot (Step 3b above), then use `restore baseline` after every run.

```bash
# 1. Apply the scenario
python3 qc_testing_debug.py apply BL-XX

# 2. Run the QC script
python3 quickQC_api_calling_v7_relaunch.py

# 3. Verify results
python3 qc_testing_debug.py verify BL-XX

# 4. Restore the baseline snapshot before the next scenario
python3 qc_testing_debug.py restore baseline
```

**Useful commands:**
```bash
python3 qc_testing_debug.py list              # show all scenario IDs and expected outcomes
python3 qc_testing_debug.py show SCR-05       # print scenario details without applying
```

---

## Important Notes Before Running

- **Always restore before applying the next scenario.** Leftover field values from the previous run will corrupt the test state.
- **ELIG scenarios auto-restore** — no manual `restore screening` needed after each ELIG run. Just press Enter when prompted.
- **INCOMPLETE flag files block the QC script.** If a run crashes mid-execution, flag files remain in `qc_test_drive/qc_to_dos/`. The `restore` command clears them automatically.
- **SCR-07 sets `ip_zoom_invite=1`.** This field is written to REDCap and will appear in the restored snapshot's fields. The snapshot already contains the pre-test value, so `restore` handles it.
- **BL-16a/b/c and SCR-04/SCR-07 use record_id=9998.** The `restore` command clears all test fields on record 9998 after each run.
- **Task retry scenarios (BL-17 through BL-26) do NOT set `qc_passed=0`.** At baseline, task slope failures route to `_queue_task_retry()`. Only questionnaire/fraud checks cause `qc_passed=0`. See scenario notes.
- **Snapshots must be retaken** if you permanently change record_id=1's data. Retake `snapshot screening` if you change demographics or screening fields; retake `snapshot baseline` if you update task data or questionnaire values.

---

## Stage 0 — Eligibility Scenarios (ELIG-XX)

These scenarios test REDCap's eligibility formula and branching logic. The QC script never sees participants who fail eligibility (they can't reach `submit_screen_v3`), so these are manual checks only.

**Cycle for each ELIG scenario:**
1. Run `apply ELIG-XX` — imports fields, prints what to verify in REDCap, waits for Enter, then auto-restores
2. Navigate to the record in REDCap and confirm what you see matches the expected outcome
3. Press Enter — script restores the screening snapshot automatically

The record link is printed by `apply` as a clickable hyperlink in the terminal.

---

### ELIG-00 — Age Too Old

**Field set:** `age_v2=70`

**Expected in REDCap:** INELIGIBLE — `inelig_age_old` descriptive field visible in `screening_result`. `submit_screen_v3` not accessible.

```bash
python3 qc_testing_debug.py apply ELIG-00
```

---

### ELIG-01 — Age Too Young

**Field set:** `age_v2=16`

**Expected in REDCap:** INELIGIBLE — `inelig_age_young` descriptive field visible in `screening_result`.

```bash
python3 qc_testing_debug.py apply ELIG-01
```

---

### ELIG-02 — Cognition Screener Failed

**Field set:** `cognition_screener_v2=1`

**Expected in REDCap:** INELIGIBLE — cognition ineligibility message visible in `screening_result`.

```bash
python3 qc_testing_debug.py apply ELIG-02
```

---

### ELIG-03 — Seizure History

**Field set:** `seizure_hx_v2=1`

**Expected in REDCap:** INELIGIBLE — seizure ineligibility message visible in `screening_result`.

```bash
python3 qc_testing_debug.py apply ELIG-03
```

---

### ELIG-04 — Intoxication at Intake

**Field set:** `intox_screen_v2=1`

**Expected in REDCap:** INELIGIBLE — intoxication ineligibility message visible in `screening_result`.

```bash
python3 qc_testing_debug.py apply ELIG-04
```

---

### ELIG-05 — No Computer Access

**Field set:** `no_computer=1`

**Expected in REDCap:** INELIGIBLE — no-computer ineligibility message visible in `screening_result`.

```bash
python3 qc_testing_debug.py apply ELIG-05
```

---

### ELIG-06 — Raven Score Too Low

**Field set:** `raven_total_score_v2=0`

**Expected in REDCap:** INELIGIBLE — Raven ineligibility message visible in `screening_result`.

```bash
python3 qc_testing_debug.py apply ELIG-06
```

---

### ELIG-07 — Geographic Criterion Not Met

**Field set:** `geo_crit=""` (blank)

**Expected in REDCap:** INELIGIBLE — geographic ineligibility message visible in `screening_result`.

```bash
python3 qc_testing_debug.py apply ELIG-07
```

---

### ELIG-08 — No Prior Psychedelic Use

**Field set:** `psycheduse_yn=2`

**Expected in REDCap:** INELIGIBLE — SP-use ineligibility message visible in `screening_result`. `sp_dayslastuse` will be blank because the SP use question is hidden.

```bash
python3 qc_testing_debug.py apply ELIG-08
```

---

### ELIG-09 — English Fluency Not Met

**Field set:** `english_fluency=0`

**Expected in REDCap:** INELIGIBLE — English fluency ineligibility message visible in `screening_result`.

```bash
python3 qc_testing_debug.py apply ELIG-09
```

---

### ELIG-10 — SP Used Within 6 Weeks, NOT Willing to Wait

**Field set:** `sp_dayslastuse_date` = today − 30 days (computed by `apply`; sets the `sp_dayslastuse` calc to ~30). `psychedelic_abstinence_yn` not set.

**Expected in REDCap:** INELIGIBLE — `inelig_sp_recentuse` descriptive field visible. `submit_screen_v3` not accessible.

```bash
python3 qc_testing_debug.py apply ELIG-10
```

---

### ELIG-11 — SP Used Within 6 Weeks, WILLING to Wait

**Field set:** `sp_dayslastuse_date` = today − 30 days, `psychedelic_abstinence_yn=1`

**Expected in REDCap:** ELIGIBLE — `submit_screen_v3` accessible. `inelig_sp_recentuse` NOT visible. `days_to_eligible` should show ~12 days.

```bash
python3 qc_testing_debug.py apply ELIG-11
```

---

### ELIG-12 — Salvia Used Within 6 Weeks, NOT Willing to Wait

**Field set:** `salvia_lifetime=1`, `salvia_dayslastuse_date` = today − 14 days (sets `salvia_dayslastuse` calc to ~14, which triggers `atypical_recentuse=1`). `psychedelic_abstinence_yn` not set.

**Expected in REDCap:** INELIGIBLE — `inelig_atypical` descriptive field visible.

```bash
python3 qc_testing_debug.py apply ELIG-12
```

---

### ELIG-13 — Salvia Used Within 6 Weeks, WILLING to Wait

**Field set:** `salvia_lifetime=1`, `salvia_dayslastuse_date` = today − 14 days, `psychedelic_abstinence_yn=1`

**Expected in REDCap:** ELIGIBLE — `submit_screen_v3` accessible. `inelig_atypical` NOT visible. `days_to_eligible` should show ~28 days.

```bash
python3 qc_testing_debug.py apply ELIG-13
```

---

### ELIG-14 — MDMA Used Within 6 Weeks, NOT Willing to Wait

**Field set:** `mdma_lifetime=1`, `mdma_dayslastuse_date` = today − 14 days (sets `mdma_dayslastuse` calc to ~14, which triggers `atypical_recentuse=1`). `psychedelic_abstinence_yn` not set.

**Expected in REDCap:** INELIGIBLE — `inelig_atypical` descriptive field visible.

```bash
python3 qc_testing_debug.py apply ELIG-14
```

---

### ELIG-15 — MDMA Used Within 6 Weeks, WILLING to Wait

**Field set:** `mdma_lifetime=1`, `mdma_dayslastuse_date` = today − 14 days, `psychedelic_abstinence_yn=1`

**Expected in REDCap:** ELIGIBLE — `submit_screen_v3` accessible. `inelig_atypical` NOT visible. `days_to_eligible` should show ~28 days.

```bash
python3 qc_testing_debug.py apply ELIG-15
```

---

## Graduating from Stage 0 to Stage 1

Once all ELIG scenarios check out:

1. Confirm record_id=1 is in the clean screening-ready state (the auto-restore after the last ELIG scenario handles this, but verify `screening_pass` and `qc_passed` are null).
2. Confirm the screening snapshot still reflects the clean state. If you changed any fields manually during ELIG testing, retake it:
   ```bash
   python3 qc_testing_debug.py snapshot screening
   ```
3. Proceed to SCR-00 below.

---

## Stage 1 — Screening Fraud Detection Scenarios (SCR-XX)

All screening scenarios require record_id=1 to be in the screening queue: screening survey submitted, `screening_pass` and `qc_passed` null, `phone_number` present.

**Cycle for each SCR scenario:**
1. `apply SCR-XX` — sets REDCap fields and updates `ips_full.csv`
2. `python3 quickQC_api_calling_v7_relaunch.py` — follow prompts shown by apply
3. `verify SCR-XX` — checks expected fields
4. `restore screening` — restores clean snapshot

---

### SCR-00 — Passes Screening

**What it tests:** Full screening pass path — all hard-fail checks pass, phone is valid, record gets `screening_pass=1`.

**Setup:** No overrides needed. Confirm record_id=1 has clean screening data.
```bash
python3 qc_testing_debug.py apply SCR-00
```

**QC script prompts:**
- User code: `m`
- Phone verdict: `n` (number looks clean)
- Import prompt: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 1 |
| `eligible_notify` | 1 |

**Verify:** `python3 qc_testing_debug.py verify SCR-00`
**Reset:** `python3 qc_testing_debug.py restore screening`

**Notes:** Reference case only. No field overrides are applied by `apply`. This confirms the clean state is actually passing before testing failure scenarios.

---

### SCR-01 — Recent SP Use, Willing to Wait (Clean)

**What it tests:** `sp_dayslastuse` ~30 (via `sp_dayslastuse_date` = today − 30) AND `psychedelic_abstinence_yn=1` AND clean IP/phone → sp_wait path → `screening_pass=1`, `eligible_afterwait_notify=1` (NOT `eligible_notify`).

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-01
```
Sets `sp_dayslastuse_date` to 30 days before today (computed at run time) and `psychedelic_abstinence_yn=1`.

**QC script prompts:**
- User code: `m`
- Phone verdict: `n` (looks clean)
- Import prompt: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 1 |
| `eligible_afterwait_notify` | 1 |
| `eligible_notify` | (blank/null — NOT set) |

**Verify:** `python3 qc_testing_debug.py verify SCR-01`
**Reset:** `python3 qc_testing_debug.py restore screening`

**Notes:** This record is now queued to receive a continuation email at `continue_date` (calculated from the substance dayslastuse fields). The participant never receives the immediate `eligible_notify` email.

---

### SCR-02 — Recent SP Use, Willing to Wait, Fraudulent Phone

**What it tests:** `sp_dayslastuse` ~30 (via `sp_dayslastuse_date`), `psychedelic_abstinence_yn=1` (willing to wait), but user enters `y` at phone verdict → normal fraud path. sp_wait does NOT protect against explicit phone fraud.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-02
```
Sets `sp_dayslastuse_date` to 30 days before today and `psychedelic_abstinence_yn=1`. No other overrides — the `y` verdict causes the fail.

**QC script prompts:**
- User code: `m`
- Phone verdict: `y` (fraudulent/VOIP)
- Import prompt: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |
| `eligible_afterwait_notify` | (blank/null — NOT set) |

**Verify:** `python3 qc_testing_debug.py verify SCR-02`
**Reset:** `python3 qc_testing_debug.py restore screening`

---

### SCR-03 — Recent MDMA Use, Willing to Wait (Clean)

**What it tests:** `mdma_lifetime=1`, `mdma_dayslastuse_date` = today − 14 → `mdma_dayslastuse` calc ~14 → `atypical_recentuse=1` → sp_wait path. `psychedelic_abstinence_yn=1` → `screening_pass=1`, `eligible_afterwait_notify=1`.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-03
```
Sets `mdma_lifetime=1`, `mdma_dayslastuse_date` to 14 days before today (computed at run time), `psychedelic_abstinence_yn=1`.

**QC script prompts:**
- User code: `m`
- Phone verdict: `n`
- Import prompt: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 1 |
| `eligible_afterwait_notify` | 1 |
| `eligible_notify` | (blank/null) |

**Verify:** `python3 qc_testing_debug.py verify SCR-03`
**Reset:** `python3 qc_testing_debug.py restore screening`

**Notes:** `mdma_dayslastuse` and `atypical_recentuse` are REDCap calc fields — they are driven by `mdma_dayslastuse_date`, not set directly. If `atypical_recentuse` doesn't fire (REDCap calc lag after API import), set `atypical_recentuse=1` directly as a fallback.

---

### SCR-04 — Duplicate Email

**What it tests:** `email_rpt` on record_id=1 matches a prior screened record's email. `_apply_duplicate_identity_checks()` finds the match and fires hard fail.

**How it works:** `apply` sets `email_rpt=dupe_test@example.com` on record_id=1. It also imports `email_rpt=dupe_test@example.com` plus `datedone_screening_survey=2025-01-01` to record_id=9998 (marking it as a prior screened record). When the QC script runs, the email lookup finds the match.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-04
```

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |

**Verify:** `python3 qc_testing_debug.py verify SCR-04`
**Reset:** `python3 qc_testing_debug.py restore screening` (clears record_id=9998 fields)

---

### SCR-05 — Forbidden IP Organization

**What it tests:** IP org in `FORBIDDEN_IP_ORGS` (AS174 Cogent Communications) — hard fail from `ips_full.csv` lookup.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-05
```
Updates `ips_full.csv` row for record_id=1 to `org="AS174 Cogent Communications"`. No REDCap field overrides.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |

**Verify:** `python3 qc_testing_debug.py verify SCR-05`
**Reset:** `python3 qc_testing_debug.py restore screening`

---

### SCR-06 — Forbidden IP Country

**What it tests:** IP `country_name` in `FORBIDDEN_IP_COUNTRIES` (Nigeria) — hard fail from `ips_full.csv` lookup.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-06
```
Updates `ips_full.csv` row for record_id=1 to `country_name="Nigeria"`. No REDCap field overrides.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |

**Verify:** `python3 qc_testing_debug.py verify SCR-06`
**Reset:** `python3 qc_testing_debug.py restore screening`

---

### SCR-07 — Suspicious Duplicate IP

**What it tests:** Record_id=1 shares an IP with a prior reviewed/ineligible record. Automated checks pass, but `ip_zoom_invite=1` is set alongside `screening_pass=1` (flag for manual Zoom verification).

**How it works:** `apply` sets record_id=1's IP to `5.5.5.5` in `ips_full.csv`. It also adds record_id=9998 to `ips_full.csv` with the same IP, and imports `datedone_screening_survey=2025-01-01` + `qc_passed=0` to record_id=9998. The `prior_bad_ips` set in the script now includes `5.5.5.5`, which triggers the suspicious IP flag.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-07
```

**QC script prompts:**
- User code: `m`
- Phone verdict: `n` (number looks clean — the suspicious IP flag is separate from the phone check)
- Import prompt: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 1 |
| `eligible_notify` | 1 |
| `ip_zoom_invite` | 1 |

**Verify:** `python3 qc_testing_debug.py verify SCR-07`
**Reset:** `python3 qc_testing_debug.py restore screening`

**Notes:** Unlike SCR-05/06, this is NOT a hard fail. The participant passes screening but is flagged for an extra Zoom verification call.

---

### SCR-08 — Phone Verdict: VOIP/Fraudulent

**What it tests:** User enters `y` at the phone verdict prompt (phone appears fraudulent/VOIP) — manual hard fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-08
```
No field overrides — the record passes all automated checks. Only the `y` verdict causes the fail.

**QC script prompts:**
- User code: `m`
- Phone verdict: `y` (fraudulent/VOIP)
- Import prompt: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |

**Verify:** `python3 qc_testing_debug.py verify SCR-08`
**Reset:** `python3 qc_testing_debug.py restore screening`

---

### SCR-09 — Phone Verdict: Manual Follow-Up

**What it tests:** User enters `?` at the phone verdict prompt — record is flagged for Max's review (`max_number_followup=1`). NOT a fail — `screening_pass` and `qc_passed` remain blank.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-09
```
No field overrides.

**QC script prompts:**
- User code: `m`
- Phone verdict: `?` (needs manual review by Max)
- Import prompt: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `max_number_followup` | 1 |
| `screening_pass` | (blank/null) |
| `qc_passed` | (blank/null) |

**Verify:** `python3 qc_testing_debug.py verify SCR-09`
**Reset:** `python3 qc_testing_debug.py restore screening`

---

### SCR-10 — Missing IP Metadata

**What it tests:** No IP row exists for record_id=1 in `ips_full.csv` — record goes to `max_number_followup`. NOT a fail — `screening_pass` and `qc_passed` remain blank.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-10
```
Deletes the row for record_id=1 from `ips_full.csv`.

**QC script prompts:**
- User code: `m`
- When prompted for REDCap PDF archive rows: type `no ip` and press Enter
- Import prompt: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `max_number_followup` | 1 |
| `screening_pass` | (blank/null) |
| `qc_passed` | (blank/null) |

**Verify:** `python3 qc_testing_debug.py verify SCR-10`
**Reset:** `python3 qc_testing_debug.py restore screening`

---

### SCR-11 — Fake Drug Endorsed at Screening (Kaopectamine)

**What it tests:** `kaopectamine_lifetime='1'` — participant endorsed the fake trap drug during the screening survey → hard fail with `qc_notes` containing "kaopectamine".

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-11
```
Sets `kaopectamine_lifetime=1` on record_id=1.

**QC script prompts:** User code: `m` | Import: `yes`

**Note:** Hard fail before phone verdict — you will not be asked for a phone verdict.

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |
| `qc_notes` | (contains "kaopectamine") |

**Verify:** `python3 qc_testing_debug.py verify SCR-11`
**Reset:** `python3 qc_testing_debug.py restore screening`

---

### SCR-12 — AI Prompt Injection Field Filled (flexibility_yn)

**What it tests:** `flexibility_yn` is non-blank — the `@HIDDEN-SURVEY` honeypot field was filled in. Normal participants never see this field; an AI agent that reads the raw HTML may follow the embedded instruction and type something. Hard fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-12
```
Sets `flexibility_yn="ok"` on record_id=1.

**QC script prompts:** User code: `m` | Import: `yes`

**Note:** Hard fail before phone verdict — you will not be asked for a phone verdict.

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |
| `qc_notes` | (contains "flexibility_yn") |

**Verify:** `python3 qc_testing_debug.py verify SCR-12`
**Reset:** `python3 qc_testing_debug.py restore screening`

---

### SCR-13 — Screening Completed Too Quickly (screen_seconds_taken < 90)

**What it tests:** `screen_seconds_taken=45` — participant completed the screening survey in under 90 seconds. Hard fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-13
```
Sets `screen_seconds_taken=45` on record_id=1.

**QC script prompts:** User code: `m` | Import: `yes`

**Note:** Hard fail before phone verdict — you will not be asked for a phone verdict.

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |
| `qc_notes` | (contains "screen_seconds_taken") |

**Verify:** `python3 qc_testing_debug.py verify SCR-13`
**Reset:** `python3 qc_testing_debug.py restore screening`

---

### SCR-14 — screen_motive Exactly 500 Characters (Length Heuristic Only)

**What it tests:** `screen_motive` is exactly 500 characters but does NOT begin with the AI template phrase — fires heuristic 1 only ("response is exactly 500 characters"). With `AI_MOTIVE_AUTOFAIL=False` (default), the record is NOT auto-failed; instead it goes to phone review with a red warning banner, and the researcher manually fails it.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-14
```
Sets `screen_motive` to a 500-character string that does not start with "I would describe my personal motivation" (e.g., `"a" * 500`).

**QC script prompts:** User code: `m` | Import: `yes` | Phone verdict: `y`

**What to confirm during the run:**
- Record appears in the phone review queue (NOT auto-failed)
- A red `*** AI-GENERATED RESPONSE FLAG ***` banner prints before the phone verdict prompt, listing the 500-char flag
- The phone verdict prompt itself is prefixed with a red `[!!! AI FLAG — check NoGPT first !!!]` reminder
- A link to NoGPT is printed in the banner — paste the motivation text there before deciding

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |
| `qc_notes` | (contains "exactly 500 characters") |
| `qc_notes` | (does NOT contain "AI template phrase") |

**Verify:** `python3 qc_testing_debug.py verify SCR-14`
**Reset:** `python3 qc_testing_debug.py restore screening`

---

### SCR-15 — screen_motive AI Template Phrase (Phrase Heuristic Only)

**What it tests:** `screen_motive` starts with "I would describe my personal motivation" and is in the 476–524 character range, but is NOT exactly 500 characters — fires heuristic 2 only ("begins with AI template phrase"). With `AI_MOTIVE_AUTOFAIL=False` (default), record goes to phone review with a red warning banner.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-15
```
Sets `screen_motive` to a 490-character string beginning with "I would describe my personal motivation" (e.g., `"I would describe my personal motivation" + "x" * 452`). Confirm `len(value) == 490`.

**QC script prompts:** User code: `m` | Import: `yes` | Phone verdict: `y`

**What to confirm during the run:**
- Record appears in the phone review queue (NOT auto-failed)
- A red `*** AI-GENERATED RESPONSE FLAG ***` banner prints with the template-phrase flag
- NoGPT link is printed — paste motivation text there before deciding

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |
| `qc_notes` | (contains "AI template phrase") |
| `qc_notes` | (does NOT contain "exactly 500 characters") |

**Verify:** `python3 qc_testing_debug.py verify SCR-15`
**Reset:** `python3 qc_testing_debug.py restore screening`

---

### SCR-16 — screen_motive Both AI Flags Together

**What it tests:** `screen_motive` starts with "I would describe my personal motivation" AND is exactly 500 characters — both heuristics fire simultaneously. Both reasons appear as separate lines in the red warning banner and semicolon-joined in `qc_notes`. With `AI_MOTIVE_AUTOFAIL=False` (default), record goes to phone review.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-16
```
Sets `screen_motive` to `"I would describe my personal motivation" + "x" * 462` (exactly 500 characters, starts with the template phrase). Confirm `len(value) == 500`.

**QC script prompts:** User code: `m` | Import: `yes` | Phone verdict: `y`

**What to confirm during the run:**
- Record appears in the phone review queue (NOT auto-failed)
- The red warning banner prints **two separate flag lines** (one for 500-char, one for template phrase)
- NoGPT link is printed

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |
| `qc_notes` | (contains "exactly 500 characters") |
| `qc_notes` | (contains "AI template phrase") |

**Verify:** `python3 qc_testing_debug.py verify SCR-16`
**Reset:** `python3 qc_testing_debug.py restore screening`

**Notes:** Both semicolon-joined reasons should appear in a single `qc_notes` string. Confirm the output reads like: `"screen_motive: response is exactly 500 characters; screen_motive: response is 500 chars and begins with AI template phrase"`.

---


## Graduating from Stage 1 to Stage 2

Once all SCR-XX scenarios pass, upgrade record_id=1 from screening-ready to baseline-ready:

1. **Run SCR-00** (or manually set `screening_pass=1`, `eligible_notify=1`) so the record is in an approved state.
2. **Add task data** to the three task fields (`task_data_ach_task_short_baseline`, `task_data_vch_short_psychedelic_bl`, `task_data_prltask`) — paste valid passing JSON into each field via the REDCap UI or API.
3. **Fill in all questionnaire fields** with plausible passing values (attention checks = 1, `race_qc` = copy of `race_v2`, etc.).
4. **Null out `qc_passed`** so the record sits in the baseline completion queue.
5. **Take the baseline snapshot:**
   ```bash
   python3 qc_testing_debug.py snapshot baseline
   ```
6. Confirm by running BL-00 (should produce `qc_passed=1`) before proceeding to failure scenarios.

---

## Baseline QC Scenarios

All baseline scenarios require record_id=1 to be in the baseline QC queue: `qc_passed` null, `screening_pass > 0`, `race_qc` present, and all three task data fields present.

**Critical distinction — task retry vs. critical fail:**
- Questionnaire and fraud checks set `qc_passed=0` directly.
- Task slope failures (BL-17 through BL-26) route to `_queue_task_retry()`, which sets `ach/vch/prl_replay=1` and clears the task data field. They do NOT set `qc_passed=0`.

---

### BL-00 — Passes QC

**What it tests:** Full baseline QC pass — all checks pass, `qc_passed=1`, expense sheet generated, payment confirmation sent.

**Setup:** No overrides. Confirm record_id=1 has clean baseline data.
```bash
python3 qc_testing_debug.py apply BL-00
```

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `qc_passed` | 1 |
| `send_pay_confirm` | 1 |
| `employee_name` | (any non-empty value) |

**Verify:** `python3 qc_testing_debug.py verify BL-00`
**Reset:** `python3 qc_testing_debug.py restore`

**Notes:** An expense sheet CSV should appear in `qc_test_drive/qc_to_dos/`. Reference case only.

---

### BL-01 — Attention Check Fail

**What it tests:** All `attn_check_surveybl` fields set to 0 — `failedAttnCheck` critical fail → `qc_passed=0`.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-01
```
Sets `attn_check_surveybl`, `attn_check_surveybl2`, `attn_check_surveybl3`, `attn_check_surveybl4` all to `0`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `qc_passed` | 0 |
| `qc_notes` | (contains "Failed attention check") |

**Verify:** `python3 qc_testing_debug.py verify BL-01`
**Reset:** `python3 qc_testing_debug.py restore`

**Notes:** `fraudulent_email_inconsistentanswers=1` is also set. Check `qc_notes` manually to confirm the message text.

---

### BL-02 — Race/Age Mismatch

**What it tests:** `race_qc != race_v2` (racediff > 1) AND `age_qc != age_v2` → `failed_new_qc` critical fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-02
```
Sets `race_qc=3`, `race_v2=1`, `age_qc=35`, `age_v2=25`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `qc_passed` | 0 |
| `qc_notes` | (contains "race/age consistency QC") |

**Verify:** `python3 qc_testing_debug.py verify BL-02`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-03 — Fake Drug Endorsed (Kaopectamine)

**What it tests:** `kaopectamine_lifetime=1` — endorsed the trap/fake drug → `failed_trap_questions` critical fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-03
```
Sets `kaopectamine_lifetime=1`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `qc_passed` | 0 |
| `qc_notes` | (contains "trap/fraud-detection") |

**Verify:** `python3 qc_testing_debug.py verify BL-03`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-04 — SP agefirst > age_v2

**What it tests:** `psyched_agefirst_{dose} > age_v2` — age of first use at a dose level exceeds current age → impossible → `_evaluate_absurd_sp_responses` fires `failed_sp_qc`. Tests the threshold (micro) dose; the same logic runs for all 5 dose levels.

> **Note:** The `fraud_recent_dose` check that previously occupied this slot has been retired. `validity_sp_dose` and `fraud_recent_dose` have been removed from the data dictionary entirely.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-04
```
Sets `psycheduse_yn=1`, `psycheduse_life_nomic=5`, `sp_type_recent=1`, `sp_dayslastuse=400`, `psyched_micro_yn=1`, `psyched_agefirst_micro=80`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `qc_passed` | 0 |
| `qc_notes` | contains "threshold" and "exceeds current age" |

**Verify:** `python3 qc_testing_debug.py verify BL-04`
**Reset:** `python3 qc_testing_debug.py restore`

---

### REDCap-side dose consistency checks (survey-level blocking)

These four checks are enforced directly in the REDCap survey as `@READONLY` required `text` fields. When the impossible condition is true the field appears, is empty, and is required — blocking submission until the participant corrects the underlying values. They are **not** tested through the QC script.

| Field (per dose) | Condition | Error shown |
|---|---|---|
| `err_agefirst_{dose}` | `psyched_agefirst_{dose} < psychedelic_age` (non-micro only) | Age of first dose-level use predates overall first psychedelic use |
| `err_uses_b18_{dose}` | `psyched_uses_{dose} < doses_before_18_{dose}` | Before-18 count exceeds total count |
| `err_uses_b25_{dose}` | `psyched_uses_{dose} < doses_before_25_{dose}` | Before-25 count exceeds total count |
| `err_b25_b18_{dose}` | `doses_before_25_{dose} < doses_before_18_{dose}` | Before-25 count is less than before-18 count |

**To verify in REDCap:** Import the updated data dictionary, open the survey for a test record, enter an impossible combination (e.g., `psyched_uses_micro=5`, `doses_before_18_micro=10`), and confirm `err_uses_b18_micro` appears with the correct piped message and that the survey cannot be submitted until the values are corrected.

---

### BL-05 — CAPS Attention Check Fail

**What it tests:** `fraud_caps=0` — answered No to the embedded CAPS attention item (correct answer is Yes) → critical fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-05
```
Sets `fraud_caps=0`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `qc_passed` | 0 |
| `qc_notes` | (not empty) |

**Verify:** `python3 qc_testing_debug.py verify BL-05`
**Reset:** `python3 qc_testing_debug.py restore`

**Notes:** Script checks `fraud_caps.astype(str).strip() == '0'`.

---

### BL-06 — PDI Attention Check Fail

**What it tests:** `fraud_pdi=0` — answered No to the embedded PDI attention item (correct answer is Yes) → critical fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-06
```
Sets `fraud_pdi=0`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `qc_passed` | 0 |
| `qc_notes` | (not empty) |

**Verify:** `python3 qc_testing_debug.py verify BL-06`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-07 — No SP Use in Main Survey

**What it tests:** Participant reported psychedelic use at screening (`psycheduse_yn=1`) but `psycheduse_life_nomic=0` and `psychedelicuse_lifetimetot=0` in main survey → "absurd SP response" critical fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-07
```
Sets `psycheduse_yn=1`, `psycheduse_life_nomic=0`, `psychedelicuse_lifetimetot=0`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `qc_passed` | 0 |
| `qc_notes` | (contains "no SP use in main survey") |

**Verify:** `python3 qc_testing_debug.py verify BL-07`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-08 — Non-SP Effects Endorsed

**What it tests:** `sp_fraud_aes___1=1` — endorsed non-SP effects as coming from SP use → critical fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-08
```
Sets `psycheduse_yn=1`, `sp_fraud_aes___1=1`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `qc_passed` | 0 |
| `qc_notes` | (contains "Reported non-SP effects from SPs") |

**Verify:** `python3 qc_testing_debug.py verify BL-08`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-09 — Bizarre Route of Administration

**What it tests:** `sp_fraud_psi=3` (below threshold of 6) — bizarre/implausible route of administration for psilocybin → critical fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-09
```
Sets `psycheduse_yn=1`, `sp_fraud_psi=3`. Other `sp_fraud_*` fields should be at or above thresholds in the clean snapshot.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `qc_passed` | 0 |
| `qc_notes` | (contains "bizarre route of administration") |

**Verify:** `python3 qc_testing_debug.py verify BL-09`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-10 — Twice-Inconsistent SP (Post-Verification Fail)

**What it tests:** `verify_emailed=1` and `sp_verify_pass=0` — participant gave inconsistent SP answers on initial QC and again on the verification follow-up → "twice inconsistent" critical fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-10
```
Sets `verify_emailed=1`, `sp_verify_pass=0`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `qc_passed` | 0 |
| `qc_notes` | (contains "inconsistent answers about SP use twice") |

**Verify:** `python3 qc_testing_debug.py verify BL-10`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-11 — SP Nanresponses (Verify Path)

**What it tests:** `sp_type_recent` and `sp_dayslastuse` blank when SP use is expected → `inconsistent_sp_answers=1` + `verify_emailed=1`. NOT a critical fail — `qc_passed` remains blank.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-11
```
Sets `psycheduse_life_nomic=3`, clears `sp_type_recent` and `sp_dayslastuse`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `verify_emailed` | 1 |
| `inconsistent_sp_answers` | 1 |
| `qc_passed` | (blank/null — NOT set to 0) |

**Verify:** `python3 qc_testing_debug.py verify BL-11`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-12 — Illogical Year SP Use (Verify Path)

**What it tests:** `psycheduse_year_nomic < psycheduse_6month_nomic` (used more in past 6 months than the full past year) → verify path. NOT a critical fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-12
```
Sets `psycheduse_year_nomic=2`, `psycheduse_6month_nomic=3` along with other required SP fields.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `verify_emailed` | 1 |
| `qc_passed` | (blank/null) |

**Verify:** `python3 qc_testing_debug.py verify BL-12`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-13 — Illogical Lifetime SP Use (Verify Path)

**What it tests:** `psycheduse_life_nomic < psycheduse_6month_nomic` (lifetime total less than 6-month total) → verify path. NOT a critical fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-13
```
Sets `psycheduse_life_nomic=2`, `psycheduse_year_nomic=1`, `psycheduse_6month_nomic=3`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `verify_emailed` | 1 |
| `qc_passed` | (blank/null) |

**Verify:** `python3 qc_testing_debug.py verify BL-13`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-14 — Wrong Recent SP Type (Verify Path)

**What it tests:** `sp_type_recent != sp_type_recent_qc` — participant reported a different recent SP in the QC check than in the main survey → verify path. NOT a critical fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-14
```
Sets `sp_type_recent=psilocybin`, `sp_type_recent_qc=lsd`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `verify_emailed` | 1 |
| `qc_passed` | (blank/null) |

**Verify:** `python3 qc_testing_debug.py verify BL-14`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-15 — Inconsistent SP Usetime 6-Month Window (Verify Path)

**What it tests:** `sp_dayslastuse=100` (<180 days → used within 6 months) but `psycheduse_6month_nomic=0` (reported zero uses in past 6 months) → failed_usetime_qc → verify path. NOT a critical fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-15
```
Sets `sp_dayslastuse=100`, `sp_lastuse_days_screen=100`, `psycheduse_6month_nomic=0`, `psycheduse_year_nomic=1`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `verify_emailed` | 1 |
| `qc_passed` | (blank/null) |

**Verify:** `python3 qc_testing_debug.py verify BL-15`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-16a — Copy-Paste ACH Data

**What it tests:** Identical ACH task RT data across two records → `fraud_copy_paste_ach` → `qc_passed=0` on both records.

**How it works:** `apply` exports the ACH task data string from record_id=1 and imports the **identical string** to record_id=9998 (with `screening_pass=1`, `race_qc` copied from record 1, `qc_passed` blank). Both records now appear in the baseline QC queue. `_load_ach_trials()` pivots on `(record_id x trial)` RT values and flags the duplicate rows across participants.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-16a
```

**QC script prompts:**
- User code: `m`
- **Note:** Both record_id=1 AND record_id=9998 will appear in the QC queue during this run.
- Import prompt: `yes`

**Expected REDCap result:**
| Record | Field | Expected value |
|---|---|---|
| record_id=1 | `qc_passed` | 0 |
| record_id=1 | `qc_notes` | (contains "Copy pasted ACH data") |
| record_id=9998 | `qc_passed` | 0 |
| record_id=9998 | `qc_notes` | (not empty) |

**Verify:** `python3 qc_testing_debug.py verify BL-16a`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-16b — Copy-Paste VCH Data

**What it tests:** Identical VCH task data across two records → `fraud_copy_paste_vch` → `qc_passed=0` on both.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-16b
```
Same mechanism as BL-16a but for the VCH task field.

**QC script prompts:** User code: `m` | Note: both records in queue | Import: `yes`

**Expected REDCap result:**
| Record | Field | Expected value |
|---|---|---|
| record_id=1 | `qc_passed` | 0 |
| record_id=1 | `qc_notes` | (contains "Copy pasted VCH data") |
| record_id=9998 | `qc_passed` | 0 |
| record_id=9998 | `qc_notes` | (not empty) |

**Verify:** `python3 qc_testing_debug.py verify BL-16b`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-16c — Copy-Paste PRL Data

**What it tests:** Identical PRL task data across two records → `fraud_copy_paste_prl` → `qc_passed=0` on both.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-16c
```
Same mechanism as BL-16a but for the PRL task field.

**QC script prompts:** User code: `m` | Note: both records in queue | Import: `yes`

**Expected REDCap result:**
| Record | Field | Expected value |
|---|---|---|
| record_id=1 | `qc_passed` | 0 |
| record_id=1 | `qc_notes` | (contains "Copy pasted PRL data") |
| record_id=9998 | `qc_passed` | 0 |
| record_id=9998 | `qc_notes` | (not empty) |

**Verify:** `python3 qc_testing_debug.py verify BL-16c`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-17 — ACH Negative Slope (Task Retry)

**What it tests:** ACH data with a negative detection slope → `_queue_task_retry()` → `ach_replay=1`, task data cleared.

**Requires:** `ach_negative` payload — run `python3 qc_testing_debug.py load-payloads` first and paste the ACH negative-slope JSON string.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-17
```
Imports the `ach_negative` payload to `task_data_ach_task_short_baseline`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `ach_replay` | 1 |
| `replay_links_ach` | 1 |
| `task_data_ach_task_short_baseline` | (blank — cleared after retry queued) |
| `qc_passed` | (blank/null — NOT 0) |

**Verify:** `python3 qc_testing_debug.py verify BL-17`
**Reset:** `python3 qc_testing_debug.py restore`

**Notes:** Task retry does NOT set `qc_passed=0`. The script routes through `_task_failures_for_record()` → `_queue_task_retry()`. The participant will receive a link to redo the task.

---

### BL-18 — ACH Zero/Non-Significant Slope (Task Retry)

**What it tests:** ACH data with p>0.05 (non-significant) detection slope → task retry queued.

**Payload:** `ach_zero` — auto-loaded from `resources/failed_task_examples.csv`. No `load-payloads` needed.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-18
```

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `ach_replay` | 1 |
| `replay_links_ach` | 1 |
| `qc_passed` | (blank/null) |

**Verify:** `python3 qc_testing_debug.py verify BL-18`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-19 — ACH Fail-First-Fifteen (Task Retry)

**What it tests:** ACH data where mean response in the first 15 trials is below 0.5 → task retry queued.

**Requires:** `ach_fail_first_fifteen` payload — run `load-payloads` first.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-19
```

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `ach_replay` | 1 |
| `replay_links_ach` | 1 |
| `qc_passed` | (blank/null) |

**Verify:** `python3 qc_testing_debug.py verify BL-19`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-20 — VCH Negative Slope (Task Retry)

**What it tests:** VCH data with a negative detection slope → task retry queued.

**Payload:** `vch_negative` — auto-loaded from `resources/failed_task_examples.csv`.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-20
```

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `vch_replay` | 1 |
| `replay_links_vch` | 1 |
| `qc_passed` | (blank/null) |

**Verify:** `python3 qc_testing_debug.py verify BL-20`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-21 — VCH Zero/Non-Significant Slope (Task Retry)

**What it tests:** VCH data with p>0.05 detection slope → task retry queued.

**Requires:** `vch_zero` payload — run `load-payloads` first.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-21
```

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `vch_replay` | 1 |
| `replay_links_vch` | 1 |
| `qc_passed` | (blank/null) |

**Verify:** `python3 qc_testing_debug.py verify BL-21`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-22 — VCH Fail-First-Fifteen (Task Retry)

**What it tests:** VCH data where mean response in the first 15 trials is below 0.5 → task retry queued.

**Requires:** `vch_fail_first_fifteen` payload — run `load-payloads` first.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-22
```

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `vch_replay` | 1 |
| `replay_links_vch` | 1 |
| `qc_passed` | (blank/null) |

**Verify:** `python3 qc_testing_debug.py verify BL-22`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-23 — PRL Worse Than Chance (<34% Correct)

**What it tests:** PRL data where `rewardProbChoice==0.85` choice rate is below 34% → task retry queued.

**Payload:** `prl_worse_than_chance` — auto-loaded from `resources/failed_task_examples.csv`.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-23
```

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `prl_replay` | 1 |
| `replay_links_prl` | 1 |
| `qc_passed` | (blank/null) |

**Verify:** `python3 qc_testing_debug.py verify BL-23`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-24 — PRL Non-Responders (>10% No Response)

**What it tests:** PRL data where more than 10% of trials have `keyChoice==-999` (no response recorded) → task retry queued.

**Payload:** `prl_non_responders` — auto-loaded from `resources/failed_task_examples.csv`.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-24
```

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `prl_replay` | 1 |
| `replay_links_prl` | 1 |
| `qc_passed` | (blank/null) |

**Verify:** `python3 qc_testing_debug.py verify BL-24`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-25 — PRL No Lose-Stay (<1%)

**What it tests:** PRL data with a lose-stay rate below 1% → task retry queued.

**Requires:** `prl_no_lose_stay` payload — run `load-payloads` first.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-25
```

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `prl_replay` | 1 |
| `replay_links_prl` | 1 |
| `qc_passed` | (blank/null) |

**Verify:** `python3 qc_testing_debug.py verify BL-25`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-26 — Fourth Task Failure (fourth_fail=1)

**What it tests:** All four ACH replay slots already filled (`ach_replay` through `ach_replay_4=1`) and the participant submits another failing ACH dataset → `fourth_fail=1` instead of queuing a new retry.

**How it works:** `_replay_attempt_number()` counts filled replay fields. With all 4 filled, `next_index=4 >= len(replay_fields)=4` → `fourth_fail` is set instead of assigning another retry slot.

**Payload:** Uses `ach_zero` (auto-loaded).

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-26
```
Sets `ach_replay=1`, `ach_replay_2=1`, `ach_replay_3=1`, `ach_replay_4=1` and imports the `ach_zero` payload.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `fourth_fail` | 1 |

**Verify:** `python3 qc_testing_debug.py verify BL-26`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-17b — ACH 2nd Replay Attempt (Slot 2)

**What it tests:** Participant has already done one ACH retry (`ach_replay=1` is set, task data cleared), submits a second failing dataset → `_queue_task_retry()` assigns the next available slot: `ach_replay_2=1`, `replay_links_ach_2=1`. Verifies that slot assignment walks correctly from index 0 to index 1.

**Payload:** `ach_zero` (auto-loaded from `resources/failed_task_examples.csv`).

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-17b
```
Sets `ach_replay=1` (simulating a completed first retry), then imports the `ach_zero` payload to `task_data_ach_task_short_baseline`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `ach_replay` | 1 (pre-existing, unchanged) |
| `ach_replay_2` | 1 |
| `replay_links_ach_2` | 1 |
| `task_data_ach_task_short_baseline` | (blank — cleared) |
| `qc_passed` | (blank/null) |

**Verify:** `python3 qc_testing_debug.py verify BL-17b`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-23b — PRL 2nd Replay Attempt (Slot 2)

**What it tests:** Participant has already done one PRL retry (`prl_replay=1` is set, task data cleared), submits a second failing dataset → `prl_replay_2=1`, `replay_links_prl_2=1`.

**Payload:** `prl_worse_than_chance` (auto-loaded from `resources/failed_task_examples.csv`).

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-23b
```
Sets `prl_replay=1`, then imports the `prl_worse_than_chance` payload to `task_data_prltask`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `prl_replay` | 1 (pre-existing, unchanged) |
| `prl_replay_2` | 1 |
| `replay_links_prl_2` | 1 |
| `task_data_prltask` | (blank — cleared) |
| `qc_passed` | (blank/null) |

**Verify:** `python3 qc_testing_debug.py verify BL-23b`
**Reset:** `python3 qc_testing_debug.py restore`

---

### BL-27 — Post-Verification Pass (sp_verify_pass=1)

**What it tests:** Participant was previously flagged for inconsistent SP answers (`verify_emailed=1`) and the researcher has reviewed and cleared them (`sp_verify_pass=1`). The record re-enters the baseline QC queue and should pass QC normally — no re-verification triggered, `qc_passed=1`, expense sheet generated.

**How it works:** `_evaluate_absurd_sp_responses()` skips records where `verify_emailed=1 AND sp_verify_pass > 0`, so none of the SP inconsistency flags are set. `_verification_needed()` therefore finds nothing to flag. The record flows through to the task checks and passes.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-27
```
Sets `verify_emailed=1` and `sp_verify_pass=1` on record_id=1. All other fields remain at passing clean-snapshot values.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `qc_passed` | 1 |
| `send_pay_confirm` | 1 |
| `verify_emailed` | 1 (pre-existing, unchanged) |
| `sp_verify_pass` | 1 (pre-existing, unchanged) |

**Verify:** `python3 qc_testing_debug.py verify BL-27`
**Reset:** `python3 qc_testing_debug.py restore`

**Notes:** Confirm in the console output that NO verification email note appears. An expense sheet should appear in `qc_test_drive/qc_to_dos/`. This test closes the loop on BL-10 (twice-inconsistent fail) and BL-11–15 (first-time verify path).

---

## Known Limitations

**Copy-paste detection requires two records in the queue.** This is inherent to the pivot-based detection logic — duplicates only appear when comparing across ≥2 participants. The workaround (BL-16a/b/c) creates a temporary record at record_id=9998 with identical task data. After testing, `restore` clears record_id=9998. This is the only way to exercise this code path in a single-record testing setup.

**`ips_full.csv` bypasses the live ipinfo.io API.** The QC script normally calls ipinfo.io to look up IP metadata for new screeners. During testing, we pre-populate `ips_full.csv` in the mock drive with the desired IP scenario. This means the `_lookup_and_cache_ip()` step is bypassed for record_id=1. Scenarios SCR-05, SCR-06, SCR-07, and SCR-10 rely entirely on the `ips_full.csv` state.

**Snapshot freshness.** If you modify record_id=1's task data or questionnaire responses outside of a test cycle, retake the snapshot with `python3 qc_testing_debug.py snapshot` before continuing.

---

## Troubleshooting

**"Snapshot not found" on restore:**
Run `python3 qc_testing_debug.py snapshot` (requires record_id=1 to be in a clean passing state first).

**"Payload 'X' not found" on apply:**
Run `python3 qc_testing_debug.py load-payloads` and paste the missing JSON string. The five manually-provided payloads are: `ach_negative`, `ach_fail_first_fifteen`, `vch_zero`, `vch_fail_first_fifteen`, `prl_no_lose_stay`.

**QC script says "no records to screen/check":**
The record is not in the expected queue. Common causes:
- For screening scenarios: `screening_pass` or `qc_passed` was already set (run `restore`).
- For baseline scenarios: `qc_passed` was already set, or `race_qc`/task data fields are missing.
- For BL-16x: the dupe record (9998) was not set up — check that `apply` ran without errors.

**QC script hangs on "INCOMPLETE flag" check:**
A prior test left flag files in `qc_test_drive/qc_to_dos/`. Run `python3 qc_testing_debug.py restore` to clear them, then retry.

**`verify` reports unexpected blank for `qc_notes`:**
The QC script may have taken a different code path than expected. Check the script's terminal output for the actual failure reason. Then re-read the scenario's field_overrides in `qc_testing_debug.py show <ID>` to confirm the setup was applied correctly.

**Record_id=9998 conflicts error:**
If record_id=9998 already exists with real data, change `DUPE_RECORD_ID` at the top of `qc_testing_debug.py` to a safe unused ID and retake the snapshot.
