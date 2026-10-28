"""Milestone 1 screens: orders list, master order sheet, quantities, dia program & trims, costing, repeats, fabric planning."""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from ..forms import CostingForm, DiaFormSet, LotForm, OrderForm, RepeatForm, StageForm, TrimFormSet
from ..models import (
    STAGES,
    Amendment,
    Costing,
    DiaLine,
    FabricLot,
    Order,
    OrderLine,
    TrimLine,
    fabric_window,
    tracker,
)
from ..permissions import ADMIN, DATA_ENTRY, FABRIC, role, roles, stamp

# ---------- pages ----------

STATUS_RANK = {"on_track": 0, "late": 1, "short": 2}


@login_required
def home(request):
    orders = []
    for o in Order.objects.select_related("buyer"):
        rows = fabric_window(o)
        worst = max((r["status"] for r in rows), key=STATUS_RANK.get, default="")
        orders.append((o, worst, sum((r["gap"] for r in rows), Decimal(0))))
    return render(request, "core/home.html", {"orders": orders, "followups": followup_list(), "today": timezone.localdate()})


@roles(DATA_ENTRY)
def order_new(request):
    form = OrderForm(request.POST or None)
    if form.is_valid():
        with transaction.atomic():
            order = stamp(form.save(commit=False), request)
            order.save()
            for colour in [c.strip() for c in form.cleaned_data["colours"].split(",") if c.strip()]:
                for size in order.size_list:
                    stamp(OrderLine(order=order, colour=colour, size=size), request).save()
        messages.success(request, _("Order created. Enter quantities and consumption."))
        return redirect("order_grid", order.pk)
    return render(request, "core/form.html", {"form": form, "title": _("New order")})


@login_required
def order_detail(request, pk):
    order = get_object_or_404(Order.objects.select_related("buyer", "repeat_of"), pk=pk)
    sizes, lines = order.size_list, list(order.lines.all())
    qty = {(l.colour, l.size): l.qty for l in lines}
    kg = {l.size: l.costed_kg for l in lines}
    grid = [(c, [qty.get((c, s), 0) for s in sizes], sum(qty.get((c, s), 0) for s in sizes)) for c in order.colours]
    size_totals = [sum(qty.get((c, s), 0) for c in order.colours) for s in sizes]
    bundles = [order.bundles_for(t) for t in size_totals]
    return render(
        request,
        "core/order_detail.html",
        {
            "order": order,
            "sizes": sizes,
            "grid": grid,
            "size_totals": size_totals,
            "total": sum(size_totals),
            "kg": [kg.get(s, 0) for s in sizes],
            "bundles": bundles,
            "tickets": sum(bundles) * len(order.part_list),
            "trims": [(t, t.required(order.total_qty)) for t in order.trims.select_related("supplier")],
            "window": fabric_window(order),
            "tracker": tracker(order),
        },
    )


@roles(DATA_ENTRY)
def order_grid(request, pk):
    order = get_object_or_404(Order, pk=pk)
    sizes = order.size_list
    lines = {(l.colour, l.size): l for l in order.lines.all()}
    errors = []
    if request.method == "POST":
        colours = order.colours
        new_colour = request.POST.get("new_colour", "").strip()
        if new_colour and new_colour not in colours:
            colours.append(new_colour)
        changes, updated = [], []
        had_qty = any(l.qty for l in lines.values())
        try:
            for si, size in enumerate(sizes):
                kg = Decimal(request.POST.get(f"kg-{si}") or 0)
                for ci, colour in enumerate(colours):
                    q = int(request.POST.get(f"qty-{ci}-{si}") or 0)
                    if q < 0 or kg < 0:
                        raise ValueError
                    line = lines.get((colour, size)) or OrderLine(order=order, colour=colour, size=size)
                    if line.pk and line.qty != q:
                        changes.append(f"{colour} / {size}: {line.qty} → {q}")
                    elif not line.pk and q:
                        changes.append(f"{colour} / {size}: {_('new')} → {q}")
                    if line.pk and line.costed_kg != kg and ci == 0:
                        changes.append(f"{size} kg/pc: {line.costed_kg} → {kg}")
                    line.qty, line.costed_kg = q, kg
                    updated.append(stamp(line, request))
        except (ValueError, InvalidOperation):
            errors.append(_("Quantities must be whole numbers and kg must be a number, neither negative."))
        reason = request.POST.get("reason", "").strip()
        if had_qty and changes and not reason:
            errors.append(_("This order already has quantities. Give a reason for the amendment."))
        if not errors:
            with transaction.atomic():
                for line in updated:
                    line.save()
                if had_qty and changes:
                    stamp(Amendment(order=order, reason=reason, change="\n".join(changes)), request).save()
            messages.success(request, _("Saved. Fabric and trims requirements recalculated."))
            return redirect("order_detail", pk)
    qty = {k: l.qty for k, l in lines.items()}
    kg = {l.size: l.costed_kg for l in lines.values()}
    rows = [(ci, c, [(si, qty.get((c, s), 0)) for si, s in enumerate(sizes)]) for ci, c in enumerate(order.colours)]
    return render(
        request,
        "core/order_grid.html",
        {
            "order": order,
            "sizes": list(enumerate(sizes)),
            "rows": rows,
            "kg": [(si, kg.get(s, "")) for si, s in enumerate(sizes)],
            "errors": errors,
            "has_qty": any(qty.values()),
        },
    )


@roles(DATA_ENTRY)
def order_setup(request, pk):
    order = get_object_or_404(Order, pk=pk)
    dia = DiaFormSet(request.POST or None, instance=order, prefix="dia")
    trims = TrimFormSet(request.POST or None, instance=order, prefix="trim")
    if request.method == "POST" and dia.is_valid() and trims.is_valid():
        with transaction.atomic():
            for fs in (dia, trims):
                for obj in fs.save(commit=False):
                    stamp(obj, request).save()
        messages.success(request, _("Dia program and trims saved."))
        return redirect("order_detail", pk)
    return render(request, "core/order_setup.html", {"order": order, "dia": dia, "trims": trims})


@roles()
def costing(request, pk):
    order = get_object_or_404(Order, pk=pk)
    obj = Costing.objects.filter(order=order).first() or Costing(order=order)
    form = CostingForm(request.POST or None, instance=obj)
    if form.is_valid():
        stamp(form.save(commit=False), request).save()
        messages.success(request, _("Costing saved."))
        return redirect("costing", pk)
    c = obj if obj.pk else None
    return render(
        request,
        "core/costing.html",
        {
            "order": order,
            "form": form,
            "c": c,
            "quoted_margin": c and c.margin(c.quoted_usd),
            "agreed_margin": c and c.margin(c.agreed_usd),
        },
    )


@roles(DATA_ENTRY)
def order_repeat(request, pk):
    src = get_object_or_404(Order, pk=pk)
    form = RepeatForm(request.POST or None, initial={"buyer_po": src.buyer_po})
    if form.is_valid():
        with transaction.atomic():
            new = stamp(form.save(commit=False), request)
            for f in (
                "buyer",
                "style",
                "garment_type",
                "fabric_quality",
                "target_gsm",
                "sizes",
                "pieces_per_bundle",
                "bundle_parts",
            ):
                setattr(new, f, getattr(src, f))
            new.repeat_of = src
            new.save()
            for l in src.lines.all():
                stamp(OrderLine(order=new, colour=l.colour, size=l.size, qty=0, costed_kg=l.costed_kg), request).save()
            for d in src.dia_lines.all():
                stamp(
                    DiaLine(
                        order=new,
                        sizes=d.sizes,
                        knit_dia=d.knit_dia,
                        gauge=d.gauge,
                        table_dia=d.table_dia,
                        width_type=d.width_type,
                    ),
                    request,
                ).save()
            for t in src.trims.all():
                stamp(
                    TrimLine(
                        order=new,
                        item=t.item,
                        unit=t.unit,
                        per_piece=t.per_piece,
                        wastage_pct=t.wastage_pct,
                        size_wise=t.size_wise,
                        supplier=t.supplier,
                    ),
                    request,
                ).save()
        messages.success(
            request,
            _("Repeat created from %(src)s: consumption, dia program, bundles and trims copied. Enter the new quantities.")
            % {"src": src.order_no},
        )
        return redirect("order_grid", new.pk)
    return render(request, "core/form.html", {"form": form, "title": _("Repeat order from %(src)s") % {"src": src}})


# ---------- fabric ----------


def inward_chart(order, rows, today):
    """Cumulative kg in-house / expected over time vs total need, as SVG coordinates."""
    events = []
    for r in rows:
        for lot in r["lots"]:
            if lot.stage == "in_house":
                events.append((lot.updates.filter(stage="in_house").last().date, lot.in_house_kg))
            else:
                events.append((lot.expected_date, lot.planned_kg))
    need = sum((r["need"] for r in rows), Decimal(0))
    if not events or not need:
        return None
    events.sort()
    start = min(events[0][0], today) - timedelta(days=2)
    end = max(events[-1][0], order.cut_start) + timedelta(days=3)
    days = (end - start).days or 1
    top = float(max(need, sum(kg for _d, kg in events))) * 1.1
    W, H = 640, 200
    x = lambda d: round((d - start).days / days * W, 1)
    y = lambda kg: round(H - float(kg) / top * H, 1)
    pts, total = [f"0,{H}"], Decimal(0)
    for d, kg in events:
        pts.append(f"{x(d)},{y(total)}")
        total += kg
        pts.append(f"{x(d)},{y(total)}")
    pts.append(f"{W},{y(total)}")
    return {
        "w": W,
        "h": H,
        "points": " ".join(pts),
        "need_y": y(need),
        "need": need,
        "cut_x": x(order.cut_start),
        "today_x": x(today),
        "start": start,
        "end": end,
    }


@login_required
def fabric(request, pk):
    order = get_object_or_404(Order, pk=pk)
    can_edit = role(request.user) in (ADMIN, FABRIC)
    lot_form = LotForm(order, prefix="lot")
    stage_form = StageForm(order, prefix="st", initial={"date": timezone.localdate()})
    if request.method == "POST":
        if not can_edit:
            raise PermissionDenied
        if "add_lot" in request.POST:
            lot_form = LotForm(order, request.POST, prefix="lot")
            if lot_form.is_valid():
                lot = stamp(lot_form.save(commit=False), request)
                lot.order = order
                lot.save()
                messages.success(request, _("Lot added."))
                return redirect("fabric", pk)
        else:
            stage_form = StageForm(order, request.POST, prefix="st")
            if stage_form.is_valid():
                stamp(stage_form.save(commit=False), request).save()
                messages.success(request, _("Stage updated."))
                return redirect("fabric", pk)
    today = timezone.localdate()
    rows = fabric_window(order)
    return render(
        request,
        "core/fabric.html",
        {
            "order": order,
            "rows": rows,
            "chart": inward_chart(order, rows, today),
            "stages": STAGES,
            "lot_form": lot_form,
            "stage_form": stage_form,
            "can_edit": can_edit,
            "followups": followup_list(order),
            "today": today,
        },
    )


def followup_list(order=None):
    """Lots due within 3 days or overdue, grouped by the party holding them, with a ready message."""
    today = timezone.localdate()
    lots = FabricLot.objects.select_related("order", "dia_line").filter(expected_date__lte=today + timedelta(days=3))
    if order:
        lots = lots.filter(order=order)
    by_party = defaultdict(list)
    for lot in lots:
        last = lot.last_update
        if last and last.stage == "in_house":
            continue
        by_party[last.party if last and last.party else None].append((lot, last))
    out = []
    for party, items in by_party.items():
        body = [_("Hello %(name)s,") % {"name": party.name if party else _("team")}, _("Please confirm dispatch for:")]
        for lot, _last in items:
            when = (
                _("overdue since %(d)s") % {"d": lot.expected_date.strftime("%d %b")}
                if lot.expected_date < today
                else _("due %(d)s") % {"d": lot.expected_date.strftime("%d %b")}
            )
            body.append(
                f'• {lot.order.order_no} · {_("lot")} {lot.lot_no} · {lot.colour} · {lot.dia_line.table_dia.normalize()}" · {lot.planned_kg:.0f} kg · {when}'
            )
        body.append(_("Thank you — SY Exports"))
        out.append({"party": party, "items": items, "message": "\n".join(body)})
    return out
