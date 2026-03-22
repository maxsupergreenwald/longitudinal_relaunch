from __future__ import annotations

import copy
import re
from pathlib import Path
import xml.etree.ElementTree as ET


NS = {
    "odm": "http://www.cdisc.org/ns/odm/v1.3",
    "redcap": "https://projectredcap.org",
}
RED = "{https://projectredcap.org}"
ODM = "{http://www.cdisc.org/ns/odm/v1.3}"

ET.register_namespace("", NS["odm"])
ET.register_namespace("redcap", NS["redcap"])
ET.register_namespace("ds", "http://www.w3.org/2000/09/xmldsig#")
ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")


WORKDIR = Path(__file__).resolve().parent
BASE_XML = WORKDIR / "PsychedelicsAim1Repe_2026-03-17_1912.REDCap.xml"
LONG_XML = WORKDIR / "PsychedelicsAim1Repe_2026-03-17_1656.REDCap.xml"
OUT_XML = WORKDIR / "PsychedelicsAim1Repe_2026-03-17_1912_merged_draft.REDCap.xml"


IMPORT_FORMS = [
    "hyperacute_presurvey",
    "visual_ch_task_hyp",
    "probabilistic_reversal_task_hyp",
    "auditory_ch_task_hyp",
    "space_junk_hyp",
    "hyperacute_postsurvey",
    "acute_presurvey",
    "visual_ch_task_acu",
    "probabilistic_reversal_task_acu",
    "auditory_ch_task_acu",
    "space_junk_acu",
    "acute_postsurvey",
    "subacute_presurvey",
    "visual_ch_task_sub",
    "probabilistic_reversal_task_sub",
    "auditory_ch_task_sub",
    "space_junk_sub",
    "subacute_postsurvey",
    "persisting_presurvey",
    "visual_ch_task_pers",
    "probabilistic_reversal_task_pers",
    "auditory_ch_task_pers",
    "space_junk_pers",
    "persisting_postsurvey",
    "payment_form_hyp",
    "payment_confirmation_hyp",
    "payment_form_acu",
    "payment_confirmation_acu",
    "payment_form_sub",
    "payment_confirmation_sub",
    "payment_form_pers",
    "payment_confirmation_pers",
]

CONSENT_RPT_FIELDS_TO_ADD = {
    "random_rpt",
    "email_rpt",
    "include_hyp_measures",
    "prolific_yn_rpt",
}

REMOVE_FORMS = {
    "longitudinal_study_waiting",
    "prolific_screening_result",
    "visual_ch_task_shortened_dlb",
    "extra_questions",
    "add_on_questions",
    "add_on_questions_yale",
    "payment_confirmation",
    "delayed_payment_confirmation",
    "participation_resume",
    "new_payment",
    "email_alerts",
    "reconsent_baseline",
}

REMOVE_ALERT_TITLES = {
    "Add On Questionnaire Payment Request Submitted",
    "Add On Invitation",
    "longitudinal_waiting_confirmation_better",
    "longitudinal_continue_link",
    "zoom_eligibility",
    "cannabis_continue",
    "Cannabis Study Invitation",
    "Yale Add On Invitation",
    "Yale Add On Invitation #2",
    "Participation Resume",
    "Participation Restart",
    "Cannabis Longitudinal Re-Contact",
    "CORRECTED: Cannabis Longitudinal Re-Contact",
}


def clone(el: ET.Element) -> ET.Element:
    return copy.deepcopy(el)


def child_text(parent: ET.Element, tag: str) -> str:
    child = parent.find(tag, NS)
    return child.text if child is not None and child.text is not None else ""


def set_child_text(parent: ET.Element, tag: str, text: str) -> None:
    child = parent.find(tag, NS)
    if child is None:
        child = ET.SubElement(parent, tag)
    child.text = text


def get_maps(mdv: ET.Element):
    forms = {
        form.get(f"{RED}FormName"): form
        for form in mdv.findall("odm:FormDef", NS)
    }
    itemgroups = {ig.get("OID"): ig for ig in mdv.findall("odm:ItemGroupDef", NS)}
    items = {item.get("OID"): item for item in mdv.findall("odm:ItemDef", NS)}
    codelists = {cl.get("OID"): cl for cl in mdv.findall("odm:CodeList", NS)}
    return forms, itemgroups, items, codelists


def get_group_to_items(itemgroups: dict[str, ET.Element]) -> dict[str, list[str]]:
    return {
        oid: [ref.get("ItemOID") for ref in ig.findall("odm:ItemRef", NS)]
        for oid, ig in itemgroups.items()
    }


def get_item_to_group(itemgroups: dict[str, ET.Element]) -> dict[str, str]:
    out: dict[str, str] = {}
    for oid, ig in itemgroups.items():
        refs = ig.findall("odm:ItemRef", NS)
        for ref in refs:
            out[ref.get("ItemOID")] = oid
    return out


def insert_before_first(mdv: ET.Element, tag_local: str, el: ET.Element) -> None:
    tag = f"{ODM}{tag_local}"
    for idx, child in enumerate(list(mdv)):
        if child.tag == tag:
            mdv.insert(idx, el)
            return
    mdv.append(el)


def ensure_codelist(item: ET.Element, src_codelists: dict[str, ET.Element], dst_codelists: dict[str, ET.Element], dst_mdv: ET.Element) -> None:
    ref = item.find("odm:CodeListRef", NS)
    if ref is None:
        return
    oid = ref.get("CodeListOID")
    if not oid or oid in dst_codelists:
        return
    if oid in src_codelists:
        dst_cl = clone(src_codelists[oid])
        dst_mdv.append(dst_cl)
        dst_codelists[oid] = dst_cl


def ensure_item(oid: str, src_items: dict[str, ET.Element], src_codelists: dict[str, ET.Element], dst_items: dict[str, ET.Element], dst_codelists: dict[str, ET.Element], dst_mdv: ET.Element) -> None:
    if oid in dst_items:
        return
    item = src_items[oid]
    ensure_codelist(item, src_codelists, dst_codelists, dst_mdv)
    dst_item = clone(item)
    insert_before_first(dst_mdv, "CodeList", dst_item)
    dst_items[oid] = dst_item


def ensure_itemgroup(oid: str, src_itemgroups: dict[str, ET.Element], src_items: dict[str, ET.Element], src_codelists: dict[str, ET.Element], dst_itemgroups: dict[str, ET.Element], dst_items: dict[str, ET.Element], dst_codelists: dict[str, ET.Element], dst_mdv: ET.Element) -> None:
    if oid in dst_itemgroups:
        return
    ig = src_itemgroups[oid]
    for ref in ig.findall("odm:ItemRef", NS):
        ensure_item(ref.get("ItemOID"), src_items, src_codelists, dst_items, dst_codelists, dst_mdv)
    dst_ig = clone(ig)
    insert_before_first(dst_mdv, "ItemDef", dst_ig)
    dst_itemgroups[oid] = dst_ig


def ensure_form_support(formname: str, src_forms: dict[str, ET.Element], src_itemgroups: dict[str, ET.Element], src_items: dict[str, ET.Element], src_codelists: dict[str, ET.Element], dst_forms: dict[str, ET.Element], dst_itemgroups: dict[str, ET.Element], dst_items: dict[str, ET.Element], dst_codelists: dict[str, ET.Element], dst_mdv: ET.Element) -> None:
    form = src_forms[formname]
    for ref in form.findall("odm:ItemGroupRef", NS):
        ensure_itemgroup(ref.get("ItemGroupOID"), src_itemgroups, src_items, src_codelists, dst_itemgroups, dst_items, dst_codelists, dst_mdv)
    if formname not in dst_forms:
        insert_before_first(dst_mdv, "ItemGroupDef", clone(form))
        dst_forms[formname] = next(
            x for x in dst_mdv.findall("odm:FormDef", NS)
            if x.get(f"{RED}FormName") == formname
        )


def survey_map(gv: ET.Element) -> dict[str, ET.Element]:
    return {
        survey.get("form_name"): survey
        for survey in gv.findall("redcap:SurveysGroup/redcap:Surveys", NS)
    }


def queue_list(gv: ET.Element) -> list[ET.Element]:
    return gv.findall("redcap:SurveysQueueGroup/redcap:SurveysQueue", NS)


def alert_group(gv: ET.Element) -> ET.Element:
    return gv.find("redcap:AlertsGroup", NS)


def remove_by_formname(mdv: ET.Element, gv: ET.Element, formnames: set[str]) -> None:
    for form in list(mdv.findall("odm:FormDef", NS)):
        if form.get(f"{RED}FormName") in formnames:
            mdv.remove(form)
    surveys_group = gv.find("redcap:SurveysGroup", NS)
    for survey in list(surveys_group.findall("redcap:Surveys", NS)):
        if survey.get("form_name") in formnames:
            surveys_group.remove(survey)
    queue_group = gv.find("redcap:SurveysQueueGroup", NS)
    if queue_group is not None:
        for q in list(queue_group.findall("redcap:SurveysQueue", NS)):
            if q.get("survey_id") in formnames:
                queue_group.remove(q)


def remove_alerts(gv: ET.Element, titles: set[str]) -> None:
    group = alert_group(gv)
    for alert in list(group.findall("redcap:Alerts", NS)):
        if (alert.get("alert_title") or "") in titles:
            group.remove(alert)


def clear_scheduler(gv: ET.Element) -> None:
    group = gv.find("redcap:SurveysSchedulerGroup", NS)
    if group is None:
        return
    for sched in list(group.findall("redcap:SurveysScheduler", NS)):
        group.remove(sched)


def add_survey_from_source(formname: str, src_surveys: dict[str, ET.Element], dst_gv: ET.Element) -> None:
    dst_surveys_group = dst_gv.find("redcap:SurveysGroup", NS)
    existing = survey_map(dst_gv)
    if formname in existing:
        return
    if formname in src_surveys:
        dst_surveys_group.append(clone(src_surveys[formname]))


def update_item_question(item: ET.Element, html: str) -> None:
    question = item.find("odm:Question", NS)
    if question is None:
        question = ET.SubElement(item, f"{ODM}Question")
    translated = question.find("odm:TranslatedText", NS)
    if translated is None:
        translated = ET.SubElement(question, f"{ODM}TranslatedText")
    translated.text = html


def update_item(item: ET.Element, *, html: str | None = None, choices: str | None = None, branching: str | None = None, note: str | None = None, annotation: str | None = None) -> None:
    if html is not None:
        update_item_question(item, html)
    if choices is not None:
        set_child_text(item, f"{redcap_tag('SelectChoicesOrCalculations')}", choices)
    if branching is not None:
        set_child_text(item, f"{redcap_tag('BranchingLogic')}", branching)
    if note is not None:
        set_child_text(item, f"{redcap_tag('FieldNote')}", note)
    if annotation is not None:
        set_child_text(item, f"{redcap_tag('FieldAnnotation')}", annotation)


def redcap_tag(local: str) -> str:
    return f"{RED}{local}"


def find_item(items: dict[str, ET.Element], oid: str) -> ET.Element:
    return items[oid]


def find_items_with_base(items: dict[str, ET.Element], base: str) -> list[ET.Element]:
    matches = [item for oid, item in items.items() if oid == base or oid.startswith(f"{base}___")]
    return sorted(matches, key=lambda item: item.get("OID"))


def update_item_family(items: dict[str, ET.Element], base: str, **kwargs) -> None:
    for item in find_items_with_base(items, base):
        update_item(item, **kwargs)


def add_itemgroup_ref(form: ET.Element, itemgroup_oid: str, mandatory: str = "No", after_oid: str | None = None) -> None:
    if any(ref.get("ItemGroupOID") == itemgroup_oid for ref in form.findall("odm:ItemGroupRef", NS)):
        return
    ref = ET.Element(f"{ODM}ItemGroupRef", {"ItemGroupOID": itemgroup_oid, "Mandatory": mandatory})
    refs = form.findall("odm:ItemGroupRef", NS)
    if after_oid is None:
        form.append(ref)
        return
    for idx, existing in enumerate(refs):
        if existing.get("ItemGroupOID") == after_oid:
            form.insert(list(form).index(existing) + 1, ref)
            return
    form.append(ref)


def create_single_itemgroup(oid: str, name: str, item_oid: str, mandatory: str = "No") -> ET.Element:
    ig = ET.Element(f"{ODM}ItemGroupDef", {"OID": oid, "Name": name, "Repeating": "No"})
    ref = ET.SubElement(ig, f"{ODM}ItemRef", {"ItemOID": item_oid, "Mandatory": mandatory})
    ref.set(f"{RED}Variable", item_oid)
    return ig


def next_alert_numbers(group: ET.Element) -> tuple[str, str]:
    nums = [int(a.get("alert_number")) for a in group.findall("redcap:Alerts", NS) if (a.get("alert_number") or "").isdigit()]
    orders = [int(a.get("alert_order")) for a in group.findall("redcap:Alerts", NS) if (a.get("alert_order") or "").isdigit()]
    return str(max(nums, default=0) + 1), str(max(orders, default=0) + 1)


def add_alert(group: ET.Element, template: ET.Element, *, title: str, email_to: str, subject: str, message: str, condition: str, send_on: str = "time_lag", lag_days: str = "", lag_hours: str = "", lag_minutes: str = "", lag_field: str = "", ensure_logic: str = "1") -> None:
    alert = clone(template)
    number, order = next_alert_numbers(group)
    alert.set("alert_title", title)
    alert.set("email_to", email_to)
    alert.set("email_subject", subject)
    alert.set("alert_message", message)
    alert.set("alert_condition", condition)
    alert.set("cron_send_email_on", send_on)
    alert.set("cron_send_email_on_time_lag_days", lag_days)
    alert.set("cron_send_email_on_time_lag_hours", lag_hours)
    alert.set("cron_send_email_on_time_lag_minutes", lag_minutes)
    alert.set("cron_send_email_on_field", lag_field)
    alert.set("ensure_logic_still_true", ensure_logic)
    alert.set("alert_number", number)
    alert.set("alert_order", order)
    alert.set("email_deleted", "0")
    alert.set("email_sent", "0")
    alert.set("email_timestamp_sent", "")
    group.append(alert)


def replace_text_recursive(node: ET.Element, replacements: list[tuple[str, str]]) -> None:
    for el in node.iter():
        if el.text:
            text = el.text
            for old, new in replacements:
                text = text.replace(old, new)
            el.text = text
        for key, value in list(el.attrib.items()):
            text = value
            for old, new in replacements:
                text = text.replace(old, new)
            el.attrib[key] = text


def main() -> None:
    base_tree = ET.parse(BASE_XML)
    long_tree = ET.parse(LONG_XML)

    root = clone(base_tree.getroot())
    long_root = long_tree.getroot()

    study = root.find("odm:Study", NS)
    gv = study.find("odm:GlobalVariables", NS)
    mdv = study.find("odm:MetaDataVersion", NS)

    long_study = long_root.find("odm:Study", NS)
    long_gv = long_study.find("odm:GlobalVariables", NS)
    long_mdv = long_study.find("odm:MetaDataVersion", NS)

    dst_forms, dst_itemgroups, dst_items, dst_codelists = get_maps(mdv)
    src_forms, src_itemgroups, src_items, src_codelists = get_maps(long_mdv)
    src_item_to_group = get_item_to_group(src_itemgroups)
    src_surveys = survey_map(long_gv)

    set_child_text(gv, f"{redcap_tag('SurveyInvitationEmailField')}", "email_rpt")
    set_child_text(gv, f"{redcap_tag('ProjectNotes')}", "Merged baseline + repeated-measures SP workflow draft")
    set_child_text(
        gv,
        f"{redcap_tag('SurveyQueueCustomText')}",
        "<p>Complete consent, screening, baseline questionnaires, and games here. Follow-up survey links will be emailed to you for the appropriate time points.</p>",
    )

    remove_by_formname(mdv, gv, REMOVE_FORMS)
    remove_alerts(gv, REMOVE_ALERT_TITLES)
    clear_scheduler(gv)

    for formname in IMPORT_FORMS:
        ensure_form_support(
            formname,
            src_forms,
            src_itemgroups,
            src_items,
            src_codelists,
            dst_forms,
            dst_itemgroups,
            dst_items,
            dst_codelists,
            mdv,
        )
        add_survey_from_source(formname, src_surveys, gv)

    consent_form = dst_forms["consent_baseline"]
    consent_rpt = src_forms["consent_rpt"]
    consent_rpt_ref_map = {
        ref.get("ItemGroupOID"): ref.get("Mandatory", "No")
        for ref in consent_rpt.findall("odm:ItemGroupRef", NS)
    }
    consent_rpt_fields = {oid for oid in src_items if oid.startswith("task_data_")} | CONSENT_RPT_FIELDS_TO_ADD
    for field in sorted(consent_rpt_fields):
        if field in dst_items:
            continue
        if field not in src_item_to_group:
            continue
        group_oid = src_item_to_group[field]
        ensure_itemgroup(
            group_oid,
            src_itemgroups,
            src_items,
            src_codelists,
            dst_itemgroups,
            dst_items,
            dst_codelists,
            mdv,
        )
        add_itemgroup_ref(
            consent_form,
            group_oid,
            mandatory=consent_rpt_ref_map.get(group_oid, "No"),
        )

    if "screening_result.continue_date" not in dst_itemgroups:
        new_ig = create_single_itemgroup("screening_result.continue_date", "Screening Result", "continue_date", "No")
        insert_before_first(mdv, "ItemDef", new_ig)
        dst_itemgroups["screening_result.continue_date"] = new_ig
    add_itemgroup_ref(dst_forms["screening_result"], "screening_result.continue_date", "No", after_oid="screening_result.sp_wait_pls")

    hidden_zero = "@HIDDEN-SURVEY\n@DEFAULT='0'"
    hidden_two = "@HIDDEN-SURVEY\n@DEFAULT='2'"
    hidden_yeah = "@HIDDEN-SURVEY\n@DEFAULT='yeah'"
    hidden_blank = "@HIDDEN-SURVEY"

    update_item(
        find_item(dst_items, "student_yn"),
        html="Internal legacy field retained for compatibility.",
        annotation=hidden_zero,
    )
    for field in [
        "sona_id",
        "study_summary_yale",
        "screen_yaleemail",
        "prolific_yn",
        "prolific_id_bl",
        "mturk_yn",
        "mturk_id",
        "no_prolific___1",
        "no_prolific_2___1",
        "no_mturk___1",
        "nousbank",
        "usbankinfo",
        "firstname",
        "lastname",
        "payment_address_bl",
    ]:
        if field in dst_items:
            update_item(find_item(dst_items, field), annotation=hidden_blank)

    update_item(
        find_item(dst_items, "payment_pref"),
        html="Internal payment method flag.",
        choices="2, Amazon.com (US) electronic gift card",
        annotation=hidden_two,
    )
    update_item(
        find_item(dst_items, "payment_email_bl"),
        html=(
            "<div class=\"rich-text-field-label\"><p>Please enter the email address where you want us to send your "
            "<strong>Amazon.com (US) electronic gift card</strong>.</p>"
            "<p>Payments for this amended workflow are issued only through Amazon.com US electronic gift cards.</p></div>"
        ),
        branching="",
    )
    update_item(
        find_item(dst_items, "payment_email_bl_2"),
        html="<div class=\"rich-text-field-label\"><p>Please re-enter the same Amazon gift card email address to confirm there are no typos.</p></div>",
        branching="",
    )

    if "email_rpt" in dst_items:
        update_item(
            find_item(dst_items, "email_rpt"),
            html=(
                "<div class=\"rich-text-field-label\"><p>Please enter the email address you want us to use for "
                "<strong>study links and reminders</strong>.</p>"
                "<p>This can be the same as, or different from, your Amazon gift card email.</p></div>"
            ),
        )
    if "random_rpt" in dst_items:
        update_item(find_item(dst_items, "random_rpt"), annotation=hidden_blank)
    if "include_hyp_measures" in dst_items:
        update_item(find_item(dst_items, "include_hyp_measures"), annotation=hidden_yeah)
    if "prolific_yn_rpt" in dst_items:
        update_item(find_item(dst_items, "prolific_yn_rpt"), annotation=hidden_zero)

    update_item_family(
        dst_items,
        "interested_spstudy_consent",
        html=(
            "<div class=\"rich-text-field-label\"><p>This study now directly enrolls people into the "
            "<strong>prospective serotonergic psychedelic repeated-measures study</strong>.</p>"
            "<p>Please confirm that the following statements are true before continuing.</p></div>"
        ),
        choices=(
            "1, At least 6 weeks have passed since my last serotonergic or atypical psychedelic use (or I have never had one).|"
            "2, I am planning a future macro/museum-level serotonergic psychedelic use event.|"
            "3, I am willing to complete a baseline session and follow-up sessions during use and/or the day after, 1-2 weeks after, and 1-6 months after.|"
            "4, I will not use additional serotonergic or atypical psychedelics before I finish the final follow-up.|"
            "5, I do not meet the above requirements and do not want to continue."
        ),
    )
    update_item(
        find_item(dst_items, "study_summary"),
        html=(
            "<div class=\"rich-text-field-label\">"
            "<p style=\"text-align:center;\"><span style=\"font-size:14pt;text-decoration:underline;\">Study Summary</span></p>"
            "<hr>"
            "<p><strong>What this study involves</strong></p>"
            "<ul>"
            "<li>Consent, screening, and researcher review of eligibility/fraud checks.</li>"
            "<li>One baseline online session before your next planned serotonergic psychedelic use.</li>"
            "<li>Up to four additional follow-up opportunities: during use, the day after use, 1-2 weeks after use, and 1-6 months after use.</li>"
            "<li>Online questionnaires plus auditory, visual, decision-making, and reinforcement-learning games.</li>"
            "</ul>"
            "<p><strong>Compensation</strong></p>"
            "<ul><li>$50 per completed session, up to 5 sessions total, maximum $250.</li></ul>"
            "<p><strong>Requirements</strong></p>"
            "<ul>"
            "<li>Computer or laptop, not a phone or tablet.</li>"
            "<li>Stable internet, headphones, and a distraction-free space.</li>"
            "<li>No additional serotonergic or atypical psychedelic use before the final follow-up is complete.</li>"
            "<li>At least 6 weeks since your last serotonergic or atypical psychedelic use at baseline.</li>"
            "</ul>"
            "</div>"
        ),
    )
    update_item(
        find_item(dst_items, "sp_lastuse_days_screen"),
        html=(
            "<div class=\"rich-text-field-label\"><p>How many days has it been since your most recent "
            "<strong>serotonergic or atypical psychedelic experience</strong>? "
            "(Do not include microdoses.)</p></div>"
        ),
        note="If over 1 year it is okay to estimate; use 30 days per month and 365 days per year.",
    )
    update_item(
        find_item(dst_items, "planning_trip"),
        html=(
            "<div class=\"rich-text-field-label\"><p>Are you anticipating a future "
            "<strong>macro/museum-level serotonergic psychedelic use event</strong> during the study period?</p></div>"
        ),
    )
    update_item(
        find_item(dst_items, "sp_wait_pls"),
        html=(
            "<div class=\"rich-text-field-label\"><h3><span style=\"text-decoration:underline;\">You are not yet eligible to begin baseline.</span></h3>"
            "<p>For this longitudinal study, baseline must happen <strong>at least 6 weeks</strong> after your most recent serotonergic or atypical psychedelic use.</p>"
            "<p>If you want, we can email you a link to continue once you reach that 6-week point.</p>"
            "<p>Please select Yes if you want that reminder.</p></div>"
        ),
        branching=(
            "[planning_trip]='1' and [psycheduse_yn]='1' and [sp_lastuse_days_screen]<>'' and "
            "[sp_lastuse_days_screen]<42 and [age_v2] < 65 and [age_v2] > 17 and [cognition_screener_v2]='0' and "
            "[seizure_hx_v2]='0' and [intox_screen_v2]='0' and [sp_naiive]='1' and [no_computer]='0' and [geo_crit]<>''"
        ),
    )
    if "continue_date" in dst_items:
        update_item(
            find_item(dst_items, "continue_date"),
            html="",
            annotation="@HIDDEN-SURVEY\n@CALCDATE([timestamp_screen_day], 42-[sp_lastuse_days_screen], 'd')",
        )

    for field in [
        "cb_email_yn",
        "longitudinal_cb_yn",
        "cb_continue_date",
        "cb_wait_time",
        "cb_abstinence_yn",
        "zoom_email",
        "not_eligible_weed___1",
        "not_eligible_weed_2___1",
        "not_eligibile_email",
    ]:
        if field in dst_items:
            update_item(find_item(dst_items, field), annotation=hidden_blank)

    update_item(
        find_item(dst_items, "submit_screen_v3"),
        html=(
            "<div class=\"rich-text-field-label\"><p><span style=\"font-size:18pt;\"><em>You are likely eligible.</em></span></p>"
            "<p>Researchers will review your responses for eligibility and fraud checks, usually within 1 business day.</p>"
            "<p>If approved, we will email you a link to begin the baseline session.</p>"
            "<p>Please keep your personal survey link and do not share it with anyone else.</p></div>"
        ),
        choices="1, Please email me when I am cleared to begin baseline.",
        branching=(
            "[age_v2] < 65 and [age_v2] > 17 and [cognition_screener_v2]='0' and [seizure_hx_v2]='0' and "
            "[intox_screen_v2]='0' and [sp_naiive]='1' and [no_computer]='0' and [geo_crit]<>'' and [planning_trip]='1' and "
            "(([psycheduse_yn]='2' or [psycheduse_yn]='3') or ([sp_lastuse_days_screen]<>'' and [sp_lastuse_days_screen]>=42))"
        ),
    )
    if "email_notify_only" in dst_items:
        update_item(
            find_item(dst_items, "email_notify_only"),
            html="What email should we use for the baseline-approval notification?",
            branching="([submit_screen_v3]='1') and ([email_rpt]='') and ([email_addtl_contact]='')",
        )

    replacements = [
        ("[payment_email_rpt]", "[payment_email_bl]"),
        ("$40", "$50"),
        ("$60", "$50"),
        ("$240", "$250"),
        ("$180", "$200"),
        ("US Bank/Amazon", "Amazon"),
        ("US Bank", "Amazon"),
    ]
    for formname in [
        "payment_form_hyp",
        "payment_confirmation_hyp",
        "payment_form_acu",
        "payment_confirmation_acu",
        "payment_form_sub",
        "payment_confirmation_sub",
        "payment_form_pers",
        "payment_confirmation_pers",
    ]:
        form = dst_forms[formname]
        for ref in form.findall("odm:ItemGroupRef", NS):
            ig = dst_itemgroups[ref.get("ItemGroupOID")]
            for item_ref in ig.findall("odm:ItemRef", NS):
                item = dst_items[item_ref.get("ItemOID")]
                replace_text_recursive(item, replacements)

    queue_entries = {q.get("survey_id"): q for q in queue_list(gv)}
    if "screening_survey" in queue_entries:
        q = queue_entries["screening_survey"]
        q.set("condition_surveycomplete_survey_id", "consent_baseline")
        q.set("condition_logic", "")
    if "sms_verification" in queue_entries:
        q = queue_entries["sms_verification"]
        q.set("condition_surveycomplete_survey_id", "screening_survey")
        q.set("condition_logic", "[phone_number]<>\"\"")
    if "screening_result" in queue_entries:
        q = queue_entries["screening_result"]
        q.set("condition_surveycomplete_survey_id", "sms_verification")
        q.set("condition_logic", "[phone_number]<>\"\"")
    if "eligibile" in queue_entries:
        q = queue_entries["eligibile"]
        q.set("condition_surveycomplete_survey_id", "screening_result")
        q.set("condition_logic", "[screening_pass]='1' and [sp_wait_pls]<>'1'")
    if "survey_perception_substance_use" in queue_entries:
        q = queue_entries["survey_perception_substance_use"]
        q.set("condition_surveycomplete_survey_id", "eligibile")
        q.set("condition_andor", "AND")
        q.set("condition_logic", "")
    if "family_history_and_asi" in queue_entries:
        q = queue_entries["family_history_and_asi"]
        q.set("condition_surveycomplete_survey_id", "survey_perception_substance_use")
        q.set("condition_logic", "")
    if "visual_ch_task" in queue_entries:
        q = queue_entries["visual_ch_task"]
        q.set("condition_surveycomplete_survey_id", "family_history_and_asi")
        q.set("condition_logic", "")
    if "prl_task" in queue_entries:
        q = queue_entries["prl_task"]
        q.set("condition_surveycomplete_survey_id", "visual_ch_task")
        q.set("condition_logic", "")
    if "auditory_ch_task" in queue_entries:
        q = queue_entries["auditory_ch_task"]
        q.set("condition_surveycomplete_survey_id", "prl_task")
        q.set("condition_logic", "")
    if "spacejunk_game" in queue_entries:
        q = queue_entries["spacejunk_game"]
        q.set("condition_surveycomplete_survey_id", "auditory_ch_task")
        q.set("condition_logic", "")
    if "validity_checks" in queue_entries:
        q = queue_entries["validity_checks"]
        q.set("condition_surveycomplete_survey_id", "spacejunk_game")
        q.set("condition_logic", "")

    surveys = survey_map(gv)
    if "consent_baseline" in surveys:
        surveys["consent_baseline"].set("title", "Consent and Study Setup")
        surveys["consent_baseline"].set(
            "instructions",
            "<p><strong>Please read the consent and enter the information we need to manage screening, payment, and later study links.</strong></p>",
        )
    if "screening_survey" in surveys:
        surveys["screening_survey"].set("title", "Screening Survey")
        surveys["screening_survey"].set(
            "instructions",
            "<p>Answer the following questions so we can review eligibility and run fraud checks before baseline.</p>",
        )
    if "screening_result" in surveys:
        surveys["screening_result"].set("title", "Screening Results")
        surveys["screening_result"].set(
            "instructions",
            "<p>This page explains whether you appear eligible, whether you need to wait until 6 weeks after your last psychedelic use, and how we will notify you when you can continue.</p>",
        )
    if "eligibile" in surveys:
        surveys["eligibile"].set("title", "Eligible to Begin Baseline")
        surveys["eligibile"].set(
            "instructions",
            "<p>You have been cleared to begin the baseline session. Please continue only when you are ready to complete the baseline questionnaires and games.</p>",
        )

    alerts = alert_group(gv)
    template = next(a for a in alerts.findall("redcap:Alerts", NS) if a.get("alert_title") == "eligible_notify")

    add_alert(
        alerts,
        template,
        title="6-Week Wait Confirmation",
        email_to="[email_rpt];[email_addtl_contact];[interested_spstudy]",
        subject="Powers Lab Online Study: We will email you when you can continue",
        message=(
            "<p>Hello,</p>"
            "<p>Thanks for completing screening. Because your most recent serotonergic or atypical psychedelic use was less than 6 weeks ago, you cannot begin the baseline session yet.</p>"
            "<p>We recorded that you want a reminder. We will send you a continuation link on or after the date when 6 weeks have passed since your last use.</p>"
            "<p>- Powers Lab</p>"
        ),
        condition="[sp_wait_pls]='1' and [continue_date]<>''",
        lag_minutes="15",
    )
    add_alert(
        alerts,
        template,
        title="6-Week Continue Link",
        email_to="[email_rpt];[email_addtl_contact];[interested_spstudy]",
        subject="Powers Lab Online Study: You can now continue to baseline",
        message=(
            "<p>Hello,</p>"
            "<p>You are now at least 6 weeks past the last serotonergic or atypical psychedelic use you reported during screening.</p>"
            "<p>You can continue your study enrollment here:</p>"
            "<p><strong>[survey-link:screening_result:Continue from your screening results page]</strong></p>"
            "<p>- Powers Lab</p>"
        ),
        condition="[sp_wait_pls]='1' and [continue_date]<>'' and [screening_pass]=''",
        lag_field="[continue_date]",
    )
    add_alert(
        alerts,
        template,
        title="Baseline Complete: Save Day-Of Link",
        email_to="[email_rpt]",
        subject="Powers Lab Online Study: Save your day-of survey link",
        message=(
            "<p>Hello,</p>"
            "<p>You have completed the baseline session.</p>"
            "<p>Please save this email. When you are ready for the <strong>day-of / hyperacute</strong> timepoint, start here:</p>"
            "<p><strong>[survey-link:hyperacute_presurvey:Open the day-of / hyperacute session link]</strong></p>"
            "<p>Use this link only on the intended day, before beginning your planned serotonergic psychedelic use event.</p>"
            "<p>- Powers Lab</p>"
        ),
        condition="[validity_checks_complete]='2'",
        lag_minutes="15",
    )
    add_alert(
        alerts,
        template,
        title="Baseline Complete: Save Day-After Link",
        email_to="[email_rpt]",
        subject="Powers Lab Online Study: Save your day-after survey link",
        message=(
            "<p>Hello,</p>"
            "<p>You have completed the baseline session.</p>"
            "<p>Please save this email. When you are ready for the <strong>day-after / acute</strong> timepoint, start here:</p>"
            "<p><strong>[survey-link:acute_presurvey:Open the day-after / acute session link]</strong></p>"
            "<p>Use this link the day after your planned serotonergic psychedelic use event.</p>"
            "<p>- Powers Lab</p>"
        ),
        condition="[validity_checks_complete]='2'",
        lag_minutes="15",
    )
    add_alert(
        alerts,
        template,
        title="1-2 Week Follow-Up Invite From Hyperacute",
        email_to="[email_rpt]",
        subject="Powers Lab Online Study: It is time for your 1-2 week follow-up",
        message=(
            "<p>Hello,</p>"
            "<p>It is now time for your 1-2 week follow-up session.</p>"
            "<p><strong>[survey-link:subacute_presurvey:Open your 1-2 week follow-up session]</strong></p>"
            "<p>- Powers Lab</p>"
        ),
        condition="[timestamp_hyp_post]<>'' and [timestamp_acu_post]='' and [timestamp_sub_pre]=''",
        lag_days="7",
        lag_field="[timestamp_hyp_post]",
    )
    add_alert(
        alerts,
        template,
        title="1-2 Week Follow-Up Invite From Acute",
        email_to="[email_rpt]",
        subject="Powers Lab Online Study: It is time for your 1-2 week follow-up",
        message=(
            "<p>Hello,</p>"
            "<p>It is now time for your 1-2 week follow-up session.</p>"
            "<p><strong>[survey-link:subacute_presurvey:Open your 1-2 week follow-up session]</strong></p>"
            "<p>- Powers Lab</p>"
        ),
        condition="[timestamp_acu_post]<>'' and [timestamp_sub_pre]=''",
        lag_days="7",
        lag_field="[timestamp_acu_post]",
    )
    add_alert(
        alerts,
        template,
        title="1-6 Month Follow-Up Invite From Hyperacute",
        email_to="[email_rpt]",
        subject="Powers Lab Online Study: It is time for your 1-6 month follow-up",
        message=(
            "<p>Hello,</p>"
            "<p>Your 1-6 month follow-up window is now open.</p>"
            "<p><strong>[survey-link:persisting_presurvey:Open your 1-6 month follow-up session]</strong></p>"
            "<p>- Powers Lab</p>"
        ),
        condition="[timestamp_hyp_post]<>'' and [timestamp_acu_post]='' and [timestamp_pers_pre]=''",
        lag_days="30",
        lag_field="[timestamp_hyp_post]",
    )
    add_alert(
        alerts,
        template,
        title="1-6 Month Follow-Up Invite From Acute",
        email_to="[email_rpt]",
        subject="Powers Lab Online Study: It is time for your 1-6 month follow-up",
        message=(
            "<p>Hello,</p>"
            "<p>Your 1-6 month follow-up window is now open.</p>"
            "<p><strong>[survey-link:persisting_presurvey:Open your 1-6 month follow-up session]</strong></p>"
            "<p>- Powers Lab</p>"
        ),
        condition="[timestamp_acu_post]<>'' and [timestamp_pers_pre]=''",
        lag_days="30",
        lag_field="[timestamp_acu_post]",
    )

    long_24h = next(a for a in long_gv.findall("redcap:AlertsGroup/redcap:Alerts", NS) if a.get("alert_title") == "24 Hour Timepoint Reminder")
    add_alert(
        alerts,
        long_24h,
        title="24 Hour Timepoint Reminder",
        email_to="[email_rpt]",
        subject="Powers Lab Online Study: Reminder for your day-after session",
        message=long_24h.get("alert_message", ""),
        condition="[timestamp_hyp_pre]<>'' and ([timestamp_vch_hyp]<>'' or [timestamp_hyp_post]<>'') and [timestamp_acu_pre]=''",
        lag_hours="12",
        lag_field="[timestamp_hyp_pre]",
    )

    if "email_rpt" in dst_items:
        update_item(find_item(dst_items, "email_rpt"), annotation="")

    keyword_hides = [
        "yale",
        "sona",
        "intro to psychology",
        "course credit",
        "prolific",
        "mturk",
        "us bank",
        "physical visa",
        "prepaid",
    ]
    for oid, item in dst_items.items():
        if oid in {"payment_email_bl", "payment_email_bl_2", "email_rpt"}:
            continue
        text = (
            item.findtext("odm:Question/odm:TranslatedText", default="", namespaces=NS).lower()
            + " "
            + oid.lower()
        )
        if any(keyword in text for keyword in keyword_hides):
            current = item.findtext("redcap:FieldAnnotation", default="", namespaces=NS)
            if "@HIDDEN-SURVEY" not in current:
                new_annotation = f"{current}\n@HIDDEN-SURVEY".strip()
                set_child_text(item, f"{redcap_tag('FieldAnnotation')}", new_annotation)

    root.set("Description", "Psychedelics Aim 1 -- Repeated Measures (Merged Relaunch Draft)")
    study.find("odm:GlobalVariables/odm:StudyName", NS).text = "Psychedelics Aim 1 -- Repeated Measures (Merged Relaunch Draft)"
    study.find("odm:GlobalVariables/odm:StudyDescription", NS).text = (
        "This file contains a draft merged REDCap build combining baseline screening with the repeated-measures follow-up workflow."
    )
    study.find("odm:GlobalVariables/odm:ProtocolName", NS).text = "Psychedelics Aim 1 -- Repeated Measures (Merged Relaunch Draft)"

    base_tree._setroot(root)
    base_tree.write(OUT_XML, encoding="UTF-8", xml_declaration=True)
    print(f"Wrote {OUT_XML.name}")


if __name__ == "__main__":
    main()
