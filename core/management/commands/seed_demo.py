from datetime import timedelta
from decimal import Decimal as D

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import Amendment, Buyer, Costing, DiaLine, FabricLot, LotStageUpdate, Order, OrderLine, Party, TrimLine
from core.views import ADMIN, CUTTING, DATA_ENTRY, FABRIC, SUPERVISOR


class Command(BaseCommand):
    help = "Load demo users and one realistic order (dates relative to today) for the client demo."

    @transaction.atomic
    def handle(self, *args, **opts):
        if Order.objects.exists():
            self.stdout.write("Demo data already loaded.")
            return
        today = timezone.localdate()
        day = lambda n: today + timedelta(days=n)

        for g in (ADMIN, DATA_ENTRY, FABRIC, CUTTING, SUPERVISOR):
            Group.objects.get_or_create(name=g)
        users = {}
        for username, pw, first, group in [
            ("admin", "admin123", "Abhi", None), ("entry", "entry123", "Meena", DATA_ENTRY),
            ("fabric", "fabric123", "Ravi", FABRIC), ("cutting", "cutting123", "Selvam", CUTTING),
            ("supervisor", "super123", "Ramesh", SUPERVISOR),
        ]:
            u = User.objects.create_user(username, password=pw, first_name=first, is_superuser=group is None, is_staff=group is None)
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
            order_no="SY-2611", buyer=buyer, buyer_po="NW-PO-88412", style="NW-TS-204", garment_type="Crew neck T-shirt",
            fabric_quality="100% cotton single jersey 30s combed", target_gsm=180, cut_start=day(6), delivery=day(48), created_by=me,
        )
        kg = {"S": "0.165", "M": "0.180", "L": "0.195", "XL": "0.212", "XXL": "0.230"}
        qty = {"Navy": [300, 600, 700, 500, 200], "White": [200, 500, 600, 400, 150]}
        for colour, qs in qty.items():
            for size, q in zip(o.size_list, qs):
                OrderLine.objects.create(order=o, colour=colour, size=size, qty=q, costed_kg=D(kg[size]), created_by=me)
        Amendment.objects.create(order=o, reason="Buyer revised PO (rev. 2) on 24 Oct", change="Navy / M: 550 → 600\nNavy / L: 650 → 700", created_by=me)
        d1 = DiaLine.objects.create(order=o, sizes="S,M", knit_dia=30, gauge=24, table_dia=34, created_by=me)
        d2 = DiaLine.objects.create(order=o, sizes="L,XL,XXL", knit_dia=34, gauge=24, table_dia=38, created_by=me)
        for item, unit, per, w, sw, sup in [
            ("Main label", "pcs", 1, 2, False, labels), ("Size label", "pcs", 1, 2, True, labels),
            ("Care label", "pcs", 1, 2, False, labels), ("Hang tag", "pcs", 1, 3, False, labels),
            ("Sewing thread", "cones", "0.012", 5, False, annai), ("Polybag", "pcs", 1, 2, True, pack),
            ("Export carton", "pcs", "0.025", 1, False, pack),
        ]:
            TrimLine.objects.create(order=o, item=item, unit=unit, per_piece=D(str(per)), wastage_pct=w, size_wise=sw, supplier=sup, created_by=me)
        Costing.objects.create(
            order=o, yarn_per_kg=290, knitting_per_kg=22, dyeing_per_kg=95, trims_per_pc=D("8.5"), cmt_per_pc=28,
            overhead_per_pc=12, quoted_usd=D("1.85"), agreed_usd=D("1.72"), exchange_rate=84, created_by=users["admin"],
        )

        def lot(no, colour, dia, planned, expected, path, washing=False):
            l = FabricLot.objects.create(lot_no=no, order=o, colour=colour, dia_line=dia, planned_kg=planned, expected_date=expected, uses_washing=washing, created_by=fab)
            for stage, d, kgs, party, ref in path:
                LotStageUpdate.objects.create(lot=l, stage=stage, date=d, kg=kgs, party=party, reference=ref, created_by=fab)

        yarn = lambda n, kgs: [("yarn_ordered", day(-20), kgs, mill, f"YPO-{n}"), ("yarn_in", day(-15), kgs, mill, f"YL-{n}")]
        lot("FL-24031", "Navy", d1, 162, day(-3), yarn(731, 172) + [
            ("knitting", day(-12), 168, knit, "M-04 · 30\" 24G"), ("dyeing", day(-8), 164, dyer, "B-5521 Navy"),
            ("compacting", day(-5), 162, compact, "182 GSM · 34\""), ("in_house", day(-3), D("159.4"), None, "DC 1183")])
        lot("FL-24032", "Navy", d2, 150, day(-2), yarn(732, 160) + [
            ("knitting", day(-11), 156, knit, "M-07 · 34\" 24G"), ("dyeing", day(-7), 152, dyer, "B-5530 Navy"),
            ("compacting", day(-4), 150, compact, "179 GSM · 38\""), ("in_house", day(-2), D("148.6"), None, "DC 1190")])
        lot("FL-24033", "Navy", d2, 142, day(10), yarn(733, 152) + [
            ("knitting", day(-6), 148, knit, "M-07 · 34\" 24G"), ("dyeing", day(-2), 145, dyer, "B-5547 Navy — shade re-dip")])
        lot("FL-24034", "White", d1, 126, day(2), yarn(734, 134) + [
            ("knitting", day(-7), 131, knit, "M-02 · 30\" 24G"), ("dyeing", day(-4), 128, dyer, "B-5538 Optic white"),
            ("compacting", day(-1), 126, compact, "")])
        lot("FL-24035", "White", d2, 200, day(3), yarn(735, 212) + [("knitting", day(-1), 206, knit, "M-09 · 34\" 24G")])

        # ---- order 2: small boxer order, all fabric in-house ----
        o2 = Order.objects.create(
            order_no="SY-2604", buyer=buyer, buyer_po="NW-PO-88377", style="NW-BX-031", garment_type="Knit boxer",
            fabric_quality="Cotton/elastane 95/5 jersey", target_gsm=200, sizes="S,M,L,XL", pieces_per_bundle=25,
            bundle_parts="Front,Back,Waistband", cut_start=day(2), delivery=day(30), created_by=me,
        )
        for size, q, k in zip(o2.size_list, [400, 800, 800, 400], ["0.105", "0.112", "0.120", "0.128"]):
            OrderLine.objects.create(order=o2, colour="Grey melange", size=size, qty=q, costed_kg=D(k), created_by=me)
        bd = DiaLine.objects.create(order=o2, sizes="S,M,L,XL", knit_dia=28, gauge=24, table_dia=30, width_type="open", created_by=me)
        l2 = FabricLot.objects.create(lot_no="FL-24019", order=o2, colour="Grey melange", dia_line=bd, planned_kg=280, expected_date=day(-6), created_by=fab)
        LotStageUpdate.objects.create(lot=l2, stage="in_house", date=day(-6), kg=D("281.5"), reference="DC 1171", created_by=fab)

        self.stdout.write(self.style.SUCCESS("Demo loaded. Logins: admin/admin123, entry/entry123, fabric/fabric123"))
