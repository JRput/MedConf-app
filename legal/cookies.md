---
title: Cookie Policy
slug: /cookies
status: DRAFT — not yet reviewed by a solicitor
last_updated: "[[PLACEHOLDER: publication date]]"
---

<!--
  DRAFT NOTES FOR CLAUDE CODE (do not render)
  - The table below reflects the code as of 31 Oct 2026. Re-audit (grep for document.cookie, cookies().set,
    localStorage, sessionStorage, third-party <script>/<iframe>) before publishing and whenever a feature is added.
  - The Supabase cookie name includes the project ref (currently zcpszfbmvfylicpxgsfc). Replace [project-ref] if you
    prefer to show the exact name, and update it if the Supabase project changes.
  - A consent banner exists for Google Analytics (src/components/analytics/CookieConsent.tsx). Adding ads, affiliate tracking,
    embedded maps/videos or Cloudflare Turnstile means revisiting this page and the banner text; bump CONSENT_VERSION in
    src/lib/analytics/consent.ts if the banner starts asking for more. See legal/CLAUDE_CODE_BRIEF.md.
-->

# Cookie Policy

**Last updated:** [[PLACEHOLDER: publication date]]

This policy explains how MediCon uses cookies and similar technologies on our website.

## The short version

- We use cookies and device storage that are **needed to make the site work** or that **remember choices you make**, such as light or dark mode. UK law allows these without consent, as long as we explain them clearly — which is what this page does.
- With your permission, we also use **Google Analytics** cookies to understand how the site is used. These are **only set if you click "Accept analytics"** in our cookie banner. If you reject them, or ignore the banner, they're never set.
- We **don't** use advertising, social media or cross-site tracking cookies.
- You can change your choice at any time using **Cookie settings** at the bottom of every page.

## What are cookies and local storage?

**Cookies** are small text files a website saves on your device so it can recognise your browser. **Local storage** is a similar feature that lets a website save small amounts of information in your browser. Information in local storage stays on your device and isn't sent to us automatically.

## What we use

### Strictly necessary cookies

These keep you signed in and make sign-in work securely. The Platform can't work without them.

| Name | Purpose | How long it lasts |
|---|---|---|
| `sb-[project-ref]-auth-token` (may be split into parts ending `.0`, `.1`, …) | Keeps you signed in to your account. Set by our authentication provider, Supabase, on our own domain | Up to 400 days, or until you sign out |
| `sb-[project-ref]-auth-token-code-verifier` | A one-time security code used while you sign in, verify your email or reset your password | Short-lived; normally removed once the step is complete |
| `mc_next` | Remembers the page you were trying to reach, so we can take you back there after you sign up or verify your email | 1 hour |
| `mc_consent` | Remembers whether you accepted or rejected analytics cookies, so we don't ask you on every page | 6 months |

### Preferences stored on your device (local storage)

These remember choices you make. They're only saved on your device, and we never receive them.

| Name | Purpose | How long it lasts |
|---|---|---|
| `medconf-theme` | Remembers whether you chose light or dark mode | Until you clear your browser storage |
| `medconf-accent` | Remembers the colour accent you chose | Until you clear your browser storage |
| `medconf:recent-searches` | Remembers your recent searches in the quick-search box so you can repeat them | Until you clear your browser storage |
| `medconf:submit-draft:<user id>` | Keeps your in-progress "Submit an event" form (event details and fee rows you have typed) so a page reload does not lose it; removed when the submission is sent or you clear it | Until sent or cleared |

### Analytics cookies — only if you accept

If you click **"Accept analytics"**, we load Google Analytics, which sets these cookies on our website to tell visits apart and measure how the site is used. We've configured it to remove personal details from page addresses and to turn off Google's advertising features. The information is sent to Google — see [how Google uses information from sites that use its services](https://policies.google.com/technologies/partner-sites).

| Name | Purpose | How long it lasts |
|---|---|---|
| `_ga` | Distinguishes one visitor's browser from another with a random identifier | About 13 months |
| `_ga_M2DLMQR888` | Keeps track of your current visit (session) | About 13 months |

If you later choose **"Reject analytics"** in Cookie settings, we delete these cookies and stop loading Google Analytics. You can also install Google's [opt-out browser add-on](https://tools.google.com/dlpage/gaoptout).

<!-- If GA settings change (Google signals, advertising features, user-ID, cookie lifetime in src/lib/analytics/config.ts), update this section. If a cookieless/first-party analytics tool replaces GA, note the PECR statistical-purposes exemption (in force since 5 Feb 2026) requires clear info + a simple opt-out. -->

<!-- FUTURE: advertising, sponsored listings and affiliate links. Ad networks and affiliate tracking almost always use cookies that need prior consent. Before launch: add a consent banner (reject as easy as accept, nothing non-essential set before consent), list each cookie and provider here, and add a "Cookie settings" link in the footer. -->

<!-- FUTURE: Cloudflare Turnstile (bot protection on sign-up/sign-in) — list its cookie/storage use here as strictly necessary for security. -->

## Third-party websites

MediCon links to event organisers' websites and to services such as Google Maps. We don't embed these services in our pages, so they can't set cookies through MediCon. If you follow a link, the other website may use its own cookies — please check its cookie policy.

## How to control cookies and local storage

You can change your analytics choice at any time using **Cookie settings** at the bottom of every page.

You can also block or delete cookies and clear local storage in your browser settings. Most browsers explain how in their help pages. If you block or delete the strictly necessary cookies, you'll be signed out and won't be able to use the parts of MediCon that need an account. Clearing local storage resets your display preferences and recent searches.

## Changes to this policy

We'll update this page if we change the cookies or similar technologies we use. The date at the top shows when it was last updated. If we start using any other cookies that need your consent, we'll ask for it before setting them.

## Contact us

Questions about cookies: **hellomedicon@gmail.com**. For more about how we handle personal information, see our [Privacy Policy](/privacy).
