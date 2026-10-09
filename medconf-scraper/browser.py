# browser.py
"""Browser automation layer - Playwright wrapper for web navigation."""

from playwright.sync_api import sync_playwright, Page, Browser, Playwright
from config import SCRAPER_DELAY_SECS, SCRAPER_TIMEOUT_MS
from typing import List, Dict, Any, Optional
import re
import time


# Cloudflare's interstitial. Real pages embed Turnstile scripts too, so only
# the <title> is a safe marker (learned the hard way 2026-09-26).
_CHALLENGE_TITLE_RE = re.compile(r"<title>\s*(?:just a moment|attention required|human verification|security verification|verify you are human|access denied|403 - forbidden)", re.I)

# Strong markers: only ever present on a real interstitial (never on a page that
# merely embeds Cloudflare's passive /cdn-cgi/challenge-platform/ script).
_CHALLENGE_STRONG_RE = re.compile(
    r"sgcaptcha|cf-chl|cf_chl_opt|__cf_chl_rt_tk|cf-browser-verification|"
    r"checking your browser|aws-waf-token",
    re.I,
)
# Weak markers: also appear on ordinary pages (login-form Turnstile widgets,
# AWS WAF captcha script tags, the phrase "just a moment" in copy). They only
# count when the page has no real content shape (<=1 link).
_CHALLENGE_WEAK_RE = re.compile(r"turnstile|awswaf|aws\s*waf|just a moment|attention required", re.I)
_ANCHOR_RE = re.compile(r"<a\s[^>]*href=", re.I)
_BLOCKED_STATUSES = {403, 429, 503}


def looks_like_challenge(html, status=None) -> bool:
    """True if `html` (and optional HTTP status) is a bot-challenge interstitial.

    Shared by BrowserController._is_challenged and extractors.http_fetch.
    The passive challenge-platform script alone is NOT a challenge.
    """
    if status in _BLOCKED_STATUSES:
        return True
    head = html or ""
    if _CHALLENGE_TITLE_RE.search(head[:5000]):
        return True
    if _CHALLENGE_STRONG_RE.search(head):
        return True
    if _CHALLENGE_WEAK_RE.search(head) and len(_ANCHOR_RE.findall(head)) <= 1:
        return True
    return False


def has_content_shape(html) -> bool:
    """A real listing/detail page links to more than one place."""
    return len(_ANCHOR_RE.findall(html or "")) > 1


# Alternate browser profile — a plain desktop Chrome. Cloudflare's managed
# challenge is configured per site: RCoA / FICM / ARVO / HIMSS / ABN reject
# Playwright's default headless profile ("HeadlessChrome" UA, no locale,
# 1280x720) but accept this one, while RSM does the exact opposite and
# BTOG's host 403s this UA outright. So neither profile can be THE default:
# navigate() starts on the default (proven across 39 sources) and switches
# to this profile for the rest of the session the first time a page comes
# back challenged. Measured 2026-09-26 with probe_headed.py.
ALT_PROFILE = {
    "user_agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "viewport": {"width": 1366, "height": 850},
    "locale": "en-GB",
}


class BrowserController:
    """Wrapper around Playwright for browser automation."""
    
    def __init__(self):
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self._alt_context = None   # created lazily on first challenge
        self._on_alt_profile = False
        # Anti-bot evidence for scrape_source: bumped whenever a page stays
        # challenged after every browser profile has been tried.
        self.challenged_count = 0
        self.last_challenge_url: Optional[str] = None

    def launch(self) -> None:
        """Launch a headless Chromium browser and open a blank page."""
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=True)
        self.page = self.browser.new_page()
        self.page.set_default_timeout(SCRAPER_TIMEOUT_MS)

    def navigate(self, url: str) -> str:
        """Navigate to a URL and return the page text content."""
        if not self.page:
            raise RuntimeError("Browser not launched. Call launch() first.")
        
        # Use 'load' instead of 'networkidle' to avoid hanging on pages with continuous network activity
        # 'load' waits for the load event, which is more reliable and faster
        # Add timeout to prevent indefinite hanging
        try:
            self.page.goto(url, wait_until="load", timeout=SCRAPER_TIMEOUT_MS)
        except Exception as e:
            # If load fails, try domcontentloaded as fallback (faster, less reliable but better than hanging)
            try:
                self.page.goto(url, wait_until="domcontentloaded", timeout=SCRAPER_TIMEOUT_MS)
            except Exception as e2:
                # If both fail, log error but continue - page might still have usable content
                import logging
                logger = logging.getLogger("medconf-scraper")
                logger.warning(f"Navigation timeout for {url}, attempting to get page content anyway: {str(e2)}")
        
        if self._is_challenged() and not self._on_alt_profile:
            self._wait_out_challenge()   # first time only: some clear on their own
        if self._is_challenged():
            # First challenge: move to the alternate profile. Later
            # challenges: the alt context's clearance only lasts ONE load on
            # some sites (FICM, RCoA — measured 2026-09-27: page 2 of the
            # same site is re-challenged and never resolves), whereas a
            # brand-new alt context clears in <1 s every time. So rotate.
            self._switch_to_alt_profile(url)

        time.sleep(SCRAPER_DELAY_SECS)  # Respectful delay
        return self.get_page_text()

    # --- Cloudflare challenge handling ---------------------------------
    def _is_challenged(self) -> bool:
        try:
            return looks_like_challenge(self.page.content())
        except Exception:
            return False

    def _wait_out_challenge(self, max_s: float = 8.0) -> None:
        """Some challenges auto-resolve via JS in a few seconds; give them a chance."""
        deadline = time.time() + max_s
        while time.time() < deadline and self._is_challenged():
            self.page.wait_for_timeout(1000)

    def _switch_to_alt_profile(self, url: str) -> None:
        """Re-open the page in a FRESH alternate-profile context and stay on
        it. If that is challenged too, fall back to the previous page so
        callers see the same (challenged) content they would have anyway."""
        import logging
        logger = logging.getLogger("medconf-scraper")
        try:
            prev_context = self._alt_context
            old_page = self.page
            # Fresh alt-profile context first; if that is challenged too, a
            # fresh DEFAULT-profile context (sites like RSM reject the alt
            # profile but accept the default — only matters if one session
            # ever spans both kinds of site).
            for profile in (ALT_PROFILE, {}):
                self._alt_context = self.browser.new_context(**profile)
                alt_page = self._alt_context.new_page()
                alt_page.set_default_timeout(SCRAPER_TIMEOUT_MS)
                alt_page.goto(url, wait_until="load", timeout=SCRAPER_TIMEOUT_MS)
                self.page = alt_page
                self._wait_out_challenge(4.0)
                if not self._is_challenged():
                    break
                self._alt_context.close()
            else:
                self.page = old_page
                self._alt_context = prev_context
                self.challenged_count += 1
                self.last_challenge_url = url
                logger.warning(f"Cloudflare challenge on {url} not cleared by either browser profile")
                return
            if not self._on_alt_profile:
                logger.warning(f"Cloudflare challenge on {url}: switched to alternate browser profile for this session")
            self._on_alt_profile = True
            old_page.close()
            if prev_context is not None:
                try:
                    prev_context.close()
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Alternate browser profile failed for {url}: {e}")

    def get_page_text(self) -> str:
        """Extract all visible text from the current page."""
        if not self.page:
            raise RuntimeError("Browser not launched.")
        return self.page.inner_text("body")

    def get_page_links(self) -> List[Dict[str, str]]:
        """Extract all links (href + text) from the current page."""
        if not self.page:
            raise RuntimeError("Browser not launched.")
        
        links = self.page.evaluate("""() => {
            return Array.from(document.querySelectorAll('a')).map(a => ({
                href: a.getAttribute('href'),
                text: a.innerText.trim()
            })).filter(a => a.href && a.text);
        }""")
        return links

    def get_current_url(self) -> str:
        """Return the current page URL."""
        if not self.page:
            raise RuntimeError("Browser not launched.")
        return self.page.url

    def get_event_cards(self) -> List[Dict[str, Any]]:
        """
        Walk the rendered DOM of a listing page and return a structured list of
        event-card shells: title, booking_url, is_sold_out, start_date, start_time,
        location_hint. Deterministic — no LLM involved.

        Generalised for three real-world card layouts:
          - RCGP: <h2/h3 in card> + "DATE\\n07 May 2026" + "START TIME\\n09:00"
          - RSM:  <article class="m-event-block"> + "Date\\nTue 12 May 2026"
          - RCSEng: <div class="resultMain"> + stacked "WED\\n20\\nMAY\\n2026"
        Falls back gracefully on other layouts.
        """
        if not self.page:
            raise RuntimeError("Browser not launched.")

        cards = self.page.evaluate("""() => {
            // Month lookup — case-insensitive, accepts 3-letter or full names + 'sept'
            const monthMap = {
              jan:1, feb:2, mar:3, apr:4, may:5, jun:6, jul:7, aug:8, sep:9, sept:9, oct:10, nov:11, dec:12,
              january:1, february:2, march:3, april:4, june:6, july:7, august:8,
              september:9, october:10, november:11, december:12
            };
            const monthFromString = (s) => {
              if (!s) return null;
              const k = s.toLowerCase();
              return monthMap[k] || monthMap[k.slice(0,3)] || null;
            };

            // Two parallel passes of candidate container detection. The order
            // matters: process SPECIFIC selectors first (Pass A), then the generic
            // heading walk-up (Pass B). When both produce blocks for the same
            // event, the specific selector typically captures more context (date
            // labels are often siblings of the heading, not children) and the
            // generic walk-up gets de-duplicated.
            const candidateBlocks = [];
            const seenBlocks = new Set();
            const addBlock = (el) => {
              if (el && !seenBlocks.has(el)) { seenBlocks.add(el); candidateBlocks.push(el); }
            };

            // Pass A: container-class fingerprints common across event listings
            const containerSelectors = [
              'article[class*="event"]',
              '[class*="event-block"]',
              '[class*="eventBlock"]',
              '[class*="event-card"]',
              '[class*="eventCard"]',
              '[class*="event-item"]',
              '[class*="eventItem"]',
              '.resultMain',                                  // RCSEng calendar
              '[class*="search-results__result"]',
              '.event-results__result',                       // RCP upcoming-events cards
            ];
            for (const sel of containerSelectors) {
              for (const el of document.querySelectorAll(sel)) {
                addBlock(el);
              }
            }
            // Pass B: walk up from headings to a reasonable container
            for (const h of document.querySelectorAll('h1, h2, h3, h4')) {
              const block = h.closest('article, li, section, div');
              if (block) addBlock(block);
            }

            const seenTitles = new Set();
            const out = [];

            const isEventUrl = (h) => {
              if (!h) return false;
              return /engage\\.|eventbrite|\\/event\\/|\\/events?\\/[a-z]|conference|rcgpac|rsmevents|event-booking|\\/calendar\\/[a-z]/i.test(h);
            };
            const isListingUrl = (h) => {
              if (!h) return true;
              // Catches the listing page itself, including paginated variants
              return /\\/events\\/?(\\?page=\\d+)?(#|$)|\\/calendar\\/?#\\/?(.*)?$|\\/search-results\\/?(\\?|#|$)/i.test(h);
            };

            for (const block of candidateBlocks) {
              const blockText = (block.innerText || '').trim();
              if (!blockText || blockText.length < 20) continue;
              // Size guard: real event cards are concise. A "block" that's more
              // than 1500 chars or has more than 5 anchors is almost always a
              // wrapper container (page section, results wrapper, footer) — skip.
              if (blockText.length > 1500) continue;

              // Anchors inside the block, excluding the listing page itself
              const anchors = Array.from(block.querySelectorAll('a[href]'))
                .filter(a => a.href && !a.href.endsWith('#') && a.href !== document.location.href);
              if (anchors.length === 0) continue;
              if (anchors.length > 5) continue;

              // Title — prefer first heading inside block; else the longest anchor text
              let title = '';
              const heading = block.querySelector('h1, h2, h3, h4');
              if (heading && heading.innerText.trim().length >= 5) {
                title = heading.innerText.trim();
              } else {
                let longest = anchors[0];
                for (const a of anchors) {
                  if ((a.innerText || '').trim().length > (longest.innerText || '').trim().length) longest = a;
                }
                title = (longest.innerText || '').trim();
              }
              if (!title || title.length < 5) continue;
              if (seenTitles.has(title)) continue;

              // Booking URL — prefer event-y URLs; else first non-listing anchor
              let bookingUrl = null;
              for (const a of anchors) {
                if (isEventUrl(a.href) && !isListingUrl(a.href)) { bookingUrl = a.href; break; }
              }
              if (!bookingUrl) {
                for (const a of anchors) {
                  if (!isListingUrl(a.href)) { bookingUrl = a.href; break; }
                }
              }
              if (!bookingUrl) continue;

              // Sold-out indicator
              const isSoldOut = /\\bsold\\s*out\\b/i.test(blockText);

              // Category badge (RCP exposes .event-results__first-tag with values
              // like Conference / Workshop / Webinar / Social / Ceremony). Resolve
              // it from the enclosing card so both detection passes see the badge.
              // Null for sources that don't use this markup.
              let category = null;
              const cardRoot = block.closest('.event-results__result') ||
                               (block.classList && block.classList.contains('event-results__result') ? block : null);
              const catEl = (cardRoot || block).querySelector('.event-results__first-tag, [class*="first-tag"]');
              if (catEl) category = (catEl.textContent || '').trim();
              // Exclude ceremony events entirely — admission/graduation ceremonies
              // are not CPD/conference content. Match on the badge or the title.
              if ((category && /ceremon(y|ies)/i.test(category)) || /\\bceremon(y|ies)\\b/i.test(title)) continue;

              // Date — try three formats, in priority order
              let startDate = null;
              // (a) Stacked four-line (RCSEng): WED\\n20\\nMAY\\n2026
              let m = blockText.match(/(?:MON|TUE|WED|THU|FRI|SAT|SUN)\\s*\\n\\s*(\\d{1,2})\\s*\\n\\s*([A-Z][A-Za-z]+)\\s*\\n\\s*(\\d{4})/);
              // (b) DATE/Date label + date (RCGP): "DATE\\n07 May 2026" or "Date\\nTue 12 May 2026"
              if (!m) {
                m = blockText.match(/(?:DATE|Date)\\s*\\n?\\s*(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\\s+)?(\\d{1,2})\\s+([A-Za-z]{3,})\\s+(\\d{4})/);
              }
              // (c) Weekday-prefixed inline (RSM): "Tue 12 May 2026"
              if (!m) {
                m = blockText.match(/(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\\s+(\\d{1,2})\\s+([A-Za-z]{3,})\\s+(\\d{4})/);
              }
              if (m) {
                const day = parseInt(m[1], 10);
                const monNum = monthFromString(m[2]);
                const year = parseInt(m[3], 10);
                if (monNum) {
                  startDate = `${year}-${String(monNum).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
                }
              }

              // Start time — RCGP style label
              let startTime = null;
              const tm = blockText.match(/START\\s*TIME\\s*\\n?\\s*(\\d{1,2}):(\\d{2})/i);
              if (tm) {
                startTime = `${tm[1].padStart(2,'0')}:${tm[2]}`;
              }

              // Location hint
              let locationHint = null;
              const pipeParts = title.split('|').map(s => s.trim()).filter(Boolean);
              // Only treat pipe-suffix as a location when:
              //   (a) There are 3+ pipes (typical "Topic | Subtopic | Location" format), OR
              //   (b) The suffix is a known UK city / "Online" / "Webinar" keyword.
              // 2-pipe titles like "Diabetes | One Day Essentials" are topic+subtitle, NOT location.
              const knownPlace = /^(London|Manchester|Liverpool|Leeds|Sheffield|York|Newcastle|Middlesbrough|Birmingham|Bristol|Exeter|Cardiff|Swansea|Edinburgh|Glasgow|Belfast|Cambridge|Norwich|Oxford|Brighton|Doncaster|Warrington|Reigate|Online|Webinar|Hybrid)$/i;
              if (pipeParts.length >= 3) {
                locationHint = pipeParts[pipeParts.length - 1];
              } else if (pipeParts.length === 2 && knownPlace.test(pipeParts[1])) {
                locationHint = pipeParts[1];
              }
              if (!locationHint && /\\bonline\\b/i.test(blockText) && !/\\bin[- ]person\\b/i.test(blockText)) {
                locationHint = 'Online';
              }
              // Detect "Webinar" mention as an online signal
              if (!locationHint && /\\bwebinar\\b/i.test(blockText)) {
                locationHint = 'Online';
              }
              // RSM/RCSEng often have "Location\\n<text>" pattern
              if (!locationHint) {
                const lm = blockText.match(/Location\\s*\\n\\s*([^\\n]+)/);
                if (lm) {
                  const loc = lm[1].trim();
                  if (/^online/i.test(loc) || /\\bwebinar\\b/i.test(loc)) {
                    locationHint = 'Online';
                  } else {
                    // Filter UK postcodes out before picking the city — they're never
                    // the city even though they sit second-to-last in addresses.
                    const ukPostcode = /^[A-Z]{1,2}\\d[A-Z\\d]?\\s*\\d[A-Z]{2}$/i;
                    const parts = loc.split(',')
                      .map(s => s.trim())
                      .filter(s => s && !ukPostcode.test(s));
                    if (parts.length >= 3) {
                      // Format: venue, [street, area, ...,] city, country → second-to-last is city
                      locationHint = parts[parts.length - 2];
                    } else if (parts.length === 2) {
                      locationHint = parts[1]; // venue, city
                    } else if (parts.length === 1) {
                      locationHint = parts[0];
                    }
                  }
                }
              }

              // Quality filter — must have booking URL and either a date or strong-event URL
              if (!startDate && !isEventUrl(bookingUrl)) continue;

              // Reject "shallow" event URLs that are actually faculty/year listings
              // (e.g. RSM /events/<faculty>/<year>/ with no event slug after).
              // A real event detail URL has at least 3 path segments after /events/.
              try {
                const u = new URL(bookingUrl);
                if (u.hostname.endsWith('rsm.ac.uk')) {
                  const segs = u.pathname.split('/').filter(Boolean);
                  // /events/<faculty>/<year>/ = 3 segments → faculty page; need 4+
                  const eventsIdx = segs.indexOf('events');
                  if (eventsIdx >= 0 && segs.length - eventsIdx <= 3) continue;
                }
              } catch (e) { /* malformed URL — fall through to keep the card */ }

              // Description hint — useful for sources whose detail pages are
              // thin (e.g. RCGP engage subdomain). We grab the longest paragraph
              // text inside the card that ISN'T the title or one of the labels.
              let descriptionHint = null;
              try {
                const noiseRe = /^(date|location|start time|book|sold out|cpd|when|where|format|new|filters?)$/i;
                const candidates = Array.from(block.querySelectorAll('p, div, span'))
                  .map(el => (el.innerText || '').trim())
                  .filter(t => t.length > 60 && t.length < 800 && t !== title && !noiseRe.test(t));
                if (candidates.length > 0) {
                  // Pick the longest, but cap at 600 chars
                  candidates.sort((a, b) => b.length - a.length);
                  descriptionHint = candidates[0].slice(0, 600);
                }
              } catch (e) { /* keep null on any failure */ }

              seenTitles.add(title);
              out.push({
                title,
                booking_url: bookingUrl,
                is_sold_out: isSoldOut,
                start_date: startDate,
                start_time: startTime,
                location_hint: locationHint,
                description_hint: descriptionHint,
                category: category
              });
            }
            return out;
        }""")
        return cards

    def get_event_cards_paginated(self, source: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Walk all listing pages for a source and aggregate event-card shells.

        Behaviour depends on the source's pagination_type:
          - single_page:      one navigation, one get_event_cards() call
          - page_query:       iterate ?page=1..N using pagination_template
          - next_link:        TODO (follow rel=next anchors)
          - infinite_scroll:  TODO (scroll-and-wait)

        Stops walking when:
          * max_pages_hint reached
          * a page returns 0 NEW cards (deduplicated by booking_url)
          * 2 consecutive pages return 0 new cards (lenient stop)
          * absolute safety cap of 60 pages
          * page navigation fails
        """
        if not self.page:
            raise RuntimeError("Browser not launched.")

        ptype = (source.get("pagination_type") or "single_page").lower()
        base_url = source["base_url"]

        if ptype != "page_query":
            # Fallback: single-page walk
            self.navigate(base_url)
            self.page.wait_for_timeout(2000)
            return self.get_event_cards()

        template = source.get("pagination_template") or "?page={n}"
        max_pages = source.get("max_pages_hint")
        seen_urls = set()
        all_shells: List[Dict[str, Any]] = []
        consecutive_empty = 0
        page_num = 1
        # Soft cap so a mis-configured source can't run away forever
        SAFETY_CAP = 60

        while page_num <= SAFETY_CAP:
            url = base_url + template.replace("{n}", str(page_num))
            try:
                self.navigate(url)
                self.page.wait_for_timeout(2000)  # extra settle for SPAs
            except Exception as e:
                import logging
                logging.getLogger("medconf-scraper").warning(
                    f"  Pagination: page {page_num} navigation failed ({e}); stopping"
                )
                break

            # On the first page, auto-detect max_pages if not pre-configured
            if page_num == 1 and not max_pages:
                detected = self._detect_max_pages()
                if detected and detected > 1:
                    max_pages = detected
                    import logging
                    logging.getLogger("medconf-scraper").info(
                        f"  Pagination: auto-detected {max_pages} total pages"
                    )

            shells = self.get_event_cards()
            new_count = 0
            for s in shells:
                bu = s.get("booking_url")
                if bu and bu not in seen_urls:
                    seen_urls.add(bu)
                    s["page_index"] = page_num
                    all_shells.append(s)
                    new_count += 1

            import logging
            logging.getLogger("medconf-scraper").info(
                f"  Pagination: page {page_num} → {len(shells)} cards, {new_count} new (running total {len(all_shells)})"
            )

            if new_count == 0:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    break
            else:
                consecutive_empty = 0

            if max_pages and page_num >= max_pages:
                break

            page_num += 1

        return all_shells

    # ------------------------------------------------------------------------
    # Multi-page hub crawler — for sources whose "detail page" is actually the
    # homepage of a small subsite with info split across sub-pages.
    # Example: rcgpac.org.uk has /tickets, /programme, /abstract-submissions
    # etc. — none of which appear on the landing page.
    # ------------------------------------------------------------------------
    # Same-domain link path keywords that probably contain event detail
    URL_ALLOWLIST_KEYWORDS = [
        "programme", "ticket", "venue", "location", "abstract", "poster",
        "overview", "speakers", "registration", "register", "whats-on",
        "what-s-on", "faqs", "faq", "agenda", "schedule", "about", "info",
        "highlights",
    ]
    # Same-domain link path keywords we never want to follow
    URL_BLOCKLIST_KEYWORDS = [
        "cookie", "privacy", "terms", "accessibility", "sustainability",
        "sponsor", "exhibit", "phishing", "contact", "press", "media",
        "policy", "covid", "social-and-networking",
    ]

    def fetch_multi_page_text(
        self,
        start_url: str,
        max_pages: int = 8,
    ) -> Dict[str, str]:
        """
        Visit start_url + up to (max_pages-1) same-domain sub-pages whose URL
        path matches the event-relevance allowlist. Returns {url -> textContent}.

        Used for detail pages that are micro-websites (e.g. annual conference
        landing pages with /tickets, /programme, /abstracts sub-pages).
        """
        if not self.page:
            raise RuntimeError("Browser not launched.")

        pages: Dict[str, str] = {}

        # 1. Visit the start page
        try:
            self.navigate(start_url)
            self.page.wait_for_timeout(2000)
            pages[start_url] = self.page.evaluate("() => document.body.textContent || ''") or ""
        except Exception as e:
            import logging
            logging.getLogger("medconf-scraper").warning(
                f"  fetch_multi_page_text: start navigation failed for {start_url}: {e}"
            )
            return pages

        # 2. Discover same-domain candidate URLs (allowlist filter)
        try:
            candidates = self.page.evaluate(
                """({allowlist, blocklist}) => {
                    const out = [];
                    const seen = new Set();
                    const start = new URL(document.location.href);
                    const startPath = start.origin + start.pathname;
                    document.querySelectorAll('a[href]').forEach(a => {
                        try {
                            const u = new URL(a.href);
                            if (u.hostname !== start.hostname) return;
                            const clean = u.origin + u.pathname;
                            if (clean === startPath) return;
                            if (seen.has(clean)) return;
                            const path = u.pathname.toLowerCase();
                            if (blocklist.some(kw => path.includes(kw))) return;
                            if (allowlist.some(kw => path.includes(kw))) {
                                seen.add(clean);
                                out.push(clean);
                            }
                        } catch (e) {}
                    });
                    return out;
                }""",
                {"allowlist": self.URL_ALLOWLIST_KEYWORDS, "blocklist": self.URL_BLOCKLIST_KEYWORDS},
            ) or []
        except Exception as e:
            import logging
            logging.getLogger("medconf-scraper").warning(
                f"  fetch_multi_page_text: candidate discovery failed: {e}"
            )
            candidates = []

        # 3. Visit each candidate up to the cap
        budget = max_pages - 1  # already visited start_url
        for url in candidates[:budget]:
            try:
                self.navigate(url)
                self.page.wait_for_timeout(1500)
                txt = self.page.evaluate("() => document.body.textContent || ''") or ""
                if txt.strip():
                    pages[url] = txt
            except Exception as e:
                import logging
                logging.getLogger("medconf-scraper").warning(
                    f"  fetch_multi_page_text: sub-page nav failed for {url}: {e}"
                )
                continue

        # 4. Return browser state to the start URL so the caller's expectations hold
        try:
            self.navigate(start_url)
            self.page.wait_for_timeout(1000)
        except Exception:
            pass

        return pages

    def _detect_max_pages(self) -> Optional[int]:
        """Inspect pagination anchors to find the largest ?page=N value."""
        if not self.page:
            return None
        try:
            return self.page.evaluate("""() => {
                const links = Array.from(document.querySelectorAll('a[href*="page="]'));
                let maxPage = 0;
                for (const a of links) {
                    const m = (a.href || '').match(/[?&]page=(\\d+)/);
                    if (m) {
                        const n = parseInt(m[1], 10);
                        if (n > maxPage) maxPage = n;
                    }
                }
                return maxPage;
            }""")
        except Exception:
            return None

    def close(self) -> None:
        """Close the browser and clean up."""
        if self.page:
            self.page.close()
        if self._alt_context:
            try:
                self._alt_context.close()
            except Exception:
                pass
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()


