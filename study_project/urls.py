from django.urls import path, include
from django.contrib import admin

urlpatterns = [
    path("", include("train_engine.urls")),
    path("admin/", admin.site.urls),
]