# Why the Scraper Got Stuck - Root Cause Analysis

## Primary Issue: Browser Navigation Timeout

### Problem Location
**File**: `browser.py`, line 30
```python
self.page.goto(url, wait_until="networkidle")
```

### Why It Gets Stuck

1. **`networkidle` Wait Condition**
   - Playwright's `networkidle` waits for the network to be idle (no requests for 500ms)
   - **Problem**: Many modern websites have continuous network activity:
     - Analytics tracking (Google Analytics, etc.)
     - Ad networks loading
     - WebSocket connections
     - Auto-refresh mechanisms
     - Lazy-loading images
   - **Result**: The page may NEVER reach "networkidle" state, causing indefinite hang

2. **Timeout Configuration**
   - `SCRAPER_TIMEOUT_MS = 10000` (10 seconds)
   - But `networkidle` can take much longer or never complete
   - If networkidle never happens, the timeout may not trigger properly

3. **No Fallback Mechanism**
   - If `page.goto()` hangs, there's no timeout or error handling
   - The scraper waits indefinitely for the page to load
   - No way to skip to next step if navigation fails

4. **Cascading Effect**
   - If one navigation hangs, the entire extraction phase stops
   - No data is saved until extraction completes
   - All 270 conferences wait until navigation completes

## Secondary Issues

### Issue 2: No Progress Logging During Extraction
- The scraper doesn't log progress during the extraction loop
- Can't tell if it's making progress or stuck
- Only logs after extraction completes

### Issue 3: All-or-Nothing Extraction
- Extracts ALL conferences before saving ANY
- If extraction gets stuck, nothing is saved
- No incremental progress

### Issue 4: LLM Response Time
- Each LLM call takes 1-2 minutes
- With 30 max steps = 30-60 minutes total
- If stuck on navigation, wastes all that time

## Evidence from the Run

- **8 LLM calls completed** (took ~17 minutes)
- **No new conferences saved** (extraction phase never completed)
- **Low CPU usage** (0.0%) - browser waiting for networkidle
- **Process appeared idle** - stuck in `page.goto()` call

## Solution

### Fix 1: Change Wait Strategy
Instead of `networkidle`, use `load` or `domcontentloaded`:
- `load`: Waits for page load event (faster, more reliable)
- `domcontentloaded`: Even faster, waits for DOM ready
- Add explicit timeout handling

### Fix 2: Add Timeout and Error Handling
- Wrap navigation in try/except
- Use explicit timeout
- Fallback to continue if navigation fails

### Fix 3: Add Progress Logging
- Log each step during extraction
- Show when navigation starts/completes
- Log extracted count incrementally

### Fix 4: Consider Incremental Saving
- Save conferences as they're extracted (not all at end)
- Prevents losing all progress if scraper gets stuck

