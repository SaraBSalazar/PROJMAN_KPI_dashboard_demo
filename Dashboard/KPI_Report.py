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

# Sidebar icons are Material Symbols (":material/name:"), not emoji: they're monochrome, they
# take the theme's own ink colour, and they line up at one optical weight -- a row of emoji
# reads as decoration next to them. The browser-tab icon each page sets in its own
# st.set_page_config stays an emoji, where a flat glyph is the thing that's legible at 16px.
pg = st.navigation({
    "Reporting": [
        st.Page("pages/0_Overview.py", title="Overview", icon=":material/dashboard:", default=True),
        st.Page("pages/1_Projects_Review.py", title="Projects Review", icon=":material/folder_open:"),
        st.Page("pages/6_Publications_Courses.py", title="Publications & Courses",
                icon=":material/menu_book:"),
    ],
    "Development": [
        st.Page("pages/2_Special_Projects.py", title="Special Projects", icon=":material/flag:"),
        st.Page("pages/3_Tools.py", title="Tools & AI Skills", icon=":material/handyman:"),
        st.Page("pages/5_Gains.py", title="Gains & Outputs", icon=":material/trending_up:"),
    ],
    "Profile": [
        st.Page("pages/7_CV.py", title="CV", icon=":material/badge:"),
    ],
    "Data": [
        st.Page("pages/4_Add_Data.py", title="Add Data", icon=":material/edit_note:"),
    ],
})
pg.run()
