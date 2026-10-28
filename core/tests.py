from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from .models import Amendment, CutLot, CutSize, FabricLot, Order, TrimPO, fabric_window, tracker


class Milestone1Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def setUp(self):
        self.order = Order.objects.get(order_no="SY-2611")

    def window(self):
        return {(r["colour"], r["dia"].sizes): r for r in fabric_window(self.order)}

    def test_fabric_window_states_and_gaps(self):
        w = self.window()
        self.assertEqual(w["Navy", "S,M"]["status"], "on_track")
        # need 288.5 kg; 148.6 in-house; 142 kg lot lands after cut-start
        self.assertEqual(w["Navy", "L,XL,XXL"]["status"], "late")
        self.assertEqual(w["Navy", "L,XL,XXL"]["gap"], Decimal("139.9"))
        self.assertEqual(w["White", "S,M"]["status"], "on_track")
        # need 236.3 kg, only 200 kg booked
        self.assertEqual(w["White", "L,XL,XXL"]["status"], "short")
        self.assertEqual(w["White", "L,XL,XXL"]["gap"], Decimal("36.3"))

    def test_costing_hidden_from_data_entry(self):
        self.client.login(username="entry", password="entry123")
        self.assertEqual(self.client.get(f"/orders/{self.order.pk}/costing/").status_code, 403)
        page = self.client.get(f"/orders/{self.order.pk}/").content.decode()
        self.assertNotIn("/costing/", page)
        self.assertNotIn("1.72", page)

    def test_admin_sees_margin(self):
        self.client.login(username="admin", password="admin123")
        self.assertContains(self.client.get(f"/orders/{self.order.pk}/costing/"), "margin")

    def test_amendment_needs_reason_and_is_logged(self):
        self.client.login(username="entry", password="entry123")
        url = f"/orders/{self.order.pk}/grid/"
        data = {f"qty-{ci}-{si}": "100" for ci in range(2) for si in range(5)} | {f"kg-{si}": "0.2" for si in range(5)}
        self.assertContains(self.client.post(url, data), "Give a reason")
        self.client.post(url, data | {"reason": "Buyer rev. 3"})
        self.assertEqual(Amendment.objects.filter(order=self.order, reason="Buyer rev. 3").count(), 1)
        self.assertEqual(self.order.total_qty, 1000)

    def test_consumption_change_is_an_amendment(self):
        self.client.login(username="entry", password="entry123")
        lines = {(l.colour, l.size): l.qty for l in self.order.lines.all()}
        data = {
            f"qty-{ci}-{si}": lines[c, s] for ci, c in enumerate(self.order.colours) for si, s in enumerate(self.order.size_list)
        }
        data |= {"kg-0": "0.170", "kg-1": "0.180", "kg-2": "0.195", "kg-3": "0.212", "kg-4": "0.230"}
        self.assertContains(self.client.post(f"/orders/{self.order.pk}/grid/", data), "Give a reason")
        self.client.post(f"/orders/{self.order.pk}/grid/", data | {"reason": "Marker re-done"})
        self.assertIn("S kg/pc", Amendment.objects.get(reason="Marker re-done").change)

    def test_trim_requirement_rounds_up_with_wastage(self):
        thread = self.order.trims.get(item="Sewing thread")
        self.assertEqual(thread.required(4150), 53)  # 4150 × 0.012 × 1.05 = 52.29

    def test_fabric_in_charge_cannot_edit_orders(self):
        self.client.login(username="fabric", password="fabric123")
        self.assertEqual(self.client.get(f"/orders/{self.order.pk}/grid/").status_code, 403)
        self.assertEqual(self.client.get(f"/orders/{self.order.pk}/fabric/").status_code, 200)


class FloorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def setUp(self):
        self.order = Order.objects.get(order_no="SY-2611")
        self.client.login(username="entry", password="entry123")

    def cut_post(self, lot, dia, kg="21.0", pcs=110, order=None, colour="Navy"):
        order = order or self.order
        return self.client.post(
            "/cutting/new/",
            {
                "order": order.pk,
                "colour": colour,
                "dia": dia.pk,
                "cut_no": f"CL-T{lot.pk}{pcs}{kg}",
                "date": "2026-10-28",
                "r0-lot": lot.pk,
                "r0-roll": "R-9",
                "r0-kg": kg,
                "r0-gsm": str(order.target_gsm),
                "r0-width": str(dia.table_dia),
                "r0-ret": "0",
                f"pcs-{dia.size_list[0]}": pcs,
            },
        )

    def test_wrong_dia_roll_is_blocked(self):
        d1, d2 = self.order.dia_lines.order_by("id")
        lot_d2 = FabricLot.objects.get(lot_no="FL-24032")
        self.assertContains(self.cut_post(lot_d2, d1), "Blocked")
        self.assertFalse(CutLot.objects.filter(cut_no__startswith="CL-T").exists())

    def test_lot_cannot_go_below_zero(self):
        d1 = self.order.dia_lines.order_by("id").first()
        self.assertContains(self.cut_post(FabricLot.objects.get(lot_no="FL-24031"), d1, kg="5.0", pcs=30), "in hand")

    def test_consumption_beyond_ten_percent_is_blocked_and_bundles_never_overlap(self):
        o2 = Order.objects.get(order_no="SY-2604")
        dia, lot = o2.dia_lines.first(), FabricLot.objects.get(lot_no="FL-24019")
        self.assertContains(self.cut_post(lot, dia, kg="30.0", pcs=100, order=o2, colour="Grey melange"), "beyond ±10%")
        self.cut_post(lot, dia, kg="11.7", pcs=110, order=o2, colour="Grey melange")  # 110 × 0.105 = 11.55 kg costed → +1.3%
        ranges = sorted((s.bundle_from, s.bundle_to) for s in CutSize.objects.filter(cut_lot__order=o2))
        self.assertTrue(all(a[1] < b[0] for a, b in zip(ranges, ranges[1:])))
        self.assertEqual(CutLot.objects.filter(cut_no__startswith="CL-T").count(), 1)

    def test_checking_cannot_exceed_sewn_and_packing_cannot_exceed_passed(self):
        r = {(x["colour"], x["size"]): x for x in tracker(self.order)}["Navy", "XXL"]
        self.assertEqual(r["sewn"], 0)
        page = self.client.post("/checking/", {"order": self.order.pk, "colour": "Navy", "size": "XXL", "hour": 9, "checked": 5})
        self.assertContains(page, "waiting for checking")
        page = self.client.post(
            "/checking/", {"order": self.order.pk, "pack": 1, "colour": "Navy", "size": "XXL", "pieces": 5, "cartons": "C-9"}
        )
        self.assertContains(page, "waiting to be packed")

    def test_raise_trim_pos_one_per_supplier_with_size_lines(self):
        o2 = Order.objects.get(order_no="SY-2604")
        self.client.post("/trims/", {"order": o2.pk})
        self.assertEqual(TrimPO.objects.filter(order=o2).count(), 3)  # three suppliers
        po = TrimPO.objects.get(order=o2, supplier__name="Tiruppur Labels & Tags")
        sizes = po.lines.filter(trim__item="Size label").values_list("size", flat=True)
        self.assertEqual(sorted(sizes), sorted(o2.size_list))
        self.client.post("/trims/", {"order": o2.pk})  # nothing left to order → no duplicate PO
        self.assertEqual(TrimPO.objects.filter(order=o2).count(), 3)

    def test_floor_pages_render(self):
        for url in (
            "/trims/",
            "/cutting/",
            f"/cutting/new/?order={self.order.pk}",
            "/sewing/",
            "/checking/",
            "/dashboard/",
            f"/orders/{self.order.pk}/",
        ):
            self.assertEqual(self.client.get(url).status_code, 200, url)
