"""Every form in SY OS. Model forms extend TidyForm so dropdowns read "Select…" in all three languages."""

from django import forms
from django.forms import inlineformset_factory
from django.utils.translation import gettext as _

from .models import Costing, CutLot, DiaLine, FabricLot, LotStageUpdate, Order, TrimLine

STAMPED = ("created_by", "created_at", "source")
DATE = forms.DateInput(attrs={"type": "date"})


class TidyForm(forms.ModelForm):
    """Readable placeholders in every dropdown instead of Django's '---------'."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        for f in self.fields.values():
            if getattr(f, "empty_label", None):
                f.empty_label = _("Select…")
            elif isinstance(f, forms.TypedChoiceField) and f.choices and f.choices[0][0] == "":
                f.choices = [("", _("Select…"))] + list(f.choices)[1:]


class OrderForm(TidyForm):
    colours = forms.CharField(label="", help_text="", max_length=200)

    class Meta:
        model = Order
        exclude = (*STAMPED, "repeat_of")
        widgets = {"cut_start": DATE, "delivery": DATE}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["colours"].label = _("Colours")
        self.fields["colours"].help_text = _("Comma separated, e.g. Navy, White")


class RepeatForm(TidyForm):
    class Meta:
        model = Order
        fields = ("order_no", "buyer_po", "cut_start", "delivery")
        widgets = {"cut_start": DATE, "delivery": DATE}


class CostingForm(TidyForm):
    class Meta:
        model = Costing
        exclude = (*STAMPED, "order")


class LotForm(TidyForm):
    class Meta:
        model = FabricLot
        fields = ("lot_no", "colour", "dia_line", "planned_kg", "expected_date", "uses_washing")
        widgets = {"expected_date": DATE}

    def __init__(self, order, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["dia_line"].queryset = order.dia_lines.all()
        self.fields["colour"] = forms.ChoiceField(label=_("Colour"), choices=[(c, c) for c in order.colours])


class StageForm(TidyForm):
    class Meta:
        model = LotStageUpdate
        fields = ("lot", "stage", "date", "kg", "party", "reference", "note")
        widgets = {"date": DATE}

    def __init__(self, order, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["lot"].queryset = order.lots.all()
        self.fields["party"].queryset = self.fields["party"].queryset.exclude(kind="trims")


# No hard deletes (brief): rows can be edited, never removed.
DiaFormSet = inlineformset_factory(Order, DiaLine, form=TidyForm, exclude=STAMPED, extra=1, can_delete=False)
TrimFormSet = inlineformset_factory(Order, TrimLine, form=TidyForm, exclude=STAMPED, extra=1, can_delete=False)


class CutHeadForm(TidyForm):
    class Meta:
        model = CutLot
        fields = ("cut_no", "date")
        widgets = {"date": DATE}
