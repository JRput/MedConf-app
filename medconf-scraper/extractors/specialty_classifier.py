# extractors/specialty_classifier.py
"""
Deterministic title/description-based specialty classifier.

Used as a BACKSTOP when the LLM soft-fields call fails (common when cloud
workers hit NVIDIA's rate limit harder than a home connection would). Always
runs alongside the LLM call; LLM result wins when both produce a value.

Matching is plain lowercase substring containment — no regex word boundaries,
so prefixes like "dermatolog" match all of "dermatology" / "dermatological" /
"dermatologist". Order matters: each rule's keywords are checked in order,
FIRST match wins, so put specific clinical specialties before generic
catch-alls.
"""

from typing import Optional, List, Tuple

# Order matters — specific specialties first, generic last.
SPECIALTY_RULES: List[Tuple[str, List[str]]] = [
    # --- Clinical specialties ---
    ("Dermatology",                  ["dermatolog", "dermoscop", "rashes", "eczema", "psoriasis", "acne", "skin condition"]),
    ("Cardiology",                   ["cardiolog", "cardiovascular", "heart failure", "hypertension",
                                      "atrial fibrillation", "ischaemic heart", "cardiac surgery",
                                      "non-cardiac surgery", "cardiac and non-cardiac"]),
    ("Diabetes & Endocrinology",     ["diabetes", "diabet", "thyroid", "endocrin", "metabolic syndrome"]),
    ("Mental Health",                ["mental health", "psychiatr", "depression", "anxiety",
                                      "ptsd", "bipolar", "suicide", "self-harm"]),
    ("Women's Health",               ["women's health", "womens health", "menopause", "gynaecolog",
                                      "gynecolog", "obstetric", "contraception", "smear test",
                                      "cervical screen", "perinatal", "pelvic care", "pelvic floor",
                                      "women's pelvic"]),
    ("Men's Health",                 ["men's health", "mens health", "prostate", "testosterone", "erectile"]),
    ("Paediatrics",                  ["paediatric", "pediatric", "child health", "young people",
                                      "adolescent", "children and young"]),
    ("Geriatric Medicine",           ["geriatric", "older adult", "elderly", "dementia", "frailty", "alzheimer"]),
    ("Respiratory",                  ["respirator", "asthma", "copd", "pulmonary"]),
    ("Musculoskeletal & Trauma",     ["musculoskeletal", " msk ", "orthopaedic", "orthopedic", "joint injection",
                                      "joint pain", "back pain", "rheumat", "trauma symposium",
                                      "trauma management", "fracture",
                                      "trauma life support", "atls", "advanced trauma life",
                                      "trauma nursing", "atnc", "tnc"]),
    ("Neurology",                    ["neurolog", "stroke", "epilepsy", "migraine", "headache", "parkinson"]),
    ("Oncology",                     ["oncolog", "cancer ", "tumour", "chemotherap", "palliative", "breast cancer"]),
    ("Gastroenterology",             ["gastroenterolog", "gastrointestinal", " ibd ", " ibs ",
                                      "crohn", "ulcerative", "coeliac"]),
    ("Urology",                      ["urology", "urological", "incontinence", " uti ", "kidney stone"]),
    ("Sexual & Reproductive Health", ["sexual health", "reproductive health", "fertility", " sti ", " stis ",
                                      " hiv ", "contraception"]),
    ("Ophthalmology",                ["ophthalmolog", "retinal ", "glaucoma", "cataract", "vision loss"]),
    ("ENT",                          [" ent ", "ear nose throat", "otolaryngolog", "tinnitus"]),
    ("Dentistry",                    ["dentist", "dental", "oral health"]),
    ("Sleep Medicine",               ["sleep medicine", "insomnia", "sleep disorder", "paediatric and adolescent sleep"]),
    ("Allergy & Immunology",         ["allergy", "allergi", "immunolog", "anaphylaxis"]),
    ("Public Health",                ["public health", "epidemiolog", "population health", "screening programme"]),
    ("Infectious Disease",           ["infectious disease", "antibiotic", "antimicrobial", "vaccin"]),
    ("Minor Surgery & Procedures",   ["minor surgery", " dops ", "skin biopsy", "joint injections"]),
    ("Aesthetic & Cosmetic Medicine", ["aesthetic", "cosmetic", "botox", "filler"]),
    ("Surgery (General)",            ["surgical training", "operative", "perioperative", "general surgery"]),
    ("Telehealth",                   ["telephone consult", "remote consult", "triage skills",
                                      "virtual consult", "telephone consulting"]),
    ("Primary Care AI / Digital",    ["clinical ai", "ai in primary", "ambient voice", "digital health",
                                      "ehr", "clinical risk management"]),
    ("Surgery (RCS)",                ["mrcs ", " mrcs", "frcs", " frcs", "general surgery", "surgical training",
                                      "surgical skills", "basic surgical", " bss ",
                                      "applied anatomy", "scalpel",
                                      "ccrisp", "critically ill surgical", "care of the critically ill",
                                      "surgical care", "surgical patient", "stratos", "anatomy for surgical"]),

    # --- Practice / training / professional development ---
    ("Exam Preparation",             ["mrcgp", "sca exam", "akt exam", "akt preparation", "preparation course",
                                      "mock exam", "exam prep", "examiner"]),
    ("GP Training",                  ["gp training", "registrar", "trainee", "ifst", " vts "]),
    ("Leadership & Management",      ["leadership", "management", "mentoring", "first5",
                                      "career development", "appraisal"]),
    ("Research",                     ["research", "publication", "evidence base", "literature review"]),
    ("Medical Education",            ["teaching", "supervision", "medical education"]),
    ("Finance & Pensions",           ["finance", "financial planning", "financial", "pension", "tax", "accountancy",
                                      "wesleyan", "retirement", "money work"]),
    ("Wellbeing",                    ["wellbeing", "well-being", "mindful", "burnout", "yoga",
                                      "stress management"]),

    # --- Networking / social ---
    ("Faculty & Networking",         ["faculty board", "fellows dinner", "fun day", "vision board",
                                      "networking", "annual dinner", "garden party", "spring social",
                                      "summer social", "winter social", "international meeting"]),

    # --- History / humanities ---
    ("Medical History & Humanities", ["history of medicine", "medical history", "graphic medicine",
                                      "poetry", "writing circle", "charles dickens"]),

    # --- Flagship General ---
    ("General Practice",             ["annual conference", "general practice", "primary care"]),
]


def classify_specialty(title: Optional[str], description: Optional[str] = None) -> Optional[str]:
    """
    Return the FIRST matching specialty by keyword. None if nothing matched.

    Title runs first; description is only consulted as a tiebreaker when the
    title alone yields nothing. Why: many sources have site-wide navigation
    or boilerplate text (e.g. RCSEng's "Dental Courses" nav link) that leaks
    into the page body and was making the classifier mis-tag clearly-surgical
    courses as "Dentistry". Trusting the title first avoids that.
    """
    if not title and not description:
        return None

    title_lc = f" {(title or '').lower()} "
    if title_lc.strip():
        for label, keywords in SPECIALTY_RULES:
            for kw in keywords:
                if kw in title_lc:
                    return label

    # Title didn't match — fall back to the body. The body still helps for
    # short titles like "MRCS prep" where the topic is only stated below.
    desc_lc = f" {(description or '').lower()} "
    if desc_lc.strip():
        for label, keywords in SPECIALTY_RULES:
            for kw in keywords:
                if kw in desc_lc:
                    return label
    return None
