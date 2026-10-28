import math
from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
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
    supplier = models.ForeignKey(
        Party, null=True, blank=True, on_delete=models.PROTECT, limit_choices_to={"kind": "trims"}, verbose_name=_("supplier")
    )

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
        return [
            (label, "done" if i < at or self.stage == "in_house" else "now" if i == at else "todo")
            for i, (_k, label) in enumerate(used)
        ]


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
            rows.append(
                {
                    "colour": colour,
                    "dia": dia,
                    "need": need,
                    "in_house": in_house,
                    "by_cut": by_cut,
                    "after_cut": after_cut,
                    "status": status,
                    "gap": gap,
                    "lots": lots,
                }
            )
    return rows


# ---------- Milestone 2: trims POs and inward ----------


class TrimPO(Stamped):
    po_no = models.CharField(_("PO no."), max_length=20, unique=True)
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="trim_pos")
    supplier = models.ForeignKey(Party, on_delete=models.PROTECT, verbose_name=_("supplier"))
    required_by = models.DateField(_("required by"))

    class Meta:
        ordering = ["-created_at", "po_no"]

    def __str__(self):
        return self.po_no

    @property
    def status(self):
        lines = list(self.lines.all())
        got = sum(l.received for l in lines)
        if got and all(l.received >= l.qty for l in lines):
            return "received"
        if got:
            return "partial"
        return "overdue" if self.required_by < timezone.localdate() else "on_order"


class TrimPOLine(Stamped):
    po = models.ForeignKey(TrimPO, on_delete=models.PROTECT, related_name="lines")
    trim = models.ForeignKey(TrimLine, on_delete=models.PROTECT, related_name="po_lines")
    size = models.CharField(_("size"), max_length=10, blank=True)
    qty = models.PositiveIntegerField(_("quantity"))

    class Meta:
        ordering = ["id"]

    @property
    def received(self):
        return sum(r.qty for r in self.receipts.all())

    @property
    def short(self):
        return max(self.qty - self.received, 0)


class TrimReceipt(Stamped):
    line = models.ForeignKey(TrimPOLine, on_delete=models.PROTECT, related_name="receipts")
    qty = models.PositiveIntegerField(_("quantity"))
    challan = models.CharField(_("challan no."), max_length=30)
    date = models.DateField(_("date"))


# ---------- Milestone 3: cutting ----------

# Defect at the lay → the vertical that caused it (Party.kind).
FABRIC_DEFECTS = [
    ("neps", _("Neps / slubs / contamination"), "mill"),
    ("holes", _("Holes / drop stitch / needle lines"), "knit"),
    ("shade", _("Shade variation / dye spots"), "dye"),
    ("chemical", _("Chemical or softener spots"), "wash"),
    ("dimension", _("GSM / width off / spirality"), "compact"),
]
DEFECT_VERTICAL = {k: v for k, _l, v in FABRIC_DEFECTS}
LEVELS = [("minor", _("Minor")), ("major", _("Major")), ("critical", _("Critical"))]


class CutLot(Stamped):
    cut_no = models.CharField(_("cut lot no."), max_length=20, unique=True)
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="cut_lots")
    colour = models.CharField(_("colour"), max_length=40)
    dia_line = models.ForeignKey(DiaLine, on_delete=models.PROTECT, verbose_name=_("dia line"))
    date = models.DateField(_("date"))

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.cut_no

    @property
    def kg_used(self):
        return sum((r.kg - r.kg_returned for r in self.rolls.all()), Decimal(0))

    @property
    def kg_costed(self):
        kg = {l.size: l.costed_kg for l in self.order.lines.filter(colour=self.colour)}
        return sum((s.pieces * kg.get(s.size, 0) for s in self.sizes.all()), Decimal(0))

    @property
    def consumption_pct(self):
        costed = self.kg_costed
        return (self.kg_used - costed) / costed * 100 if costed else Decimal(0)

    @property
    def consumption_status(self):
        return consumption_status(self.consumption_pct)

    @property
    def pieces(self):
        return sum(s.pieces for s in self.sizes.all())


def consumption_status(pct):
    """green ≤ +2%, amber +2–4%, red > +4% (brief starting values)."""
    return "ok" if pct <= 2 else "warn" if pct <= 4 else "bad"


class RollLaid(Stamped):
    cut_lot = models.ForeignKey(CutLot, on_delete=models.PROTECT, related_name="rolls")
    fabric_lot = models.ForeignKey(FabricLot, on_delete=models.PROTECT, related_name="rolls", verbose_name=_("fabric lot"))
    roll_no = models.CharField(_("roll no."), max_length=20)
    kg = models.DecimalField(_("kg"), max_digits=7, decimal_places=2)
    gsm = models.PositiveIntegerField(_("GSM"))
    width = models.DecimalField(_("width (in)"), max_digits=5, decimal_places=1)
    defect = models.CharField(_("defect"), max_length=12, choices=[(k, l) for k, l, _v in FABRIC_DEFECTS], blank=True)
    level = models.CharField(_("level"), max_length=10, choices=LEVELS, blank=True)
    kg_rejected = models.DecimalField(_("kg rejected"), max_digits=7, decimal_places=2, default=0)
    kg_returned = models.DecimalField(_("kg returned"), max_digits=7, decimal_places=2, default=0)

    class Meta:
        ordering = ["id"]

    @property
    def vertical(self):
        return dict(Party.KINDS).get(DEFECT_VERTICAL.get(self.defect))

    @property
    def made_by(self):
        """The stage update that made this fabric — the party and machine/batch the flag goes to."""
        stage = {"mill": "yarn_in", "knit": "knitting", "dye": "dyeing", "wash": "washing", "compact": "compacting"}.get(
            DEFECT_VERTICAL.get(self.defect)
        )
        return self.fabric_lot.updates.filter(stage=stage).select_related("party").last() if stage else None

    @property
    def rupees(self):
        """kg rejected × fabric cost per kg (yarn + knitting + dyeing). Admin only — it reveals costing."""
        c = Costing.objects.filter(order=self.fabric_lot.order).first()
        return self.kg_rejected * (c.yarn_per_kg + c.knitting_per_kg + c.dyeing_per_kg) if c else None


class CutSize(Stamped):
    cut_lot = models.ForeignKey(CutLot, on_delete=models.PROTECT, related_name="sizes")
    size = models.CharField(_("size"), max_length=10)
    pieces = models.PositiveIntegerField(_("pieces"))
    bundle_from = models.PositiveIntegerField()
    bundle_to = models.PositiveIntegerField()

    class Meta:
        ordering = ["id"]


def lot_balance(lot):
    """kg in hand = in-house kg − kg taken by cutting (laid − returned)."""
    used = sum((r.kg - r.kg_returned for r in lot.rolls.all()), Decimal(0))
    return lot.in_house_kg - used


# ---------- Milestone 4: sewing, checking, packing ----------


class Line(Stamped):
    name = models.CharField(_("line"), max_length=10, unique=True)
    operators = models.PositiveIntegerField(_("operators"), default=20)
    order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.PROTECT, verbose_name=_("order"))
    colour = models.CharField(_("colour"), max_length=40, blank=True)
    size = models.CharField(_("size"), max_length=10, blank=True)
    target_per_hour = models.PositiveIntegerField(_("target / hour"), default=40)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class SewingEntry(Stamped):
    date = models.DateField(_("date"))
    hour = models.PositiveSmallIntegerField(_("hour"))
    line = models.ForeignKey(Line, on_delete=models.PROTECT, related_name="entries")
    order = models.ForeignKey(Order, on_delete=models.PROTECT)
    colour = models.CharField(_("colour"), max_length=40)
    size = models.CharField(_("size"), max_length=10)
    pieces = models.PositiveIntegerField(_("pieces"))

    class Meta:
        unique_together = [("date", "hour", "line")]


CHECK_DEFECTS = [
    ("open_seam", _("Open seam")),
    ("skip_stitch", _("Skip stitch")),
    ("uncut_thread", _("Uncut thread")),
    ("oil_stain", _("Oil / stain")),
    ("measurement", _("Measurement")),
    ("shade", _("Shade variation")),
    ("hole", _("Hole / damage")),
    ("label", _("Label wrong")),
]


class CheckingEntry(Stamped):
    date = models.DateField(_("date"))
    hour = models.PositiveSmallIntegerField(_("hour"))
    order = models.ForeignKey(Order, on_delete=models.PROTECT)
    colour = models.CharField(_("colour"), max_length=40)
    size = models.CharField(_("size"), max_length=10)
    checked = models.PositiveIntegerField(_("checked"))
    rework = models.PositiveIntegerField(_("rework"), default=0)
    reject = models.PositiveIntegerField(_("reject"), default=0)
    rework_ok = models.PositiveIntegerField(_("rework OK'd"), default=0)
    defect = models.CharField(_("main defect"), max_length=16, choices=CHECK_DEFECTS, blank=True)

    @property
    def passed(self):
        return self.checked - self.rework - self.reject + self.rework_ok


class PackingEntry(Stamped):
    date = models.DateField(_("date"))
    order = models.ForeignKey(Order, on_delete=models.PROTECT)
    colour = models.CharField(_("colour"), max_length=40)
    size = models.CharField(_("size"), max_length=10)
    pieces = models.PositiveIntegerField(_("pieces"))
    cartons = models.CharField(_("carton nos."), max_length=60)


def tracker(order):
    """Size-wise tracker: per colour × size, how far each piece has got."""

    def sums(qs, field):
        out = defaultdict(int)
        for row in qs.values("colour", "size").annotate(t=models.Sum(field)):
            out[row["colour"], row["size"]] = row["t"] or 0
        return out

    cut = defaultdict(int)
    for s in CutSize.objects.filter(cut_lot__order=order).select_related("cut_lot"):
        cut[s.cut_lot.colour, s.size] += s.pieces
    sewn = sums(SewingEntry.objects.filter(order=order), "pieces")
    chk = CheckingEntry.objects.filter(order=order)
    checked = sums(chk, "checked")
    passed = defaultdict(int)
    rework_open = defaultdict(int)
    for e in chk:
        passed[e.colour, e.size] += e.passed
        rework_open[e.colour, e.size] += e.rework - e.rework_ok
    packed = sums(PackingEntry.objects.filter(order=order), "pieces")
    rows = []
    for l in order.lines.order_by("id"):
        k = (l.colour, l.size)
        rows.append(
            {
                "colour": l.colour,
                "size": l.size,
                "qty": l.qty,
                "cut": cut[k],
                "sewn": sewn[k],
                "checked": checked[k],
                "passed": passed[k],
                "rework": rework_open[k],
                "packed": packed[k],
                "balance": l.qty - packed[k],
            }
        )
    return rows
