# OrangeHRM attendance automation (punch-in / punch-out)

Target login page (from your screenshot):

```text
https://shaafiya-osondemand.orangehrm.com/auth/login
```

This guide implements a reusable attendance workflow with:

- local stack bring-up checks (API/dashboard/noVNC)
- site-specific environment hardening (`ALLOWED_HOSTS`, auth, limits)
- login + attendance navigation + punch action + verification
- MFA/CAPTCHA fallback takeover on the same live session
- auth-profile save/reuse
- scheduled punch-in and punch-out runs
- retries, element/time guards, duplicate-punch guard
- audit + screenshot receipts review

---

## 1) Start locally and verify endpoints

```bash
cd ~/auto-browser
docker compose up --build
```

In another terminal:

```bash
curl -fsS http://127.0.0.1:8000/healthz | jq
curl -fsS http://127.0.0.1:8000/readyz | jq
```

Open:

- API docs: `http://127.0.0.1:8000/docs`
- Dashboard: `http://127.0.0.1:8000/dashboard`
- noVNC: `http://127.0.0.1:6080/vnc.html?autoconnect=true&resize=scale`

---

## 2) Environment configuration for this site

In your `.env`:

```env
# Restrict browser navigation to your OrangeHRM host(s)
ALLOWED_HOSTS=shaafiya-osondemand.orangehrm.com

# Keep one live session for attendance automation safety
MAX_SESSIONS=1

# Strongly recommended when running outside local dev
API_BEARER_TOKEN=change-me
REQUIRE_OPERATOR_ID=true
AUTH_STATE_ENCRYPTION_KEY=change-me
REQUIRE_AUTH_STATE_ENCRYPTION=true
REQUEST_RATE_LIMIT_ENABLED=true
```

Restart after env changes:

```bash
cd ~/auto-browser
docker compose up --build
```

---

## 3) Dedicated workflow script (run file)

Save this as `/tmp/orangehrm_attendance.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
LOGIN_URL="${LOGIN_URL:-https://shaafiya-osondemand.orangehrm.com/auth/login}"
ATTENDANCE_URL="${ATTENDANCE_URL:-https://shaafiya-osondemand.orangehrm.com/attendance/viewMyAttendanceRecord}"
ACTION="${1:-in}"   # in | out
USERNAME="${USERNAME:?set USERNAME}"
PASSWORD="${PASSWORD:?set PASSWORD}"
AUTH_PROFILE="${AUTH_PROFILE:-orangehrm-default}"

HDRS=(-H 'content-type: application/json')
if [[ -n "${API_BEARER_TOKEN:-}" ]]; then
  HDRS+=(-H "Authorization: Bearer ${API_BEARER_TOKEN}")
fi
if [[ -n "${OPERATOR_ID:-}" ]]; then
  HDRS+=(-H "X-Operator-Id: ${OPERATOR_ID}")
fi

api_post() {
  local path="$1" body="$2"
  curl -fsS --max-time 40 "${BASE_URL}${path}" -X POST "${HDRS[@]}" -d "${body}"
}
api_get() {
  local path="$1"
  curl -fsS --max-time 40 "${BASE_URL}${path}" "${HDRS[@]}"
}

retry() {
  local tries="$1"; shift
  local i base delay
  base="${RETRY_BASE_DELAY_SECONDS:-1}"
  for i in $(seq 1 "$tries"); do
    if "$@"; then return 0; fi
    delay=$(( base * (2 ** (i - 1)) ))
    sleep "$delay"
  done
  return 1
}

# 1) Open session on login page (reuse auth profile if present)
SESSION_CREATE_BODY=$(jq -nc \
  --arg n "orangehrm-attendance-${ACTION}" \
  --arg u "$LOGIN_URL" \
  --arg p "$AUTH_PROFILE" \
  '{name:$n,start_url:$u,auth_profile:$p}')

SESSION_JSON="$(api_post /sessions "$SESSION_CREATE_BODY" || true)"
SESSION_ID="$(echo "$SESSION_JSON" | jq -r '.session_id // .id // empty')"
if [[ -z "$SESSION_ID" ]]; then
  SESSION_JSON="$(api_post /sessions "$(jq -nc --arg n "orangehrm-attendance-${ACTION}" --arg u "$LOGIN_URL" '{name:$n,start_url:$u}')")"
  SESSION_ID="$(echo "$SESSION_JSON" | jq -r '.session_id // .id')"
fi

echo "SESSION_ID=$SESSION_ID"

# 2) Login only if not already authenticated
OBSERVE="$(api_post "/sessions/${SESSION_ID}/observe" '{"preset":"rich","limit":120}')"
PAGE_TEXT="$(echo "$OBSERVE" | jq -r '[.text_excerpt, .ocr.text_excerpt, (.interactables[]?.label)] | map(select(.!=null)) | join(" ")')"

if echo "$PAGE_TEXT" | grep -Eiq 'login|username|password'; then
  retry 3 api_post "/sessions/${SESSION_ID}/actions/type" "$(jq -nc --arg s "input[name='username']" --arg t "$USERNAME" '{selector:$s,text:$t,clear_first:true}')" >/dev/null
  retry 3 api_post "/sessions/${SESSION_ID}/actions/type" "$(jq -nc --arg s "input[name='password']" --arg t "$PASSWORD" '{selector:$s,text:$t,clear_first:true,sensitive:true}')" >/dev/null
  retry 3 api_post "/sessions/${SESSION_ID}/actions/click" '{"selector":"button[type='\''submit'\'']"}' >/dev/null
fi

api_post "/sessions/${SESSION_ID}/actions/wait" '{"wait_ms":2500}' >/dev/null

# 3) Fallback takeover for MFA/CAPTCHA/login failures on same session
OBSERVE="$(api_post "/sessions/${SESSION_ID}/observe" '{"preset":"rich","limit":120}')"
PAGE_TEXT="$(echo "$OBSERVE" | jq -r '[.text_excerpt, .ocr.text_excerpt, (.interactables[]?.label)] | map(select(.!=null)) | join(" ")')"
if echo "$PAGE_TEXT" | grep -Eiq 'captcha|mfa|two-factor|verification code|invalid credentials|login'; then
  TAKEOVER="$(api_post "/sessions/${SESSION_ID}/takeover" '{"reason":"OrangeHRM login recovery required"}')"
  echo "Manual takeover required:"
  echo "$TAKEOVER" | jq -r '.takeover_url'
  exit 2
fi

# 4) Save reusable auth profile after successful login
api_post "/sessions/${SESSION_ID}/auth-profiles" "$(jq -nc --arg p "$AUTH_PROFILE" '{profile_name:$p}')" >/dev/null || true

# 5) Navigate to attendance page
retry 3 api_post "/sessions/${SESSION_ID}/actions/navigate" "$(jq -nc --arg u "$ATTENDANCE_URL" '{url:$u}')" >/dev/null
api_post "/sessions/${SESSION_ID}/actions/wait" '{"wait_ms":2000}' >/dev/null

# 6) Duplicate-punch guard
OBSERVE="$(api_post "/sessions/${SESSION_ID}/observe" '{"preset":"rich","limit":160}')"
PAGE_TEXT="$(echo "$OBSERVE" | jq -r '[.text_excerpt, .ocr.text_excerpt, (.interactables[]?.label)] | map(select(.!=null)) | join(" ")')"
if [[ "$ACTION" == "in" ]] && echo "$PAGE_TEXT" | grep -Eiq 'already.*punch.*in|punched in|checked in'; then
  echo "Already punched in; skipping."
  api_post "/sessions/${SESSION_ID}/screenshot" '{"label":"already-punched-in"}' >/dev/null
  exit 0
fi
if [[ "$ACTION" == "out" ]] && echo "$PAGE_TEXT" | grep -Eiq 'already.*punch.*out|punched out|checked out'; then
  echo "Already punched out; skipping."
  api_post "/sessions/${SESSION_ID}/screenshot" '{"label":"already-punched-out"}' >/dev/null
  exit 0
fi

# 7) Click punch button with retries
if [[ "$ACTION" == "in" ]]; then
  PUNCH_ID="$(echo "$OBSERVE" | jq -r '.interactables[]? | select((.label // "") | test("punch\\s*in";"i")) | .element_id' | head -n1)"
else
  PUNCH_ID="$(echo "$OBSERVE" | jq -r '.interactables[]? | select((.label // "") | test("punch\\s*out";"i")) | .element_id' | head -n1)"
fi
if [[ -z "$PUNCH_ID" ]]; then
  echo "Punch button not found; requesting takeover."
  api_post "/sessions/${SESSION_ID}/takeover" '{"reason":"Punch button not found"}' | jq
  exit 3
fi
retry 3 api_post "/sessions/${SESSION_ID}/actions/click" "$(jq -nc --arg id "$PUNCH_ID" '{element_id:$id}')" >/dev/null

# 8) Verify success state/message and capture proof
api_post "/sessions/${SESSION_ID}/actions/wait" '{"wait_ms":2000}' >/dev/null
api_post "/sessions/${SESSION_ID}/screenshot" "$(jq -nc --arg l "attendance-${ACTION}-result" '{label:$l}')" >/dev/null
OBSERVE_AFTER="$(api_post "/sessions/${SESSION_ID}/observe" '{"preset":"rich","limit":160}')"
TEXT_AFTER="$(echo "$OBSERVE_AFTER" | jq -r '[.text_excerpt, .ocr.text_excerpt, (.interactables[]?.label)] | map(select(.!=null)) | join(" ")')"
if [[ "$ACTION" == "in" ]] && ! echo "$TEXT_AFTER" | grep -Eiq 'punched in|checked in|attendance'; then
  echo "Could not verify punch-in state; requesting takeover."
  api_post "/sessions/${SESSION_ID}/takeover" '{"reason":"Punch-in verification failed"}' | jq
  exit 4
fi
if [[ "$ACTION" == "out" ]] && ! echo "$TEXT_AFTER" | grep -Eiq 'punched out|checked out|attendance'; then
  echo "Could not verify punch-out state; requesting takeover."
  api_post "/sessions/${SESSION_ID}/takeover" '{"reason":"Punch-out verification failed"}' | jq
  exit 5
fi

# 9) Audit / receipts
api_get "/sessions/${SESSION_ID}/audit?limit=200" | jq '.count'
api_get "/sessions/${SESSION_ID}/witness?limit=100" | jq '.count'

echo "Attendance ${ACTION} completed for session ${SESSION_ID}"
```

Run:

```bash
chmod +x /tmp/orangehrm_attendance.sh
USERNAME='your-username' PASSWORD='your-password' /tmp/orangehrm_attendance.sh in
USERNAME='your-username' PASSWORD='your-password' /tmp/orangehrm_attendance.sh out
```

---

## 4) Schedule two runs

### Linux cron example

```bash
crontab -e
```

```cron
# Punch-in at 09:00 weekdays
0 9 * * 1-5 [ -f ~/.orangehrm_attendance_env ] && [ "$(stat -c '%a' ~/.orangehrm_attendance_env)" = "600" ] && . ~/.orangehrm_attendance_env && /tmp/orangehrm_attendance.sh in >> /tmp/orangehrm-punch-in.log 2>&1

# Punch-out at 18:00 weekdays
0 18 * * 1-5 [ -f ~/.orangehrm_attendance_env ] && [ "$(stat -c '%a' ~/.orangehrm_attendance_env)" = "600" ] && . ~/.orangehrm_attendance_env && /tmp/orangehrm_attendance.sh out >> /tmp/orangehrm-punch-out.log 2>&1
```

Create the env file with secure permissions first:

```bash
(umask 077; : > ~/.orangehrm_attendance_env)
chmod 600 ~/.orangehrm_attendance_env
```

Then put:

```bash
export USERNAME='your-username'
export PASSWORD='your-password'
export AUTH_PROFILE='orangehrm-default'
export API_BEARER_TOKEN='optional-token'
export OPERATOR_ID='ops'
```

---

## 5) Post-run proof and troubleshooting

After each run:

1. Check session audit:
   - `GET /sessions/{session_id}/audit`
2. Check witness receipts:
   - `GET /sessions/{session_id}/witness`
3. Review screenshots under:
   - `/artifacts/{session_id}/`
4. If failed, use takeover URL in the returned payload to recover the same live session in noVNC.

---

## 6) Safety rollout

1. Validate full flow with a non-critical test account first.
2. Confirm duplicate guard behavior for both directions.
3. Move to production credentials only after authorized sign-off.
