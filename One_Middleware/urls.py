from django.urls import path
from .views import user_commands
from .views import get_token
from .views import get_general_token
from .views import refresh_token
from .views import general_Commands
urlpatterns = [
    # POST /api/get-device-list/
    path("user-commands/", user_commands, name="user-commands"),
    path("get-token/", get_token, name="get-token"),
    path("get-general-token", get_general_token, name="get-general-token"),
    path("general_Commands", general_Commands, name="general_Commands"),
    path("refresh_token", refresh_token, name="refresh-token"),
]
