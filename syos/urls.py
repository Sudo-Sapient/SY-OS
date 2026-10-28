from django.contrib import admin
from django.contrib.auth import views as auth
from django.urls import include, path

from core import views as v

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
    path("preview/trims/", v.preview_trims, name="preview_trims"),
    path("preview/cutting/", v.preview_cutting, name="preview_cutting"),
    path("preview/sewing/", v.preview_sewing, name="preview_sewing"),
    path("preview/dashboard/", v.preview_dashboard, name="preview_dashboard"),
]
