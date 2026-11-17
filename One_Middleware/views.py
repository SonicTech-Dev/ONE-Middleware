from django.shortcuts import render
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
import requests
import os
import json
# Create your views here.


@csrf_exempt
def user_commands(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    # Upstream device URL (override via settings or env in production)
    target_url = getattr(
        settings,
        "DEVICE_API_TARGET",
        "https://api.ecloud.akubela.com/api/v1.0/invoke/open-ability/method/user-commands",
    )

    # Forward only these headers from incoming request (safe & simple)
    forward_headers = {}
    for header_name in ("Content-Type", "Accept", "Authorization"):
        val = request.headers.get(header_name)
        if val:
            forward_headers[header_name] = val

    # Raw body (keeps JSON or any other payload intact)
    body = request.body or b""

    # --- Simple substitution: allow callers to send "get_intercom_device_list"
    # but upstream expects "get_akuvox_device_list". We only change that token.
    body_to_send = body
    try:
        text = body.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        # Not UTF-8 / not text — leave as-is
        text = None

    if text is not None:
        # Replace request command if caller used intercom token
        if "intercom" in text:
            text = text.replace("intercom", "akuvox")
            body_to_send = text.encode("utf-8")

    try:
        upstream = requests.post(target_url, headers=forward_headers, data=body_to_send, timeout=15)
    except requests.RequestException as exc:
        return JsonResponse({"error": "Upstream request failed", "detail": str(exc)}, status=502)

    # Build Django response with same body and status code
    # --- Simple substitution in response: replace "akuvox" with "intercom" in textual responses
    resp_content = upstream.content
    try:
        resp_text = upstream.content.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        resp_text = None

    if resp_text is not None and "akuvox" in resp_text:
        resp_text = resp_text.replace("akuvox", "intercom")
        resp_content = resp_text.encode("utf-8")

    resp = HttpResponse(content=resp_content, status=upstream.status_code)

    # Set content-type to whatever upstream returned (if present)
    if "Content-Type" in upstream.headers:
        resp["Content-Type"] = upstream.headers["Content-Type"]

    # Optionally copy a couple safe headers back
    for h in ("X-Request-ID", "Location"):
        if h in upstream.headers:
            resp[h] = upstream.headers[h]

    return resp

@csrf_exempt
def general_Commands(request):
    """
    POST-only proxy to the general-commands upstream.
    Forwards Content-Type, Accept and Authorization headers and the raw body.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    # Upstream URL for general-commands (can be overridden in settings)
    target_url = getattr(
        settings,
        "DEVICE_GENERAL_TARGET",
        "https://api.ecloud.akubela.com/api/v1.0/invoke/open-ability/method/general-commands",
    )

    # Forward only these headers from incoming request
    forward_headers = {}
    for header_name in ("Content-Type", "Accept", "Authorization"):
        val = request.headers.get(header_name)
        if val:
            forward_headers[header_name] = val

    # Preserve raw body (JSON or other)
    body = request.body or b""

    try:
        upstream = requests.post(target_url, headers=forward_headers, data=body, timeout=15)
    except requests.RequestException as exc:
        return JsonResponse({"error": "Upstream request failed", "detail": str(exc)}, status=502)

    # Return upstream response content and status
    resp = HttpResponse(content=upstream.content, status=upstream.status_code)

    if "Content-Type" in upstream.headers:
        resp["Content-Type"] = upstream.headers["Content-Type"]

    for h in ("X-Request-ID", "Location"):
        if h in upstream.headers:
            resp[h] = upstream.headers[h]

    return resp

@csrf_exempt
def get_token(request):
    """
    Simple token proxy endpoint.

    - Caller provides JSON or form with:
        {
          "username": "...",
          "password": "...",
          "expires_in": 3600   # OPTIONAL — if provided it will be forwarded
        }
    - The view builds an x-www-form-urlencoded body with grant_type, client_id,
      client_secret, scope, username, password and (optionally) expires_in,
      sends it to the upstream token URL, and returns the upstream response.
    """

    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    # Parse incoming body (accept JSON or form)
    content_type = request.META.get("CONTENT_TYPE", "")
    username = None
    password = None
    expires_in_raw = None

    try:
        if content_type.startswith("application/json"):
            payload = json.loads(request.body.decode("utf-8") or "{}")
            username = payload.get("username")
            password = payload.get("password")
            expires_in_raw = payload.get("expires_in")
        else:
            # e.g. client sends application/x-www-form-urlencoded to this endpoint
            username = request.POST.get("username")
            password = request.POST.get("password")
            expires_in_raw = request.POST.get("expires_in")
    except Exception:
        return JsonResponse({"error": "Invalid request body"}, status=400)

    if not username or not password:
        return JsonResponse({"error": "username and password are required"}, status=400)

    # If expires_in provided, validate it is an integer (optional)
    expires_in = None
    if expires_in_raw is not None and expires_in_raw != "":
        try:
            # allow strings that contain integers
            expires_in = int(expires_in_raw)
            if expires_in <= 0:
                raise ValueError()
        except Exception:
            return JsonResponse({"error": "expires_in must be a positive integer"}, status=400)

    # Upstream/token configuration (override in settings or env)
    TOKEN_URL = getattr(
        settings, "DEVICE_TOKEN_URL",
        os.environ.get(
            "DEVICE_TOKEN_URL",
            "https://api.ecloud.akubela.com/api/v1.0/invoke/open-ability/method/oauth2/token",
        ),
    )
    CLIENT_ID = getattr(settings, "OAUTH_CLIENT_ID", os.environ.get("OAUTH_CLIENT_ID", "your_client_id_here"))
    CLIENT_SECRET = getattr(settings, "OAUTH_CLIENT_SECRET", os.environ.get("OAUTH_CLIENT_SECRET", "your_client_secret_here"))
    SCOPE = getattr(settings, "OAUTH_SCOPE", os.environ.get("OAUTH_SCOPE", "user"))

    # Build x-www-form-urlencoded data
    form_data = {
        "grant_type": "password",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "username": username,
        "password": password,
        "scope": SCOPE,
    }

    # Optionally forward expires_in if provided
    if expires_in is not None:
        form_data["expires_in"] = str(expires_in)

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }

    try:
        upstream = requests.post(TOKEN_URL, data=form_data, headers=headers, timeout=10)
    except requests.RequestException as exc:
        return JsonResponse({"error": "Upstream request failed", "detail": str(exc)}, status=502)

    # Return upstream response content and status back to caller
    resp = HttpResponse(content=upstream.content, status=upstream.status_code)
    resp["Content-Type"] = upstream.headers.get("Content-Type", "application/json")
    return resp

@csrf_exempt
def refresh_token(request):
    """
    Refresh token proxy endpoint.

    - Caller provides JSON or form with:
        {
          "refresh_token": "...",
          "expires_in": 3600   # OPTIONAL — if provided it will be forwarded
        }
    - The view builds an x-www-form-urlencoded body with grant_type, client_id,
      client_secret, refresh_token and (optionally) expires_in,
      sends it to the upstream token URL, and returns the upstream response.
    """

    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    # Parse incoming body (accept JSON or form)
    content_type = request.META.get("CONTENT_TYPE", "")
    refresh_token_value = None
    expires_in_raw = None

    try:
        if content_type.startswith("application/json"):
            payload = json.loads(request.body.decode("utf-8") or "{}")
            refresh_token_value = payload.get("refresh_token")
            expires_in_raw = payload.get("expires_in")
        else:
            # e.g. client sends application/x-www-form-urlencoded to this endpoint
            refresh_token_value = request.POST.get("refresh_token")
            expires_in_raw = request.POST.get("expires_in")
    except Exception as e:
        return JsonResponse({"error": "Invalid request body", "detail": str(e)}, status=400)

    if not refresh_token_value:
        return JsonResponse({"error": "refresh_token is required"}, status=400)

    # If expires_in provided, validate it is an integer (optional)
    expires_in = None
    if expires_in_raw is not None and expires_in_raw != "":
        try:
            # allow strings that contain integers
            expires_in = int(expires_in_raw)
            if expires_in <= 0:
                raise ValueError("expires_in must be positive")
        except (ValueError, TypeError) as e:
            return JsonResponse({"error": "expires_in must be a positive integer", "detail": str(e)}, status=400)

    # Upstream/token configuration (override in settings or env)
    TOKEN_URL = getattr(
        settings, "DEVICE_TOKEN_URL",
        os.environ.get(
            "DEVICE_TOKEN_URL",
            "https://api.ecloud.akubela.com/api/v1.0/invoke/open-ability/method/oauth2/token",
        ),
    )
    CLIENT_ID = getattr(settings, "OAUTH_CLIENT_ID", os.environ.get("OAUTH_CLIENT_ID", "your_client_id_here"))
    CLIENT_SECRET = getattr(settings, "OAUTH_CLIENT_SECRET", os.environ.get("OAUTH_CLIENT_SECRET", "your_client_secret_here"))

    # Build x-www-form-urlencoded data
    form_data = {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token_value,
    }

    # Optionally forward expires_in if provided
    if expires_in is not None:
        form_data["expires_in"] = str(expires_in)

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }

    try:
        upstream = requests.post(TOKEN_URL, data=form_data, headers=headers, timeout=10)
    except requests.RequestException as exc:
        return JsonResponse({"error": "Upstream request failed", "detail": str(exc)}, status=502)
    except Exception as exc:
        return JsonResponse({"error": "Internal server error", "detail": str(exc)}, status=500)

    # Return upstream response content and status back to caller
    try:
        resp = HttpResponse(content=upstream.content, status=upstream.status_code)
        resp["Content-Type"] = upstream.headers.get("Content-Type", "application/json")
        return resp
    except Exception as exc:
        return JsonResponse({"error": "Failed to process upstream response", "detail": str(exc)}, status=500)

@csrf_exempt
def get_general_token(request):
    """
    Token endpoint using OAuth2 client_credentials grant.

    - Caller may send JSON or form with:
        {
          "client_id": "...",         # OPTIONAL - will use settings/env fallback if not provided
          "client_secret": "...",     # OPTIONAL - will use settings/env fallback if not provided
          "expires_in": 3600          # OPTIONAL - forwarded if provided
        }

    - The view builds an x-www-form-urlencoded body with:
        grant_type=client_credentials
        client_id=...
        client_secret=...
        scope=general
        (optionally) expires_in=...

    - It sends the request to the configured upstream token URL and returns the upstream response.
    """

    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    # Parse incoming body (accept JSON or form)
    content_type = request.META.get("CONTENT_TYPE", "")
    client_id = None
    client_secret = None
    expires_in_raw = None

    try:
        if content_type.startswith("application/json"):
            payload = json.loads(request.body.decode("utf-8") or "{}")
            client_id = payload.get("client_id")
            client_secret = payload.get("client_secret")
            expires_in_raw = payload.get("expires_in")
        else:
            # e.g., client sends application/x-www-form-urlencoded to this endpoint
            client_id = request.POST.get("client_id")
            client_secret = request.POST.get("client_secret")
            expires_in_raw = request.POST.get("expires_in")
    except Exception:
        return JsonResponse({"error": "Invalid request body"}, status=400)

    # Fallback to configured client credentials in settings/env if not provided
    CLIENT_ID = client_id or getattr(settings, "OAUTH_CLIENT_ID", os.environ.get("OAUTH_CLIENT_ID"))
    CLIENT_SECRET = client_secret or getattr(settings, "OAUTH_CLIENT_SECRET", os.environ.get("OAUTH_CLIENT_SECRET"))

    if not CLIENT_ID or not CLIENT_SECRET:
        return JsonResponse({"error": "client_id and client_secret are required (or set in settings/env)"}, status=400)

    # Validate optional expires_in
    expires_in = None
    if expires_in_raw is not None and expires_in_raw != "":
        try:
            expires_in = int(expires_in_raw)
            if expires_in <= 0:
                raise ValueError()
        except Exception:
            return JsonResponse({"error": "expires_in must be a positive integer"}, status=400)

    # Upstream/token configuration (override in settings or env)
    TOKEN_URL = getattr(
        settings, "DEVICE_TOKEN_URL",
        os.environ.get(
            "DEVICE_TOKEN_URL",
            "https://api.ecloud.akubela.com/api/v1.0/invoke/open-ability/method/oauth2/token",
        ),
    )

    # Build x-www-form-urlencoded data for client_credentials
    form_data = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "general",
    }

    if expires_in is not None:
        form_data["expires_in"] = str(expires_in)

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }

    try:
        upstream = requests.post(TOKEN_URL, data=form_data, headers=headers, timeout=10)
    except requests.RequestException as exc:
        return JsonResponse({"error": "Upstream request failed", "detail": str(exc)}, status=502)

    # Return upstream response content and status back to caller
    resp = HttpResponse(content=upstream.content, status=upstream.status_code)
    resp["Content-Type"] = upstream.headers.get("Content-Type", "application/json")
    return resp
