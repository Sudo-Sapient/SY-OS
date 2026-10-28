"""Milestones 2–4: trims POs, cutting, hourly sewing, checking & packing, dashboard."""

import math
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Max, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from ..forms import CutHeadForm
from ..models import (
    CHECK_DEFECTS,
    FABRIC_DEFECTS,
    LEVELS,
    CheckingEntry,
    CutLot,
    CutSize,
    FabricLot,
    Line,
    Order,
    PackingEntry,
    RollLaid,
    SewingEntry,
    TrimPO,
    TrimPOLine,
    TrimReceipt,
    fabric_window,
    lot_balance,
    tracker,
)
from ..permissions import CUTTING, DATA_ENTRY, can_post, roles, stamp

GSM_TOL, WIDTH_TOL, CONSUMPTION_BLOCK = Decimal("0.05"), Decimal("0.5"), 10
HOURS = list(range(9, 19))


def num(value, kind=int):
    """Parse a typed number; blank is None; negative or junk raises ValueError."""
    if value in (None, ""):
        return None
    try:
        v = kind(value)
    except (ValueError, InvalidOperation):
        raise ValueError(value) from None
    if v < 0:
        raise ValueError(value)
    return v


# ---------- trims ----------


def trim_rows(order):
    """Calculator: required per trim (and per size for size-wise trims) vs what is already on PO."""
    by_size = defaultdict(int)
    for l in order.lines.all():
        by_size[l.size] += l.qty
    on_po = defaultdict(int)
    for pl in TrimPOLine.objects.filter(po__order=order):
        on_po[pl.trim_id, pl.size] += pl.qty
    rows = []
    for t in order.trims.select_related("supplier"):
        parts = [(s, by_size[s]) for s in order.size_list] if t.size_wise else [("", order.total_qty)]
        for size, qty in parts:
            need = t.required(qty)
            rows.append(
                {"trim": t, "size": size, "need": need, "on_po": on_po[t.id, size], "to_order": max(need - on_po[t.id, size], 0)}
            )
    return rows


@login_required
def trims(request):
    can_post(request, DATA_ENTRY)
    if request.method == "POST":
        order = get_object_or_404(Order, pk=request.POST.get("order"))
        rows = [r for r in trim_rows(order) if r["to_order"] and r["trim"].supplier]
        by_supplier = defaultdict(list)
        for r in rows:
            by_supplier[r["trim"].supplier].append(r)
        with transaction.atomic():
            n = TrimPO.objects.count()
            for supplier, items in by_supplier.items():
                n += 1
                po = stamp(
                    TrimPO(po_no=f"TPO-{n:04d}", order=order, supplier=supplier, required_by=order.cut_start - timedelta(days=2)),
                    request,
                )
                po.save()
                for r in items:
                    stamp(TrimPOLine(po=po, trim=r["trim"], size=r["size"], qty=r["to_order"]), request).save()
        if by_supplier:
            messages.success(request, _("%(n)s POs raised for %(order)s.") % {"n": len(by_supplier), "order": order.order_no})
        return redirect("trims")
    orders = []
    for o in Order.objects.prefetch_related("trims"):
        rows = trim_rows(o)
        grouped = {}
        for r in rows:  # one line per trim; size-wise quantities shown as tags
            g = grouped.setdefault(r["trim"].id, {"trim": r["trim"], "need": 0, "on_po": 0, "to_order": 0, "sizes": []})
            for k in ("need", "on_po", "to_order"):
                g[k] += r[k]
            if r["size"]:
                g["sizes"].append((r["size"], r["need"]))
        orders.append(
            {
                "order": o,
                "rows": list(grouped.values()),
                "to_order": sum(1 for r in rows if r["to_order"]),
                "pos": o.trim_pos.select_related("supplier").prefetch_related("lines__receipts"),
            }
        )
    return render(request, "core/trims.html", {"orders": orders})


@login_required
def trim_po(request, pk):
    po = get_object_or_404(TrimPO.objects.select_related("order", "supplier"), pk=pk)
    can_post(request, DATA_ENTRY)
    lines = list(po.lines.select_related("trim").prefetch_related("receipts"))
    errors = []
    if request.method == "POST":
        challan = request.POST.get("challan", "").strip()
        when = request.POST.get("date") or timezone.localdate()
        got = []
        try:
            for l in lines:
                q = num(request.POST.get(f"q-{l.id}"))
                if q:
                    got.append((l, q))
        except ValueError:
            errors.append(_("Quantities must be whole numbers, not negative."))
        if not challan:
            errors.append(_("Enter the supplier's challan number."))
        if not got and not errors:
            errors.append(_("Enter the quantity received for at least one line."))
        if not errors:
            with transaction.atomic():
                for l, q in got:
                    stamp(TrimReceipt(line=l, qty=q, challan=challan, date=when), request).save()
            messages.success(request, _("Receipt saved against challan %(c)s.") % {"c": challan})
            return redirect("trim_po", pk)
    text = [
        _("PO %(po)s — %(order)s / %(style)s / buyer PO %(bpo)s")
        % {"po": po.po_no, "order": po.order.order_no, "style": po.order.style, "bpo": po.order.buyer_po},
        _("Required by %(d)s") % {"d": po.required_by.strftime("%d %b %Y")},
    ]
    for l in lines:
        text.append(f"• {l.trim.item}{' ' + l.size if l.size else ''}: {l.qty} {l.trim.unit}")
    text.append(_("Thank you — SY Exports"))
    return render(
        request,
        "core/trim_po.html",
        {"po": po, "lines": lines, "errors": errors, "message": "\n".join(text), "today": timezone.localdate()},
    )


# ---------- cutting ----------


@login_required
def cutting(request):
    lots = CutLot.objects.select_related("order", "dia_line").prefetch_related("rolls__fabric_lot", "sizes")
    flags = [r for c in lots for r in c.rolls.all() if r.defect]
    balances = [(l, lot_balance(l)) for l in FabricLot.objects.select_related("order", "dia_line") if l.stage == "in_house"]
    return render(
        request, "core/cutting.html", {"lots": lots, "flags": flags, "balances": balances, "orders": Order.objects.all()}
    )


@roles(CUTTING, DATA_ENTRY)
def cut_new(request):
    order = get_object_or_404(Order, pk=request.GET.get("order") or request.POST.get("order"))
    colour = request.GET.get("colour") or request.POST.get("colour") or order.colours[0]
    dia = get_object_or_404(order.dia_lines, pk=request.GET.get("dia") or request.POST.get("dia") or order.dia_lines.first().pk)
    # Every in-house lot of the order is offered, so a roll from the wrong colour or dia can be caught and blocked.
    all_lots = [l for l in FabricLot.objects.filter(order=order).select_related("dia_line") if l.stage == "in_house"]
    lots = all_lots
    next_no = (CutLot.objects.count() or 0) + 401
    head = CutHeadForm(request.POST or None, initial={"cut_no": f"CL-{next_no:04d}", "date": timezone.localdate()})
    errors, warnings, rolls, sizes = [], [], [], []
    if request.method == "POST":
        lot_by_id = {str(l.pk): l for l in FabricLot.objects.filter(order=order)}
        try:
            for i in range(8):

                def g(f, i=i):
                    return request.POST.get(f"r{i}-{f}", "").strip()

                if not g("kg"):
                    continue
                lot = lot_by_id.get(g("lot"))
                r = RollLaid(
                    fabric_lot=lot,
                    roll_no=g("roll") or f"R-{i + 1}",
                    kg=num(g("kg"), Decimal),
                    gsm=num(g("gsm")) or 0,
                    width=num(g("width"), Decimal) or Decimal(0),
                    defect=g("defect"),
                    level=g("level"),
                    kg_rejected=num(g("rej"), Decimal) or 0,
                    kg_returned=num(g("ret"), Decimal) or 0,
                )
                rolls.append(r)
            for s in dia.size_list:
                p = num(request.POST.get(f"pcs-{s}"))
                if p:
                    sizes.append((s, p))
        except ValueError:
            errors.append(_("Numbers only — no letters or negative values."))
        if not rolls:
            errors.append(_("Enter at least one roll."))
        if not sizes:
            errors.append(_("Enter pieces cut for at least one size."))
        used_now = defaultdict(Decimal)
        for r in rolls:
            lot = r.fabric_lot
            if lot is None:
                errors.append(_("Roll %(r)s: choose the fabric lot.") % {"r": r.roll_no})
                continue
            if lot.colour != colour or lot.dia_line_id != dia.pk:
                errors.append(
                    _('Roll %(r)s is from lot %(lot)s (%(c)s, %(d)s") — this lay is %(c2)s, %(d2)s". Blocked.')
                    % {
                        "r": r.roll_no,
                        "lot": lot.lot_no,
                        "c": lot.colour,
                        "d": lot.dia_line.table_dia.normalize(),
                        "c2": colour,
                        "d2": dia.table_dia.normalize(),
                    }
                )
            if r.kg_returned + r.kg_rejected > r.kg:
                errors.append(_("Roll %(r)s: returned + rejected kg is more than the roll weight.") % {"r": r.roll_no})
            used_now[lot.pk] += r.kg - r.kg_returned
            if abs(r.gsm - order.target_gsm) > order.target_gsm * GSM_TOL:
                warnings.append(
                    _("Roll %(r)s GSM %(g)s is outside %(t)s ±5%%.") % {"r": r.roll_no, "g": r.gsm, "t": order.target_gsm}
                )
            if r.width < dia.table_dia - WIDTH_TOL:
                warnings.append(
                    _('Roll %(r)s width %(w)s" is under the %(d)s" table dia.')
                    % {"r": r.roll_no, "w": r.width.normalize(), "d": dia.table_dia.normalize()}
                )
        for lot in lots:
            if used_now[lot.pk] > lot_balance(lot):
                errors.append(
                    _("Lot %(lot)s has only %(kg)s kg in hand.")
                    % {"lot": lot.lot_no, "kg": lot_balance(lot).quantize(Decimal("0.1"))}
                )
        kg_map = {l.size: l.costed_kg for l in order.lines.filter(colour=colour)}
        costed = sum((p * kg_map.get(s, 0) for s, p in sizes), Decimal(0))
        used = sum(used_now.values(), Decimal(0))
        pct = (used - costed) / costed * 100 if costed else Decimal(0)
        if costed and abs(pct) > CONSUMPTION_BLOCK:
            errors.append(
                _(
                    "Consumption is %(p)s%% against costed — beyond ±10%%, so the lot is blocked. Check the roll weights and piece counts."
                )
                % {"p": f"{pct:+.1f}"}
            )
        if warnings and not request.POST.get("confirm"):
            errors.append(_("Tick the confirmation to use rolls outside tolerance."))
        if head.is_valid() and not errors:
            with transaction.atomic():
                cut = stamp(head.save(commit=False), request)
                cut.order, cut.colour, cut.dia_line = order, colour, dia
                cut.save()
                for r in rolls:
                    r.cut_lot = cut
                    stamp(r, request).save()
                bundle = (CutSize.objects.filter(cut_lot__order=order).aggregate(m=Max("bundle_to"))["m"] or 0) + 1
                for s, p in sizes:
                    n = math.ceil(p / order.pieces_per_bundle)
                    stamp(CutSize(cut_lot=cut, size=s, pieces=p, bundle_from=bundle, bundle_to=bundle + n - 1), request).save()
                    bundle += n
            messages.success(request, _("Cut lot %(c)s saved — consumption %(p)s%%.") % {"c": cut.cut_no, "p": f"{pct:+.1f}"})
            return redirect("cutting")
    fields = ("lot", "roll", "kg", "gsm", "width", "defect", "level", "rej", "ret")
    rows = [{"i": i, "n": 101 + i, **{f: request.POST.get(f"r{i}-{f}", "") for f in fields}} for i in range(6)]
    return render(
        request,
        "core/cut_new.html",
        {
            "order": order,
            "colour": colour,
            "dia": dia,
            "lots": all_lots,
            "head": head,
            "errors": errors,
            "warnings": warnings,
            "rows": rows,
            "pcs": [(s, request.POST.get(f"pcs-{s}", "")) for s in dia.size_list],
            "defects": [(k, l) for k, l, _v in FABRIC_DEFECTS],
            "levels": LEVELS,
            "orders": Order.objects.all(),
        },
    )


# ---------- sewing ----------


def floor_day():
    last = SewingEntry.objects.aggregate(m=Max("date"))["m"]
    return last or timezone.localdate()


@login_required
def sewing(request):
    can_post(request, DATA_ENTRY)
    day = request.GET.get("date") or request.POST.get("date") or str(floor_day())
    # Open on the next hour still to be keyed for that day.
    last = SewingEntry.objects.filter(date=day).aggregate(m=Max("hour"))["m"]
    hour = int(request.GET.get("hour") or request.POST.get("hour") or min((last or 8) + 1, HOURS[-1]))
    lines = list(Line.objects.select_related("order"))
    errors = []
    if request.method == "POST":
        saved = 0
        try:
            with transaction.atomic():
                for ln in lines:
                    pcs = num(request.POST.get(f"p-{ln.id}"))
                    if pcs is None or not ln.order:
                        continue
                    colour, size = request.POST.get(f"c-{ln.id}"), request.POST.get(f"s-{ln.id}")
                    if colour not in ln.order.colours or size not in ln.order.size_list:
                        raise ValueError(ln.name)
                    e = SewingEntry.objects.filter(date=day, hour=hour, line=ln).first() or SewingEntry(
                        date=day, hour=hour, line=ln
                    )
                    e.order, e.colour, e.size, e.pieces = ln.order, colour, size, pcs
                    stamp(e, request).save()
                    saved += 1
        except ValueError:
            errors.append(_("Pieces must be whole numbers, and colour and size must belong to the line's order."))
        if not errors:
            messages.success(request, _("%(n)s lines saved for %(h)s:00.") % {"n": saved, "h": hour})
            return redirect(f"{request.path}?date={day}&hour={hour}")
    entries = {(e.line_id, e.hour): e for e in SewingEntry.objects.filter(date=day)}
    rows = []
    for ln in lines:
        e = entries.get((ln.id, hour))
        pcs = e.pieces if e else None
        rows.append(
            {
                "line": ln,
                "colour": e.colour if e else ln.colour,
                "size": e.size if e else ln.size,
                "pieces": pcs,
                "eff": round(pcs / ln.target_per_hour * 100) if pcs is not None else None,
                "day": [entries[ln.id, h].pieces if (ln.id, h) in entries else None for h in HOURS],
                "total": sum(entries[ln.id, h].pieces for h in HOURS if (ln.id, h) in entries),
            }
        )
    return render(request, "core/sewing.html", {"rows": rows, "day": day, "hour": hour, "hours": HOURS, "errors": errors})


# ---------- checking & packing ----------


@login_required
def checking(request):
    can_post(request, DATA_ENTRY)
    order = get_object_or_404(
        Order, pk=request.GET.get("order") or request.POST.get("order") or Order.objects.order_by("created_at").first().pk
    )
    rows = tracker(order)
    by_key = {(r["colour"], r["size"]): r for r in rows}
    errors = []
    day = request.POST.get("date") or str(floor_day())
    if request.method == "POST":
        colour, size = request.POST.get("colour"), request.POST.get("size")
        r = by_key.get((colour, size))
        try:
            if r is None:
                raise ValueError
            if "pack" in request.POST:
                pcs = num(request.POST.get("pieces")) or 0
                cartons = request.POST.get("cartons", "").strip()
                if pcs > r["passed"] - r["packed"]:
                    errors.append(
                        _("Only %(n)s passed pieces of %(c)s / %(s)s are waiting to be packed.")
                        % {"n": r["passed"] - r["packed"], "c": colour, "s": size}
                    )
                if not cartons:
                    errors.append(_("Enter the carton numbers."))
                if not errors and pcs:
                    stamp(
                        PackingEntry(date=day, order=order, colour=colour, size=size, pieces=pcs, cartons=cartons), request
                    ).save()
                    messages.success(request, _("Packed %(n)s pcs of %(c)s / %(s)s.") % {"n": pcs, "c": colour, "s": size})
                    return redirect(f"{request.path}?order={order.pk}")
            else:
                e = CheckingEntry(
                    date=day,
                    hour=num(request.POST.get("hour")) or 9,
                    order=order,
                    colour=colour,
                    size=size,
                    checked=num(request.POST.get("checked")) or 0,
                    rework=num(request.POST.get("rework")) or 0,
                    reject=num(request.POST.get("reject")) or 0,
                    rework_ok=num(request.POST.get("rework_ok")) or 0,
                    defect=request.POST.get("defect", ""),
                )
                if e.checked > r["sewn"] - r["checked"]:
                    errors.append(
                        _("Only %(n)s sewn pieces of %(c)s / %(s)s are waiting for checking.")
                        % {"n": r["sewn"] - r["checked"], "c": colour, "s": size}
                    )
                if e.rework + e.reject > e.checked:
                    errors.append(_("Rework + reject can't be more than pieces checked."))
                if e.rework_ok > r["rework"] + e.rework:
                    errors.append(_("Only %(n)s pieces are in rework.") % {"n": r["rework"] + e.rework})
                if (e.rework or e.reject) and not e.defect:
                    errors.append(_("Choose the main defect for the rework and rejects."))
                if not errors and (e.checked or e.rework_ok):
                    stamp(e, request).save()
                    messages.success(
                        request,
                        _("Checked %(n)s pcs of %(c)s / %(s)s — %(p)s passed.")
                        % {"n": e.checked, "c": colour, "s": size, "p": e.passed},
                    )
                    return redirect(f"{request.path}?order={order.pk}")
        except ValueError:
            errors.append(_("Numbers only — no letters or negative values."))
    today = CheckingEntry.objects.filter(order=order).order_by("-date", "-hour", "-id")[:8]
    return render(
        request,
        "core/checking.html",
        {
            "order": order,
            "orders": Order.objects.all(),
            "rows": rows,
            "errors": errors,
            "recent": today,
            "defects": CHECK_DEFECTS,
            "hours": HOURS,
            "post": request.POST,
            "packed": PackingEntry.objects.filter(order=order).order_by("-date", "-id")[:6],
        },
    )


# ---------- dashboard ----------


@login_required
def dashboard(request):
    day = floor_day()
    entries = list(SewingEntry.objects.filter(date=day).select_related("line"))
    by_hour = defaultdict(lambda: [0, 0])
    by_line = defaultdict(lambda: [0, 0, []])
    for e in entries:
        by_hour[e.hour][0] += e.pieces
        by_hour[e.hour][1] += e.line.target_per_hour
        bl = by_line[e.line]
        bl[0] += e.pieces
        bl[1] += e.line.target_per_hour
        bl[2].append((e.hour, e.pieces / e.line.target_per_hour))
    peak = max([t for _p, t in by_hour.values()] + [1])
    hours = [
        {"hour": h, "done": d, "target": t, "pct": round(d / t * 100), "h": round(d / peak * 100), "t": round(t / peak * 100)}
        for h, (d, t) in sorted(by_hour.items())
    ]
    lines = sorted(
        ({"line": ln, "done": d, "target": t, "eff": round(d / t * 100)} for ln, (d, t, _x) in by_line.items()),
        key=lambda r: r["line"].name,
    )

    alerts = []
    for ln, (_d, _t, hrs) in by_line.items():
        last3 = [p for _h, p in sorted(hrs)[-3:]]
        if len(last3) == 3 and all(p < 0.8 for p in last3):
            alerts.append(("bad", _("%(l)s under 80%% of target for the last 3 hours") % {"l": ln.name}))
    pipeline = []
    for o in Order.objects.all():
        t = tracker(o)
        q = sum(r["qty"] for r in t)
        stages = [
            (_("Cut"), sum(r["cut"] for r in t)),
            (_("Sewn"), sum(r["sewn"] for r in t)),
            (_("Passed"), sum(r["passed"] for r in t)),
            (_("Packed"), sum(r["packed"] for r in t)),
        ]
        pipeline.append({"order": o, "qty": q, "stages": [(n, v, round(v / q * 100) if q else 0) for n, v in stages]})
        for r in fabric_window(o):
            if r["status"] == "late":
                alerts.append(
                    (
                        "warn",
                        _('%(o)s: %(c)s %(d)s" fabric lands after cut-start — %(kg)s kg late')
                        % {"o": o.order_no, "c": r["colour"], "d": r["dia"].table_dia.normalize(), "kg": f"{r['gap']:.0f}"},
                    )
                )
            elif r["status"] == "short":
                alerts.append(
                    (
                        "bad",
                        _('%(o)s: %(c)s %(d)s" fabric short — %(kg)s kg still to book')
                        % {"o": o.order_no, "c": r["colour"], "d": r["dia"].table_dia.normalize(), "kg": f"{r['gap']:.0f}"},
                    )
                )
    short_lines = [l for po in TrimPO.objects.prefetch_related("lines__receipts") for l in po.lines.all() if l.short]
    late_pos = [po for po in TrimPO.objects.prefetch_related("lines__receipts") if po.status == "overdue"]
    for po in late_pos:
        alerts.append(("warn", _("Trims PO %(po)s from %(s)s is overdue") % {"po": po.po_no, "s": po.supplier}))
    red_cuts = [c for c in CutLot.objects.prefetch_related("rolls", "sizes") if c.consumption_status == "bad"]
    for c in red_cuts:
        alerts.append(
            ("warn", _("Cut lot %(c)s used %(p)s%% more fabric than costed") % {"c": c.cut_no, "p": f"{c.consumption_pct:.1f}"})
        )

    chk = CheckingEntry.objects.filter(date=day)
    checked = chk.aggregate(s=Sum("checked"))["s"] or 0
    faults = defaultdict(int)
    for e in chk:
        if e.defect:
            faults[e.get_defect_display()] += e.rework + e.reject
    defects = sorted(faults.items(), key=lambda x: -x[1])[:5]
    top = max([n for _d, n in defects] + [1])
    bad = sum(n for _d, n in faults.items())
    return render(
        request,
        "core/dashboard.html",
        {
            "day": day,
            "hours": hours,
            "lines": lines,
            "pipeline": pipeline,
            "alerts": alerts,
            "defects": [(d, n, round(n / top * 100)) for d, n in defects],
            "defect_rate": round(bad / checked * 100, 1) if checked else 0,
            "trims_short": len(short_lines),
            "total": sum(h["done"] for h in hours),
            "target": sum(h["target"] for h in hours),
        },
    )
