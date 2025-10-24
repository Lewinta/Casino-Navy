# Copyright (c) 2025, Lewin Villar and contributors
# For license information, please see license.txt

import re
import frappe
from collections import defaultdict, OrderedDict
from frappe.utils.nestedset import get_descendants_of
from frappe.model.document import Document

class AccountantMapper(Document):
	pass


def _pick_mapper(report, company=None):
    filters = {"report": report, "is_default": 1}
    # Prefer company-specific, then any-company default
    if company:
        existing = frappe.get_all("Accountant Mapper",
            filters={**filters, "company": company},
            fields=["name"], limit=1
        )
        if existing:
            return existing[0].name

    any_company = frappe.get_all("Accountant Mapper",
        filters={**filters, "company": ["is", "not set"]},
        fields=["name"], limit=1
    )
    if any_company:
        return any_company[0].name

    # Fallback: just any mapper for the report
    any_mapper = frappe.get_all("Accountant Mapper",
        filters={"report": report},
        fields=["name"], limit=1
    )
    return any_mapper[0].name if any_mapper else None


def _load_sections_from_mapper(report, company):
    mapper = _pick_mapper(report, company)
    if not mapper:
        frappe.throw(f"No Accountant Mapper found for report '{report}'. Create one and mark it as Default.")

    items = frappe.get_all(
        "Accountant Mapper Item",
        filters={"parent": mapper},
        fields=["section_label", "row_type", "account", "include_children", "sign", "formula", "sort_order"],
        order_by="sort_order asc, section_label asc"
    )

    # sections: OrderedDict[str, dict]
    sections = OrderedDict()
    for it in items:
        sec = sections.setdefault(it.section_label, {"buckets": [], "formulas": []})
        if it.row_type == "Bucket":
            sec["buckets"].append({
                "account": it.account,
                "include_children": int(it.include_children or 0),
                "sign": int(it.sign or 1),
            })
        else:
            # store formulas at the section-level (one section can have 1 formula row if you like)
            sec["formulas"].append({
                "formula": it.formula or "",
                "sign": int(it.sign or 1),
            })
    return sections


def _expand_to_leaf_accounts(company, account_name, include_children=True):
    if not include_children:
        return [account_name]
    # If it's a group, expand to all leafs; else keep single
    is_group = frappe.db.get_value("Account", {"company": company, "name": account_name}, "is_group")
    if is_group:
        leafs = get_descendants_of("Account", account_name)
        return leafs or []
    return [account_name]


def _resolve_sections_leafs(company, sections):
    """Return dict: {section_label: {"leafs": set(), "signs": {leaf: sign}, "formulas": [...]}}"""
    out = OrderedDict()
    for label, cfg in sections.items():
        leafs = set()
        signs = {}
        for b in cfg["buckets"]:
            for leaf in _expand_to_leaf_accounts(company, b["account"], b["include_children"]):
                leafs.add(leaf)
                signs[leaf] = b["sign"]
        out[label] = {"leafs": leafs, "signs": signs, "formulas": cfg.get("formulas", [])}
    return out


def _evaluate_formulas(section_totals, formulas):
    """formulas: list of {"formula": "Revenue - Total Expenses", "sign": 1} -> float"""
    values = []
    for f in formulas:
        expr = f.get("formula") or ""
        # Very simple safe evaluation: only allow section labels, + - * / ( )
        # Replace labels with numeric totals
        safe = expr
        for lbl, val in section_totals.items():
            safe = re.sub(rf"\b{re.escape(lbl)}\b", str(val), safe)
        # Remove unsafe chars (leave digits, operators, dots, spaces, parentheses)
        if re.search(r"[^0-9\.\+\-\*\/\(\) ]", safe):
            values.append(0.0)
            continue
        try:
            values.append((eval(safe) if safe.strip() else 0.0) * float(f.get("sign", 1)))
        except Exception:
            values.append(0.0)
    return sum(values) if values else 0.0