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
        selected_sprint = st.selectbox("Select Sprint to View Report", sprint_names)
        
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
        tab1, tab2, tab3 = st.tabs(["Executive Summary", "Developer Workload", "Backlog & Buffer Details"])
        
        with tab1:
            st.markdown("### Executive Summary")
            st.info(report_doc.get('summary', 'No summary available.'))
            
            k_col1, k_col2, k_col3, k_col4 = st.columns(4)
            with k_col1:
                st.metric("Committed SP", f"{report_doc['planned_sp']:.1f}")
            with k_col2:
                st.metric("Delivered SP", f"{report_doc['delivered_sp']:.1f}")
            with k_col3:
                st.metric("SP Completion Rate", f"{report_doc['completion_rate_sp']:.1f}%")
            with k_col4:
                st.metric("Net Utilization Rate", f"{report_doc['utilization_rate']:.1f}%")
                
        with tab2:
            st.markdown("### Developer performance metrics")
            dev_df = pd.DataFrame(report_doc['dev_details'])
            if not dev_df.empty:
                dev_df.columns = ["Developer Name", "Role", "Net Days Capacity", "Committed SP", "Completed SP", "Delivery Rate (%)"]
                st.dataframe(dev_df.set_index("Developer Name"), use_container_width=True)
            else:
                st.info("No developer capacity records in this sprint.")
                
        with tab3:
            st.markdown("### Buffer Usage Highlights")
            b_col1, b_col2, b_col3 = st.columns(3)
            with b_col1:
                st.metric("Bug Buffer Allocated vs Used", f"{report_doc['bug_buffer_allocated']:.1f} SP", f"Used: {report_doc['bug_buffer_used']:.1f} SP", delta_color="inverse")
            with b_col2:
                st.metric("Adhoc Buffer Allocated vs Used", f"{report_doc['adhoc_buffer_allocated']:.1f} SP", f"Used: {report_doc['adhoc_buffer_used']:.1f} SP", delta_color="inverse")
            with b_col3:
                st.metric("Ceremony Buffer Allocated", f"{report_doc['ceremony_buffer_allocated']:.1f} SP", help="Assumed fully consumed by ceremonies and admin tasks.")
                
            st.markdown("### Committed Backlog Items")
            tickets = report_doc.get('tickets', [])
            if tickets:
                tickets_df = pd.DataFrame(tickets)
                tickets_df.columns = ["Ticket ID", "Title", "Assignee", "Category", "Story Points", "Status"]
                st.dataframe(tickets_df.set_index("Ticket ID"), use_container_width=True)
            else:
                st.info("No backlog tickets found in this report.")
