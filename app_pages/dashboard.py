import streamlit as st
import pandas as pd
import altair as alt
from datetime import date
from utils.db import get_sprints, get_team, get_leaves, get_holidays, get_backlog
from utils.helpers import get_workdays

# Title
st.title("Sprint analytics & context")

# Theme Colors for Charts
color_primary = '#1f4e78'
color_blue = '#4a90d9'
color_green = '#28a745'
color_orange = '#ffa500'
color_red = '#e74c3c'
color_gray = '#999'
color_light = '#a8c4de'

sprints_df = get_sprints()

if sprints_df.empty:
    st.info("Create a sprint first in Team & System Setup.", icon=":material/info:")
else:
    tab_analytics, tab_performance = st.tabs(["Sprint Analytics & Context", "Team Performance"])
    
    with tab_analytics:
        col_s1, _ = st.columns([2, 2])
        with col_s1:
            sprint_choice = st.selectbox("View sprint", sprints_df['name'].tolist(), index=0)

        s_info = sprints_df[sprints_df['name'] == sprint_choice].iloc[0]
        s_id, s_start, s_end = s_info['id'], s_info['start_date'], s_info['end_date']

        # --- CAPACITY ENGINE ---
        team = get_team()
        leaves = get_leaves(s_id)
        hols = get_holidays(s_id, s_start, s_end)
        work_days = get_workdays(s_start, s_end)

        cap_list = []
        for _, dev in team.iterrows():
            d_leaves = leaves[leaves['name'] == dev['name']]
            l_days = 0
            for _, l in d_leaves.iterrows():
                l_s = max(pd.to_datetime(l['start_date']).date(), pd.to_datetime(s_start).date())
                l_e = min(pd.to_datetime(l['end_date']).date(), pd.to_datetime(s_end).date())
                if l_s <= l_e:
                    l_days += get_workdays(l_s, l_e)

            dev_role = dev.get('role', '')
            daily_sp = 0.0 if dev_role in ['PM', 'EM'] else dev['daily_sp']
            net = (work_days - l_days - len(hols)) * daily_sp
            
            # Read member-specific buffer percentages from team table
            b_p = dev.get('bug_p', 15.0)
            a_p = dev.get('adhoc_p', 10.0)
            c_p = dev.get('ceremony_p', 10.0)
            
            dev_bug = net * (b_p / 100)
            dev_adhoc = net * (a_p / 100)
            dev_cere = net * (c_p / 100)
            plannable = net - (dev_bug + dev_adhoc + dev_cere)
            
            cap_list.append({
                "Name": dev['name'], 
                "Role": dev['role'], 
                "Net SP": net,
                "Bug SP": dev_bug,
                "Adhoc SP": dev_adhoc,
                "Ceremony SP": dev_cere,
                "Plannable SP": plannable
            })

        cap_df = pd.DataFrame(cap_list)
        total_net_sp = cap_df['Net SP'].sum()
        bug_v = cap_df['Bug SP'].sum()
        adhoc_v = cap_df['Adhoc SP'].sum()
        cere_v = cap_df['Ceremony SP'].sum()
        final_plannable = cap_df['Plannable SP'].sum()

        tasks = get_backlog(s_id)
        planned = tasks['sp'].sum() if not tasks.empty else 0

        done_tasks = tasks[tasks['status'] == 'Done'] if 'status' in tasks.columns and not tasks.empty else pd.DataFrame()
        inprog_tasks = tasks[tasks['status'] == 'In Progress'] if 'status' in tasks.columns and not tasks.empty else pd.DataFrame()
        velocity_sp = done_tasks['sp'].sum() if not done_tasks.empty else 0
        remaining_sp = planned - velocity_sp

        # --- METRICS OVERVIEW ---
        pct_used = (planned / final_plannable * 100) if final_plannable > 0 else 0
        pct_done = (velocity_sp / planned * 100) if planned > 0 else 0

        # Calculate trends over the last 5 sprints for rich sparkline displays
        last_5_sprints = sprints_df.head(5).iloc[::-1]
        capacity_trend = []
        velocity_trend = []
        buffers_trend = []

        for _, spr in last_5_sprints.iterrows():
            spr_id = spr['id']
            spr_start = spr['start_date']
            spr_end = spr['end_date']
            
            # Gross capacity calculation
            wk_days_spr = get_workdays(spr_start, spr_end)
            hols_spr = get_holidays(spr_id, spr_start, spr_end)
            leaves_spr = get_leaves(spr_id)
            
            net_sp_spr = 0
            buf_sp_spr = 0
            for _, dev in team.iterrows():
                d_leaves = leaves_spr[leaves_spr['name'] == dev['name']]
                l_days = 0
                for _, l in d_leaves.iterrows():
                    l_s = max(pd.to_datetime(l['start_date']).date(), pd.to_datetime(spr_start).date())
                    l_e = min(pd.to_datetime(l['end_date']).date(), pd.to_datetime(spr_end).date())
                    if l_s <= l_e:
                        l_days += get_workdays(l_s, l_e)
                
                dev_role = dev.get('role', '')
                daily_sp = 0.0 if dev_role in ['PM', 'EM'] else dev['daily_sp']
                dev_net = (wk_days_spr - l_days - len(hols_spr)) * daily_sp
                net_sp_spr += dev_net
                
                b_p = dev.get('bug_p', 15.0)
                a_p = dev.get('adhoc_p', 10.0)
                c_p = dev.get('ceremony_p', 10.0)
                buf_sp_spr += dev_net * (b_p + a_p + c_p) / 100
            
            capacity_trend.append(net_sp_spr)
            
            # Velocity trend
            sp_t = get_backlog(spr_id)
            sp_d = sp_t[sp_t['status'] == 'Done'] if 'status' in sp_t.columns and not sp_t.empty else pd.DataFrame()
            velocity_trend.append(sp_d['sp'].sum() if not sp_d.empty else 0)
            
            # Buffers trend
            buffers_trend.append(buf_sp_spr)

        # Fallback to single value if trends are empty
        if not capacity_trend:
            capacity_trend = [total_net_sp]
        if not velocity_trend:
            velocity_trend = [velocity_sp]
        if not buffers_trend:
            buffers_trend = [bug_v + adhoc_v + cere_v]

        # --- PROGRESS CARD ---
        with st.container(border=True):
            r1, r2 = st.columns([1, 3])
            with r1:
                st.markdown("### Sprint progress")
            with r2:
                st.progress(int(min(pct_done, 100)), text=f"{velocity_sp:.0f} / {planned:.0f} SP completed ({pct_done:.0f}%)")

        # --- SPARKLINE KPI CARDS ---
        m_cols = st.columns(4, border=True)
        m_cols[0].metric(
            "Team capacity", f"{total_net_sp:.0f}",
            help="Gross capacity (all members, full sprint)",
            chart_data=capacity_trend, chart_type="line"
        )
        m_cols[1].metric(
            "Plannable SP", f"{final_plannable:.1f}",
            help="After buffer deductions"
        )
        m_cols[2].metric(
            "Allocated SP", f"{planned:.1f}",
            delta=f"{final_plannable - planned:.1f}"
        )
        m_cols[3].metric(
            "Utilization", f"{pct_used:.0f}%",
            help="Allocated / Plannable"
        )

        # --- BURNDOWN CALCULATIONS ---
        burn_df = pd.DataFrame()
        sprint_not_started = False
        invalid_dates = False
        
        if not tasks.empty:
            s_start_dt = pd.to_datetime(s_start)
            s_end_dt = pd.to_datetime(s_end)
            today_dt = pd.to_datetime(date.today())
            
            if s_start_dt > s_end_dt:
                invalid_dates = True
            elif s_start_dt > today_dt:
                sprint_not_started = True
            else:
                end_dt = min(s_end_dt, today_dt)
                sprint_days = pd.bdate_range(s_start_dt, end_dt)
                total_days = len(pd.bdate_range(s_start_dt, s_end_dt)) or 1
                total_sp = tasks['sp'].sum()

                burn_rows = []
                for d in sprint_days:
                    d_done = done_tasks[pd.to_datetime(done_tasks['end_date'], errors='coerce').dt.normalize() <= pd.Timestamp(d.date())] if not done_tasks.empty else pd.DataFrame()
                    completed_by = d_done['sp'].sum() if not d_done.empty else 0
                    actual = total_sp - completed_by
                    idx = (d - s_start_dt).days
                    ideal = total_sp * (1 - idx / total_days)
                    burn_rows.append({"Date": d, "Actual": max(actual, 0), "Ideal": max(ideal, 0)})

                burn_df = pd.DataFrame(burn_rows)

        m_cols2 = st.columns(4, border=True)
        m_cols2[0].metric(
            "Completed", f"{velocity_sp:.1f}",
            help="SP marked Done",
            chart_data=velocity_trend, chart_type="line"
        )
        m_cols2[1].metric(
            "Remaining", f"{remaining_sp:.1f}",
            chart_data=burn_df["Actual"].tolist() if not burn_df.empty else [remaining_sp],
            chart_type="line"
        )
        m_cols2[2].metric(
            "Velocity", f"{pct_done:.0f}%" if planned > 0 else "N/A"
        )
        m_cols2[3].metric(
            "Buffers", f"{(bug_v + adhoc_v + cere_v):.1f}",
            help="Total buffer reservation",
            chart_data=buffers_trend, chart_type="bar"
        )

        # --- BURNDOWN CHART ---
        st.subheader("Sprint burndown")
        if not burn_df.empty:
            burn_melt = burn_df.melt(id_vars=['Date'], value_vars=['Actual', 'Ideal'], var_name='Type', value_name='Remaining SP')
            chart_burn = alt.Chart(burn_melt).mark_line(point=True).encode(
                x=alt.X("Date:T", title="Date"),
                y=alt.Y("Remaining SP:Q", title="Story Points"),
                color=alt.Color("Type:N", scale=alt.Scale(range=[color_primary, color_red]))
            ).properties(height=300)
            st.altair_chart(chart_burn)
        else:
            if tasks.empty:
                st.info("No tasks committed yet for this sprint.", icon=":material/info:")
            elif sprint_not_started:
                st.info(f"Sprint has not started yet. Planned start date is {s_start}.", icon=":material/info:")
            elif invalid_dates:
                st.error("Sprint start date is after end date. Please check sprint configuration.", icon=":material/error:")
            else:
                st.info("Burndown data not available — sprint dates may be invalid.", icon=":material/warning:")

        # --- MIDDLE ROW: Status / Buffers / Velocity Detail ---
        st.divider()
        c_dist, c_buf, c_velo = st.columns([1.2, 1, 1.5])

        with c_dist:
            st.subheader("Task status")
            if not tasks.empty and 'status' in tasks.columns:
                dist_data = tasks['status'].fillna('Todo').value_counts().reset_index()
                dist_data.columns = ['Status', 'Count']
                chart_dist = alt.Chart(dist_data).mark_bar(size=24, cornerRadius=4).encode(
                    x=alt.X("Status:N", title=None),
                    y=alt.Y("Count:Q", title="Count"),
                    color=alt.Color("Status:N", scale=alt.Scale(domain=['Todo', 'In Progress', 'Done'], range=[color_gray, color_orange, color_green]))
                ).properties(height=240)
                st.altair_chart(chart_dist)

        with c_buf:
            st.subheader("Buffer distribution")
            buf_tab1, buf_tab2 = st.tabs(["Capacity Budget", "Actual Task Load"])
            with buf_tab1:
                buf_df = pd.DataFrame({
                    "Category": ["Prod Bug", "Adhoc", "Ceremonies"],
                    "SP": [bug_v, adhoc_v, cere_v],
                })
                chart_pie = alt.Chart(buf_df).mark_arc(innerRadius=45).encode(
                    theta=alt.Theta(field="SP", type="quantitative"),
                    color=alt.Color(field="Category", type="nominal", scale=alt.Scale(range=[color_red, color_orange, color_primary])),
                    tooltip=["Category", "SP"]
                ).properties(height=200)
                st.altair_chart(chart_pie, use_container_width=True)
            with buf_tab2:
                actual_bug = tasks[tasks['category'] == 'Bug Fix']['sp'].sum() if not tasks.empty else 0.0
                actual_adhoc = tasks[tasks['category'] == 'Adhoc']['sp'].sum() if not tasks.empty else 0.0
                actual_buf_df = pd.DataFrame({
                    "Category": ["Prod Bug", "Adhoc", "Ceremonies"],
                    "SP": [actual_bug, actual_adhoc, cere_v],
                })
                chart_pie_act = alt.Chart(actual_buf_df).mark_arc(innerRadius=45).encode(
                    theta=alt.Theta(field="SP", type="quantitative"),
                    color=alt.Color(field="Category", type="nominal", scale=alt.Scale(range=[color_red, color_orange, color_primary])),
                    tooltip=["Category", "SP"]
                ).properties(height=200)
                st.altair_chart(chart_pie_act, use_container_width=True)

        with c_velo:
            st.subheader("Developer velocity")
            if not done_tasks.empty:
                velo_detail = done_tasks.copy()
                velo_detail['Duration'] = velo_detail.apply(
                    lambda r: (pd.to_datetime(r['end_date']) - pd.to_datetime(r['start_date'])).days
                    if r.get('end_date') and r.get('start_date') else None, axis=1)
                summary = velo_detail.groupby('assignee').agg(
                    Done=('ticket_id', 'count'), SP=('sp', 'sum'),
                    Avg_Days=('Duration', 'mean')).reset_index()
                summary['Avg_Days'] = summary['Avg_Days'].round(1)
                summary.columns = ['Assignee', 'Done', 'SP Completed', 'Avg Days/Ticket']
                st.dataframe(summary, hide_index=True, height=240)
            else:
                st.info("No completed tasks.", icon=":material/info:")

        # --- VELOCITY TREND ---
        st.divider()
        st.subheader("Velocity trend across sprints")
        velo_across = []
        for _, spr in sprints_df.iterrows():
            sp_t = get_backlog(spr['id'])
            sp_d = sp_t[sp_t['status'] == 'Done'] if 'status' in sp_t.columns else pd.DataFrame()
            velo_across.append({
                "Sprint": spr['name'],
                "Planned": sp_t['sp'].sum() if not sp_t.empty else 0,
                "Completed": sp_d['sp'].sum() if not sp_d.empty else 0,
            })

        velo_df = pd.DataFrame(velo_across)
        if not velo_df.empty and (velo_df['Planned'].sum() > 0 or velo_df['Completed'].sum() > 0):
            velo_melt = velo_df.melt(id_vars=['Sprint'], value_vars=['Planned', 'Completed'], var_name='Type', value_name='SP')
            chart_trend = alt.Chart(velo_melt).mark_bar(size=14, cornerRadius=4, opacity=0.85).encode(
                x=alt.X("Sprint:N", title="Sprint"),
                y=alt.Y("SP:Q", title="Story Points"),
                color=alt.Color("Type:N", scale=alt.Scale(range=[color_light, color_green])),
                xOffset="Type:N"
            ).properties(height=300)
            st.altair_chart(chart_trend)
        else:
            st.info("No sprint data available for trend analysis.", icon=":material/info:")

        # --- ROLE CHART + CEREMONY BREAKDOWN ---
        st.divider()
        c_role, c_cere = st.columns([1.5, 1])

        with c_role:
            st.subheader("Role load balancing (Supply vs Demand)")
            role_cap = cap_df.groupby('Role').agg(
                Net_SP=('Net SP', 'sum'),
                Plannable=('Plannable SP', 'sum')
            ).reset_index()
            role_alloc = tasks.groupby('role')['sp'].sum().reset_index() if not tasks.empty else pd.DataFrame(columns=['role', 'sp'])

            role_df = pd.merge(role_cap, role_alloc, left_on='Role', right_on='role', how='left').fillna(0)
            role_df = role_df.rename(columns={'sp': 'Allocated'})
            role_melt = role_df.melt(id_vars=['Role'], value_vars=['Plannable', 'Allocated'], var_name='Type', value_name='SP')

            chart_role = alt.Chart(role_melt).mark_bar(size=20, cornerRadius=4).encode(
                x=alt.X("Type:N", title=None),
                y=alt.Y("SP:Q", title="Story Points"),
                color=alt.Color("Type:N", scale=alt.Scale(range=[color_light, color_primary])),
                column=alt.Column("Role:N", title=None)
            ).properties(height=260, width=120)
            st.altair_chart(chart_role)

        with c_cere:
            st.subheader("Ceremony & buffer breakdown")
            actual_bug = tasks[tasks['category'] == 'Bug Fix']['sp'].sum() if not tasks.empty else 0.0
            actual_adhoc = tasks[tasks['category'] == 'Adhoc']['sp'].sum() if not tasks.empty else 0.0
            
            breakdown_data = [
                {"Activity": "Grooming", "Type": "Capacity Budget", "SP": cere_v * 0.5},
                {"Activity": "Grooming", "Type": "Actual Task Load", "SP": cere_v * 0.5},
                {"Activity": "Planning", "Type": "Capacity Budget", "SP": cere_v * 0.3},
                {"Activity": "Planning", "Type": "Actual Task Load", "SP": cere_v * 0.3},
                {"Activity": "Demo/Retro", "Type": "Capacity Budget", "SP": cere_v * 0.2},
                {"Activity": "Demo/Retro", "Type": "Actual Task Load", "SP": cere_v * 0.2},
                {"Activity": "Prod Support", "Type": "Capacity Budget", "SP": bug_v},
                {"Activity": "Prod Support", "Type": "Actual Task Load", "SP": actual_bug},
                {"Activity": "Adhoc", "Type": "Capacity Budget", "SP": adhoc_v},
                {"Activity": "Adhoc", "Type": "Actual Task Load", "SP": actual_adhoc},
            ]
            cere_df = pd.DataFrame(breakdown_data)
            
            chart_cere = alt.Chart(cere_df).mark_bar(size=8, cornerRadius=2).encode(
                y=alt.Y("Activity:N", sort=["Grooming", "Planning", "Demo/Retro", "Prod Support", "Adhoc"], title=None),
                x=alt.X("SP:Q", title="Story Points"),
                color=alt.Color("Type:N", scale=alt.Scale(range=[color_light, color_primary])),
                yOffset="Type:N"
            ).properties(height=260)
            st.altair_chart(chart_cere, use_container_width=True)

        # --- DEVELOPER PERFORMANCE ---
        st.divider()
        st.subheader("Team Allocation & Capacity Balancing")
        
        perf_list = []
        for _, dev in team.iterrows():
            dev_name = dev['name']
            cap_row = cap_df[cap_df['Name'] == dev_name].iloc[0]
            
            net_sp = cap_row['Net SP']
            bug_sp = cap_row['Bug SP']
            adhoc_sp = cap_row['Adhoc SP']
            cere_sp = cap_row['Ceremony SP']
            plannable_sp = cap_row['Plannable SP']
            
            dev_tasks = tasks[tasks['assignee'] == dev_name] if not tasks.empty else pd.DataFrame()
            tickets = len(dev_tasks)
            allocated_sp = dev_tasks['sp'].sum() if not dev_tasks.empty else 0.0
            
            remaining_sp = max(plannable_sp - allocated_sp, 0.0)
            util_pct = round((allocated_sp / plannable_sp * 100), 1) if plannable_sp > 0 else 0.0
            
            perf_list.append({
                "Name": dev_name,
                "Tickets": tickets,
                "Total capacity": round(net_sp, 1),
                "Prod bug buffer": round(bug_sp, 1),
                "Adhoc buffer": round(adhoc_sp, 1),
                "Ceremony buffer": round(cere_sp, 1),
                "Plannable": round(plannable_sp, 1),
                "Allocated": round(allocated_sp, 1),
                "Remaining": round(remaining_sp, 1),
                "Utilization %": util_pct
            })
            
        perf = pd.DataFrame(perf_list)

        if not perf.empty:
            tot_capacity = perf['Total capacity'].sum()
            tot_plannable = perf['Plannable'].sum()
            tot_allocated = perf['Allocated'].sum()
            tot_remaining = perf['Remaining'].sum()
            overall_util = round((tot_allocated / tot_plannable * 100), 1) if tot_plannable > 0 else 0.0
            
            # Draw beautiful KPI cards
            st.markdown("##### Overall Sprint Resource Balance")
            kpi_cols = st.columns(4)
            with kpi_cols[0]:
                st.metric("Total Sprint Capacity", f"{tot_capacity:.1f} SP", help="Total raw net capacity across team")
            with kpi_cols[1]:
                st.metric("Plannable Capacity", f"{tot_plannable:.1f} SP", help="Capacity available for backlog tasks (excluding buffers)")
            with kpi_cols[2]:
                st.metric("Allocated Backlog", f"{tot_allocated:.1f} SP", help="Sum of estimated story points of all assigned tasks")
            with kpi_cols[3]:
                delta_val = f"{tot_remaining:.1f} SP left" if tot_remaining > 0 else "Fully utilized"
                st.metric("Overall Utilization", f"{overall_util}%", delta=delta_val, delta_color="normal" if overall_util <= 100 else "inverse")
        
        # Melt and chart all 5 capacity components in a sleek vertical stacked bar
        perf_melt = perf.melt(
            id_vars=['Name'],
            value_vars=['Allocated', 'Remaining', 'Prod bug buffer', 'Adhoc buffer', 'Ceremony buffer'],
            var_name='Component',
            value_name='SP'
        )
        
        chart_perf = alt.Chart(perf_melt).mark_bar(size=24, cornerRadius=4).encode(
            x=alt.X("Name:N", title="Team member", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("SP:Q", title="Story Points", stack="zero"),
            color=alt.Color("Component:N", scale=alt.Scale(
                domain=['Allocated', 'Remaining', 'Prod bug buffer', 'Adhoc buffer', 'Ceremony buffer'],
                range=[color_green, color_blue, color_red, color_orange, color_primary]
            ), legend=alt.Legend(title="Capacity Allocation Components", orient="bottom")),
            tooltip=['Name:N', 'Component:N', 'SP:Q']
        ).properties(height=350)
        
        st.altair_chart(chart_perf, use_container_width=True)

        st.markdown("##### Detailed Allocation Breakdown")
        
        # Prepare fractional utilization for st.column_config.ProgressColumn
        perf_display = perf.copy()
        perf_display['Utilization Status'] = perf_display['Utilization %'] / 100.0
        
        st.dataframe(
            perf_display,
            column_config={
                "Name": st.column_config.TextColumn("Team Member", width="medium"),
                "Tickets": st.column_config.NumberColumn("Tickets", format="%d", width="small"),
                "Total capacity": st.column_config.NumberColumn("Total Capacity", format="%.1f SP", width="small"),
                "Prod bug buffer": st.column_config.NumberColumn("Bug Buffer", format="%.1f SP", width="small"),
                "Adhoc buffer": st.column_config.NumberColumn("Adhoc Buffer", format="%.1f SP", width="small"),
                "Ceremony buffer": st.column_config.NumberColumn("Ceremony Buffer", format="%.1f SP", width="small"),
                "Plannable": st.column_config.NumberColumn("Plannable", format="%.1f SP", width="small"),
                "Allocated": st.column_config.NumberColumn("Allocated", format="%.1f SP", width="small"),
                "Remaining": st.column_config.NumberColumn("Remaining", format="%.1f SP", width="small"),
                "Utilization %": st.column_config.NumberColumn("Util %", format="%.1f%%", width="small"),
                "Utilization Status": st.column_config.ProgressColumn(
                    "Utilization Status",
                    help="Story points allocated vs plannable capacity",
                    format="%.0f%%",
                    min_value=0.0,
                    max_value=1.5
                )
            },
            hide_index=True,
            use_container_width=True
        )

    with tab_performance:
        st.subheader("Team Performance per Sprint")
        
        # Sort sprints chronologically
        sprints_sorted = sprints_df.copy()
        sprints_sorted['start_date_dt'] = pd.to_datetime(sprints_sorted['start_date'])
        sprints_sorted = sprints_sorted.sort_values('start_date_dt')
        last_5 = sprints_sorted.tail(5)
        
        if not last_5.empty:
            # 1. Grouped Bar Chart of Planned vs Completed SP
            perf_data = []
            for _, spr in last_5.iterrows():
                spr_id = spr['id']
                spr_tasks = get_backlog(spr_id)
                planned_sp = spr_tasks['sp'].sum() if not spr_tasks.empty else 0.0
                completed_sp = spr_tasks[spr_tasks['status'] == 'Done']['sp'].sum() if not spr_tasks.empty else 0.0
                perf_data.append({
                    "Sprint": spr['name'],
                    "Planned SP": planned_sp,
                    "Completed SP": completed_sp,
                    "Spillover SP": max(planned_sp - completed_sp, 0.0)
                })
            df_perf_compare = pd.DataFrame(perf_data)
            
            df_melted = df_perf_compare.melt(id_vars=['Sprint'], value_vars=['Planned SP', 'Completed SP'], var_name='Type', value_name='Story Points')
            chart_vel = alt.Chart(df_melted).mark_bar(size=14, cornerRadius=4).encode(
                x=alt.X('Sprint:N', sort=df_perf_compare['Sprint'].tolist(), title="Sprint"),
                y=alt.Y('Story Points:Q', title="Story Points"),
                color=alt.Color('Type:N', scale=alt.Scale(domain=['Planned SP', 'Completed SP'], range=[color_blue, color_green])),
                xOffset='Type:N'
            ).properties(height=350, title="Velocity Comparison (Planned vs Completed)")
            st.altair_chart(chart_vel, use_container_width=True)
            
            # 2. Multi-Sprint Burndown Curves Comparison
            st.subheader("Burndown Curve Comparison (Normalized)")
            st.caption("This chart displays remaining SP (%) over duration (%) of each sprint to compare progress patterns.")
            comparison_rows = []
            for _, spr in last_5.iterrows():
                spr_id = spr['id']
                spr_name = spr['name']
                spr_tasks = get_backlog(spr_id)
                if spr_tasks.empty:
                    continue
                
                s_start_raw = spr.get('actual_start_date') or spr.get('start_date')
                s_end_raw = spr.get('actual_end_date') or spr.get('end_date')
                if not s_start_raw or not s_end_raw:
                    continue
                s_start = pd.to_datetime(s_start_raw, errors='coerce')
                s_end = pd.to_datetime(s_end_raw, errors='coerce')
                if pd.isna(s_start) or pd.isna(s_end):
                    continue
                work_days_list = pd.bdate_range(s_start, s_end)
                if len(work_days_list) <= 1:
                    continue
                    
                total_sp = spr_tasks['sp'].sum()
                if total_sp == 0:
                    continue
                    
                done_tasks = spr_tasks[spr_tasks['status'] == 'Done'] if 'status' in spr_tasks.columns else pd.DataFrame()
                
                # Day 0
                comparison_rows.append({
                    "Sprint": spr_name,
                    "% Days Elapsed": 0.0,
                    "% SP Remaining": 100.0
                })
                
                total_days = len(work_days_list) - 1
                for idx, day in enumerate(work_days_list[1:], start=1):
                    if not done_tasks.empty:
                        completed_by = done_tasks[pd.to_datetime(done_tasks['end_date'], errors='coerce').dt.normalize() <= pd.Timestamp(day.date())]['sp'].sum()
                    else:
                        completed_by = 0
                        
                    remaining_sp_pct = max(total_sp - completed_by, 0.0) / total_sp * 100
                    days_elapsed_pct = (idx / total_days) * 100
                    
                    comparison_rows.append({
                        "Sprint": spr_name,
                        "% Days Elapsed": round(days_elapsed_pct, 1),
                        "% SP Remaining": round(remaining_sp_pct, 1)
                    })
                    
            if comparison_rows:
                df_compare_burn = pd.DataFrame(comparison_rows)
                chart_burn_compare = alt.Chart(df_compare_burn).mark_line(interpolate='monotone', point=True).encode(
                    x=alt.X('% Days Elapsed:Q', title="% Days Elapsed in Sprint"),
                    y=alt.Y('% SP Remaining:Q', title="% SP Remaining"),
                    color=alt.Color('Sprint:N')
                ).properties(height=350, title="Normalized Burndown Curves Comparison")
                st.altair_chart(chart_burn_compare, use_container_width=True)
            else:
                st.info("Not enough data to compute normalized burndown curves.")
                
            # 3. Highlights (Good & Bad things)
            st.subheader("Performance & Lifecycle Highlights")
            good_points = []
            bad_points = []
            
            for _, spr in last_5.iterrows():
                spr_id = spr['id']
                spr_name = spr['name']
                spr_tasks = get_backlog(spr_id)
                planned_sp = spr_tasks['sp'].sum() if not spr_tasks.empty else 0.0
                completed_sp = spr_tasks[spr_tasks['status'] == 'Done']['sp'].sum() if not spr_tasks.empty else 0.0
                
                completion_rate = (completed_sp / planned_sp * 100) if planned_sp > 0 else 0.0
                
                p_start = pd.to_datetime(spr['start_date'])
                p_end = pd.to_datetime(spr['end_date'])
                a_start_val = spr.get('actual_start_date')
                a_start = pd.to_datetime(a_start_val) if pd.notna(a_start_val) and a_start_val else None
                a_end_val = spr.get('actual_end_date')
                a_end = pd.to_datetime(a_end_val) if pd.notna(a_end_val) and a_end_val else None
                
                start_lag = (a_start - p_start).days if a_start else 0
                end_lag = (a_end - p_end).days if a_end else 0
                
                # Good things
                if completion_rate >= 90:
                    good_points.append(f"🎉 **{spr_name}** achieved an outstanding completion rate of **{completion_rate:.0f}%** ({completed_sp:.1f}/{planned_sp:.1f} SP completed).")
                elif completion_rate >= 75:
                    good_points.append(f"👍 **{spr_name}** completed a solid **{completion_rate:.0f}%** of its planned scope.")
                if a_start and start_lag <= 0:
                    good_points.append(f"⏱️ **{spr_name}** started on time (or early) on **{a_start.date()}**.")
                
                # Room for improvement (Bad things)
                if completion_rate < 70 and planned_sp > 0:
                    bad_points.append(f"⚠️ **{spr_name}** experienced high spillover, completing only **{completion_rate:.0f}%** of planned SP.")
                if start_lag > 0:
                    bad_points.append(f"⏳ **{spr_name}** started late by **{start_lag}** day(s).")
                if end_lag > 0:
                    bad_points.append(f"🚨 **{spr_name}** completed late by **{end_lag}** day(s).")
                    
            c_good, c_bad = st.columns(2)
            with c_good:
                st.markdown("#### 🟢 What Went Well")
                if good_points:
                    for pt in good_points[:5]:
                        st.markdown(pt)
                else:
                    st.markdown("No positive highlights recorded for the recent sprints yet.")
                    
            with c_bad:
                st.markdown("#### 🔴 Room for Improvement")
                if bad_points:
                    for pt in bad_points[:5]:
                        st.markdown(pt)
                else:
                    st.markdown("No significant negative anomalies detected. Sprints are running smoothly!")
        else:
            st.info("Create and complete sprints to see performance trends.")
