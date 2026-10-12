from django.urls import include, path, re_path

from routing.views import spa

urlpatterns = [
    path("api/", include("routing.urls")),
    # Everything else is the React single-page app.
    re_path(r"^(?!api/|static/).*$", spa),
]
