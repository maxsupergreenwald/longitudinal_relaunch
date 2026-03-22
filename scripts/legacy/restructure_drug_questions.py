#!/usr/bin/env python3
"""
Restructures the 'Other Substance Use' section of the REDCap data dictionary.
Rows 701-853 are removed and replaced with a new, streamlined structure.
The _dp (treatment sought) and _age rows within that range are preserved.
"""
import csv, copy

CSV_PATH = '/Users/msg74/Desktop/powers_lab/psychedelics_dissertation/Aim1_Online_Survey_Tasks/RedCapStuff/Longitudinal_Relaunch/csvs/Psychedelics1BLongitudinalRela_DataDictionary_2026-03-19.csv'
FORM = 'survey_perception_substance_use'

with open(CSV_PATH, encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    rows = list(reader)

# ── Drug list ──────────────────────────────────────────────────────────────────
# (prefix, lifetime_bl_field, display_name, age_field_override_or_None)
DRUGS = [
    ('alc',         'alc_lifetime',         'Alcohol (beer, wine, liquor, etc.)',                    None),
    ('mj',          'mj_lifetime',           'Cannabis (marijuana, weed, hash, THC, etc.)',            None),
    ('coke',        'coke_lifetime',         'Cocaine (coke, crack, etc.)',                            None),
    ('opioids',     'opioids_lifetime',      'Opioids (heroin, morphine, Rx opioids misused, etc.)',  'opiates_age'),
    ('pcp',         'pcp_lifetime',          'PCP (angel dust) or Ketamine (special K)',               None),
    ('amph',        'amph_lifetime',         'Amphetamines (speed, meth, Adderall/Ritalin misused)',   None),
    ('mdma',        'mdma_lifetime',         'MDMA (ecstasy, molly)',                                  None),
    ('ghb',         'ghb_lifetime',          'GHB / Benzos / Sedative-Hypnotics (misused)',            None),
    ('inhalants',   'inhalants_lifetime',    'Inhalants (glue, gasoline, paint thinner, etc.)',        'huffing_age'),
    ('halluc',      'halluc_lifetime',       'Other Hallucinogens / Psychedelics (non-serotonergic)', None),
    ('ibogaine',    'ibogaine_lifetime',     'Ibogaine (Iboga bush)',                                  None),
    ('salvia',      'salvia_lifetime',       'Salvia Divinorum',                                       None),
    ('scopolamine', 'scopoalmine_lifetime',  'Scopolamine ("Devil\'s Breath")',                        None),
    ('dxm',         'dxm_lifetime',          'Dextromethorphan / DXM ("Robotripping")',               None),
    ('other',       'other_lifetime',        'Other substance(s)',                                     None),
]

PREF_CHOICES = (
    '1, Based on a <strong>single, estimated number</strong> '
    '(easier if you have not used many times or very regularly) | '
    '2, Based on <strong>how many times I used per day/week/month</strong> '
    '(easier if you used somewhat regularly or in hard-to-recall amounts)'
)
UNIT_CHOICES = '1, per Day | 2, per Week | 3, per Month'
YN_CHOICES   = '1, Yes | 2, No'

def blank():
    return {k: '' for k in fieldnames}

def row(var, ftype='text', label='', choices='', bl='', required='y',
        annotation='', matrix='', section='', val_type='', val_min='', val_max='',
        note=''):
    r = blank()
    r['Variable / Field Name'] = var
    r['Form Name'] = FORM
    r['Section Header'] = section
    r['Field Type'] = ftype
    r['Field Label'] = label
    r['Choices, Calculations, OR Slider Labels'] = choices
    r['Field Note'] = note
    r['Text Validation Type OR Show Slider Number'] = val_type
    r['Text Validation Min'] = val_min
    r['Text Validation Max'] = val_max
    r['Branching Logic (Show field only if...)'] = bl
    r['Required Field?'] = required
    r['Field Annotation'] = annotation
    r['Matrix Group Name'] = matrix
    return r

def drug_bold(name):
    return f'<strong>{name}</strong>'

# ── Section header (goes on first descriptive) ────────────────────────────────
SECTION_HDR = (
    '<div class="rich-text-field-label">'
    '<p><strong style="font-size:14pt;">Module: Other Substance Use</strong></p>'
    '<p><em>YOU ARE DOING GREAT! You are almost past the hump! '
    'Remember -- you have 72 hours so it\'s OK to take a break! '
    'This is the LAST of the hard questions about estimating past drug use -- '
    'THE QUESTIONNAIRES AFTER THIS SECTION ARE MUCH MUCH EASIER!</em></p>'
    '</div>'
)

# ── any_lifetime branching (for the descriptive field above each matrix) ──────
ANY_LIFETIME_BL = ' or '.join(f"[{d[1]}]='1'" for d in DRUGS)

# ═══════════════════════════════════════════════════════════════════════════════
#  BUILD NEW ROWS
# ═══════════════════════════════════════════════════════════════════════════════
new_rows = []

# ── 0.  BLOCK: Past-6-month use matrix ──────────────────────────────────────
new_rows.append(row(
    'past_6month_matrix_hdr',
    ftype='descriptive',
    label=(
        '<div class="rich-text-field-label">'
        '<p>In the past <strong style="font-size:14pt;">6 months</strong>, '
        'have you used any of the following substances?</p>'
        '</div>'
    ),
    bl=ANY_LIFETIME_BL,
    required='',
    section=SECTION_HDR,
))

for i, (pfx, bl_field, dname, _) in enumerate(DRUGS):
    new_rows.append(row(
        f'{pfx}_6month_yn',
        ftype='radio',
        label=f'<div class="rich-text-field-label"><p>{drug_bold(dname)}</p></div>',
        choices=YN_CHOICES,
        bl=f"[{bl_field}]='1'",
        required='y',
        matrix='past_6month_use',
    ))

# ── 1.  BLOCK: Kept _dp rows (treatment-sought matrix) ──────────────────────
# We clear the section header from tob_dp (it had one) and blank it out —
# it will stay in its existing position. The existing rows are untouched
# structurally; we just re-insert them here.
dp_rows  = rows[730:746]   # rows 730-745
dp_copy  = copy.deepcopy(dp_rows)
dp_copy[0]['Section Header'] = ''   # remove the old section header (it will appear in the middle of our new section)
new_rows.extend(dp_copy)

# ── 2.  BLOCK: Age of first use (existing rows + new halluc_age) ─────────────
age_rows = rows[746:760]   # rows 746-759
age_copy = copy.deepcopy(age_rows)
# Clear section header on first (it was blank anyway)
new_rows.extend(age_copy)

# Add halluc_age (was missing)
new_rows.append(row(
    'halluc_age',
    ftype='text',
    label=(
        '<div class="rich-text-field-label">'
        '<p>At what age did you first use <strong>other hallucinogens / non-serotonergic psychedelics</strong>?</p>'
        '</div>'
    ),
    bl="[halluc_lifetime]='1'",
    required='y',
    val_type='integer',
    val_min='0', val_max='99',
))

# ── 3.  BLOCK: Date of last use (new per-drug date fields) ───────────────────
new_rows.append(row(
    'dayslastuse_date_hdr',
    ftype='descriptive',
    label=(
        '<div class="rich-text-field-label">'
        '<p>For each substance you have used, '
        'please enter the <strong>date you last used it</strong> '
        '(approximate is fine — just your best estimate).</p>'
        '</div>'
    ),
    bl=ANY_LIFETIME_BL,
    required='',
))

for pfx, bl_field, dname, _ in DRUGS:
    new_rows.append(row(
        f'{pfx}_dayslastuse_date',
        ftype='text',
        label=(
            f'<div class="rich-text-field-label">'
            f'<p>When did you last use <strong>{dname}</strong>?</p>'
            f'</div>'
        ),
        bl=f"[{bl_field}]='1'",
        required='y',
        val_type='date_mdy',
    ))

# ── 4.  BLOCK: Lifetime preference matrix ────────────────────────────────────
new_rows.append(row(
    'life_pref_matrix_hdr',
    ftype='descriptive',
    label=(
        '<div class="rich-text-field-label">'
        '<p>For your <strong style="font-size:14pt;">lifetime</strong> use of each drug below, '
        'would you prefer to give your answer based on a single estimated total number, '
        'or based on how often you typically used?</p>'
        '</div>'
    ),
    bl=ANY_LIFETIME_BL,
    required='',
))

for i, (pfx, bl_field, dname, _) in enumerate(DRUGS):
    new_rows.append(row(
        f'{pfx}_life_freq_pref',
        ftype='radio',
        label=f'<div class="rich-text-field-label"><p>{drug_bold(dname)}</p></div>',
        choices=PREF_CHOICES,
        bl=f"[{bl_field}]='1'",
        required='y',
        matrix='life_freq_pref_matrix',
    ))

# ── 5.  BLOCK: Past-6-month preference matrix ────────────────────────────────
new_rows.append(row(
    '6mo_pref_matrix_hdr',
    ftype='descriptive',
    label=(
        '<div class="rich-text-field-label">'
        '<p>For your <strong style="font-size:14pt;">past 6 months</strong> of use, '
        'would you prefer to give your answer based on a single estimated total number, '
        'or based on how often you typically used?</p>'
        '</div>'
    ),
    bl=' or '.join(f"[{d[0]}_6month_yn]='1'" for d in DRUGS),
    required='',
))

for pfx, bl_field, dname, _ in DRUGS:
    new_rows.append(row(
        f'{pfx}_6mo_freq_pref',
        ftype='radio',
        label=f'<div class="rich-text-field-label"><p>{drug_bold(dname)}</p></div>',
        choices=PREF_CHOICES,
        bl=f"[{pfx}_6month_yn]='1'",
        required='y',
        matrix='6mo_freq_pref_matrix',
    ))

# ── 6.  BLOCK: Lifetime frequency-unit matrix ─────────────────────────────────
new_rows.append(row(
    'life_freq_unit_hdr',
    ftype='descriptive',
    label=(
        '<div class="rich-text-field-label">'
        '<p>For the drugs below where you chose to answer by frequency: '
        'how often did you typically use each over <strong style="font-size:14pt;">your entire life</strong>?</p>'
        '</div>'
    ),
    bl=' or '.join(f"[{d[0]}_life_freq_pref]='2'" for d in DRUGS),
    required='',
))

for pfx, bl_field, dname, _ in DRUGS:
    new_rows.append(row(
        f'{pfx}_life_freq_unit',
        ftype='radio',
        label=f'<div class="rich-text-field-label"><p>{drug_bold(dname)}</p></div>',
        choices=UNIT_CHOICES,
        bl=f"[{pfx}_life_freq_pref]='2'",
        required='y',
        matrix='life_freq_unit_matrix',
    ))

# ── 7.  BLOCK: Past-6-month frequency-unit matrix ────────────────────────────
new_rows.append(row(
    '6mo_freq_unit_hdr',
    ftype='descriptive',
    label=(
        '<div class="rich-text-field-label">'
        '<p>For the drugs below where you chose to answer by frequency: '
        'how often did you typically use each over the '
        '<strong style="font-size:14pt;">past 6 months</strong>?</p>'
        '</div>'
    ),
    bl=' or '.join(f"([{d[0]}_6month_yn]='1' and [{d[0]}_6mo_freq_pref]='2')" for d in DRUGS),
    required='',
))

for pfx, bl_field, dname, _ in DRUGS:
    new_rows.append(row(
        f'{pfx}_6mo_freq_unit',
        ftype='radio',
        label=f'<div class="rich-text-field-label"><p>{drug_bold(dname)}</p></div>',
        choices=UNIT_CHOICES,
        bl=f"[{pfx}_6month_yn]='1' and [{pfx}_6mo_freq_pref]='2'",
        required='y',
        matrix='6mo_freq_unit_matrix',
    ))

# ── 8.  BLOCK: Hidden calc for unit-text labels (life) ───────────────────────
for pfx, _, _, _ in DRUGS:
    calc = (
        f"if([{pfx}_life_freq_unit]='1', 'per Day', "
        f"if([{pfx}_life_freq_unit]='2', 'per Week', "
        f"if([{pfx}_life_freq_unit]='3', 'per Month', '')))"
    )
    new_rows.append(row(
        f'{pfx}_life_freq_unit_text',
        ftype='calc',
        label=f'Calculated unit label for {pfx} lifetime frequency',
        choices=calc,
        required='',
        annotation='@HIDDEN-SURVEY',
    ))

# ── 9.  BLOCK: Per-drug lifetime count questions ──────────────────────────────
for pfx, bl_field, dname, _ in DRUGS:
    # raw number option
    new_rows.append(row(
        f'{pfx}_life_n',
        ftype='text',
        label=(
            f'<div class="rich-text-field-label">'
            f'<p>How many times in total would you say you used '
            f'<strong>{dname}</strong> over <strong style="font-size:14pt;">your entire life</strong>?</p>'
            f'</div>'
        ),
        bl=f"[{bl_field}]='1' and [{pfx}_life_freq_pref]='1'",
        required='y',
        val_type='integer',
        val_min='0',
    ))
    # frequency rate option
    new_rows.append(row(
        f'{pfx}_life_rate',
        ftype='text',
        label=(
            f'<div class="rich-text-field-label">'
            f'<p>How many times <strong>[{pfx}_life_freq_unit_text]</strong> would you say '
            f'you typically used <strong>{dname}</strong> over '
            f'<strong style="font-size:14pt;">your entire life</strong>?</p>'
            f'</div>'
        ),
        bl=f"[{bl_field}]='1' and [{pfx}_life_freq_pref]='2'",
        required='y',
        val_type='number',
        val_min='0',
    ))

# ── 10. BLOCK: Hidden calc for unit-text labels (6mo) ────────────────────────
for pfx, _, _, _ in DRUGS:
    calc = (
        f"if([{pfx}_6mo_freq_unit]='1', 'per Day', "
        f"if([{pfx}_6mo_freq_unit]='2', 'per Week', "
        f"if([{pfx}_6mo_freq_unit]='3', 'per Month', '')))"
    )
    new_rows.append(row(
        f'{pfx}_6mo_freq_unit_text',
        ftype='calc',
        label=f'Calculated unit label for {pfx} 6-month frequency',
        choices=calc,
        required='',
        annotation='@HIDDEN-SURVEY',
    ))

# ── 11. BLOCK: Per-drug 6-month count questions ───────────────────────────────
for pfx, _, dname, _ in DRUGS:
    # raw number option
    new_rows.append(row(
        f'{pfx}_6mo_n',
        ftype='text',
        label=(
            f'<div class="rich-text-field-label">'
            f'<p>How many times in total would you say you used '
            f'<strong>{dname}</strong> in the <strong style="font-size:14pt;">past 6 months</strong>?</p>'
            f'</div>'
        ),
        bl=f"[{pfx}_6month_yn]='1' and [{pfx}_6mo_freq_pref]='1'",
        required='y',
        val_type='integer',
        val_min='0',
    ))
    # frequency rate option
    new_rows.append(row(
        f'{pfx}_6mo_rate',
        ftype='text',
        label=(
            f'<div class="rich-text-field-label">'
            f'<p>How many times <strong>[{pfx}_6mo_freq_unit_text]</strong> would you say '
            f'you typically used <strong>{dname}</strong> in the '
            f'<strong style="font-size:14pt;">past 6 months</strong>?</p>'
            f'</div>'
        ),
        bl=f"[{pfx}_6month_yn]='1' and [{pfx}_6mo_freq_pref]='2'",
        required='y',
        val_type='number',
        val_min='0',
    ))

# ── 12. BLOCK: Hidden calc fields (dayslastuse, firstuse_date, yearsusing) ────
new_rows.append(row(
    'yob_calc',
    ftype='calc',
    label='Calculated year of birth (today minus age)',
    choices='dateadd([today_survey_bl], -[age_v2], "y")',
    required='',
    annotation='@HIDDEN-SURVEY',
))

for pfx, bl_field, _, age_field in DRUGS:
    age_ref = age_field if age_field else f'{pfx}_age'

    # dayslastuse (calc from date)
    new_rows.append(row(
        f'{pfx}_dayslastuse',
        ftype='calc',
        label=f'Calculated days since last {pfx} use',
        choices=f'datediff([{pfx}_dayslastuse_date], [today_survey_bl], "d", "mdy")',
        required='',
        annotation='@HIDDEN-SURVEY',
    ))

    # firstuse_date
    new_rows.append(row(
        f'{pfx}_firstuse_date',
        ftype='calc',
        label=f'Calculated estimated first {pfx} use date',
        choices=f'dateadd([yob_calc], [{age_ref}], "y")',
        required='',
        annotation='@HIDDEN-SURVEY',
    ))

    # yearsusing
    new_rows.append(row(
        f'{pfx}_yearsusing',
        ftype='calc',
        label=f'Calculated years of {pfx} use (first use to last use)',
        choices=(
            f'datediff([{pfx}_firstuse_date], [{pfx}_dayslastuse_date], "y", "ymd", true)'
        ),
        required='',
        annotation='@HIDDEN-SURVEY',
    ))

    # 6month calc (total uses in 6 months)
    calc_6month = (
        f"if([{bl_field}]<>'1', '', "
        f"if([{pfx}_6month_yn]='2', 0, "
        f"if([{pfx}_6mo_freq_pref]='1', [{pfx}_6mo_n], "
        f"if([{pfx}_6mo_freq_unit]='1', [{pfx}_6mo_rate]*180, "
        f"if([{pfx}_6mo_freq_unit]='2', [{pfx}_6mo_rate]*26, "
        f"[{pfx}_6mo_rate]*6)))))"
    )
    new_rows.append(row(
        f'{pfx}_6month',
        ftype='calc',
        label=f'Calculated total {pfx} uses in past 6 months',
        choices=calc_6month,
        required='',
        annotation='@HIDDEN-SURVEY',
    ))

    # month calc (total uses in past month)
    calc_month = (
        f"if([{bl_field}]<>'1', '', "
        f"if([{pfx}_6month_yn]='2', 0, "
        f"if([{pfx}_6mo_freq_pref]='1', round([{pfx}_6mo_n]/6, 1), "
        f"if([{pfx}_6mo_freq_unit]='1', [{pfx}_6mo_rate]*30, "
        f"if([{pfx}_6mo_freq_unit]='2', round([{pfx}_6mo_rate]*4.33, 1), "
        f"[{pfx}_6mo_rate])))))"
    )
    new_rows.append(row(
        f'{pfx}_month',
        ftype='calc',
        label=f'Calculated {pfx} uses in past month',
        choices=calc_month,
        required='',
        annotation='@HIDDEN-SURVEY',
    ))

# ── ASSEMBLE FINAL ROW LIST ───────────────────────────────────────────────────
# Keep rows 0-700 (before the section), insert new_rows, then rows 854+ (after)
before = rows[:701]
after  = rows[854:]
final  = before + new_rows + after

print(f'Rows before:  {len(before)}')
print(f'New rows:     {len(new_rows)}')
print(f'Rows after:   {len(after)}')
print(f'Total output: {len(final)}')

# Verify no duplicate variable names (REDCap requires uniqueness)
names = [r['Variable / Field Name'] for r in final]
from collections import Counter
dupes = {k: v for k, v in Counter(names).items() if v > 1}
if dupes:
    print(f'WARNING - Duplicate variable names: {dupes}')
else:
    print('No duplicate variable names — OK')

with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(final)

print('CSV saved.')

# Print summary of new fields for memory
print('\n=== NEW CALCULATED FIELDS (for beta testing) ===')
calc_fields = [(r['Variable / Field Name'], r['Choices, Calculations, OR Slider Labels'][:80]) 
               for r in new_rows if r['Field Type'] == 'calc']
for v, c in calc_fields:
    print(f'  {v}: {c}')
