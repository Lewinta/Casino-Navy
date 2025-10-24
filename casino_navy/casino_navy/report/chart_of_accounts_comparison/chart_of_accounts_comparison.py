# Copyright (c) 2025, Lewin Villar and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import cstr

STAT_MATCH = "Match"
STAT_DIFF_NAME = "Different Name"
STAT_NOT_IN_PARENT = "Not in Parent"
STAT_DOESNT_EXIST = "Doesn't exists"  # keep exact wording

def execute(filters=None):
    filters = filters or {}
    return get_columns(filters), get_data(filters)

# ---------- helpers ----------
def _parse_selected_companies(filters):
    """Read filters.compaies (MultiSelectList). Returns a set of company names (may be empty)."""
    sel = filters.get("compaies")
    if isinstance(sel, str):
        parts = [p.strip() for p in sel.replace("\n", ",").split(",") if p.strip()]
        return set(parts)
    if isinstance(sel, (list, tuple, set)):
        return set([c for c in sel if c])
    return set()

def _ordered_companies(filters):
    """
    Returns list of company rows [{name, abbr}, ...] with:
    - main company first (required),
    - then either selected companies (if filters.compaies provided) or all others,
      ordered by abbr.
    """
    main_company = filters.get("main_company")
    if not main_company:
        frappe.throw("Please select a Main Company in the report filters.")

    all_companies = frappe.get_all("Company", fields=["name", "abbr"], order_by="abbr")
    selected = _parse_selected_companies(filters)
    selected.discard(main_company)

    if selected:
        tail = [c for c in all_companies if c.name in selected]
    else:
        tail = [c for c in all_companies if c.name != main_company]

    head = [c for c in all_companies if c.name == main_company]
    return head + tail

# ---------- columns ----------
def get_columns(filters):
    columns = []
    companies = _ordered_companies(filters)
    for c in companies:
        if c.name == filters.get("main_company"):
            columns += get_company_columns(c.name, add_status=False)
        else:
            columns += get_company_columns(c.name)
    return columns

def get_company_columns(company, add_status=True):
    abbr = frappe.get_cached_value("Company", company, "abbr")
    columns = [
        {"fieldname": f"account_number_{abbr}", "label": f"Number ({abbr})", "fieldtype": "Data", "width": 120},
        {"fieldname": f"account_name_{abbr}",   "label": f"Name ({abbr})",   "fieldtype": "Data", "width": 240},
    ]
    if add_status:
        columns.append(
            {"fieldname": f"status_{abbr}", "label": f"Status ({abbr})", "fieldtype": "Data", "width": 140}
        )
    return columns

# ---------- data ----------
def get_data(filters):
    main_company = (filters or {}).get("main_company")
    mismatches_only = bool((filters or {}).get("mismatches_only"))
    if not main_company:
        frappe.throw("Please select a Main Company in the report filters.")

    companies = _ordered_companies(filters)
    abbr_by_company = {c.name: c.abbr for c in companies}
    company_names = [c.name for c in companies]

    # Fetch accounts (group + leaf) only for selected companies (+ main)
    accounts = frappe.get_all(
        "Account",
        fields=["company", "account_number", "account_name"],
        filters={"company": ["in", company_names]},
    )

    # by_company[company][normalized_num] = {"raw_name": ..., "raw_num": ...}
    # normalized_num = raw_num.strip() — used only as the join key
    by_company = {}
    for acc in accounts:
        comp = acc.company
        raw_num = cstr(acc.account_number)
        norm_num = raw_num.strip()
        if not norm_num:
            # skip unusable numbers (can't align)
            continue
        raw_name = cstr(acc.account_name)

        by_company.setdefault(comp, {})
        if norm_num not in by_company[comp]:  # keep first deterministically
            by_company[comp][norm_num] = {"raw_name": raw_name, "raw_num": raw_num}

    # Union of all normalized account numbers across the selected set
    all_numbers = set()
    for comp in company_names:
        all_numbers.update(by_company.get(comp, {}).keys())

    sorted_numbers = sorted(all_numbers)  # safe: strings only

    main_map = by_company.get(main_company, {})
    main_nums = set(main_map.keys())

    rows = []
    for acc_num in sorted_numbers:
        row = {}
        any_mismatch = False

        for comp in company_names:
            abbr = abbr_by_company[comp]
            comp_map = by_company.get(comp, {})
            entry = comp_map.get(acc_num)
            status_field = f"status_{abbr}"

            if comp == main_company:
                # SHOW EXACT DB VALUES for main
                if acc_num in main_nums:
                    row[f"account_number_{abbr}"] = main_map[acc_num]["raw_num"]
                    row[f"account_name_{abbr}"] = main_map[acc_num]["raw_name"]
                else:
                    row[f"account_number_{abbr}"] = ""
                    row[f"account_name_{abbr}"] = ""
                continue

            # SHOW EXACT DB VALUES for others
            row[f"account_number_{abbr}"] = (entry["raw_num"] if entry else "")
            row[f"account_name_{abbr}"] = (entry["raw_name"] if entry else "")

            in_main = acc_num in main_nums

            if not in_main and entry:
                row[status_field] = STAT_NOT_IN_PARENT
                any_mismatch = True

            elif in_main and not entry:
                row[status_field] = STAT_DOESNT_EXIST
                any_mismatch = True

            elif in_main and entry:
                main_entry = main_map[acc_num]
                main_raw_name = main_entry["raw_name"]
                comp_raw_name = entry["raw_name"]

                # EXACT comparison on raw strings (includes spaces/case)
                if comp_raw_name == main_raw_name:
                    row[status_field] = STAT_MATCH
                else:
                    row[status_field] = STAT_DIFF_NAME
                    frappe.errprint(
                        f"Account name mismatch for {acc_num} in {comp} (expected: '{main_raw_name}', found: '{comp_raw_name}')"
                    )
                    any_mismatch = True
            else:
                row[status_field] = ""

        if not mismatches_only or any_mismatch:
            rows.append(row)

    return rows