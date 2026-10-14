"""ViVE (HLTH + CHIME digital-health congress, hlth.com/events/vive): single-congress family subclass.

Fees are `price-card` blocks on /register/: card-title + display-price (current rate) + full-price (struck-through
standard rate), grouped under a section-title (General Attendees, Provider & Payer Connect, ...).
"""
import html as _html
import re

from .single_congress import SingleCongressExtractor, fees_current, html_lines, parse_amount


def _txt(frag: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", frag or ""))).strip()


class ViveExtractor(SingleCongressExtractor):
    HOME_URL = "https://hlth.com/events/vive/"
    SOCIETY = "ViVE"
    EVENT_NAME = "ViVE"
    DEFAULT_SPECIALTY = "Digital Health"
    DEFAULT_CURRENCY = "USD"
    REG_URLS = ("https://hlth.com/events/vive/register/",)

    def fees_from_pages(self, pages, year):
        for url, html in pages.items():
            if "price-card" not in html or not fees_current(html_lines(html), year):
                continue
            tiers, seen = [], set()
            for sec in re.split(r'(?i)(?=<section\b[^>]*section-reg-type)', html):
                m = re.search(r'(?is)class="section-title"[^>]*>(.*?)</', sec)
                section = _txt(m.group(1)) if m else "Registration"
                for card in re.split(r'(?i)(?=class="price-card")', sec)[1:]:
                    t = re.search(r'(?is)class="card-title"[^>]*>(.*?)</div>', card)
                    cur = re.search(r'(?is)class="display-price"[^>]*>(.*?)</div>', card)
                    full = re.search(r'(?is)class="full-price"[^>]*>(.*?)</div>', card)
                    if not (t and cur):
                        continue
                    title = _txt(t.group(1))
                    a = parse_amount(_txt(cur.group(1)), "USD")
                    f = parse_amount(_txt(full.group(1)), "USD") if full else None
                    rows = []
                    if a:
                        rows.append((a, "Early rate" if f and f[0] > a[0] else "Standard rate"))
                    if f and a and f[0] > a[0]:
                        rows.append((f, "Standard rate"))
                    for (amt, cur_), tf in [(r[0], r[1]) for r in rows]:
                        label = f"{section} · {title} · {tf}"
                        if label in seen:
                            continue
                        seen.add(label)
                        tiers.append({"tier_label": label, "price_gbp": amt, "currency": cur_,
                                      "is_early_bird": tf == "Early rate", "early_bird_deadline": None})
            if tiers:
                return tiers
        return []
