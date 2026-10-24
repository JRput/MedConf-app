# MedConf auth emails

Six transactional emails, one HTML and one plain-text file each, in `supabase/templates/`. Locally they are wired through `supabase/config.toml` (`[auth.email.template.*]`). In production they are pasted into the Supabase dashboard; the repo files are the source.

## 1. Which email belongs to which journey

| Template | Journey | Trigger | Subject |
|---|---|---|---|
| `confirm_signup` | First-time user | Sign-up on `/auth/signup`; `enable_confirmations = true`. Link goes to `/auth/callback`, then `/onboarding` | Confirm your MedConf account |
| `recovery` | Forgot password | `/auth/forgot-password`. Link goes to `/auth/callback`, then `/auth/reset-password` | Reset your MedConf password |
| `magic_link` | Passwordless sign-in | Only sent if a magic-link / OTP sign-in is called. The site has no such UI today, so this is a ready fallback | Your MedConf sign-in link |
| `email_change` | Account settings | User changes email. `double_confirm_changes = true` sends one to the old and one to the new address | Confirm your new email for MedConf |
| `reauthentication` | Sensitive change | Supabase asks for a code before e.g. a password change when `secure_password_change` is on (currently false). Contains `{{ .Token }}` | Your MedConf verification code |
| `invite` | Admin invite | Dashboard "Invite user" or `auth.admin.inviteUserByEmail` | You're invited to MedConf |

Variables used: `{{ .SiteURL }}`, `{{ .TokenHash }}`, `{{ .Token }}` (reauthentication only), `{{ .Email }}`, `{{ .NewEmail }}` (email change only). The site has no code-entry screen, so confirm and recovery omit the 6-digit code (decision recorded; default).

### Why token_hash links

Every link is `{{ .SiteURL }}/auth/callback?token_hash={{ .TokenHash }}&type=<type>` instead of `{{ .ConfirmationURL }}`. The `ConfirmationURL` form uses the PKCE `?code=` flow, which only completes in the browser that started it, so someone who signs up on a laptop and opens the email on a phone sees "verification failed". `token_hash` does not depend on the device. The callback already accepts it.

Trade-off: the sign-up intent (`next`) is kept by the site in a short-lived cookie. Same-device users still return to where they started. Cross-device users land on onboarding, then the dashboard. The recovery link carries `next=%2Fauth%2Freset-password` in the URL.

`{{ .SiteURL }}` comes from the hosted Site URL (Authentication → URL Configuration). It must be the production URL there; the owner set it to `https://medconf.vercel.app`. The local `site_url` in `config.toml` stays `127.0.0.1` for dev, so local emails link to localhost.

Expiry: the emails say "1 hour". That is `otp_expiry = 3600` in `config.toml` and the Supabase default. The hosted value is set under Authentication → Sign In / Providers → Email → "Email OTP Expiration". If you change it there, edit the sentence in all six files.

Design: single column, 560px max, table layout with inline CSS, system font stack, no images, one button. Colours come from `medconf-website/src/app/globals.css` (light theme):

| Use | Hex | Token |
|---|---|---|
| Button, wordmark | `#0f766e` | `--brand` |
| Fallback link text | `#0c5e58` | `--brand-text` |
| Headline | `#121110` | `--fg-strong` (`--n-950`) |
| Body text | `#1f1d19` | `--fg` (`--n-900`) |
| Muted text | `#5f5a50` | `--fg-muted` (`--n-600`) |
| Footer text | `#6f695d` | `--fg-subtle` (`--n-500`) |
| Page background | `#fcfbf8` | `--bg` (`--n-25`) |
| Card, border | `#ffffff`, `#e5e1d8` | `--surface`, `--border` |
| Code box | `#f1eee8` | `--n-100` |

Dark mode: every colour is set explicitly, so clients that auto-invert keep contrast. Clients that honour `prefers-color-scheme` get a dark card via a small style block (page `#121110`, card `#1f1d19`, text `#f1eee8`).

## 2. Production: Supabase dashboard

Dashboard → project `zcpszfbmvfylicpxgsfc` → Authentication → Email Templates (or run `scripts/supabase_auth_setup.py templates`, section 3c). Each template has a Subject field and one body field that takes HTML. The `.txt` files are not pasted there; they are the plain-text alternative for local testing or for a sender such as Resend if you ever send these yourself.

| Dashboard tab | Subject | Paste HTML from |
|---|---|---|
| Confirm sign up | Confirm your MedConf account | `supabase/templates/confirm_signup.html` |
| Invite user | You're invited to MedConf | `supabase/templates/invite.html` |
| Magic link | Your MedConf sign-in link | `supabase/templates/magic_link.html` |
| Change email address | Confirm your new email for MedConf | `supabase/templates/email_change.html` |
| Reset password | Reset your MedConf password | `supabase/templates/recovery.html` |
| Reauthentication | Your MedConf verification code | `supabase/templates/reauthentication.html` |

Paste the whole file including `<!DOCTYPE html>`. Save each tab separately. Leave the `{{ ... }}` placeholders untouched.

## 3. SMTP: custom sender setup

Supabase's built-in sender only delivers to addresses that belong to the project's team members, and it is rate-limited to a few emails per hour. Real sign-ups from the public will not receive confirmation or reset emails until custom SMTP is configured.

The owner has no domain yet. Resend needs a verified domain, so for now use one of the options in 3a, which verify a single sender address instead.

### 3a. No domain yet: options that verify a single sender address

In every case the Supabase fields are under Authentication → SMTP Settings (enable custom SMTP). Caps are the providers' published free-tier figures at the time of writing; recheck them on sign-up, as free plans change.

| | Brevo (free) | Gmail with App Password | SendGrid |
|---|---|---|---|
| Daily cap | 300 emails/day | about 500 emails/day | 100 emails/day on the free tier (SendGrid has been moving to a time-limited trial; check what your account gets) |
| Hourly cap | none published | none published, bursts can trigger a temporary block | none published |
| Sender email | the address you verify in Brevo (Senders & IP → Senders) | the Gmail address itself | the address verified under Single Sender Verification |
| Sender name | `MedConf` | `MedConf` | `MedConf` |
| Host | `smtp-relay.brevo.com` | `smtp.gmail.com` | `smtp.sendgrid.net` |
| Port | `587` | `587` (STARTTLS) or `465` (SSL) | `587` |
| Username | your Brevo login email | the full Gmail address | the literal text `apikey` |
| Password | an SMTP key (Brevo → SMTP & API → SMTP keys), not your login password | the 16-character App Password, entered without spaces | an API key with "Mail Send" permission |
| One-time setup | Verify the sender email by clicking the link Brevo mails to it | Turn on 2-Step Verification, then Google Account → Security → App passwords | Settings → Sender Authentication → Single Sender Verification |

Recommendation: Brevo for headroom (300/day and a proper sending service); Gmail for zero sign-up friction (no new account if you already have one). If you use Gmail, create a dedicated account such as `medconf.noreply@gmail.com` rather than using a personal address, because the App Password gives SMTP access to that whole mailbox and replies land there.

Limits of the no-domain route: mail is sent from a shared or free-mail domain, so SPF/DKIM alignment is weaker, and the first messages may land in spam. Gmail also rewrites the sender to the authenticated address. Move to 3b once a domain exists.

### 3b. When a domain exists: Resend

Free mail domains such as gmail.com or hotmail.com cannot be verified with Resend.

1. Create a Resend account.
2. Domains → Add Domain → enter the domain (a subdomain such as `mail.<domain>` is fine). Add the DNS records Resend lists (SPF, DKIM, optionally DMARC) at your DNS host. Wait until the domain shows Verified.
3. API Keys → create a key with "Sending access" for that domain. Copy it once.
4. Supabase Dashboard → Authentication → SMTP Settings → enable custom SMTP:
   - Host `smtp.resend.com`
   - Port `465`
   - Username `resend`
   - Password: the API key
   - Sender email `no-reply@<domain>`
   - Sender name `MedConf`
5. Save, then raise the email rate limit (3d) and run the smoke test (3e).

Never put the API key in the repo or in `config.toml`; if you need it locally use `env(RESEND_API_KEY)`.

### 3c. Two ways to apply

**Dashboard.** Authentication → SMTP Settings for the sender (values from 3a or 3b). Authentication → Email Templates for the six templates: paste each HTML file and its subject, as in section 2.

**Script.** `scripts/supabase_auth_setup.py` (Python 3.11, standard library only) pushes the templates and the SMTP settings through the Supabase Management API.

1. Create a personal access token: Supabase dashboard → Account (top-right avatar) → Access Tokens → Generate new token. It starts with `sbp_`. The token acts as you on every project in your account, so treat it like a password. Keep it in the shell environment only, never in a file, and revoke it from the same page when you are done.
2. Export the variables in your shell. Typing a leading space before each `export` keeps it out of bash history when `HISTCONTROL=ignorespace` is set.

```bash
export SUPABASE_ACCESS_TOKEN=sbp_...            # personal access token
export SUPABASE_PROJECT_REF=zcpszfbmvfylicpxgsfc # optional, this is the default
export SMTP_HOST=smtp-relay.brevo.com
export SMTP_PORT=587
export SMTP_USER=you@example.com
export SMTP_PASS=...                             # SMTP key / app password / API key
export SMTP_SENDER_EMAIL=medconf.noreply@example.com
export SMTP_SENDER_NAME=MedConf                  # optional, default MedConf
export SMTP_RATE_LIMIT_EMAILS_PER_HOUR=100       # optional, see 3d
```

3. Run, with `--dry-run` first on each (prints field names and sizes, sends nothing, needs no token):

```bash
python3 scripts/supabase_auth_setup.py templates --dry-run
python3 scripts/supabase_auth_setup.py templates
python3 scripts/supabase_auth_setup.py smtp --dry-run
python3 scripts/supabase_auth_setup.py smtp
python3 scripts/supabase_auth_setup.py show
```

After each real push the script re-reads the config and prints only non-secret fields (site URL, redirect allow-list, OTP expiry, SMTP host/port/user/sender, the six subjects and the first 80 characters of each body). It never prints the token or the SMTP password. When finished, `unset` the variables and revoke the token.

### 3d. Rate limits after enabling custom SMTP

Supabase starts a project with custom SMTP at 30 emails per hour. Raise it under Authentication → Rate Limits (or set `SMTP_RATE_LIMIT_EMAILS_PER_HOUR` for the script). Keep it below the provider's daily cap divided by 24 for steady use, and remember that every sign-up, reset and email change counts. Section 5 has the full table.

### 3e. Smoke test

1. Sign up on the live site with an address that is not on the team (a personal address of a friend or a second mailbox of yours).
2. Confirm the email arrives (check spam on the first send) with the right subject and a teal button.
3. Open the link on a different device from the one that signed up, for example the phone if you signed up on the laptop.
4. Expect to land signed in on `/onboarding`. A "verification failed" message means the template still uses `{{ .ConfirmationURL }}` instead of the `token_hash` link.
5. Repeat once for forgot password; the link should end on `/auth/reset-password`.

## 4. Test plan

With a team-member address (or, once SMTP is live, any address you own):
1. Trigger each email once: sign up (confirm), forgot password (recovery), change email in settings (email change, expect two messages if double confirm is on), Dashboard → Users → Invite (invite). Magic link and reauthentication only if you enable a flow that sends them; otherwise use the dashboard "Send magic link" action.
2. For each, open in Gmail web, Apple Mail and Outlook web, in light and dark mode.
3. Check: subject matches the table, the button is teal with legible white text, the fallback URL shows in full and wraps, no horizontal scroll at phone width, the footer line is present, and the button link lands on the right page (`/onboarding` after confirm, `/auth/reset-password` after recovery).
4. Check the spam folder on the first send from a new domain and view the message headers for `dkim=pass` and `spf=pass`.

## 5. Rate limits

| Setting | Local `config.toml` | Hosted default |
|---|---|---|
| Emails sent per hour (`email_sent`) | 2 | 2 on the built-in sender; adjustable only after custom SMTP is enabled (Authentication → Rate Limits) |
| Minimum gap between confirm/reset emails (`max_frequency`) | 1 s | 60 s |
| Sign-up / sign-in requests per 5 min per IP | 30 | 30 |
| OTP / magic-link verifications per 5 min per IP | 30 | 30 |

The hosted figures are the dashboard defaults as I know them and were not checked against the live project; confirm them on the Rate Limits page. After custom SMTP is on, raise emails per hour to something that fits expected sign-ups. The site already shows "Too many reset emails have been sent recently" when the limit is hit.
