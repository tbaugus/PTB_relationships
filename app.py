"""Quick internal testing UI for the PTB relationships system.

Not the candidate-facing app described in PLAN.md's "Future expansion
hooks" - this is a disposable local tool so colleagues can exercise
gap.py's closest_positions() and browse report.py's format-gap report
without touching a database or the CLI. Wraps the existing pure functions;
adds no new logic of its own.

Run with: streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from ptb import blooms, db, gap  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent
REPORT_PATH = REPO_ROOT / "reports" / "format_gaps.md"

st.set_page_config(page_title="PTB Relationships", layout="wide")


def get_connection():
    # Not cached: sqlite3 connections are thread-affine and Streamlit can
    # rerun the script on a different thread than created a cached one.
    # Opening a fresh read-only local connection per rerun is cheap enough.
    return db.connect(db.DEFAULT_DB_PATH)


@st.cache_data
def load_positions() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT p.code, p.title, sd.official, sd.format
        FROM positions p JOIN source_documents sd ON p.source_document_id = sd.id
        ORDER BY p.code
        """
    ).fetchall()
    return [dict(r) for r in rows]


@st.cache_data
def load_courses() -> list[str]:
    conn = get_connection()
    rows = conn.execute("SELECT DISTINCT value FROM position_requirements WHERE kind='course' ORDER BY value").fetchall()
    return [r["value"] for r in rows]


@st.cache_data
def load_bloom_by_position_task() -> dict[int, str]:
    """position_task_id -> Bloom's level name (from data/blooms.json)."""
    return blooms.levels_by_position_task(get_connection())


@st.cache_data
def load_tasks_for_position(code: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT pt.id, pt.task_number, pt.verbatim_text, pt.code_raw
        FROM position_tasks pt JOIN positions p ON pt.position_id = p.id
        WHERE p.code = ?
        ORDER BY pt.task_number
        """,
        (code,),
    ).fetchall()
    return [dict(r) for r in rows]


positions = load_positions()
position_labels = {f"{p['code']} — {p['title']}{' (NTFT)' if not p['official'] else ''}": p["code"] for p in positions}
courses = load_courses()
bloom_by_pt = load_bloom_by_position_task()


def bloom_tag(position_task_id: int) -> str:
    level = bloom_by_pt.get(position_task_id)
    return f"  ·  Bloom: {level}" if level else ""

st.title("PTB Relationships — Test Console")
tab_gap, tab_formats = st.tabs(["Gap analysis", "Format-gap report"])

# ---------------------------------------------------------------------------
# Tab 1: gap analysis
# ---------------------------------------------------------------------------

with tab_gap:
    st.caption(gap.DISCLAIMER)

    if "completed_tasks" not in st.session_state:
        st.session_state.completed_tasks = []  # list of (position_task_id, label, context)

    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.subheader("Candidate profile")

        held_labels = st.multiselect("Held qualifications", options=sorted(position_labels))
        held_codes = [position_labels[label] for label in held_labels]

        completed_courses = st.multiselect("Completed courses", options=courses)

        st.markdown("**Completed tasks**")
        task_source_label = st.selectbox(
            "Add a completed task from position", options=[""] + sorted(position_labels), key="task_source"
        )
        if task_source_label:
            source_code = position_labels[task_source_label]
            tasks = load_tasks_for_position(source_code)
            task_choice_labels = {
                f"#{t['task_number']} [{t['code_raw']}] {t['verbatim_text'][:70]}{bloom_tag(t['id'])}": t
                for t in tasks
            }
            chosen_task_label = st.selectbox("Task", options=[""] + list(task_choice_labels))
            context = st.selectbox(
                "Context this was completed in",
                options=["wildfire", "prescribed_fire", "incident", "simulation", "rare_event", "other", "developmental"],
            )
            if chosen_task_label and st.button("Add task"):
                t = task_choice_labels[chosen_task_label]
                st.session_state.completed_tasks.append(
                    {
                        "position_task_id": t["id"],
                        "label": f"{source_code} {chosen_task_label} ({context})",
                        "context": context,
                    }
                )
                st.rerun()

        if st.session_state.completed_tasks:
            st.markdown("_Added tasks:_")
            for i, ct in enumerate(st.session_state.completed_tasks):
                c1, c2 = st.columns([5, 1])
                c1.write(ct["label"])
                if c2.button("Remove", key=f"remove_{i}"):
                    st.session_state.completed_tasks.pop(i)
                    st.rerun()

        limit = st.slider("Show top N closest positions", min_value=1, max_value=30, value=10)
        run = st.button("Run gap analysis", type="primary")

    with col_right:
        st.subheader("Results")
        if run:
            profile = gap.CandidateProfile(
                held_qualifications=held_codes,
                completed_courses=completed_courses,
                completed_task_ids=[
                    gap.CompletedTask(position_task_id=ct["position_task_id"], context=ct["context"])
                    for ct in st.session_state.completed_tasks
                ],
            )
            results = gap.closest_positions(profile, limit=limit, conn=get_connection())

            if not results:
                st.info("No candidate positions found (everything held/conferred, or corpus is empty).")

            for pg in results:
                remaining = len(pg.gaps_tasks) + len(pg.gaps_context_only) + len(pg.gaps_requirements)
                draft_badge = f" — {gap.DRAFT_LABEL}" if pg.draft else ""
                with st.expander(f"{pg.position} — {pg.title}{draft_badge}  ·  {remaining} remaining", expanded=(remaining == 0)):
                    st.write(f"{len(pg.satisfied)}/{pg.total_slots} task slots satisfied.")

                    if pg.gaps_tasks:
                        st.markdown("**Tasks not yet demonstrated:**")
                        for g in pg.gaps_tasks:
                            st.write(f"- #{g.task_number} [{g.code_raw}] {g.verbatim_text}{bloom_tag(g.position_task_id)}")

                    if pg.gaps_context_only:
                        st.markdown("**Tasks demonstrated, but in the wrong context:**")
                        for g in pg.gaps_context_only:
                            st.write(f"- #{g.task_number} [{g.code_raw}] {g.verbatim_text}{bloom_tag(g.position_task_id)}")

                    if pg.gaps_requirements:
                        st.markdown("**Requirements remaining:**")
                        for r in pg.gaps_requirements:
                            st.write(f"- ({r.kind}) {r.value}")

                    waived = [r for r in pg.satisfied_requirements if r.derivation != "direct"]
                    if waived:
                        st.markdown("**Already satisfied via qualification chain:**")
                        for r in waived:
                            st.write(f"- {r.value} — {r.derivation} {r.derivation_position}")

                    if pg.info_requirements:
                        st.markdown("**Informational only (not assessed):**")
                        for r in pg.info_requirements:
                            st.write(f"- ({r.kind}) {r.value}")
        else:
            st.write("Set a profile on the left and click **Run gap analysis**.")

# ---------------------------------------------------------------------------
# Tab 2: format-gap report
# ---------------------------------------------------------------------------

with tab_formats:
    if REPORT_PATH.exists():
        st.markdown(REPORT_PATH.read_text(encoding="utf-8"))
    else:
        st.warning("reports/format_gaps.md not found — run `py src/ptb/report.py` first.")
