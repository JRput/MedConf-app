#!/usr/bin/env python3
"""Monitor scraper progress and detect if it's stuck on the same page."""

import time
import sys
import re
from collections import Counter

def monitor_log_file(log_file, check_interval=30):
    """Monitor log file for stuck behavior."""
    print("=" * 60)
    print("Monitoring Scraper Progress")
    print("=" * 60)
    print(f"Watching: {log_file}")
    print(f"Check interval: {check_interval} seconds")
    print("=" * 60)
    print()
    
    last_step = 0
    page_history = []
    stuck_count = 0
    max_stuck_checks = 3  # Stop after 3 checks showing no progress
    
    try:
        while True:
            time.sleep(check_interval)
            
            try:
                with open(log_file, 'r') as f:
                    lines = f.readlines()
            except FileNotFoundError:
                print(f"Log file not found: {log_file}")
                continue
            
            # Extract current step
            current_step = 0
            current_page = None
            last_navigation = None
            
            for line in lines[-50:]:  # Check last 50 lines
                # Check for step number
                step_match = re.search(r'Step (\d+)/30', line)
                if step_match:
                    current_step = int(step_match.group(1))
                
                # Check for navigation
                nav_match = re.search(r'Navigating to (https?://[^\s]+)', line)
                if nav_match:
                    last_navigation = nav_match.group(1)
                    page_history.append(last_navigation)
                    if len(page_history) > 10:
                        page_history.pop(0)
                
                # Check for current page in reasoning
                if 'page' in line.lower() and ('extract' in line.lower() or 'reasoning' in line.lower()):
                    page_match = re.search(r'page (\d+)', line, re.IGNORECASE)
                    if page_match:
                        current_page = f"page {page_match.group(1)}"
            
            # Check for completion
            if any('SCRAPER RESULTS' in line for line in lines[-20:]):
                print("\n✓ Scraper completed!")
                break
            
            # Check for stuck behavior
            if current_step == last_step and current_step > 0:
                stuck_count += 1
                print(f"⚠ Step {current_step} - No progress for {stuck_count} check(s)")
                
                if stuck_count >= max_stuck_checks:
                    print(f"\n✗ SCRAPER APPEARS STUCK!")
                    print(f"   Step {current_step} has not advanced for {stuck_count * check_interval} seconds")
                    print(f"   Last navigation: {last_navigation}")
                    print(f"   Current page: {current_page}")
                    print("\nRecent page history:")
                    page_counts = Counter(page_history[-10:])
                    for page, count in page_counts.most_common(5):
                        print(f"   {page}: {count} time(s)")
                    return False
            else:
                stuck_count = 0  # Reset if making progress
            
            # Show progress
            if current_step > last_step:
                print(f"✓ Step {current_step}/30 - Progressing...")
                if last_navigation:
                    print(f"   Last navigation: {last_navigation[:60]}")
                last_step = current_step
            
            # Check for repeated page extractions
            if len(page_history) >= 5:
                recent_pages = page_history[-5:]
                page_counts = Counter(recent_pages)
                most_common = page_counts.most_common(1)[0]
                if most_common[1] >= 4:  # Same page 4+ times in last 5 navigations
                    print(f"\n⚠ WARNING: Stuck on same page!")
                    print(f"   Page: {most_common[0]}")
                    print(f"   Visited {most_common[1]} times in last 5 navigations")
                    print("   This may indicate the LLM is not navigating properly")
            
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped by user")
        return True
    except Exception as e:
        print(f"\n\nError monitoring: {e}")
        return False
    
    return True

if __name__ == "__main__":
    log_file = sys.argv[1] if len(sys.argv) > 1 else "scraper_rcgp_run_fixed.log"
    success = monitor_log_file(log_file)
    sys.exit(0 if success else 1)

