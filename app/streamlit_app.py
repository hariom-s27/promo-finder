"""Open saved results and a temporary-file-only live demo on the official Azure models."""
from __future__ import annotations

import json
import os
import hashlib
from pathlib import Path

from promo_finder import demo

ROOT = Path(__file__).resolve().parents[1]


def setting(st, name, *, environment=False):
    try:
        value = st.secrets[name]
    except (KeyError, FileNotFoundError):
        value = None
    return value or (os.environ.get(name) if environment else None)


def full_results(st):
    try:
        data = json.loads((ROOT / "app/assets/full_results.json").read_text(encoding="utf-8"))
        metrics = (ROOT / "docs/RESULTS.md").read_text(encoding="utf-8")
    except (OSError, ValueError):
        st.error("Saved results are unavailable. Rebuild the app results export before deployment.")
        return
    st.write("Ranked promos from the completed 50-episode Azure v1 run.")
    st.subheader("Launch batch")
    launch = data["launch_batch"]
    if launch:
        columns = st.columns(len(launch))
        for column, promo in zip(columns, launch):
            with column:
                with st.container(border=True):
                    st.markdown(f"**Episode {promo['episode']} · rank {promo['rank']}**")
                    st.write(f"{promo['start']}–{promo['end']}")
                    st.caption(f"{promo['duration']:.1f} s · {promo['hook_type']} / {promo['cliff_type']}")
                    st.metric("S", f"{promo['S']:.3f}" if promo["S"] is not None else "Unscored")
    else:
        st.info("The saved run has no launch-batch promos.")
    with st.container(border=True):
        st.subheader("Cost at scale")
        scale = data["cost_at_scale"]
        st.caption(f"Assumption: {scale['shows_per_month']} shows/month, each with the same 50-episode workload, pricing and run time as P07b. Time is a serial projection.")
        st.write(f"Per show: USD {scale['per_show_usd']:.3f} · {scale['per_show_minutes']:.1f} minutes")
        st.write(f"Monthly: USD {scale['monthly_usd']:.2f} · {scale['monthly_minutes']:,.1f} minutes ({scale['monthly_serial_hours']:.1f} serial hours)")
    st.caption("Metadata only. A + separates cuts in a multi-segment promo; duration is the summed segment time in seconds. Unscored promos have an empty S score.")
    st.dataframe(data["promos"], hide_index=True, use_container_width=True)
    st.metric("Full v1 reported-usage cost (USD)", f"{data['azure_totals']['usd']:.3f}")
    st.metric("v2 rerun reported-usage cost (USD)", f"{data['v2_cost_usd']:.3f}")
    st.caption("v2 reused cached work. Costs use reported usage and configured list prices; failed-request token usage was unreported.")
    st.write("Azure usage by pipeline stage")
    st.dataframe(data["azure_stages"], hide_index=True, use_container_width=True)
    st.write("Whole-run Azure usage")
    st.dataframe([data["azure_totals"]], hide_index=True, use_container_width=True)
    with st.expander("Evaluation metrics and limitations"):
        st.markdown(metrics)


def live_demo(st):
    st.caption("Small demo on the official Azure models; full runs via CLI.")
    # Secrets come only from Streamlit secrets (or the environment) and stay in memory.
    secrets = {name: setting(st, name, environment=True) for name in demo.SECRET_NAMES}
    missing = demo.missing_secrets(secrets)
    if missing:
        st.info("live demo is not configured (missing secrets: " + ", ".join(missing) + "); full results are in Tab 1")
        return
    if demo.DAILY_CAP.remaining <= 0:
        st.info(demo.DAILY_CAP_MESSAGE)
        return
    st.write("Upload 1–3 UTF-8 episode .txt files in the input-pack format. Files and generated working data are deleted after processing. Text is sent to Azure when you start the run.")
    st.caption(f"Use episode-001-Episode 1.txt style filenames. Shared daily cap: {demo.DAILY_CAP.limit} episodes per UTC day across all visitors "
               f"({demo.DAILY_CAP.remaining} left). The demo skips the comparison baseline and is not an evaluation.")
    uploads = st.file_uploader("Episodes", type=["txt"], accept_multiple_files=True)
    if not uploads:
        return
    if len(uploads) > 3:
        st.error("Upload at most three episodes.")
        return
    entries = [(upload.name, upload.getvalue()) for upload in uploads]
    try:
        demo.validate_uploads(entries)
    except demo.DemoError as exc:
        st.error(str(exc))
        return
    signature = hashlib.sha256()
    for name, raw in entries:
        signature.update(name.encode("utf-8"))
        signature.update(b"\0")
        signature.update(hashlib.sha256(raw).digest())
    if st.session_state.get("upload_signature") != signature.hexdigest():
        st.session_state.pop("promo_result", None)
        st.session_state["upload_signature"] = signature.hexdigest()
    if st.button("Find promos", type="primary"):
        # Retain only the display/download data in the active session, never files.
        st.session_state.pop("promo_result", None)
        with st.status("Processing episodes…", expanded=True) as status:
            try:
                rows = demo.run_uploads(entries, secrets)
            except demo.DemoError as exc:
                status.update(label="Run stopped", state="error")
                (st.info if isinstance(exc, demo.DemoNotice) else st.error)(str(exc))
                return
            st.session_state["promo_result"] = rows
            status.update(label=f"Complete: {len(rows)} promos", state="complete")
    if "promo_result" in st.session_state:
        rows = st.session_state["promo_result"]
        st.dataframe(rows, hide_index=True, use_container_width=True)
        if not rows:
            st.info("No clips passed the configured builder gates.")
        st.download_button("Download JSON", json.dumps(rows, ensure_ascii=False, indent=2),
                           file_name="promos.json", mime="application/json")


def main(st=None):
    if st is None:
        import streamlit as st
    st.set_page_config(page_title="Promo finder demo", layout="wide")
    st.title("Promo finder")
    saved, live = st.tabs(["Full results (Azure run)", "Try it live"])
    with saved:
        full_results(st)
    with live:
        live_demo(st)


if __name__ == "__main__":
    main()
