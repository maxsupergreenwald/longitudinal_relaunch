# QC Testing Guide — Aim 8 Relaunch

Testing roundtrip for `quickQC_api_calling_v7_relaunch.py`. The companion script `qc_testing_debug.py` manages REDCap state before and after each scenario run so you can validate every QC code path against a single test record (record_id=1) without touching real participant data.

---

## Overview

```
qc_testing_debug.py apply <ID>        <- set up REDCap state
  |
  v
python3 quickQC_api_calling_v7_relaunch.py   <- run the QC script manually
  |
  v
qc_testing_debug.py verify <ID>       <- check expected fields
  |
  v
qc_testing_debug.py restore           <- restore snapshot before next scenario
```

**62 scenarios total:** SCR-00 through SCR-24 plus SCR-11b/c/d (screening) and BL-00 through BL-27 plus BL-17b/BL-23b (baseline QC).

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

**Step 2 — Export the env variable** (add to your shell profile for convenience):
```bash
export AIM8_SHAREDDRIVE_PATH=/path/to/scripts/qc_test_drive
```

**Step 3 — Save the clean snapshot** (run after record_id=1 is fully set up with passing data):
```bash
python3 qc_testing_debug.py snapshot
```
This saves all fields from record_id=1 to `qc_test_snapshot.json`. Every `restore` call reimports this snapshot.

**Step 4 — Load task failure payloads** (required before BL-17, BL-19, BL-21, BL-22, BL-25):
```bash
python3 qc_testing_debug.py load-payloads
```
Four payloads are auto-loaded from `resources/failed_task_examples.csv` (`ach_zero`, `vch_negative`, `prl_worse_than_chance`, `prl_non_responders`). The wizard prompts you to paste the remaining five from your saved JSON strings document.

---

## Standard Test Cycle

```bash
# 1. Apply the scenario (sets REDCap fields, updates ips_full.csv)
python3 qc_testing_debug.py apply SCR-XX

# 2. Run the QC script (follow the prompts printed by apply)
export AIM8_SHAREDDRIVE_PATH=./qc_test_drive
python3 quickQC_api_calling_v7_relaunch.py

# 3. Verify results
python3 qc_testing_debug.py verify SCR-XX

# 4. Restore before next scenario
python3 qc_testing_debug.py restore
```

**Useful commands:**
```bash
python3 qc_testing_debug.py list              # show all scenario IDs and expected outcomes
python3 qc_testing_debug.py show BL-17        # print scenario details without applying
```

---

## Important Notes Before Running

- **Always restore before applying the next scenario.** Leftover field values from the previous run will corrupt the test state.
- **INCOMPLETE flag files block the QC script.** If a run crashes mid-execution, flag files remain in `qc_test_drive/qc_to_dos/`. The `restore` command clears them automatically.
- **SCR-15 sets `ip_zoom_invite=1`.** This field is written to REDCap and will appear in the restored snapshot's fields. The snapshot already contains the pre-test value, so `restore` handles it.
- **BL-16a/b/c and SCR-12/SCR-15 use record_id=9998.** The `restore` command clears all test fields on record 9998 after each run.
- **Task retry scenarios (BL-17 through BL-26) do NOT set `qc_passed=0`.** At baseline, task slope failures route to `_queue_task_retry()`. Only questionnaire/fraud checks cause `qc_passed=0`. See scenario notes.
- **The snapshot must be retaken** if you make permanent changes to record_id=1's clean baseline data (e.g., adding new task data, changing demographics).

---

## Screening Scenarios

All screening scenarios require record_id=1 to be in the screening queue (screening survey submitted, `screening_pass` and `qc_passed` null, `phone_number` present).

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
**Reset:** `python3 qc_testing_debug.py restore`

**Notes:** Reference case only. No field overrides are applied by `apply`. This confirms the clean state is actually passing before testing failure scenarios.

---

### SCR-01 — Age Too Old

**What it tests:** `age_v2 > 65` hard fail path.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-01
```
Sets `age_v2=70` on record_id=1.

**QC script prompts:**
- User code: `m`
- Import prompt: `yes`

**Note:** Hard fails occur before the phone verdict prompt — you will not be asked for a phone verdict.

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |

**Verify:** `python3 qc_testing_debug.py verify SCR-01`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-02 — Age Too Young

**What it tests:** `age_v2 < 18` hard fail path.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-02
```
Sets `age_v2=16`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |

**Verify:** `python3 qc_testing_debug.py verify SCR-02`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-03 — Cognition Screener Failed

**What it tests:** `cognition_screener_v2=1` hard fail path.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-03
```
Sets `cognition_screener_v2=1`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |

**Verify:** `python3 qc_testing_debug.py verify SCR-03`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-04 — Seizure History

**What it tests:** `seizure_hx_v2=1` hard fail path.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-04
```
Sets `seizure_hx_v2=1`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |

**Verify:** `python3 qc_testing_debug.py verify SCR-04`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-05 — Intoxication at Intake

**What it tests:** `intox_screen_v2=1` hard fail path.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-05
```
Sets `intox_screen_v2=1`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |

**Verify:** `python3 qc_testing_debug.py verify SCR-05`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-06 — No Psychedelic Use

**What it tests:** `psycheduse_yn=2` (did not endorse serotonergic psychedelic use) hard fail path.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-06
```
Sets `psycheduse_yn=2`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |

**Verify:** `python3 qc_testing_debug.py verify SCR-06`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-07 — Raven Score Too Low

**What it tests:** `raven_total_score_v2=0` (below minimum) hard fail path.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-07
```
Sets `raven_total_score_v2=0`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |

**Verify:** `python3 qc_testing_debug.py verify SCR-07`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-08 — No Computer Access

**What it tests:** `no_computer=1` hard fail path.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-08
```
Sets `no_computer=1`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |

**Verify:** `python3 qc_testing_debug.py verify SCR-08`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-09 — English Fluency Not Met

**What it tests:** `english_fluency=0` hard fail path.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-09
```
Sets `english_fluency=0`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |

**Verify:** `python3 qc_testing_debug.py verify SCR-09`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-10 — Geographic Fraud Flag

**What it tests:** `geo_crit` blank/null — the script checks `pd.isna(row.get("geo_crit", np.nan))` which fires when `geo_crit` is empty. Hard fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-10
```
Sets `geo_crit=""` (blank string in REDCap exports as NaN in the pandas DataFrame).

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |

**Verify:** `python3 qc_testing_debug.py verify SCR-10`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-11 — Recent SP Use, Not Willing to Wait (Hard Fail)

**What it tests:** `sp_dayslastuse=30` (recent SP use) AND `psychedelic_abstinence_yn` not set to `1` (participant did NOT agree to wait) → hard fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-11
```
Sets `sp_dayslastuse=30` and clears `psychedelic_abstinence_yn`.

**QC script prompts:** User code: `m` | Import: `yes`

**Note:** Hard fail occurs before the phone verdict prompt — you will not be asked for a phone verdict.

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |

**Verify:** `python3 qc_testing_debug.py verify SCR-11`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-11b — Recent SP Use, Willing to Wait, Clean Phone/IP

**What it tests:** `sp_dayslastuse=30` (recent SP use) AND `psychedelic_abstinence_yn='1'` (willing to wait) AND phone/IP look clean → `screening_pass=1`, `eligible_afterwait_notify=1` (NOT `eligible_notify`).

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-11b
```
Sets `sp_dayslastuse=30` and `psychedelic_abstinence_yn=1`. No IP overrides — uses the clean stub IP from `ips_full.csv`.

**QC script prompts:**
- User code: `m`
- Phone verdict: `n` (looks clean)
- Import prompt: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 1 |
| `eligible_notify` | (blank/null — NOT set) |
| `eligible_afterwait_notify` | 1 |

**Verify:** `python3 qc_testing_debug.py verify SCR-11b`
**Reset:** `python3 qc_testing_debug.py restore`

**Notes:** This record is now queued to receive a continuation email at `continue_date` (calculated from the substance dayslastuse fields). The participant never receives the immediate eligible_notify email.

---

### SCR-11c — Recent SP Use, Willing to Wait, Fraudulent Phone

**What it tests:** `sp_dayslastuse=30`, `psychedelic_abstinence_yn='1'` (willing to wait), but researcher enters `y` at phone verdict → falls back to the normal fraud path. sp_wait does NOT protect against explicit phone fraud.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-11c
```
Sets `sp_dayslastuse=30` and `psychedelic_abstinence_yn=1`. No other overrides — the `y` verdict causes the fail.

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

**Verify:** `python3 qc_testing_debug.py verify SCR-11c`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-11d — Recent Atypical Use, Willing to Wait, Clean

**What it tests:** SP dayslastuse is fine but `mdma_dayslastuse=10` (atypical substance used recently) AND `psychedelic_abstinence_yn='1'` → `atypical_recentuse='1'` triggers the sp_wait path. Result: `screening_pass=1`, `eligible_afterwait_notify=1`.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-11d
```
Sets `mdma_lifetime=1`, `mdma_dayslastuse=10`, `psychedelic_abstinence_yn=1`. Leaves `sp_dayslastuse` above 42.

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

**Verify:** `python3 qc_testing_debug.py verify SCR-11d`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-12 — Duplicate Email

**What it tests:** `email_rpt` on record_id=1 matches a prior screened record's email. `_apply_duplicate_identity_checks()` finds the match and fires hard fail.

**How it works:** `apply` sets `email_rpt=dupe_test@example.com` on record_id=1. It also imports `email_rpt=dupe_test@example.com` plus `datedone_screening_survey=2025-01-01` to record_id=9998 (marking it as a prior screened record). When the QC script runs, the email lookup finds the match.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-12
```

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |

**Verify:** `python3 qc_testing_debug.py verify SCR-12`
**Reset:** `python3 qc_testing_debug.py restore` (clears record_id=9998 fields)

---

### SCR-13 — Forbidden IP Organization

**What it tests:** IP org in `FORBIDDEN_IP_ORGS` (AS174 Cogent Communications) — hard fail from `ips_full.csv` lookup.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-13
```
Updates `ips_full.csv` row for record_id=1 to `org="AS174 Cogent Communications"`. No REDCap field overrides.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |

**Verify:** `python3 qc_testing_debug.py verify SCR-13`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-14 — Forbidden IP Country

**What it tests:** IP `country_name` in `FORBIDDEN_IP_COUNTRIES` (Nigeria) — hard fail from `ips_full.csv` lookup.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-14
```
Updates `ips_full.csv` row for record_id=1 to `country_name="Nigeria"`. No REDCap field overrides.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |

**Verify:** `python3 qc_testing_debug.py verify SCR-14`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-15 — Suspicious Duplicate IP

**What it tests:** Record_id=1 shares an IP with a prior reviewed/ineligible record. Automated checks pass, but `ip_zoom_invite=1` is set alongside `screening_pass=1` (flag for manual Zoom verification).

**How it works:** `apply` sets record_id=1's IP to `5.5.5.5` in `ips_full.csv`. It also adds record_id=9998 to `ips_full.csv` with the same IP, and imports `datedone_screening_survey=2025-01-01` + `qc_passed=0` to record_id=9998. The `prior_bad_ips` set in the script now includes `5.5.5.5`, which triggers the suspicious IP flag.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-15
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

**Verify:** `python3 qc_testing_debug.py verify SCR-15`
**Reset:** `python3 qc_testing_debug.py restore`

**Notes:** Unlike SCR-13/14, this is NOT a hard fail. The participant passes screening but is flagged for an extra Zoom verification call.

---

### SCR-16 — Phone Verdict: VOIP/Fraudulent

**What it tests:** User enters `y` at the phone verdict prompt (phone appears fraudulent/VOIP) — manual hard fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-16
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

**Verify:** `python3 qc_testing_debug.py verify SCR-16`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-17 — Phone Verdict: Manual Follow-Up

**What it tests:** User enters `?` at the phone verdict prompt — record is flagged for Max's review (`max_number_followup=1`). NOT a fail — `screening_pass` and `qc_passed` remain blank.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-17
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

**Verify:** `python3 qc_testing_debug.py verify SCR-17`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-18 — Missing IP Metadata

**What it tests:** No IP row exists for record_id=1 in `ips_full.csv` — record goes to `max_number_followup`. NOT a fail — `screening_pass` and `qc_passed` remain blank.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-18
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

**Verify:** `python3 qc_testing_debug.py verify SCR-18`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-19 — Fake Drug Endorsed at Screening (Kaopectamine)

**What it tests:** `kaopectamine_lifetime='1'` — participant endorsed the fake trap drug during the screening survey → `_apply_screening_eligibility_rules()` catches it at screening time and adds to hard_fail. This is distinct from BL-03 (same trap caught at baseline QC); SCR-19 verifies the earlier screening-stage catch.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-19
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

**Verify:** `python3 qc_testing_debug.py verify SCR-19`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-20 — AI Prompt Injection Field Filled (flexibility_yn)

**What it tests:** `flexibility_yn` is non-blank — the `@HIDDEN-SURVEY` honeypot field was filled in. Normal participants never see this field; an AI agent that reads the raw HTML may follow the embedded instruction and type something. Hard fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-20
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

**Verify:** `python3 qc_testing_debug.py verify SCR-20`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-21 — Screening Completed Too Quickly (screen_seconds_taken < 90)

**What it tests:** `screen_seconds_taken=45` — participant completed the screening survey in under 90 seconds, which is too fast for a human to read and respond. Hard fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-21
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

**Verify:** `python3 qc_testing_debug.py verify SCR-21`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-22 — screen_motive Exactly 500 Characters (Length Heuristic Only)

**What it tests:** `screen_motive` is exactly 500 characters but does NOT begin with the AI template phrase — fires heuristic 1 only ("response is exactly 500 characters"). Hard fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-22
```
Sets `screen_motive` to a 500-character string that does not start with "I would describe my personal motivation" (e.g., `"a" * 500`).

**QC script prompts:** User code: `m` | Import: `yes`

**Note:** Hard fail before phone verdict — you will not be asked for a phone verdict.

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |
| `qc_notes` | (contains "exactly 500 characters") |
| `qc_notes` | (does NOT contain "AI template phrase") |

**Verify:** `python3 qc_testing_debug.py verify SCR-22`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-23 — screen_motive AI Template Phrase (Phrase Heuristic Only)

**What it tests:** `screen_motive` starts with "I would describe my personal motivation" and is in the 476–524 character range, but is NOT exactly 500 characters — fires heuristic 2 only ("begins with AI template phrase"). Hard fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-23
```
Sets `screen_motive` to a 490-character string beginning with "I would describe my personal motivation" (e.g., `"I would describe my personal motivation" + "x" * 452`). Confirm `len(value) == 490`.

**QC script prompts:** User code: `m` | Import: `yes`

**Note:** Hard fail before phone verdict — you will not be asked for a phone verdict.

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |
| `qc_notes` | (contains "AI template phrase") |
| `qc_notes` | (does NOT contain "exactly 500 characters") |

**Verify:** `python3 qc_testing_debug.py verify SCR-23`
**Reset:** `python3 qc_testing_debug.py restore`

---

### SCR-24 — screen_motive Both AI Flags Together

**What it tests:** `screen_motive` starts with "I would describe my personal motivation" AND is exactly 500 characters — both heuristics fire simultaneously, and both reasons are semicolon-joined into `qc_notes`.

**Setup:**
```bash
python3 qc_testing_debug.py apply SCR-24
```
Sets `screen_motive` to `"I would describe my personal motivation" + "x" * 462` (exactly 500 characters, starts with the template phrase). Confirm `len(value) == 500`.

**QC script prompts:** User code: `m` | Import: `yes`

**Note:** Hard fail before phone verdict — you will not be asked for a phone verdict.

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `screening_pass` | 0 |
| `qc_passed` | 0 |
| `ineligibile_fraud` | 1 |
| `qc_notes` | (contains "exactly 500 characters") |
| `qc_notes` | (contains "AI template phrase") |

**Verify:** `python3 qc_testing_debug.py verify SCR-24`
**Reset:** `python3 qc_testing_debug.py restore`

**Notes:** This is the combined case — both semicolon-joined reasons should appear in a single `qc_notes` string. Confirm the output reads like: `"screen_motive: response is exactly 500 characters; screen_motive: response is 500 chars and begins with AI template phrase"`.

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

### BL-04 — Dose Mismatch Trap

**What it tests:** `fraud_recent_dose=1` — calculated dose mismatch trap field set → critical fail.

**Setup:**
```bash
python3 qc_testing_debug.py apply BL-04
```
Sets `fraud_recent_dose=1`.

**QC script prompts:** User code: `m` | Import: `yes`

**Expected REDCap result:**
| Field | Expected value |
|---|---|
| `qc_passed` | 0 |
| `qc_notes` | (not empty) |

**Verify:** `python3 qc_testing_debug.py verify BL-04`
**Reset:** `python3 qc_testing_debug.py restore`

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

**`ips_full.csv` bypasses the live ipinfo.io API.** The QC script normally calls ipinfo.io to look up IP metadata for new screeners. During testing, we pre-populate `ips_full.csv` in the mock drive with the desired IP scenario. This means the `_lookup_and_cache_ip()` step is bypassed for record_id=1. Scenarios SCR-13, SCR-14, SCR-15, and SCR-18 rely entirely on the `ips_full.csv` state.

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
