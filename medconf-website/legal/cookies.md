---
title: Cookie Policy
slug: /cookies
status: Plain-English rewrite, 31 Oct 2026 — not yet reviewed by a solicitor
last_updated: "31 October 2026"
---

<!--
  NOTES FOR CLAUDE CODE (not rendered)
  - This page describes cookies by category on purpose (owner's choice, 31 Oct 2026). The exact list lives here so
    we can answer detailed questions — keep it in sync with the code:
      Essential cookies: sb-<project-ref>-auth-token (chunked .0/.1; up to 400 days or sign-out),
        sb-<project-ref>-auth-token-code-verifier (PKCE, removed after the step), mc_next (1 hour),
        mc_consent (cookie choice, 6 months).
      Local storage: medconf-theme, medconf-accent, medconf:recent-searches, medconf:submit-draft:<user id>.
      Analytics (after consent only): _ga, _ga_M2DLMQR888 (~13 months; cookie_expires in src/lib/analytics/config.ts).
  - Re-audit (document.cookie, cookies().set, localStorage, sessionStorage, <script>, <iframe>) whenever a feature is
    added; update this page if a new category, purpose or third party appears, and bump last_updated.
  - Consent banner: src/components/analytics/CookieConsent.tsx. Bump CONSENT_VERSION in src/lib/analytics/consent.ts if
    the banner starts asking consent for anything else.
  - FUTURE: advertising / affiliate tracking cookies need prior consent — add a separate banner choice and a section here.
-->

# Cookie Policy

**Last updated:** 31 October 2026

This page explains the cookies and similar technologies MediCon uses, and how you can control them.

## In short

- We use a few **essential cookies** to keep you signed in, and we save some **preferences** (like light or dark mode) in your browser.
- With your permission, we use **Google Analytics** to understand how the site is used. These cookies are only set if you click **"Accept analytics"** — if you reject them or ignore the banner, they're never set.
- We don't use advertising or social media tracking cookies.
- You can change your mind at any time using **Cookie settings** at the bottom of every page.

## What cookies are

Cookies are small text files a website saves in your browser so it can remember you. Local storage works in a similar way, but the information stays on your device and isn't sent to us.

## The cookies we use

**Essential cookies** keep you signed in, take you back to the right page after you sign in, and remember your cookie choice. The site can't work without them, so they can't be switched off. They last from an hour up to about a year, or until you sign out.

**Preferences** such as light or dark mode, your recent searches and any event submission you're still writing are saved in your browser only. We never receive them, and they stay until you clear your browser data.

**Analytics cookies (only if you accept).** Google Analytics sets two cookies that tell visits apart, so we can see which pages are popular and how people find us. We've set it up to remove personal details from page addresses and to switch off Google's advertising features. These cookies last about 13 months, and we delete them if you change your mind in Cookie settings. The information is processed by Google — you can read [how Google uses this information](https://policies.google.com/technologies/partner-sites).

## Other websites

When you click through to an organiser's website or a map, that site may use its own cookies. We don't embed these services in our pages, so they can't set cookies through MediCon.

## Managing cookies

Use **Cookie settings** at the bottom of any page to change your analytics choice. You can also delete cookies and site data in your browser settings — just note that deleting the essential cookies will sign you out.

## Changes and questions

We'll update this page if the cookies we use change, and we'll always ask before setting any new cookies that need your permission. Questions? Email us at hellomedicon@gmail.com.
