from django.urls import path, include
from django.contrib import admin

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/train/", include("train_engine.urls")),
]