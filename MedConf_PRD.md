**MedConf**

Medical Conference & CPD Directory

**Product Requirements Document**

  ----------------------------------- -----------------------------------
  **Version**                         1.0

  **Date**                            February 2026

  **Status**                          Draft

  **Classification**                  Confidential

  **Target Market**                   United Kingdom
  ----------------------------------- -----------------------------------

**1. Executive Summary**

MedConf is a UK-based digital platform designed to serve as a
comprehensive, single-source directory for medical professionals seeking
conferences, talks, and continuing professional development (CPD)
opportunities. The platform addresses a significant inefficiency in how
healthcare professionals currently discover, evaluate, and track
conference attendance --- a process that is fragmented, time-consuming,
and heavily reliant on manual research across dozens of individual
organiser websites, society newsletters, and institutional notice
boards.

The core value proposition is straightforward: medical professionals are
required to accumulate CPD points as part of their professional
obligations. MedConf consolidates the discovery of these opportunities
into one place, with intelligent filtering, structured data, and
user-specific tracking --- dramatically reducing the time and effort
required to find relevant events. The platform does not handle bookings
directly; instead, it redirects users to the official organiser website
to complete their registration, keeping the product lean while still
delivering substantial value.

The platform will be supported by an agentic web scraping system that
automatically collects and updates conference data from trusted sources
on a regular cadence, minimising the need for manual data entry. Over
time, conference organisers will be invited to claim and manage their
own listings directly, creating a self-sustaining data ecosystem. Future
phases will introduce monetisation through promotional listings for
smaller conferences and talks, but the initial focus is entirely on
building a trusted, accurate, and useful directory.

**2. Product Vision & Objectives**

**2.1 Vision**

To become the most trusted and comprehensive digital directory for
medical conferences and CPD opportunities in the UK, empowering
healthcare professionals to discover, plan, and track their professional
development with minimal effort.

**2.2 Strategic Objectives**

-   **Centralise discovery.** Aggregate conference and event data from
    across the UK medical landscape into a single, structured, and
    searchable platform.

-   **Reduce friction.** Eliminate the time professionals currently
    spend hunting across fragmented sources by providing filtering,
    alerts, and a clean user experience.

-   **Maintain data accuracy.** Leverage an agentic scraping system and,
    over time, organiser self-management to ensure listings are current,
    complete, and reliable.

-   **Support professional obligations.** Make it easy for users to
    identify CPD-accredited events, track points, and plan attendance
    around their annual requirements.

-   **Build a scalable foundation.** Design the platform architecture
    and data model to support future expansion into online events,
    monetisation, and geographic growth beyond the UK.

**2.3 Success Metrics**

  ----------------------------------- -----------------------------------
  **Metric**                          **Target (6 Months)**

  Registered Users                    500+

  Active Conference Listings          200+

  Specialties Covered                 10+

  User Retention (30-day)             40%+

  Data Accuracy Rate                  95%+

  Organiser Self-Managed Listings     15%+ of total
  ----------------------------------- -----------------------------------

**3. User Personas & Target Audience**

The platform serves two distinct user types: end-users (medical
professionals) and, in later phases, conference organisers. The initial
build focuses entirely on the end-user experience.

**3.1 Primary Users --- Medical Professionals**

  ---------------------- ------------------------ ------------------------
  **Attribute**          **Details**              **Key Needs**

  Role                   NHS Consultant, GP,      High-value CPD,
                         Specialist               leadership-focused
                                                  events

  Role                   Registrar / Fellow       Broad CPD, abstract
                                                  submission
                                                  opportunities,
                                                  affordable pricing

  Role                   Medical Student          Low-cost or free events,
                                                  exposure to specialties,
                                                  networking

  Role                   Nurse / Allied Health    Nursing-specific CPD,
                                                  accessible pricing,
                                                  relevant specialties
  ---------------------- ------------------------ ------------------------

**User Pain Points**

-   **Fragmented information.** Conference details are spread across
    dozens of websites, email lists, and notice boards with no central
    place to compare options.

-   **Unclear pricing.** Many conference sites bury pricing information
    or require you to navigate deep into registration flows before
    seeing costs.

-   **CPD tracking burden.** Professionals must manually keep track of
    which events are CPD-accredited and how many points they are worth.

-   **Missing deadlines.** Abstract submission and early-bird
    registration deadlines are easy to miss when monitoring multiple
    sources.

**3.2 Secondary Users --- Conference Organisers (Future Phase)**

In a later phase, smaller conferences, medical societies, and event
organisers will be able to claim or create listings on the platform.
This user type is not in scope for the initial build but the data model
and platform architecture should be designed with this in mind.

**4. Core Features & Functional Requirements**

**4.1 User Registration & Authentication**

All users must create an account to access the platform. The
registration and authentication system forms the foundation of the
personalised experience.

**Requirements**

-   **Sign-up flow.** Users must be able to register with an email
    address and password. Email verification is required before account
    activation.

-   **Profile creation.** Upon registration, users must complete a basic
    profile including: professional role (e.g. Consultant, Registrar,
    Student, Nurse), primary specialty or area of interest, and
    preferred geographic area or radius for events.

-   **Login & session management.** Standard secure login with session
    persistence. Password reset via email.

-   **Social login (stretch).** Integration with Google or Apple sign-in
    as an optional future enhancement to reduce sign-up friction.

**4.2 Conference Directory & Browsing**

The directory is the core of the platform. Users must be able to browse,
search, and explore all listed conferences and events in a clean,
intuitive interface.

**Requirements**

-   **Main listing view.** A paginated or infinitely scrolling list of
    all upcoming conferences, displayed as cards showing key details at
    a glance: conference name, specialty, dates, location, price range,
    and CPD status.

-   **Search.** A global search bar allowing users to find conferences
    by name, keyword, or organiser.

-   **Detail view.** Clicking a conference opens a full detail page
    containing: full description, exact dates and times, venue name and
    address, all pricing tiers broken down by professional level, CPD
    accreditation status and points value, whether abstract or poster
    submissions are open (with deadlines if available), and a prominent
    link to the official organiser website for booking.

-   **Sorting.** Users can sort listings by date, relevance, or price.

**4.3 Filtering System**

Filtering is a key differentiator of the platform. Users must be able to
narrow down the conference listing to find events that are relevant and
accessible to them.

**Core Filters**

-   **Specialty.** Filter by medical specialty (e.g. Cardiology,
    Orthopaedics, General Practice, Emergency Medicine, Nursing,
    Surgery). Specialties should be a controlled, curated list. The
    initial list should cover the most common UK medical specialties,
    with the ability to expand over time.

-   **Location.** Filter by city, region, or a radius from a reference
    point. Should also include a toggle for events taking place in the
    user\'s home region by default based on their profile.

-   **Price range.** A filter using defined price bands (e.g. Free,
    Under £100, £100--£300, £300--£500, £500+) to allow users to quickly
    surface events within their budget. The price displayed should
    reflect the relevant tier for the user based on their profile.

**Secondary Filters**

-   **Date range.** A date picker allowing users to filter events within
    a specific start and end date.

-   **CPD status.** A toggle to show only CPD-accredited events, or all
    events. All events should be clearly labelled as to whether they
    award CPD points or not.

-   **Abstract submissions.** A toggle to surface only conferences that
    have open poster or abstract submission opportunities.

**4.4 Notification & Alert System**

Users should be able to set up personalised alerts to stay informed
about relevant events and important deadlines without having to check
the platform constantly.

**Requirements**

-   **New event alerts.** Users can opt in to be notified when a new
    conference is added that matches their specialty or area of
    interest.

-   **Deadline reminders.** Alerts for upcoming abstract submission
    deadlines and early-bird registration close dates for conferences
    the user has saved or shown interest in.

-   **Notification preferences.** Users can configure how they receive
    notifications: email, in-app, or both. Users can also set the
    frequency of notifications (e.g. immediate, daily digest, weekly
    digest).

**4.5 Saved & Tracked Conferences**

Users must be able to save conferences they are interested in and track
their attendance history, creating a personal CPD record within the
platform.

**Requirements**

-   **Save / bookmark.** Users can save any conference to a personal
    list for easy access later. Saved conferences should trigger
    deadline reminder notifications automatically.

-   **Attendance tracking.** Users can mark conferences they have
    attended, building a personal history. This forms the basis of an
    informal CPD log within the app.

-   **CPD summary.** A simple dashboard or summary view showing total
    CPD points accumulated from attended conferences, broken down by
    specialty or time period.

**5. Data Model**

The data model is designed around the core entity --- a conference ---
and its relationships to users, specialties, locations, and pricing. It
is structured to support the agentic scraper\'s output, organiser
self-management in future phases, and efficient querying for the
filtering and search features.

**5.1 Core Entities**

  ----------------- ---------------------- ------------------------------
  **Entity**        **Purpose**            **Key Fields**

  Users             Registered platform    ID, email, password hash,
                    users                  role, specialty, location,
                                           created date

  Conferences       Core conference        ID, name, description,
                    listings               specialty ID, start date, end
                                           date, venue, city, region, CPD
                                           status, CPD points, abstract
                                           open (boolean), abstract
                                           deadline, source URL,
                                           organiser URL, created/updated
                                           dates

  Specialties       Controlled list of     ID, name, slug, category (e.g.
                    medical specialties    Clinical, Nursing)

  Pricing Tiers     Price breakdown per    ID, conference ID, tier label
                    conference per         (e.g. Student, Consultant,
                    professional level     Member, Non-Member), price
                                           (GBP), is early bird
                                           (boolean), early bird deadline

  Saved Conferences User\'s bookmarked     ID, user ID, conference ID,
                    conferences            saved date

  Attendance        User\'s attended       ID, user ID, conference ID,
  Records           conference history     attended date, CPD points
                                           claimed

  Notification      User notification      ID, user ID, alert types (new
  Preferences       settings               events, deadlines), channels
                                           (email, in-app), frequency

  Scraper Sources   Registry of websites   ID, source name, base URL,
                    the agentic scraper    extraction instructions,
                    targets for conference active (boolean), last scraped
                    data                   date, last status, created
                                           date, updated date
  ----------------- ---------------------- ------------------------------

**5.2 Entity Relationships**

-   **Conferences → Specialties:** Many-to-one. Each conference belongs
    to one primary specialty.

-   **Conferences → Pricing Tiers:** One-to-many. Each conference has
    multiple pricing tiers for different professional levels.

-   **Users → Saved Conferences:** Many-to-many. A user can save many
    conferences; a conference can be saved by many users.

-   **Users → Attendance Records:** One-to-many. A user can have
    multiple attendance records over time.

-   **Users → Notification Preferences:** One-to-one. Each user has a
    single set of notification preferences.

-   **Scraper Sources → Conferences:** One-to-many. Each source in the
    scraper registry can yield multiple conference listings. Conferences
    store a reference to the source URL they were extracted from,
    enabling traceability and duplicate detection.

**6. Agentic Scraping System**

The agentic scraping system is the data ingestion engine of MedConf.
Rather than relying on manual research or traditional rigid scrapers
tied to specific HTML structures, the system uses a large language model
(LLM) as its decision-making brain, paired with browser automation, to
navigate conference websites and extract structured data autonomously.

**6.1 Architecture Overview**

The system is composed of four layers working in sequence:

1.  **Source Registry.** A dedicated database table within Supabase that
    stores all trusted source websites --- Royal Colleges, medical
    societies, universities, and known conference organisers. Each row
    contains the source\'s starting URL and a set of natural language
    extraction instructions. The scraper queries this table at the start
    of each run to retrieve all active sources.

2.  **Browser Automation Layer.** Built on Playwright, this layer
    provides programmatic control over a real browser. It can navigate
    to URLs, click links, scroll pages, and read page content ---
    including dynamically loaded content.

3.  **LLM Orchestration Engine.** The core intelligence layer. At each
    step, the LLM receives the current page content, the original
    extraction instructions, and a record of actions already taken. It
    decides the next action: navigate deeper, extract data, or declare
    the task complete. This creates an iterative reasoning loop that
    adapts to the structure of each website without requiring hardcoded
    selectors.

4.  **Data Output & Validation.** Extracted data is structured into the
    conference data model, validated for completeness (flagging missing
    required fields), and passed to the database update pipeline.

**6.2 Extraction Instructions (Example)**

Each source in the registry is paired with a natural language
instruction set. For example:

*\"Visit the events page on this website. Find all upcoming conferences
and talks. For each event, extract: the event name, the specialty it
belongs to, the start and end dates, the venue name and city, any
pricing information broken down by professional level, whether CPD
points are awarded and how many, and whether abstract or poster
submissions are open. If detail pages exist for individual events,
navigate to each one to collect the full information. Return all
extracted data in structured format.\"*

**6.3 Scheduling & Update Logic**

-   **Frequency.** The scraper runs on a weekly cadence by default,
    triggered by a job scheduler (e.g. AWS EventBridge or cron).

-   **Duplicate handling.** Each conference is identified by a stable
    unique key --- the source URL of the official conference page. On
    each run, the system checks whether a conference with that key
    already exists in the database. If it does, it compares fields and
    updates only those that have changed. If it does not, a new record
    is inserted.

-   **Expiry handling.** Conferences whose end dates have passed are
    flagged as archived and removed from active listings.

-   **Logging.** Every scraper run produces a log: sources visited,
    conferences found, records inserted or updated, validation failures,
    and any errors encountered. This provides full visibility into the
    health of the data pipeline.

**6.4 Safeguards**

-   **Rate limiting.** The scraper respects website rate limits and
    introduces delays between requests to avoid overloading source
    websites.

-   **Terms of service.** Sources are manually vetted before being added
    to the registry. Any source that explicitly prohibits automated
    access is excluded.

-   **Failure isolation.** A failure on one source does not affect the
    scraping of other sources. Failures are logged and flagged for
    review.

-   **Step limit.** Each scrape session has a maximum number of
    navigation steps to prevent infinite loops on complex or unexpected
    page structures.

**7. Database & Infrastructure**

**7.1 Database**

-   **Type.** Supabase (built on PostgreSQL). Supabase is the
    recommended platform for MedConf. It provides a managed PostgreSQL
    database, built-in authentication (covering user registration, email
    verification, and session management), real-time data capabilities,
    and a clean dashboard for viewing and managing data directly --- all
    in one platform. The structured, relational nature of conference
    data maps well to PostgreSQL, and Supabase eliminates the need to
    build or host a separate auth system.

-   **Hosting.** Supabase provides cloud-hosted managed infrastructure
    out of the box. This includes automated backups, scalability, and
    built-in security features. A free tier is available for development
    and early-stage testing, with paid plans available as the platform
    scales.

-   **Search indexing.** Full-text search indexes on conference name,
    description, and location fields to support the global search
    feature efficiently.

**7.2 Backend**

-   **API layer.** A RESTful API serving the frontend. Handles
    authentication, conference queries with filtering and pagination,
    user profile management, saved conferences, attendance tracking, and
    notification preferences.

-   **Background jobs.** A job queue (e.g. Celery or AWS SQS) for
    running the scraper, sending notifications, and any other async
    processing.

**7.3 Frontend**

-   **Framework.** A modern JavaScript framework (e.g. React or Next.js)
    for a responsive, fast user interface.

-   **Responsive design.** The platform must be fully usable on mobile
    devices, as many professionals will browse on the go.

**8. MVP Specification**

The Minimum Viable Product is designed to validate the core concept with
real users as quickly as possible. It follows an Eventbrite-style model:
a clean browsing and discovery experience where users can explore,
filter, save, and then be redirected to the official organiser website
to complete their booking. The MVP does not handle payments, ticketing,
or bookings directly.

**8.1 MVP Scope**

  ----------------------------------- ----------------- -----------------
  **Feature**                         **In MVP**        **Post-MVP**

  User registration & email           ✓                 
  verification                                          

  Basic profile (role, specialty,     ✓                 
  region)                                               

  Conference directory with card      ✓                 
  listing                                               

  Conference detail page with         ✓                 
  redirect to organiser                                 

  Filtering: Specialty, Location,     ✓                 
  Price Range                                           

  Search by keyword                   ✓                 

  CPD accreditation label on all      ✓                 
  listings                                              

  Save / bookmark conferences         ✓                 

  Email notifications: new events &   ✓                 
  deadlines                                             

  Notification preference settings    ✓                 

  Attendance tracking & CPD summary                     ✓

  Social login (Google / Apple)                         ✓

  Organiser self-service listing                        ✓
  management                                            

  Abstract submission filter toggle                     ✓

  Promotional / paid listings for                       ✓
  organisers                                            

  Online / webinar event support                        ✓
  ----------------------------------- ----------------- -----------------

**8.2 MVP User Journey**

1.  **Discovery.** A medical professional hears about MedConf or finds
    it via search. They land on the homepage, which presents the
    directory and prompts them to sign up or browse.

2.  **Registration.** They create an account with email and password,
    verify their email, and complete their profile --- selecting their
    professional role, primary specialty, and preferred region.

3.  **Browsing & Filtering.** They browse the conference directory. The
    listing is pre-filtered to their specialty and region based on their
    profile but they can adjust filters freely. Each card shows the
    conference name, specialty, dates, location, price range, and
    whether it awards CPD points.

4.  **Detail & Decision.** They click on a conference that interests
    them. The detail page shows all available information including full
    pricing by professional level and CPD points. They can save it to
    their bookmarks or click through to the organiser\'s website to
    book.

5.  **Booking.** They are redirected to the official organiser website
    where they complete registration and payment directly. MedConf plays
    no role in the transaction.

6.  **Ongoing Engagement.** They receive email notifications when new
    conferences matching their specialty are added, and are reminded of
    deadlines for conferences they have saved. They return to the
    platform regularly to discover new opportunities.

**8.3 MVP Data Pipeline**

For the MVP, conference data is populated entirely by the agentic
scraping system. The scraper source registry --- a dedicated table
within Supabase --- is seeded with trusted UK medical conference
sources: Royal Colleges, major medical societies, and well-known
conference organisers across the target specialties. The scraper queries
this table weekly, extracts and validates data from each active source,
and writes the results to the Supabase database. The frontend reads from
this database in real time.

**9. Phased Roadmap**

  -------------- ------------------------ --------------------------------
  **Phase**      **Timeline**             **Focus & Deliverables**

  Phase 1        Months 1--3 (MVP)        Core registration, directory,
                                          filtering (specialty, location,
                                          price), conference detail with
                                          organiser redirect, email
                                          notifications, agentic scraper
                                          seeded with initial sources.
                                          2--3 specialties covered in
                                          depth.

  Phase 2        Months 4--6              Attendance tracking and CPD
                                          summary dashboard. Abstract
                                          submission filter. Social login.
                                          Expand specialty coverage to
                                          10+. Refine scraper reliability
                                          and add more sources. Begin
                                          outreach to conference
                                          organisers.

  Phase 3        Months 7--9              Organiser self-service: ability
                                          for conference organisers to
                                          claim and manage their own
                                          listings on the platform.
                                          Introduce basic promotional
                                          features for organisers. Begin
                                          monetisation planning.

  Phase 4        Months 10--12            Expand into online and hybrid
                                          events. Introduce paid
                                          promotional listings for
                                          organisers. Explore geographic
                                          expansion beyond the UK.
                                          Advanced personalisation and
                                          recommendation features.
  -------------- ------------------------ --------------------------------

**10. Non-Functional Requirements**

**10.1 Performance**

-   **Page load time.** All pages must load within 2 seconds on a
    standard mobile connection.

-   **Search & filter response.** Filtering and searching the conference
    directory must return results within 1 second.

-   **Scraper throughput.** The weekly scraper run must complete within
    a reasonable time window and not impact application performance for
    end users.

**10.2 Security**

-   **Data protection.** All user data must be stored and transmitted
    securely. Passwords must be hashed. Communications must use HTTPS.

-   **GDPR compliance.** As a UK-based platform handling personal data,
    full compliance with UK GDPR is required. This includes clear
    privacy policies, user consent mechanisms, and the ability for users
    to request deletion of their data.

-   **Input validation.** All user inputs must be validated and
    sanitised to prevent injection attacks.

**10.3 Reliability**

-   **Availability.** The platform should target 99.5% uptime during
    normal operating hours.

-   **Scraper resilience.** The scraping system must be resilient to
    individual source failures. A failure on one source must not prevent
    the rest of the pipeline from running.

**10.4 Scalability**

The architecture must be designed to accommodate growth in users,
conference listings, and source websites without requiring a fundamental
rebuild. The use of a managed cloud database, a stateless API layer, and
a decoupled background job system supports this.

**10.5 Accessibility**

The platform must meet WCAG 2.1 AA accessibility standards to ensure it
is usable by the widest possible audience, including users with
disabilities.

**11. Risks & Mitigations**

  -------------------- -------------- --------------------------------------
  **Risk**             **Severity**   **Mitigation**

  Scraper accuracy     High           Build robust logging and alerting into
  degrades over time                  the scraper pipeline. Implement
  as source websites                  periodic manual spot-checks on a
  change their                        sample of listings. Plan for ongoing
  structure                           scraper maintenance as a recurring
                                      task.

  Low initial user     High           Focus on depth over breadth in the MVP
  adoption                            --- covering 2--3 specialties with
                                      highly accurate data rather than thin
                                      coverage across all specialties. Seek
                                      early feedback from professionals in
                                      target specialties.

  Conference           Medium         Vet all sources against their terms of
  organisers block or                 service before adding to the registry.
  restrict automated                  Prioritise building direct
  scraping                            relationships with organisers over
                                      time, moving toward self-managed
                                      listings.

  Data staleness ---   Medium         Run the scraper weekly. Include
  conference details                  timestamps on all listings so users
  change between                      can see when data was last verified.
  scraper runs                        Flag any listing approaching its event
                                      date for priority re-check.

  Difficulty           Medium         The value proposition is aggregation,
  differentiating from                filtering, and personalisation --- not
  existing conference                 replication of individual organiser
  websites                            sites. Emphasise the time-saving and
                                      discovery aspects in positioning.
  -------------------- -------------- --------------------------------------

**12. Assumptions & Dependencies**

**12.1 Assumptions**

-   **UK market first.** The initial product targets the UK medical
    professional market exclusively. All specialties, terminology (CPD
    vs CME), and source websites are UK-focused.

-   **Conference data is publicly available.** The conference
    information required for the scraper --- dates, location, pricing,
    CPD accreditation --- is available on publicly accessible web pages.

-   **Redirect model is sufficient.** Users will accept being redirected
    to the organiser\'s website to complete their booking. The platform
    does not need to handle payments or ticketing in the initial phase.

-   **Email is the primary notification channel.** For the MVP, email is
    the primary channel for notifications. In-app notifications are a
    secondary enhancement.

-   **Weekly scraper cadence is sufficient.** Conference details do not
    change frequently enough to require more than weekly updates for the
    majority of listings.

**12.2 Dependencies**

-   **LLM API access.** The agentic scraper depends on access to a
    capable LLM API (e.g. Anthropic Claude or OpenAI) for its navigation
    and extraction logic.

-   **Browser automation tooling.** Playwright or equivalent must be
    available and maintained for the scraper\'s browser layer.

-   **Cloud infrastructure.** Supabase is required as the core
    infrastructure platform. It provides the managed PostgreSQL
    database, built-in authentication, and real-time capabilities. A
    separate cloud provider (AWS, GCP, or equivalent) may still be
    needed for hosting the API, frontend, and background job
    infrastructure (e.g. the scraper scheduler).

-   **Email service provider.** A transactional email service (e.g.
    SendGrid, AWS SES) is required for registration verification and
    notification delivery.

**13. Glossary**

  ------------------- ---------------------------------------------------
  **Term**            **Definition**

  CPD                 Continuing Professional Development. The ongoing
                      learning and training that healthcare professionals
                      are required to undertake to maintain and develop
                      their skills and knowledge.

  Agentic Scraper     An automated system that uses a large language
                      model to navigate websites and extract structured
                      data, adapting to different page structures without
                      requiring hardcoded selectors.

  Source Registry     The curated list of trusted websites that the
                      agentic scraper is configured to visit and extract
                      conference data from.

  Pricing Tier        A pricing level within a conference that
                      corresponds to a specific professional category
                      (e.g. Student, Consultant, Member, Non-Member).

  Organiser Redirect  The mechanism by which users are directed from
                      MedConf to the official conference organiser\'s
                      website to complete their booking.

  Royal College       A professional body in the UK that represents and
                      supports doctors in a particular medical specialty.
                      Royal Colleges are a key source of conference and
                      CPD information.
  ------------------- ---------------------------------------------------
