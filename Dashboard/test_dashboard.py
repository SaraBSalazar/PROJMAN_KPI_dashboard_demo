"""Smoke test: does every page still load against whatever's in ../Data right now?

Run from the Dashboard folder:

    python test_dashboard.py

Uses streamlit.testing.v1.AppTest to actually execute each page's script server-side and
check it raised nothing -- curling a running Streamlit app doesn't catch this, since every
route returns the same static shell regardless of what a page's own script does.

This is NOT a substitute for checking a change looks right in the browser -- it only
catches "the page crashed," not "the chart looks wrong" or "the number is off." Run it
after any change to kpi_data.py, kpi_charts.py, or a page, as a fast first check before
(or instead of) launching `streamlit run` by hand.
"""

import sys

# KPI_Report.py is now a thin st.navigation router rather than a content page itself --
# AppTest.from_file("KPI_Report.py") runs it and lands on its default page (Overview), so it
# still exercises both the router and that page in one go. The actual Overview content also
# gets its own entry below so it's checked loading directly too, same as every other page.
MAIN_PAGE = "KPI_Report.py"
PAGES = [
    MAIN_PAGE,
    "pages/0_Overview.py",
    "pages/1_Projects_Review.py",
    "pages/2_Special_Projects.py",
    "pages/3_Tools.py",
    "pages/4_Add_Data.py",
    "pages/5_Gains.py",
    "pages/6_Publications_Courses.py",
    "pages/7_CV.py",
    "pages/8_Time_Tracker.py",
]


def main():
    import kpi_data as kd

    print("--- data sanity ---")
    periods = kd.discover_periods()
    if not periods:
        print("FAIL: discover_periods() found no reporting periods in ../Data")
        return 1
    print(f"OK: {len(periods)} period(s), latest = {periods[0]['label']}")

    df, *_ = kd.load_timelog(dark=False)
    print(f"OK: track_time.csv loaded, {len(df)} rows")

    print("\n--- pages ---")
    from streamlit.testing.v1 import AppTest
    failed = []
    for page in PAGES:
        # Every page is reached THROUGH the router, not opened on its own: st.page_link only
        # resolves pages that st.navigation has declared, so a page holding a cross-link to
        # another one fails standalone while working perfectly in the real app.
        at = AppTest.from_file(MAIN_PAGE)
        if page != MAIN_PAGE:
            at.switch_page(page)
        at.run(timeout=30)
        if at.exception:
            failed.append(page)
            print(f"FAIL: {page}")
            for exc in at.exception:
                print(f"  {exc}")
        else:
            print(f"OK:   {page}")

    if failed:
        print(f"\n{len(failed)}/{len(PAGES)} page(s) failed: {', '.join(failed)}")
        return 1
    print(f"\nAll {len(PAGES)} pages loaded cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
