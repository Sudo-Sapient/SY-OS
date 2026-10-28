from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from .models import Amendment, Order, fabric_window


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

    def test_trim_requirement_rounds_up_with_wastage(self):
        thread = self.order.trims.get(item="Sewing thread")
        self.assertEqual(thread.required(4150), 53)  # 4150 × 0.012 × 1.05 = 52.29

    def test_fabric_in_charge_cannot_edit_orders(self):
        self.client.login(username="fabric", password="fabric123")
        self.assertEqual(self.client.get(f"/orders/{self.order.pk}/grid/").status_code, 403)
        self.assertEqual(self.client.get(f"/orders/{self.order.pk}/fabric/").status_code, 200)
