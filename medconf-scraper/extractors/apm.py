"""APM (Association for Palliative Medicine) events: WordPress-family subclass.

The /events/ page is a Modern Events Calendar (MEC) list skin: month dividers ("November 2026") followed by
<article class="mec-event-article"> cards whose date is year-less ("04 - 27 Jan", "11 - 12 Mar"), so the year comes
from the divider. There is no "load more" control when everything fits (7 upcoming at build time) and the MEC
REST route returns []. Detail pages are MEC single events: JSON-LD Event, a "Book Event" ticket block (name / price /
"Available Tickets"), and free-text "Fees" blocks. MEC prints a hidden 'ticket is sold out' template sentence under
every ticket, which is NOT a sold-out signal and is stripped.
"""
import html as _html
import re

from .tribe_events import html_to_lines
from .wordpress_generic import WordPressGenericExtractor, dedupe_consecutive, json_ld_events, _iso, _mon

_MONTHS = "January February March April May June July August September October November December".split()
_ART_RE = re.compile(r'(?is)<div class="mec-month-divider"[^>]*>\s*<span>([^<]*)</span>|<article class="mec-event-article.*?</article>')
_LABEL_RE = re.compile(r"^(\d{1,2})(?:\s+([A-Za-z]{3,9}))?\s*(?:-|–)\s*(\d{1,2})\s+([A-Za-z]{3,9})$|^(\d{1,2})\s+([A-Za-z]{3,9})$")
_HIDDEN_SOLD_RE = re.compile(r'(?i)The\s+"[^"]*"\s+ticket is sold out\.\s*You can try another ticket or another date\.')
_ONLINE_FMT_RE = re.compile(r"(?i)\b(?:delivered via|via)\s+(?:MS |Microsoft )?(?:Teams|Zoom)\b|\bvirtual event\b|\bwebinar\b")
_PRICE_RE = re.compile(r"^(?:£\s?)?(\d[\d,]*(?:\.\d{1,2})?)$")      # MEC prints the ticket price bare ("30") or with £
_CHROME_NO_FORM_RE = re.compile(r"(?is)<(script|style|svg|noscript|nav|footer|aside|template)\b.*?</\1\s*>")   # the ticket block sits inside a <form>


def _text(fragment):
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


class ApmExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://apmonline.org/events/"
    SOCIETY = "APM"
    DEFAULT_SPECIALTY = "Palliative Medicine"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"

    # ---- listing -----------------------------------------------------------
    def parse_listing(self, html, url):
        shells, seen = [], set()
        year = mon = None
        for m in _ART_RE.finditer(html or ""):
            if m.group(1) is not None:                                    # "November 2026"
                dm = re.match(r"([A-Za-z]+)\s+(\d{4})", m.group(1).strip())
                if dm and dm.group(1) in _MONTHS:
                    mon, year = _MONTHS.index(dm.group(1)) + 1, int(dm.group(2))
                continue
            a = m.group(0)
            tm = re.search(r'mec-event-title"[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', a, re.S)
            lm = re.search(r'mec-start-date-label">([^<]+)<', a)
            if not tm or not lm or year is None:
                continue
            link = _html.unescape(tm.group(1))
            if link in seen:
                continue
            seen.add(link)
            label = _text(lm.group(1))
            s = e = None
            g = _LABEL_RE.match(label)
            if g and g.group(5):                                          # "22 Oct"
                s = e = _iso(year, _mon(g.group(6)), int(g.group(5)))
            elif g:                                                       # "04 - 27 Jan" / "28 Feb - 02 Mar"
                m1 = _mon(g.group(2)) if g.group(2) else _mon(g.group(4))
                m2 = _mon(g.group(4))
                s = _iso(year, m1, int(g.group(1)))
                e = _iso(year + (1 if m2 < m1 else 0), m2, int(g.group(3)))
            if not s:
                continue
            st = re.search(r'mec-start-time">(\d{1,2}:\d{2})<', a)
            vm = re.search(r'mec-venue-details">(.*?)</div>', a, re.S)
            venue = ", ".join(x for x in (_text(v) for v in re.findall(r"<span>(.*?)</span>", vm.group(1), re.S)) if x) if vm else None
            shells.append({"title": _text(tm.group(2)), "booking_url": link, "source_url": link, "start_date": s, "end_date": e or s,
                           "start_time": st.group(1).zfill(5) if st else None, "venue_raw": venue or None, "category": None})
        return shells

    # ---- detail ------------------------------------------------------------
    def detail_from_html(self, html, shell, llm_call):
        html = _HIDDEN_SOLD_RE.sub(" ", html or "")
        out = super().detail_from_html(html, shell, llm_call)
        lines = dedupe_consecutive(html_to_lines(_CHROME_NO_FORM_RE.sub(" ", html)))
        text = " ".join(lines)
        out.pop("is_sold_out", None)
        raw = (shell.get("venue_raw") or "").strip()
        if re.match(r"(?i)virtual|online", raw) or (not raw and _ONLINE_FMT_RE.search(text[:6000])):
            for k in ("venue_name", "city", "region"):                    # JSON-LD address "Microsoft Office Teams" is the platform, not a place
                out.pop(k, None)
            out["event_format"] = "online"
        elif out.get("venue_name") and "," in out["venue_name"] and not out.get("city"):
            parts = [x.strip() for x in out["venue_name"].split(",") if x.strip()]    # "Lowry, Salford"
            if len(parts) == 2:
                out["venue_name"], out["city"] = parts
        # JSON-LD offers on MEC pages are the first ticket only (or a blank cost shown as 0): use the ticket block instead
        tiers, sold_out = self._tickets(lines)
        out["pricing_tiers"] = tiers
        if tiers and sold_out:
            out["is_sold_out"] = True
        if not tiers:
            out.pop("pricing_tiers")
        if out["event_type"] == "conference" and out.get("event_format") == "online" and not re.search(r"(?i)conference|congress|symposium", shell.get("title") or ""):
            out["event_type"] = "workshop"
        d = out.get("description") or ""
        if re.search(r"(?i)late (?:bookings|registrants)|registration now|^please note|^a short video", d):
            ld = (json_ld_events(html) or [{}])[0].get("description") or ""
            ld = re.sub(r"\s+", " ", _html.unescape(ld)).strip()
            if len(ld) >= 60 and not re.search(r"(?i)late (?:bookings|registrants)|registration now|cookie|consent", ld[:200]):
                out["description"] = ld[:600]
            else:
                alt = next((l for l in lines if len(l) >= 60 and not re.search(r"(?i)late (?:bookings|registrants)|registration now|^please note|^a short video|^\[", l)), None)
                if alt:
                    out["description"] = alt[:600]
        m = re.search(r"(?i)CPD approved for (\d+(?:\.\d+)?) credits?", text)
        if m:
            out["cpd_points"], out["cpd_accredited"] = float(m.group(1)), True
        # fees on a separate ticketing site / PDF price list: let the explorer follow it
        if not out.get("pricing_tiers"):
            body = html[:html.find("Share this event")] if "Share this event" in html else html
            links = [(_html.unescape(m.group(1)), _text(m.group(2))) for m in re.finditer(r"""(?is)<a\b[^>]*href=["'](https?://[^"']+)["'][^>]*>(.*?)</a\s*>""", body)]
            links = [(h, t) for h, t in links if "apmonline.org" not in h and "compleathub" not in h
                     and not re.search(r"calendar\.google|facebook|twitter|linkedin|whatsapp", h)]
            for rx in (r"(?i)book your place|buy|tickets", r"(?i)price list|register"):     # tickets page first, then the PDF price list
                hit = next((h for h, t in links if re.search(rx, t + " " + h)), None)
                if hit:
                    out["organiser_url"] = hit
                    break
        return out

    def _tickets(self, lines):
        """'Book Event' block: ticket name, optional £ price, 'Available Tickets: ...'; a FREE note instead of a price = £0.
        Early-bird wording in the page's own 'Fees' text marks the matching price."""
        if "Book Event" not in lines:
            return [], False
        block = lines[lines.index("Book Event") + 1:]
        end = next((i for i, l in enumerate(block) if l in ("Next", "Date", "Time")), len(block))
        block = block[:end]
        eb_prices = {float(p.replace(",", "")) for l in lines if re.search(r"(?i)early[\s-]?bird", l) for p in re.findall(r"£\s?(\d[\d,]*(?:\.\d+)?)", l)}
        tiers, name, price, avail = [], None, None, []
        for l in block:
            pm = _PRICE_RE.match(l)
            am = re.match(r"^Available Tickets:\s*(\w+)", l)
            if pm:
                price = float(pm.group(1).replace(",", ""))
            elif am:
                avail.append(am.group(1))
                continue
            elif name is not None and price is None and re.search(r"(?i)\bfree\b", l):
                price = 0.0
            elif re.match(r"^[A-Z][A-Za-z0-9 &/\-()]{2,60}$", l) and not re.match(r"(?i)^(?:next|date|time|book event)$", l):
                if name is not None and price is not None:
                    tiers.append((name, price))
                name, price = l, None
        if name is not None and price is not None:
            tiers.append((name, price))
        sold_out = bool(avail) and all(a == "0" for a in avail)
        out, seen = [], set()
        for n, p in tiers:
            early = p in eb_prices
            label = f"Registration · {n}" + (" · Early bird" if early else "")
            if (label, p) in seen:
                continue
            seen.add((label, p))
            out.append({"tier_label": label, "price_gbp": p, "currency": "GBP", "is_early_bird": early, "early_bird_deadline": None})
        return out, sold_out
