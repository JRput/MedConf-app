"""Per-field remediator fixers.

Each fixer is a function `(row, page_text, llm_call) -> (fixed_value, method)`.
- row: the conference row from Supabase
- page_text: the source page's body innerText (cached per run via PageCache)
- llm_call: function taking a prompt, returning text or None (existing scraper.LLM)

Returns:
- (fixed_value, method_used) on success
- (None, None) on failure / can't extract

Each fixer should be defensive: returns None rather than guessing when
the page doesn't clearly contain the field.
"""

from .description import fix_description
from .venue import fix_venue, fix_city
from .format import fix_event_format
from .cpd import fix_cpd_points
from .specialty import fix_specialty
from .pricing import fix_pricing
from .abstract import fix_abstract_status

REGISTRY = {
    "description": fix_description,
    "venue_name": fix_venue,
    "city": fix_city,
    "event_format": fix_event_format,
    "cpd_points": fix_cpd_points,
    "specialty": fix_specialty,
    "pricing": fix_pricing,
    "abstract_status": fix_abstract_status,
}
