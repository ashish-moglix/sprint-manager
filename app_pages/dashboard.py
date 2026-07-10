import streamlit as st
import pandas as pd
import altair as alt
from datetime import date
from utils.db import get_sprints, get_team, get_leaves, get_holidays, get_backlog
from utils.helpers import get_workdays

# Title
st.title("Sprint analytics & context")

# Ensure session state variables for buffers are initialized
if "bug_p" not in st.session_state:
    st.session_state.bug_p = 15
if "adhoc_p" not in st.session_state:
    st.session_state.adhoc_p = 10
if "ceremony_p" not in st.session_state:
    st.session_state.ceremony_p = 10

# Sidebar configuration
with st.sidebar:
    st.subheader("Capacity buffers")
    bug_p = st.slider("Prod bug buffer (%)", 0, 30, key="bug_p")
    adhoc_p = st.slider("Adhoc buffer (%)", 0, 20, key="adhoc_p")
    ceremony_p = st.slider("Ceremonies buffer (%)", 0, 25, key="ceremony_p")

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

        net = (work_days - l_days - len(hols)) * dev['daily_sp']
        cap_list.append({"Name": dev['name'], "Role": dev['role'], "Net SP": net})

    cap_df = pd.DataFrame(cap_list)
    total_net_sp = cap_df['Net SP'].sum()
    bug_v = total_net_sp * (bug_p / 100)
    adhoc_v = total_net_sp * (adhoc_p / 100)
    cere_v = total_net_sp * (ceremony_p / 100)
    final_plannable = total_net_sp - (bug_v + adhoc_v + cere_v)

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
        for _, dev in team.iterrows():
            d_leaves = leaves_spr[leaves_spr['name'] == dev['name']]
            l_days = 0
            for _, l in d_leaves.iterrows():
                l_s = max(pd.to_datetime(l['start_date']).date(), pd.to_datetime(spr_start).date())
                l_e = min(pd.to_datetime(l['end_date']).date(), pd.to_datetime(spr_end).date())
                if l_s <= l_e:
                    l_days += get_workdays(l_s, l_e)
            net_sp_spr += (wk_days_spr - l_days - len(hols_spr)) * dev['daily_sp']
        
        capacity_trend.append(net_sp_spr)
        
        # Velocity trend
        sp_t = get_backlog(spr_id)
        sp_d = sp_t[sp_t['status'] == 'Done'] if 'status' in sp_t.columns and not sp_t.empty else pd.DataFrame()
        velocity_trend.append(sp_d['sp'].sum() if not sp_d.empty else 0)
        
        # Buffers trend
        buffers_trend.append(net_sp_spr * (bug_p + adhoc_p + ceremony_p) / 100)

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
    if not tasks.empty:
        s_start_dt = pd.to_datetime(s_start)
        s_end_dt = pd.to_datetime(s_end)
        today_dt = pd.to_datetime(date.today())
        end_dt = min(s_end_dt, today_dt)
        sprint_days = pd.bdate_range(s_start_dt, end_dt)
        total_days = len(pd.bdate_range(s_start_dt, s_end_dt)) or 1
        total_sp = tasks['sp'].sum()

        burn_rows = []
        for d in sprint_days:
            d_done = done_tasks[pd.to_datetime(done_tasks['end_date']).dt.date <= d.date()] if not done_tasks.empty else pd.DataFrame()
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
            chart_dist = alt.Chart(dist_data).mark_bar().encode(
                x=alt.X("Status:N", title=None),
                y=alt.Y("Count:Q", title="Count"),
                color=alt.Color("Status:N", scale=alt.Scale(domain=['Todo', 'In Progress', 'Done'], range=[color_gray, color_orange, color_green]))
            ).properties(height=240)
            st.altair_chart(chart_dist)

    with c_buf:
        st.subheader("Buffer distribution")
        buf_df = pd.DataFrame({
            "Category": ["Prod Bug", "Adhoc", "Ceremonies"],
            "SP": [bug_v, adhoc_v, cere_v],
        })
        chart_pie = alt.Chart(buf_df).mark_arc(innerRadius=45).encode(
            theta=alt.Theta(field="SP", type="quantitative"),
            color=alt.Color(field="Category", type="nominal", scale=alt.Scale(range=[color_red, color_orange, color_primary])),
            tooltip=["Category", "SP"]
        ).properties(height=240)
        st.altair_chart(chart_pie)

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
        chart_trend = alt.Chart(velo_melt).mark_bar(opacity=0.85).encode(
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
        role_cap = cap_df.groupby('Role')['Net SP'].sum().reset_index()
        role_cap['Plannable'] = role_cap['Net SP'] * (1 - (bug_p + adhoc_p + ceremony_p) / 100)
        role_alloc = tasks.groupby('role')['sp'].sum().reset_index() if not tasks.empty else pd.DataFrame(columns=['role', 'sp'])

        role_df = pd.merge(role_cap, role_alloc, left_on='Role', right_on='role', how='left').fillna(0)
        role_df = role_df.rename(columns={'sp': 'Allocated'})
        role_melt = role_df.melt(id_vars=['Role'], value_vars=['Plannable', 'Allocated'], var_name='Type', value_name='SP')

        chart_role = alt.Chart(role_melt).mark_bar().encode(
            x=alt.X("Type:N", title=None),
            y=alt.Y("SP:Q", title="Story Points"),
            color=alt.Color("Type:N", scale=alt.Scale(range=[color_light, color_primary])),
            column=alt.Column("Role:N", title=None)
        ).properties(height=260, width=120)
        st.altair_chart(chart_role)

    with c_cere:
        st.subheader("Ceremony & buffer breakdown")
        cere_df = pd.DataFrame({
            "Activity": ["Grooming", "Planning", "Demo/Retro", "Prod Support", "Adhoc"],
            "SP": [cere_v * 0.5, cere_v * 0.3, cere_v * 0.2, bug_v, adhoc_v],
        })
        chart_cere = alt.Chart(cere_df).mark_bar().encode(
            x=alt.X("SP:Q", title="Story Points"),
            y=alt.Y("Activity:N", sort="-x", title=None),
            color=alt.Color("Activity:N", scale=alt.Scale(range=[color_primary, color_blue, color_orange, color_red, color_gray]))
        ).properties(height=260)
        st.altair_chart(chart_cere)

    # --- DEVELOPER PERFORMANCE ---
    st.divider()
    st.subheader("Team allocation")
    
    perf_list = []
    for _, dev in team.iterrows():
        dev_name = dev['name']
        net_sp = cap_df[cap_df['Name'] == dev_name]['Net SP'].values[0]
        
        bug_sp = net_sp * bug_p / 100
        adhoc_sp = net_sp * adhoc_p / 100
        cere_sp = net_sp * ceremony_p / 100
        plannable_sp = net_sp - (bug_sp + adhoc_sp + cere_sp)
        
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
    
    perf_melt = perf.melt(
        id_vars=['Name'],
        value_vars=['Allocated', 'Remaining', 'Prod bug buffer', 'Adhoc buffer', 'Ceremony buffer'],
        var_name='Component',
        value_name='SP'
    )
    
    chart_perf = alt.Chart(perf_melt).mark_bar().encode(
        x=alt.X("Name:N", title="Team member"),
        y=alt.Y("SP:Q", title="Story Points", stack="zero"),
        color=alt.Color("Component:N", scale=alt.Scale(
            domain=['Allocated', 'Remaining', 'Prod bug buffer', 'Adhoc buffer', 'Ceremony buffer'],
            range=[color_green, color_blue, color_red, color_orange, color_primary]
        ))
    ).properties(height=350)
    st.altair_chart(chart_perf)
    
    st.dataframe(perf, hide_index=True)

