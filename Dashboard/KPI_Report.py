"""Entrypoint / router for the KPI dashboard. Run with:  streamlit run KPI_Report.py

Just wires up st.navigation({section_header: [st.Page(...), ...]}) over the page files in
pages/ and runs the selected one -- the actual content lives in those files. st.navigation
is used instead of Streamlit's old pages/ auto-discovery specifically so the sidebar can
show section headings (Reporting / Development / Data) grouping related pages -- calling
st.navigation() switches PagesManager.uses_pages_directory off, so the files staying inside
pages/ no longer get auto-discovered/double-listed; they're only reachable through the
st.Page entries below.

The read-only query-param check below runs here too (ahead of every page, not just once)
because session_state -- not the URL -- is what actually keeps readonly mode in effect
across the sidebar's client-side page navigation, and a direct deep-link straight into a
page with ?readonly=true on it needs this same check to have run for that page as well."""

import streamlit as st

# A link with ?readonly=true hides every editing control on every page (session_state keeps
# it in effect across page navigation even if the URL's query string itself gets dropped by
# the sidebar's client-side routing; re-checking query_params each page still lets a direct
# deep-link into another page with ?readonly=true on it work on its own).
if st.query_params.get("readonly") is not None:
    st.session_state["readonly"] = st.query_params.get("readonly") in ("1", "true", "yes", "True")

pg = st.navigation({
    "Reporting": [
        st.Page("pages/0_Overview.py", title="Overview", icon="📊", default=True),
        st.Page("pages/1_Projects_Review.py", title="Projects Review", icon="🗂️"),
    ],
    "Development": [
        st.Page("pages/2_Special_Projects.py", title="Special Projects", icon="🎯"),
        st.Page("pages/3_Tools.py", title="Tools & AI Skills", icon="🛠️"),
        st.Page("pages/5_Gains.py", title="Gains & Outputs", icon="💡"),
    ],
    "Data": [
        st.Page("pages/4_Add_Data.py", title="Add Data", icon="➕"),
    ],
})
pg.run()
