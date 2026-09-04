import streamlit as st
import pandas as pd
from utils.db import get_sprints, get_sprint_report, save_sprint_report, get_current_team_id
from utils.reports_generator import compile_and_save_report

st.title("Sprint Performance Reports")
st.markdown("View historical sprint reports, download PDF & Excel summaries, and review team performance KPIs.")

sprints_df = get_sprints()

if sprints_df.empty:
    st.info("No sprints exist yet. Create a sprint to begin.", icon=":material/info:")
else:
    # 1. Selection
    team_id = get_current_team_id()
    
    col1, col2 = st.columns([3, 2])
    with col1:
        sprint_names = sprints_df['name'].tolist()
        active_sprint = sprints_df[sprints_df['status'] == 'Active']
        active_name = active_sprint.iloc[0]['name'] if not active_sprint.empty else None
        default_index = sprint_names.index(active_name) if active_name in sprint_names else 0
        selected_sprint = st.selectbox("Select Sprint to View Report", sprint_names, index=default_index)
        
    s_row = sprints_df[sprints_df['name'] == selected_sprint].iloc[0]
    s_id = s_row['id']
    s_status = s_row['status']
    
    # 2. Check if report is already stored in MongoDB
    report_doc = get_sprint_report(s_id)
    
    if not report_doc:
        st.warning(f"No performance report has been compiled yet for '{selected_sprint}'.")
        
        # Allow generating on demand for active or historical sprints
        if st.button("Generate Performance Report Now", type="primary"):
            with st.spinner("Compiling database records and generating report exports..."):
                try:
                    report_doc = compile_and_save_report(s_id)
                    st.success(f"Report compiled and archived successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to generate report: {str(e)}")
    
    if report_doc:
        st.success(f"Performance report loaded. Status: **{s_status}** (Report generated at: {report_doc.get('generated_at', 'N/A')[:19].replace('T', ' ')})")

        # Regenerate button
        regen_col1, regen_col2 = st.columns([1, 5])
        with regen_col1:
            if st.button("🔄 Regenerate Report", type="secondary", help="Recompile the report from latest data — useful if tickets were updated after the last generation."):
                with st.spinner("Regenerating report from latest data..."):
                    try:
                        report_doc = compile_and_save_report(s_id)
                        st.success("Report regenerated successfully with latest data!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to regenerate report: {str(e)}")

        # 3. Download Section
        d_col1, d_col2, d_col3 = st.columns(3)
        with d_col1:
            st.download_button(
                label="📥 Download PDF Document",
                data=bytes(report_doc['pdf_data']),
                file_name=f"{selected_sprint.replace(' ', '_')}_Report.pdf",
                mime="application/pdf",
                use_container_width=True
            )
        with d_col2:
            st.download_button(
                label="📥 Download Excel Spreadsheet",
                data=bytes(report_doc['excel_data']),
                file_name=f"{selected_sprint.replace(' ', '_')}_Backlog_Capacity.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        with d_col3:
            st.download_button(
                label="📥 Download Dashboard Card (PNG)",
                data=bytes(report_doc['png_data']),
                file_name=f"{selected_sprint.replace(' ', '_')}_Dashboard.png",
                mime="image/png",
                use_container_width=True
            )
            
        st.divider()
        
        # 4. Render Visual KPI Dashboard Card (PNG) directly onto the page!
        st.subheader("Performance Dashboard Card")
        st.image(bytes(report_doc['png_data']), use_container_width=True)
        
        st.divider()
        
        # 5. Detail Tabs
        tab1, tab2, tab3, tab4 = st.tabs(["Executive Summary", "Team Performance", "Capacity & Buffers", "Backlog Details"])

        with tab1:
            st.markdown("### Sprint Overview")
            st.info(report_doc.get('summary', 'No summary available.'))

            # Primary KPIs
            k_col1, k_col2, k_col3, k_col4 = st.columns(4)
            with k_col1:
                st.metric("Committed SP", f"{report_doc['planned_sp']:.1f}")
            with k_col2:
                st.metric("Delivered SP", f"{report_doc['delivered_sp']:.1f}")
            with k_col3:
                st.metric("SP Completion Rate", f"{report_doc['completion_rate_sp']:.1f}%")
            with k_col4:
                st.metric("Net Utilization Rate", f"{report_doc['utilization_rate']:.1f}%")

            st.divider()

            # Secondary KPIs
            st.markdown("### Capacity & Allocation Metrics")
            c_col1, c_col2, c_col3, c_col4 = st.columns(4)
            with c_col1:
                st.metric("Total Team Capacity", f"{report_doc['total_team_capacity']:.1f} SP")
            with c_col2:
                st.metric("Plannable Capacity", f"{report_doc['plannable_capacity']:.1f} SP")
            with c_col3:
                st.metric("Allocation Rate", f"{report_doc.get('allocation_rate', 0):.1f}%")
            with c_col4:
                st.metric("Avg Team Delivery", f"{report_doc.get('avg_team_delivery', 0):.1f}%")

            st.divider()

            # Sprint Health
            st.markdown("### Sprint Health")
            h_col1, h_col2, h_col3, h_col4 = st.columns(4)
            with h_col1:
                st.metric("Total Tickets", f"{report_doc['planned_tickets']}")
            with h_col2:
                st.metric("Completed Tickets", f"{report_doc['completed_tickets']}")
            with h_col3:
                st.metric("Spillover Tickets", f"{report_doc['spillover_tickets']}")
            with h_col4:
                st.metric("Bug Resolution Rate", f"{report_doc['bug_resolution_rate']:.1f}%")

        with tab2:
            st.markdown("### Team Performance Breakdown")
            dev_df = pd.DataFrame(report_doc['dev_details'])
            if not dev_df.empty:
                # Get available columns
                available_cols = dev_df.columns.tolist()

                # Define desired display columns
                display_cols = ["name", "role", "eff_days", "daily_sp", "capacity", "allocated", "remaining", "completed", "delivery_rate", "utilization_rate"]

                # Filter to only columns that exist
                actual_display_cols = [c for c in display_cols if c in available_cols]

                if actual_display_cols:
                    dev_display = dev_df[actual_display_cols].copy()

                    # Create column mapping
                    col_mapping = {
                        "name": "Name",
                        "role": "Role",
                        "eff_days": "Eff. Days",
                        "daily_sp": "Daily SP",
                        "capacity": "Capacity SP",
                        "allocated": "Allocated SP",
                        "remaining": "Remaining SP",
                        "completed": "Completed SP",
                        "delivery_rate": "Delivery %",
                        "utilization_rate": "Utilization %"
                    }

                    # Rename columns that exist in mapping
                    new_columns = [col_mapping.get(col, col) for col in actual_display_cols]
                    dev_display.columns = new_columns
                    dev_display = dev_display.set_index("Name")

                    # Create format dict for only columns that exist
                    format_dict = {}
                    if "Eff. Days" in dev_display.columns:
                        format_dict["Eff. Days"] = "{:.0f}"
                    if "Daily SP" in dev_display.columns:
                        format_dict["Daily SP"] = "{:.1f}"
                    if "Capacity SP" in dev_display.columns:
                        format_dict["Capacity SP"] = "{:.1f}"
                    if "Allocated SP" in dev_display.columns:
                        format_dict["Allocated SP"] = "{:.1f}"
                    if "Remaining SP" in dev_display.columns:
                        format_dict["Remaining SP"] = "{:.1f}"
                    if "Completed SP" in dev_display.columns:
                        format_dict["Completed SP"] = "{:.1f}"
                    if "Delivery %" in dev_display.columns:
                        format_dict["Delivery %"] = "{:.1f}"
                    if "Utilization %" in dev_display.columns:
                        format_dict["Utilization %"] = "{:.1f}"

                    st.dataframe(dev_display.style.format(format_dict), use_container_width=True)

                    st.divider()
                    st.markdown("### Role Distribution")
                    if "Role" in dev_df.columns:
                        role_summary = dev_df.groupby("Role").agg({
                            "name": "count",
                            "allocated": "sum",
                            "completed": "sum"
                        }).rename(columns={"name": "Count", "allocated": "Allocated SP", "completed": "Completed SP"})
                        st.dataframe(role_summary.style.format({"Allocated SP": "{:.1f}", "Completed SP": "{:.1f}"}), use_container_width=True)
                else:
                    st.warning("No developer data available to display")
            else:
                st.info("No developer capacity records in this sprint.")

        with tab3:
            st.markdown("### Buffer Allocation vs Usage")
            b_col1, b_col2, b_col3 = st.columns(3)
            with b_col1:
                bug_used = report_doc['bug_buffer_used']
                bug_alloc = report_doc['bug_buffer_allocated']
                st.metric("Bug Buffer", f"{bug_alloc:.1f} SP", f"Used: {bug_used:.1f} SP", delta_color="inverse")
                if bug_alloc > 0:
                    st.progress(min(bug_used / bug_alloc, 1.0), text=f"{bug_used/bug_alloc*100:.0f}% consumed")
            with b_col2:
                adhoc_used = report_doc['adhoc_buffer_used']
                adhoc_alloc = report_doc['adhoc_buffer_allocated']
                st.metric("Adhoc Buffer", f"{adhoc_alloc:.1f} SP", f"Used: {adhoc_used:.1f} SP", delta_color="inverse")
                if adhoc_alloc > 0:
                    st.progress(min(adhoc_used / adhoc_alloc, 1.0), text=f"{adhoc_used/adhoc_alloc*100:.0f}% consumed")
            with b_col3:
                cere_alloc = report_doc['ceremony_buffer_allocated']
                st.metric("Ceremony Buffer", f"{cere_alloc:.1f} SP", help="Assumed fully consumed by ceremonies and admin tasks.")

            st.divider()

            st.markdown("### Capacity Breakdown")
            cap_data = {
                "Component": ["Total Capacity", "Bug Buffer", "Adhoc Buffer", "Ceremony Buffer", "Plannable Capacity", "Allocated", "Delivered"],
                "SP": [
                    report_doc['total_team_capacity'],
                    report_doc['bug_buffer_allocated'],
                    report_doc['adhoc_buffer_allocated'],
                    report_doc['ceremony_buffer_allocated'],
                    report_doc['plannable_capacity'],
                    report_doc['planned_sp'],
                    report_doc['delivered_sp']
                ]
            }
            cap_df = pd.DataFrame(cap_data)
            st.dataframe(cap_df.set_index("Component"), use_container_width=True)

            st.divider()
            st.markdown("### Sprint Calendar")
            cal_col1, cal_col2, cal_col3, cal_col4 = st.columns(4)
            with cal_col1:
                st.metric("Work Days", f"{report_doc.get('total_work_days', 'N/A')}")
            with cal_col2:
                st.metric("Holidays", f"{report_doc.get('holiday_count', 0)}")
            with cal_col3:
                st.metric("Total Leaves", f"{report_doc.get('total_leaves', 0)}")
            with cal_col4:
                st.metric("Team Size", f"{report_doc.get('team_size', 0)}")

        with tab4:
            st.markdown("### Committed Backlog Items")
            tickets = report_doc.get('tickets', [])
            if tickets:
                tickets_df = pd.DataFrame(tickets)
                tickets_df.columns = ["Ticket ID", "Title", "Assignee", "Category", "Story Points", "Status"]
                st.dataframe(tickets_df.set_index("Ticket ID"), use_container_width=True)

                st.divider()
                st.markdown("### Category Distribution")
                if "Category" in tickets_df.columns:
                    cat_summary = tickets_df.groupby("Category").agg({
                        "Ticket ID": "count",
                        "Story Points": "sum"
                    }).rename(columns={"Ticket ID": "Count", "Story Points": "Total SP"})
                    st.dataframe(cat_summary.style.format({"Total SP": "{:.1f}"}), use_container_width=True)

                st.divider()
                st.markdown("### Status Distribution")
                if "Status" in tickets_df.columns:
                    status_summary = tickets_df.groupby("Status").agg({
                        "Ticket ID": "count",
                        "Story Points": "sum"
                    }).rename(columns={"Ticket ID": "Count", "Story Points": "Total SP"})
                    st.dataframe(status_summary.style.format({"Total SP": "{:.1f}"}), use_container_width=True)
            else:
                st.info("No backlog tickets found in this report.")
