import streamlit as st
import pandas as pd
import altair as alt
from utils.db import get_sprints, get_team, get_leaves, get_holidays, get_backlog
from utils.helpers import get_workdays

# Title
st.title("Team capacity breakdown")

# Theme Colors for Charts
color_primary = '#1f4e78'
color_blue = '#4a90d9'
color_green = '#28a745'
color_orange = '#ffa500'
color_red = '#e74c3c'
color_gray = '#999'
color_light = '#a8c4de'

sprints_df = get_sprints()
team = get_team()

if sprints_df.empty or team.empty:
    st.info("Create a sprint and add team members first.", icon=":material/info:")
else:
    sprint_names = sprints_df['name'].tolist()
    active_sprint = sprints_df[sprints_df['status'] == 'Active']
    active_name = active_sprint.iloc[0]['name'] if not active_sprint.empty else None
    default_index = sprint_names.index(active_name) if active_name in sprint_names else 0
    cap_sprint = st.selectbox("Select sprint", sprint_names, index=default_index, key="cap_sprint")
    s_info = sprints_df[sprints_df['name'] == cap_sprint].iloc[0]
    s_id, s_start, s_end = s_info['id'], s_info['start_date'], s_info['end_date']

    leaves = get_leaves(s_id)
    hols = get_holidays(s_id, s_start, s_end)
    tasks = get_backlog(s_id)

    work_days = get_workdays(s_start, s_end)
    holiday_count = len(hols)

    rows = []
    for _, dev in team.iterrows():
        dev_leaves = leaves[leaves['name'] == dev['name']]
        leave_days = dev_leaves['total_days'].sum() if not dev_leaves.empty else 0
        eff = max(work_days - holiday_count - leave_days, 0)
        dev_role = dev.get('role', '')
        daily_sp = 0.0 if dev_role in ['PM', 'EM'] else dev['daily_sp']
        total_sp = eff * daily_sp
        
        # Buffer calculation from individual developer parameters
        dev_bug_p = dev.get('bug_p', 15.0)
        dev_adhoc_p = dev.get('adhoc_p', 10.0)
        dev_cere_p = dev.get('ceremony_p', 10.0)
        
        bug_buf = total_sp * dev_bug_p / 100
        adhoc_buf = total_sp * dev_adhoc_p / 100
        cere_buf = total_sp * dev_cere_p / 100
        avail = total_sp - bug_buf - adhoc_buf - cere_buf
        alloc = tasks[tasks['assignee'] == dev['name']]['sp'].sum() if not tasks.empty else 0
        rem = avail - alloc
        rows.append({
            "Name": dev['name'],
            "Role": dev['role'],
            "Work Days": work_days,
            "Holidays": holiday_count,
            "Leaves": leave_days,
            "Effective Days": eff,
            "Total SP": round(total_sp, 1),
            "Bug Buffer": round(bug_buf, 1),
            "Adhoc Buffer": round(adhoc_buf, 1),
            "Ceremony Buffer": round(cere_buf, 1),
            "Available SP": round(avail, 1),
            "Allocated SP": round(alloc, 1),
            "Remaining SP": round(rem, 1),
        })

    cap_table = pd.DataFrame(rows)
    cap_table.index = range(1, len(cap_table) + 1)

    # Summary metrics
    total_team_sp = cap_table['Total SP'].sum()
    total_avail = cap_table['Available SP'].sum()
    total_alloc = cap_table['Allocated SP'].sum()
    total_rem = cap_table['Remaining SP'].sum()

    m_cols = st.columns(4, border=True)
    m_cols[0].metric("Team total SP", f"{total_team_sp:.1f}")
    m_cols[1].metric("Available SP", f"{total_avail:.1f}")
    m_cols[2].metric("Allocated SP", f"{total_alloc:.1f}")
    m_cols[3].metric("Remaining SP", f"{total_rem:.1f}")

    st.divider()
    st.data_editor(
        cap_table,
        column_config={
            "Name": st.column_config.TextColumn("Name", disabled=True),
            "Role": st.column_config.TextColumn("Role", disabled=True),
            "Work Days": st.column_config.NumberColumn("Work days", disabled=True),
            "Holidays": st.column_config.NumberColumn("Holidays", disabled=True),
            "Leaves": st.column_config.NumberColumn("Leaves", disabled=True),
            "Effective Days": st.column_config.NumberColumn("Effective days", disabled=True),
            "Total SP": st.column_config.NumberColumn("Total SP", disabled=True),
            "Bug Buffer": st.column_config.NumberColumn("Bug buffer", disabled=True),
            "Adhoc Buffer": st.column_config.NumberColumn("Adhoc buffer", disabled=True),
            "Ceremony Buffer": st.column_config.NumberColumn("Ceremony buffer", disabled=True),
            "Available SP": st.column_config.NumberColumn("Available SP", disabled=True),
            "Allocated SP": st.column_config.NumberColumn("Allocated SP", disabled=True),
            "Remaining SP": st.column_config.NumberColumn("Remaining SP", disabled=True),
        },
        key="cap_editor",
        num_rows="dynamic",
        use_container_width=True,
    )

    # Visual: stacked bar per person
    st.divider()
    st.subheader("Capacity vs allocation per person")
    melt = cap_table.melt(
        id_vars=['Name'],
        value_vars=['Allocated SP', 'Remaining SP', 'Bug Buffer', 'Adhoc Buffer', 'Ceremony Buffer'],
        var_name='Component', value_name='SP',
    )
    chart_cap = alt.Chart(melt).mark_bar(size=24, cornerRadius=4).encode(
        x=alt.X("Name:N", title="Team member", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("SP:Q", title="Story Points", stack="zero"),
        color=alt.Color("Component:N", scale=alt.Scale(
            domain=['Allocated SP', 'Remaining SP', 'Bug Buffer', 'Adhoc Buffer', 'Ceremony Buffer'],
            range=[color_green, color_blue, color_red, color_orange, color_primary]
        ), legend=alt.Legend(title="Capacity Allocation Components", orient="bottom")),
        tooltip=['Name:N', 'Component:N', 'SP:Q']
    ).properties(height=350)
    st.altair_chart(chart_cap, use_container_width=True)
