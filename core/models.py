import math
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

SOURCES = [("manual", _("Manual")), ("scan", _("Scan")), ("device", _("Device"))]


def csv(value):
    return [v.strip() for v in value.split(",") if v.strip()]


class Stamped(models.Model):
    """Every record keeps who entered it, when, and how (keyboard now; scanner/scale later)."""

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=10, choices=SOURCES, default="manual")

    class Meta:
        abstract = True


class Buyer(Stamped):
    name = models.CharField(_("buyer"), max_length=120, unique=True)
    country = models.CharField(_("country"), max_length=60)

    def __str__(self):
        return self.name


class Party(Stamped):
    """Yarn mills, knitters, dyers, washers, compactors and trim suppliers."""

    KINDS = [
        ("mill", _("Yarn mill")),
        ("knit", _("Knitting")),
        ("dye", _("Dyeing")),
        ("wash", _("Washing")),
        ("compact", _("Compacting")),
        ("trims", _("Trims supplier")),
    ]
    name = models.CharField(_("name"), max_length=120)
    kind = models.CharField(_("type"), max_length=10, choices=KINDS)
    phone = models.CharField(_("phone"), max_length=20, blank=True)
    in_house = models.BooleanField(_("own unit"), default=False)

    def __str__(self):
        return self.name


class Order(Stamped):
    order_no = models.CharField(_("SY order no."), max_length=20, unique=True)
    buyer = models.ForeignKey(Buyer, on_delete=models.PROTECT, verbose_name=_("buyer"))
    buyer_po = models.CharField(_("buyer PO no."), max_length=40)
    style = models.CharField(_("style"), max_length=40)
    garment_type = models.CharField(_("garment type"), max_length=40)
    fabric_quality = models.CharField(_("fabric quality"), max_length=80)
    target_gsm = models.PositiveIntegerField(_("target GSM"))
    sizes = models.CharField(_("sizes"), max_length=60, default="S,M,L,XL,XXL")
    pieces_per_bundle = models.PositiveIntegerField(_("pieces per bundle"), default=20)
    bundle_parts = models.CharField(_("bundle parts"), max_length=120, default="Front,Back,Sleeve L,Sleeve R,Neck rib")
    cut_start = models.DateField(_("cut-start date"))
    delivery = models.DateField(_("delivery date"))
    repeat_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, verbose_name=_("repeat of"))

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.order_no} · {self.style}"

    @property
    def size_list(self):
        return csv(self.sizes)

    @property
    def part_list(self):
        return csv(self.bundle_parts)

    @property
    def colours(self):
        return list(dict.fromkeys(self.lines.order_by("id").values_list("colour", flat=True)))

    @property
    def total_qty(self):
        return sum(l.qty for l in self.lines.all())

    def bundles_for(self, qty):
        return math.ceil(qty / self.pieces_per_bundle) if qty else 0

    def fabric_needed(self, colour, dia):
        """Σ over the dia line's sizes of qty × costed kg per piece, for one colour."""
        return sum(
            (l.qty * l.costed_kg for l in self.lines.filter(colour=colour, size__in=dia.size_list)),
            Decimal(0),
        )


class OrderLine(Stamped):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    colour = models.CharField(_("colour"), max_length=40)
    size = models.CharField(_("size"), max_length=10)
    qty = models.PositiveIntegerField(_("quantity"), default=0)
    costed_kg = models.DecimalField(_("costed kg / pc"), max_digits=6, decimal_places=4, default=0)

    class Meta:
        unique_together = [("order", "colour", "size")]


class DiaLine(Stamped):
    WIDTHS = [("tubular", _("Tubular")), ("open", _("Open width"))]
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="dia_lines")
    sizes = models.CharField(_("sizes"), max_length=60, help_text=_("Comma separated, e.g. S,M"))
    knit_dia = models.DecimalField(_("knit dia (in)"), max_digits=5, decimal_places=1)
    gauge = models.PositiveIntegerField(_("gauge"))
    table_dia = models.DecimalField(_("finished table dia (in)"), max_digits=5, decimal_places=1)
    width_type = models.CharField(_("tubular / open"), max_length=10, choices=WIDTHS, default="tubular")

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f'{self.table_dia}" ({self.sizes})'

    @property
    def size_list(self):
        return csv(self.sizes)


class TrimLine(Stamped):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="trims")
    item = models.CharField(_("item"), max_length=60)
    unit = models.CharField(_("unit"), max_length=10, default="pcs")
    per_piece = models.DecimalField(_("per piece"), max_digits=8, decimal_places=3, default=1)
    wastage_pct = models.DecimalField(_("wastage %"), max_digits=5, decimal_places=2, default=0)
    size_wise = models.BooleanField(_("size-wise"), default=False)
    supplier = models.ForeignKey(Party, null=True, blank=True, on_delete=models.PROTECT, limit_choices_to={"kind": "trims"}, verbose_name=_("supplier"))

    class Meta:
        ordering = ["id"]

    def required(self, qty):
        return math.ceil(qty * self.per_piece * (1 + self.wastage_pct / 100))


class Costing(Stamped):
    """Admin only. Never sent to other roles — enforced in views, not just hidden in templates."""

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="costing")
    yarn_per_kg = models.DecimalField(_("yarn ₹/kg"), max_digits=8, decimal_places=2, default=0)
    knitting_per_kg = models.DecimalField(_("knitting ₹/kg"), max_digits=8, decimal_places=2, default=0)
    dyeing_per_kg = models.DecimalField(_("dyeing ₹/kg"), max_digits=8, decimal_places=2, default=0)
    trims_per_pc = models.DecimalField(_("trims ₹/pc"), max_digits=8, decimal_places=2, default=0)
    cmt_per_pc = models.DecimalField(_("CMT ₹/pc"), max_digits=8, decimal_places=2, default=0)
    overhead_per_pc = models.DecimalField(_("overhead ₹/pc"), max_digits=8, decimal_places=2, default=0)
    quoted_usd = models.DecimalField(_("quoted price USD"), max_digits=8, decimal_places=2, default=0)
    agreed_usd = models.DecimalField(_("agreed price USD"), max_digits=8, decimal_places=2, default=0)
    exchange_rate = models.DecimalField(_("exchange rate ₹/USD"), max_digits=7, decimal_places=2, default=84)

    def cost_per_piece(self):
        qty = self.order.total_qty
        if not qty:
            return Decimal(0)
        kg = sum((l.qty * l.costed_kg for l in self.order.lines.all()), Decimal(0))
        fabric = kg * (self.yarn_per_kg + self.knitting_per_kg + self.dyeing_per_kg) / qty
        return fabric + self.trims_per_pc + self.cmt_per_pc + self.overhead_per_pc

    def margin(self, usd):
        price = usd * self.exchange_rate
        return (price - self.cost_per_piece()) / price * 100 if price else None


class Amendment(Stamped):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="amendments")
    reason = models.CharField(_("reason"), max_length=200)
    change = models.TextField(_("change"))

    class Meta:
        ordering = ["-created_at"]


STAGES = [
    ("yarn_ordered", _("Yarn ordered")),
    ("yarn_in", _("Yarn in-house")),
    ("knitting", _("Knitting")),
    ("dyeing", _("Dyeing")),
    ("washing", _("Washing")),
    ("compacting", _("Steam / compacting")),
    ("in_house", _("In-house")),
]


class FabricLot(Stamped):
    """One order × colour × dia line, tracked in kg through the making stages."""

    lot_no = models.CharField(_("lot no."), max_length=20, unique=True)
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="lots")
    colour = models.CharField(_("colour"), max_length=40)
    dia_line = models.ForeignKey(DiaLine, on_delete=models.PROTECT, verbose_name=_("dia line"))
    planned_kg = models.DecimalField(_("planned kg"), max_digits=9, decimal_places=2)
    expected_date = models.DateField(_("expected in-house"))
    uses_washing = models.BooleanField(_("washing used"), default=False)

    class Meta:
        ordering = ["lot_no"]

    def __str__(self):
        return self.lot_no

    @property
    def last_update(self):
        return self.updates.order_by("-date", "-id").first()

    @property
    def stage(self):
        u = self.last_update
        return u.stage if u else ""

    @property
    def in_house_kg(self):
        u = self.updates.filter(stage="in_house").order_by("-date", "-id").first()
        return u.kg if u else Decimal(0)

    @property
    def progress(self):
        """(label, state) per stage this lot goes through: done / now / todo."""
        used = [s for s in STAGES if self.uses_washing or s[0] != "washing"]
        keys = [k for k, _l in used]
        at = keys.index(self.stage) if self.stage in keys else -1
        return [(label, "done" if i < at or self.stage == "in_house" else "now" if i == at else "todo") for i, (_k, label) in enumerate(used)]


class LotStageUpdate(Stamped):
    lot = models.ForeignKey(FabricLot, on_delete=models.PROTECT, related_name="updates")
    stage = models.CharField(_("stage"), max_length=20, choices=STAGES)
    date = models.DateField(_("date"))
    kg = models.DecimalField(_("kg"), max_digits=9, decimal_places=2)
    party = models.ForeignKey(Party, null=True, blank=True, on_delete=models.PROTECT, verbose_name=_("party"))
    reference = models.CharField(_("machine / batch / yarn lot"), max_length=60, blank=True)
    note = models.CharField(_("note"), max_length=200, blank=True)

    class Meta:
        ordering = ["date", "id"]


def fabric_window(order):
    """Per colour × dia line: will the fabric be in-house before cutting must start?"""
    rows = []
    for colour in order.colours:
        for dia in order.dia_lines.all():
            need = order.fabric_needed(colour, dia)
            lots = list(order.lots.filter(colour=colour, dia_line=dia))
            pending = [l for l in lots if l.stage != "in_house"]
            in_house = sum((l.in_house_kg for l in lots), Decimal(0))
            by_cut = sum((l.planned_kg for l in pending if l.expected_date <= order.cut_start), Decimal(0))
            after_cut = sum((l.planned_kg for l in pending if l.expected_date > order.cut_start), Decimal(0))
            if in_house + by_cut >= need:
                status, gap = "on_track", Decimal(0)
            elif in_house + by_cut + after_cut >= need:
                status, gap = "late", need - in_house - by_cut
            else:
                status, gap = "short", need - in_house - by_cut - after_cut
            rows.append({
                "colour": colour, "dia": dia, "need": need, "in_house": in_house,
                "by_cut": by_cut, "after_cut": after_cut, "status": status, "gap": gap, "lots": lots,
            })
    return rows
