import math
from datetime import timedelta
from decimal import Decimal as D

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import (
    Amendment,
    Buyer,
    CheckingEntry,
    Costing,
    CutLot,
    CutSize,
    DiaLine,
    FabricLot,
    Line,
    LotStageUpdate,
    Order,
    OrderLine,
    PackingEntry,
    Party,
    RollLaid,
    SewingEntry,
    TrimLine,
    TrimPO,
    TrimPOLine,
    TrimReceipt,
)
from core.permissions import ADMIN, CUTTING, DATA_ENTRY, FABRIC, SUPERVISOR


class Command(BaseCommand):
    help = "Load demo users and one realistic order (dates relative to today) for the client demo."

    @transaction.atomic
    def handle(self, *args, **opts):
        if not settings.DEMO_MODE:
            raise CommandError("seed_demo creates users with known passwords; run it only with SYOS_DEMO=1 or DJANGO_DEBUG=1")
        if not Order.objects.exists():
            self.seed_orders()
        if not Line.objects.exists():
            self.seed_floor()
        self.stdout.write(
            self.style.SUCCESS("Demo loaded. Logins: admin/admin123, entry/entry123, fabric/fabric123, cutting/cutting123")
        )

    def seed_orders(self):
        today = timezone.localdate()
        day = lambda n: today + timedelta(days=n)

        for g in (ADMIN, DATA_ENTRY, FABRIC, CUTTING, SUPERVISOR):
            Group.objects.get_or_create(name=g)
        users = {}
        for username, pw, first, group in [
            ("admin", "admin123", "Abhi", None),
            ("entry", "entry123", "Meena", DATA_ENTRY),
            ("fabric", "fabric123", "Ravi", FABRIC),
            ("cutting", "cutting123", "Selvam", CUTTING),
            ("supervisor", "super123", "Ramesh", SUPERVISOR),
        ]:
            u = User.objects.create_user(
                username, password=pw, first_name=first, is_superuser=group is None, is_staff=group is None
            )
            if group:
                u.groups.add(Group.objects.get(name=group))
            users[username] = u
        me, fab = users["entry"], users["fabric"]

        buyer = Buyer.objects.create(name="Nordwear GmbH", country="Germany", created_by=users["admin"])
        P = lambda name, kind, **kw: Party.objects.create(name=name, kind=kind, created_by=users["admin"], **kw)
        mill = P("Lakshmi Yarns", "mill", phone="+91 98430 11223")
        knit = P("Sri Murugan Knits", "knit", phone="+91 94431 55678")
        P("SY Knitting (own unit)", "knit", in_house=True)
        dyer = P("Kongu Processors", "dye", phone="+91 99940 22345")
        compact = P("Noyyal Compacting", "compact", phone="+91 90030 66789")
        labels = P("Tiruppur Labels & Tags", "trims", phone="+91 98422 33441")
        annai = P("Annai Trims", "trims", phone="+91 97900 44112")
        pack = P("Velan Packaging", "trims", phone="+91 93603 77812")

        # ---- order 1: two colours, five sizes, one late lot and one short dia line ----
        o = Order.objects.create(
            order_no="SY-2611",
            buyer=buyer,
            buyer_po="NW-PO-88412",
            style="NW-TS-204",
            garment_type="Crew neck T-shirt",
            fabric_quality="100% cotton single jersey 30s combed",
            target_gsm=180,
            cut_start=day(6),
            delivery=day(48),
            created_by=me,
        )
        kg = {"S": "0.165", "M": "0.180", "L": "0.195", "XL": "0.212", "XXL": "0.230"}
        qty = {"Navy": [300, 600, 700, 500, 200], "White": [200, 500, 600, 400, 150]}
        for colour, qs in qty.items():
            for size, q in zip(o.size_list, qs):
                OrderLine.objects.create(order=o, colour=colour, size=size, qty=q, costed_kg=D(kg[size]), created_by=me)
        Amendment.objects.create(
            order=o,
            reason="Buyer revised PO (rev. 2) on 24 Oct",
            change="Navy / M: 550 → 600\nNavy / L: 650 → 700",
            created_by=me,
        )
        d1 = DiaLine.objects.create(order=o, sizes="S,M", knit_dia=30, gauge=24, table_dia=34, created_by=me)
        d2 = DiaLine.objects.create(order=o, sizes="L,XL,XXL", knit_dia=34, gauge=24, table_dia=38, created_by=me)
        for item, unit, per, w, sw, sup in [
            ("Main label", "pcs", 1, 2, False, labels),
            ("Size label", "pcs", 1, 2, True, labels),
            ("Care label", "pcs", 1, 2, False, labels),
            ("Hang tag", "pcs", 1, 3, False, labels),
            ("Sewing thread", "cones", "0.012", 5, False, annai),
            ("Polybag", "pcs", 1, 2, True, pack),
            ("Export carton", "pcs", "0.025", 1, False, pack),
        ]:
            TrimLine.objects.create(
                order=o, item=item, unit=unit, per_piece=D(str(per)), wastage_pct=w, size_wise=sw, supplier=sup, created_by=me
            )
        Costing.objects.create(
            order=o,
            yarn_per_kg=290,
            knitting_per_kg=22,
            dyeing_per_kg=95,
            trims_per_pc=D("8.5"),
            cmt_per_pc=28,
            overhead_per_pc=12,
            quoted_usd=D("1.85"),
            agreed_usd=D("1.72"),
            exchange_rate=84,
            created_by=users["admin"],
        )

        def lot(no, colour, dia, planned, expected, path, washing=False):
            l = FabricLot.objects.create(
                lot_no=no,
                order=o,
                colour=colour,
                dia_line=dia,
                planned_kg=planned,
                expected_date=expected,
                uses_washing=washing,
                created_by=fab,
            )
            for stage, d, kgs, party, ref in path:
                LotStageUpdate.objects.create(lot=l, stage=stage, date=d, kg=kgs, party=party, reference=ref, created_by=fab)

        yarn = lambda n, kgs: [("yarn_ordered", day(-20), kgs, mill, f"YPO-{n}"), ("yarn_in", day(-15), kgs, mill, f"YL-{n}")]
        lot(
            "FL-24031",
            "Navy",
            d1,
            162,
            day(-3),
            yarn(731, 172)
            + [
                ("knitting", day(-12), 168, knit, 'M-04 · 30" 24G'),
                ("dyeing", day(-8), 164, dyer, "B-5521 Navy"),
                ("compacting", day(-5), 162, compact, '182 GSM · 34"'),
                ("in_house", day(-3), D("159.4"), None, "DC 1183"),
            ],
        )
        lot(
            "FL-24032",
            "Navy",
            d2,
            150,
            day(-2),
            yarn(732, 160)
            + [
                ("knitting", day(-11), 156, knit, 'M-07 · 34" 24G'),
                ("dyeing", day(-7), 152, dyer, "B-5530 Navy"),
                ("compacting", day(-4), 150, compact, '179 GSM · 38"'),
                ("in_house", day(-2), D("148.6"), None, "DC 1190"),
            ],
        )
        lot(
            "FL-24033",
            "Navy",
            d2,
            142,
            day(10),
            yarn(733, 152)
            + [("knitting", day(-6), 148, knit, 'M-07 · 34" 24G'), ("dyeing", day(-2), 145, dyer, "B-5547 Navy — shade re-dip")],
        )
        lot(
            "FL-24034",
            "White",
            d1,
            126,
            day(2),
            yarn(734, 134)
            + [
                ("knitting", day(-7), 131, knit, 'M-02 · 30" 24G'),
                ("dyeing", day(-4), 128, dyer, "B-5538 Optic white"),
                ("compacting", day(-1), 126, compact, ""),
            ],
        )
        lot("FL-24035", "White", d2, 200, day(3), yarn(735, 212) + [("knitting", day(-1), 206, knit, 'M-09 · 34" 24G')])

        # ---- order 2: small boxer order, all fabric in-house ----
        o2 = Order.objects.create(
            order_no="SY-2604",
            buyer=buyer,
            buyer_po="NW-PO-88377",
            style="NW-BX-031",
            garment_type="Knit boxer",
            fabric_quality="Cotton/elastane 95/5 jersey",
            target_gsm=200,
            sizes="S,M,L,XL",
            pieces_per_bundle=25,
            bundle_parts="Front,Back,Waistband",
            cut_start=day(2),
            delivery=day(30),
            created_by=me,
        )
        for size, q, k in zip(o2.size_list, [400, 800, 800, 400], ["0.105", "0.112", "0.120", "0.128"]):
            OrderLine.objects.create(order=o2, colour="Grey melange", size=size, qty=q, costed_kg=D(k), created_by=me)
        bd = DiaLine.objects.create(
            order=o2, sizes="S,M,L,XL", knit_dia=28, gauge=24, table_dia=30, width_type="open", created_by=me
        )
        l2 = FabricLot.objects.create(
            lot_no="FL-24019", order=o2, colour="Grey melange", dia_line=bd, planned_kg=280, expected_date=day(-6), created_by=fab
        )
        LotStageUpdate.objects.create(lot=l2, stage="in_house", date=day(-6), kg=D("281.5"), reference="DC 1171", created_by=fab)

    def seed_floor(self):
        """Trims POs, cut lots, a day of hourly sewing, checking and packing — so every floor screen has a story."""
        today = timezone.localdate()
        day = lambda n: today + timedelta(days=n)
        me = User.objects.get(username="entry")
        cutter = User.objects.get(username="cutting")
        o, o2 = Order.objects.get(order_no="SY-2611"), Order.objects.get(order_no="SY-2604")
        d1, d2 = o.dia_lines.order_by("id")
        bd = o2.dia_lines.first()

        # Trims: POs raised for SY-2611, partly received; SY-2604 left for the "Raise POs" button.
        by_size = {s: sum(l.qty for l in o.lines.filter(size=s)) for s in o.size_list}
        for n, supplier in enumerate(sorted({t.supplier for t in o.trims.all()}, key=lambda p: p.name), start=1):
            po = TrimPO.objects.create(
                po_no=f"TPO-{n:04d}", order=o, supplier=supplier, required_by=day(-1 if n == 2 else 4), created_by=me
            )
            for t in o.trims.filter(supplier=supplier):
                parts = list(by_size.items()) if t.size_wise else [("", o.total_qty)]
                for size, qty in parts:
                    line = TrimPOLine.objects.create(po=po, trim=t, size=size, qty=t.required(qty), created_by=me)
                    got = line.qty if n == 1 else (line.qty // 2 if n == 3 else 0)
                    if got:
                        TrimReceipt.objects.create(line=line, qty=got, challan=f"CH-{700 + n}", date=day(-2), created_by=me)

        if not o2.trims.exists():  # left un-ordered on purpose: the demo raises these POs live
            sup = {x.name: x for x in Party.objects.filter(kind="trims")}
            for item, unit, per, w, sw, name in [
                ("Main label", "pcs", "1", 2, False, "Tiruppur Labels & Tags"),
                ("Size label", "pcs", "1", 2, True, "Tiruppur Labels & Tags"),
                ("Waistband elastic", "m", "0.78", 3, True, "Annai Trims"),
                ("Polybag", "pcs", "1", 2, False, "Velan Packaging"),
            ]:
                TrimLine.objects.create(
                    order=o2,
                    item=item,
                    unit=unit,
                    per_piece=D(per),
                    wastage_pct=w,
                    size_wise=sw,
                    supplier=sup[name],
                    created_by=me,
                )

        # Cutting: three lays. CL-0402 carries the needle-line roll flagged back to knitting.
        def cut(no, order, colour, dia, when, rolls, sizes):
            c = CutLot.objects.create(cut_no=no, order=order, colour=colour, dia_line=dia, date=when, created_by=cutter)
            lot = FabricLot.objects.get(order=order, colour=colour, dia_line=dia, updates__stage="in_house")
            for roll_no, kg, gsm, width, defect, level, rej, ret in rolls:
                RollLaid.objects.create(
                    cut_lot=c,
                    fabric_lot=lot,
                    roll_no=roll_no,
                    kg=D(str(kg)),
                    gsm=gsm,
                    width=D(str(width)),
                    defect=defect,
                    level=level,
                    kg_rejected=D(str(rej)),
                    kg_returned=D(str(ret)),
                    created_by=cutter,
                )
            start = (max([s.bundle_to for s in CutSize.objects.filter(cut_lot__order=order)] or [0])) + 1
            for size, pcs in sizes:
                n = math.ceil(pcs / order.pieces_per_bundle)
                CutSize.objects.create(
                    cut_lot=c, size=size, pieces=pcs, bundle_from=start, bundle_to=start + n - 1, created_by=cutter
                )
                start += n

        # Every stage fits inside the one before it: order ≥ cut ≥ sewn ≥ checked ≥ passed ≥ packed.
        cut(
            "CL-0401",
            o,
            "Navy",
            d1,
            day(-3),
            [
                (f"R-{101 + i}", kg, 180 + i % 3, 34.0, "", "", 0, 0.1)
                for i, kg in enumerate([22.8, 22.6, 23.0, 22.7, 22.9, 22.5, 22.8])
            ],
            [("S", 300), ("M", 600)],
        )
        cut(
            "CL-0402",
            o,
            "Navy",
            d2,
            day(-2),
            [
                ("R-201", 23.6, 182, 38.0, "", "", 0, 0.2),
                ("R-202", 23.4, 179, 38.0, "", "", 0, 0.2),
                ("R-203", 23.9, 166, 37.4, "holes", "major", 1.2, 0.3),
                ("R-204", 23.5, 184, 38.0, "", "", 0, 0.2),
                ("R-205", 23.7, 181, 38.0, "", "", 0, 0.1),
                ("R-206", 23.7, 180, 38.0, "", "", 0, 0.2),
            ],
            [("L", 700)],
        )
        cut(
            "CL-0403",
            o2,
            "Grey melange",
            bd,
            day(-4),
            [
                (
                    f"R-{301 + i}",
                    kg,
                    200 + i % 4 - 1,
                    30.0,
                    "shade" if i == 2 else "",
                    "minor" if i == 2 else "",
                    0.6 if i == 2 else 0,
                    0.2,
                )
                for i, kg in enumerate([21.2, 21.4, 21.0, 21.3, 21.1, 21.5, 21.3])
            ],
            [("S", 400), ("M", 500), ("L", 400)],
        )

        # Line plan and today's hourly sewing (9:00–15:00). L3 slips under 80% for the last three hours.
        plan = [
            ("L1", o, "Navy", "M", 40),
            ("L2", o, "Navy", "M", 40),
            ("L3", o, "Navy", "L", 35),
            ("L4", o, "Navy", "L", 45),
            ("L5", o2, "Grey melange", "M", 40),
            ("L6", o2, "Grey melange", "L", 35),
        ]
        out = {
            "L1": [36, 38, 39, 31, 38, 40, 37],
            "L2": [34, 38, 41, 30, 39, 40, 41],
            "L3": [30, 32, 30, 27, 25, 26, 24],
            "L4": [40, 43, 44, 36, 44, 45, 43],
            "L5": [33, 35, 37, 29, 34, 33, 36],
            "L6": [32, 34, 35, 30, 35, 34, 35],
        }
        for name, order, colour, size, target in plan:
            ln = Line.objects.create(
                name=name, operators=22, order=order, colour=colour, size=size, target_per_hour=target, created_by=me
            )
            for hour, pcs in zip(range(9, 16), out[name]):
                SewingEntry.objects.create(
                    date=today, hour=hour, line=ln, order=order, colour=colour, size=size, pieces=pcs, created_by=me
                )
        # Yesterday: L1 finished Navy S and L5 Grey S, so checking and packing have pieces to work on.
        SewingEntry.objects.bulk_create(
            [
                SewingEntry(
                    date=day(-1), hour=h, line=Line.objects.get(name=n), order=order, colour=c, size=sz, pieces=p, created_by=me
                )
                for n, order, c, sz, p in [("L1", o, "Navy", "S", 30), ("L5", o2, "Grey melange", "S", 34)]
                for h in range(9, 18)
            ]
        )

        checks = [
            (9, o, "Navy", "M", 70, 4, 1, 0, "open_seam"),
            (10, o, "Navy", "M", 75, 5, 0, 3, "skip_stitch"),
            (11, o, "Navy", "S", 80, 3, 1, 2, "open_seam"),
            (12, o, "Navy", "L", 60, 6, 2, 0, "oil_stain"),
            (13, o, "Navy", "S", 90, 2, 0, 3, "measurement"),
            (10, o2, "Grey melange", "M", 85, 3, 1, 0, "shade"),
            (12, o2, "Grey melange", "S", 120, 4, 0, 2, "open_seam"),
        ]
        for hour, order, colour, size, chk, rw, rj, ok, defect in checks:
            CheckingEntry.objects.create(
                date=today,
                hour=hour,
                order=order,
                colour=colour,
                size=size,
                checked=chk,
                rework=rw,
                reject=rj,
                rework_ok=ok,
                defect=defect,
                created_by=me,
            )
        for order, colour, size, pcs, cartons in [
            (o, "Navy", "S", 72, "C-101–C-103"),
            (o, "Navy", "M", 96, "C-104–C-107"),
            (o2, "Grey melange", "S", 100, "C-201–C-204"),
        ]:
            PackingEntry.objects.create(
                date=today, order=order, colour=colour, size=size, pieces=pcs, cartons=cartons, created_by=me
            )
