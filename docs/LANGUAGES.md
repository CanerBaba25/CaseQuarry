# Interface languages

CaseQuarry provides English (`en`), Russian (`ru`), French (`fr`), Spanish (`es`),
German (`de`), Turkish (`tr`), Greek (`el`), Italian (`it`), Portuguese (`pt`),
Ukrainian (`uk`), Simplified Chinese (`zh-Hans`), Traditional Chinese (`zh-Hant`)
and Hindi (`hi`). Each language uses the same shared interface catalog in the web
workspace and desktop connection screen.

Select a language before signing in or during initial setup. After signing in,
use the language control in the workspace navigation. The preference is stored on your
account on the firm server and is restored on another connected device. Date and
number presentation follows the interface language; the separately saved timezone
continues to determine timestamp displays and deadline classification.

The desktop connection screen has its own device language selector. It translates
the connection form and native Connection/Edit menus without changing the firm URL
or stored connection options. The workspace opened from that screen uses the
signed-in user's account preference. Selecting a language does not translate user
input, case names, evidence, document text, tags or review notes.

## Account API

`GET /api/v1/me`, sign-in responses and initial setup responses include `language`.
Cookie-authenticated changes require the normal CSRF header:

```http
PATCH /api/v1/me/preferences
Content-Type: application/json
X-CSRF-Token: YOUR_CSRF_TOKEN

{"language":"hi","time_zone":"Asia/Kolkata"}
```

Either field can be changed independently; omitted fields retain their saved
values. Only the exact language codes above are accepted. Null values, unknown
codes and non-string values return HTTP 422. Initial setup also accepts a
`language` field, defaulting to English. Language changes use the existing account
authorization and audit controls.

## Maintaining translations

English message keys live in `packages/i18n/catalogs/en.json`. Other catalogs must
contain exactly those keys and preserve every interpolation placeholder, including
its number of occurrences. Run `python scripts/check_i18n.py` before building.
This check also verifies agreement between API and interface language codes and
rejects duplicate keys, empty messages and invalid characters.

Interface catalogs are bundled locally. Changing language does not call a
translation service or transmit evidence to an external model. Unavailable
catalogs fall back to English while displaying a language-loading error.
