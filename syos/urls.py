from django.contrib import admin
from django.contrib.auth import views as auth
from django.urls import include, path
from django.views.generic import RedirectView

from core.views import floor as f
from core.views import orders as v

urlpatterns = [
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path("login/", auth.LoginView.as_view(template_name="core/login.html"), name="login"),
    path("logout/", auth.LogoutView.as_view(), name="logout"),
    path("", v.home, name="home"),
    path("orders/new/", v.order_new, name="order_new"),
    path("orders/<int:pk>/", v.order_detail, name="order_detail"),
    path("orders/<int:pk>/grid/", v.order_grid, name="order_grid"),
    path("orders/<int:pk>/setup/", v.order_setup, name="order_setup"),
    path("orders/<int:pk>/costing/", v.costing, name="costing"),
    path("orders/<int:pk>/repeat/", v.order_repeat, name="order_repeat"),
    path("orders/<int:pk>/fabric/", v.fabric, name="fabric"),
    path("trims/", f.trims, name="trims"),
    path("trims/po/<int:pk>/", f.trim_po, name="trim_po"),
    path("cutting/", f.cutting, name="cutting"),
    path("cutting/new/", f.cut_new, name="cut_new"),
    path("sewing/", f.sewing, name="sewing"),
    path("checking/", f.checking, name="checking"),
    path("dashboard/", f.dashboard, name="dashboard"),
    # Old preview addresses from the first demo still open in tabs/bookmarks.
    path("preview/trims/", RedirectView.as_view(pattern_name="trims")),
    path("preview/cutting/", RedirectView.as_view(pattern_name="cutting")),
    path("preview/sewing/", RedirectView.as_view(pattern_name="sewing")),
    path("preview/dashboard/", RedirectView.as_view(pattern_name="dashboard")),
]
