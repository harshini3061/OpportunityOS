import os
import mysql.connector
import pandas as pd
import streamlit as st

st.set_page_config(page_title="OpportunityOS", page_icon="🎯", layout="wide")
STATUSES = ["Saved", "Applied", "Shortlisted", "Interview", "Selected", "Rejected"]

def setting(key, default=None):
    try:
        value = st.secrets.get(key)
        if value not in (None, ""):
            return value
    except Exception:
        pass
    return os.getenv(key, default)

def connect():
    password = setting("DB_PASSWORD", "")
    if not password:
        raise RuntimeError("Set DB_PASSWORD in .streamlit/secrets.toml or your environment.")
    return mysql.connector.connect(
        host=setting("DB_HOST", "localhost"),
        port=int(setting("DB_PORT", "3306")),
        user=setting("DB_USER", "root"),
        password=password,
        database=setting("DB_NAME", "opportunityos"),
        connection_timeout=8,
    )

def read_sql(sql, params=()):
    cnx = connect()
    try:
        return pd.read_sql(sql, cnx, params=params)
    finally:
        cnx.close()

def write_sql(statements):
    cnx = connect()
    try:
        cur = cnx.cursor()
        for sql, params in statements:
            cur.execute(sql, params)
        cnx.commit()
    except Exception:
        cnx.rollback()
        raise
    finally:
        cnx.close()

def save_opportunity(student_id, opp_id):
    cnx = connect()
    try:
        cur = cnx.cursor()
        cur.execute(
            "INSERT IGNORE INTO applications (student_id,opp_id,status) VALUES (%s,%s,'Saved')",
            (student_id, opp_id),
        )
        inserted = cur.rowcount == 1
        if inserted:
            cur.execute(
                "INSERT INTO application_status_history (application_id,status,note) VALUES (%s,'Saved','Application created')",
                (cur.lastrowid,),
            )
        cnx.commit()
        return inserted
    except Exception:
        cnx.rollback()
        raise
    finally:
        cnx.close()

def choose_student(key):
    df = read_sql("SELECT student_id, full_name FROM students ORDER BY full_name")
    if df.empty:
        st.warning("No student profiles are in the database.")
        st.stop()
    name = st.sidebar.selectbox("Student profile", df.full_name.tolist(), key=key)
    return int(df.loc[df.full_name == name, "student_id"].iloc[0])

st.title("🎯 OpportunityOS")
st.caption("Student Opportunity Intelligence Platform")

try:
    cnx = connect()
    cnx.close()
except Exception as exc:
    st.error("Cannot connect to MySQL.")
    st.code(str(exc))
    st.markdown("""
Check that MySQL is running, the database is named `opportunityos`, and your credentials are correct.
The schema script `01_create_tables.sql` must be run before `05_replace_with_real_data.sql`.
For local use, configure `.streamlit/secrets.toml`. A local database cannot be reached by Streamlit Cloud.
""")
    st.stop()

page = st.sidebar.radio("Navigation", [
    "Dashboard", "Browse opportunities", "Recommendations", "Application tracker", "Analytics"
])

if page == "Dashboard":
    st.subheader("Your opportunity overview")
    a, b, c, d = st.columns(4)
    a.metric("All opportunities", int(read_sql("SELECT COUNT(*) n FROM opportunities").iloc[0, 0]))
    b.metric("Open opportunities", int(read_sql("SELECT COUNT(*) n FROM opportunities WHERE deadline >= CURDATE()").iloc[0, 0]))
    c.metric("Student profiles", int(read_sql("SELECT COUNT(*) n FROM students").iloc[0, 0]))
    d.metric("Applications tracked", int(read_sql("SELECT COUNT(*) n FROM applications").iloc[0, 0]))
    st.markdown("### Closing soon")
    df = read_sql("""
        SELECT o.title, g.org_name AS organization, o.opp_type AS type,
               o.deadline, DATEDIFF(o.deadline,CURDATE()) AS days_left, o.application_url
        FROM opportunities o JOIN organizations g ON g.org_id=o.org_id
        WHERE o.deadline >= CURDATE() ORDER BY o.deadline LIMIT 5
    """)
    st.dataframe(df, use_container_width=True, hide_index=True,
                 column_config={"application_url": st.column_config.LinkColumn("Official page")})
    st.caption("Always verify deadlines and eligibility on the official programme website.")

elif page == "Browse opportunities":
    st.subheader("Browse and filter opportunities")
    domains = read_sql("SELECT domain_name FROM domains ORDER BY domain_name").domain_name.tolist()
    a, b, c = st.columns(3)
    types = a.multiselect("Type", ["Internship", "Research", "Hackathon", "Competition", "Scholarship"])
    selected_domains = b.multiselect("Domain", domains)
    modes = c.multiselect("Work mode", ["Remote", "Onsite", "Hybrid", "Any"])
    days = st.slider("Deadline within (days)", 1, 365, 365)
    expired = st.checkbox("Include expired opportunities")
    sql = """
        SELECT o.opp_id, o.title, o.opp_type AS type, g.org_name AS organization,
               d.domain_name AS domain, o.work_mode, COALESCE(l.city,'Not specified') AS city,
               o.reward_amount, o.reward_unit, o.deadline,
               DATEDIFF(o.deadline,CURDATE()) AS days_left, o.data_source,
               o.description, o.application_url
        FROM opportunities o JOIN organizations g ON g.org_id=o.org_id
        JOIN domains d ON d.domain_id=o.domain_id
        LEFT JOIN locations l ON l.location_id=o.location_id
        WHERE DATEDIFF(o.deadline,CURDATE()) <= %s
    """
    params = [days]
    if not expired:
        sql += " AND (o.deadline IS NULL OR o.deadline >= CURDATE())"
    for column, values in [("o.opp_type", types), ("d.domain_name", selected_domains), ("o.work_mode", modes)]:
        if values:
            sql += f" AND {column} IN ({','.join(['%s'] * len(values))})"
            params.extend(values)
    df = read_sql(sql + " ORDER BY o.deadline IS NULL,o.deadline", params)
    st.write(f"**{len(df)} opportunities found**")
    st.dataframe(df, use_container_width=True, hide_index=True,
                 column_config={"application_url": st.column_config.LinkColumn("Official page")})

elif page == "Recommendations":
    sid = choose_student("recommendation_student")
    st.subheader("Recommended opportunities")
    st.caption("Rule-based score using skills, eligibility, domain interest and preferred work mode.")
    sql = """
    SELECT o.opp_id,o.title,g.org_name AS organization,o.opp_type AS type,
           o.deadline,o.application_url,COALESCE(sk.matched,0) AS skills_matched,
           COALESCE(sk.total,0) AS skills_total,
           ROUND(0.40*COALESCE(sk.pct,100)+25
             +0.20*IF(sd.domain_id IS NULL,0,100)
             +0.15*IF(s.preferred_work_mode IN ('Any',o.work_mode),100,0),1) AS match_score
    FROM students s JOIN opportunities o
      ON o.deadline >= CURDATE()
     AND s.cgpa >= COALESCE(o.min_cgpa,0)
     AND s.current_year BETWEEN COALESCE(o.min_year,1) AND COALESCE(o.max_year,4)
     AND (NOT EXISTS (SELECT 1 FROM opportunity_branches ob WHERE ob.opp_id=o.opp_id)
       OR EXISTS (SELECT 1 FROM opportunity_branches ob WHERE ob.opp_id=o.opp_id AND ob.branch_id=s.branch_id))
    JOIN organizations g ON g.org_id=o.org_id
    LEFT JOIN student_domains sd ON sd.student_id=s.student_id AND sd.domain_id=o.domain_id
    LEFT JOIN (
      SELECT os.opp_id,COUNT(*) total,SUM(ss.skill_id IS NOT NULL) matched,
             100*SUM(ss.skill_id IS NOT NULL)/COUNT(*) pct
      FROM opportunity_skills os LEFT JOIN student_skills ss
        ON ss.skill_id=os.skill_id AND ss.student_id=%s GROUP BY os.opp_id
    ) sk ON sk.opp_id=o.opp_id
    WHERE s.student_id=%s ORDER BY match_score DESC,o.deadline
    """
    recs = read_sql(sql, (sid, sid))
    if recs.empty:
        st.info("No open opportunities match this profile.")
    for _, row in recs.iterrows():
        with st.container(border=True):
            left, right = st.columns([5, 1])
            left.markdown(f"**{row['title']}**")
            left.write(f"{row['organization']} · {row['type']} · Deadline: {row['deadline']}")
            left.caption(f"Skills matched: {int(row['skills_matched'])}/{int(row['skills_total'])}")
            right.metric("Match", f"{row['match_score']}%")
            if row["application_url"]:
                left.link_button("Official page", row["application_url"])
            if left.button("Save to tracker", key=f"save_{int(row['opp_id'])}"):
                try:
                    if save_opportunity(sid, int(row["opp_id"])):
                        st.success("Saved to your application tracker.")
                    else:
                        st.info("Already in your tracker.")
                except Exception as exc:
                    st.error(f"Could not save: {exc}")
    with st.expander("Skills missing from open opportunities"):
        missing = read_sql("""
          SELECT DISTINCT o.title,sk.skill_name,os.is_mandatory
          FROM opportunities o JOIN opportunity_skills os ON os.opp_id=o.opp_id
          JOIN skills sk ON sk.skill_id=os.skill_id
          WHERE o.deadline >= CURDATE() AND NOT EXISTS
            (SELECT 1 FROM student_skills ss WHERE ss.student_id=%s AND ss.skill_id=os.skill_id)
          ORDER BY o.title,sk.skill_name
        """, (sid,))
        st.dataframe(missing, use_container_width=True, hide_index=True)

elif page == "Application tracker":
    sid = choose_student("tracker_student")
    st.subheader("Application tracker")
    apps = read_sql("""
      SELECT a.application_id,o.title,g.org_name AS organization,a.status,a.updated_at,o.application_url
      FROM applications a JOIN opportunities o ON o.opp_id=a.opp_id
      JOIN organizations g ON g.org_id=o.org_id
      WHERE a.student_id=%s ORDER BY a.updated_at DESC
    """, (sid,))
    if apps.empty:
        st.info("No applications yet. Save an opportunity from Recommendations.")
    else:
        for _, row in apps.iterrows():
            with st.container(border=True):
                a, b, c = st.columns([4, 2, 2])
                a.markdown(f"**{row['title']}**")
                a.caption(row["organization"])
                old = row["status"]
                new = b.selectbox("Status", STATUSES, index=STATUSES.index(old),
                                  key=f"status_{int(row['application_id'])}")
                if c.button("Update", key=f"update_{int(row['application_id'])}"):
                    if new == old:
                        st.info("Choose a different status first.")
                    else:
                        try:
                            write_sql([
                                ("UPDATE applications SET status=%s,updated_at=CURRENT_TIMESTAMP WHERE application_id=%s",
                                 (new, int(row["application_id"]))),
                                ("INSERT INTO application_status_history (application_id,status,note) VALUES (%s,%s,%s)",
                                 (int(row["application_id"]), new, f"Changed from {old} to {new}")),
                            ])
                            st.success("Status updated.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Could not update status: {exc}")
                if row["application_url"]:
                    a.link_button("Official page", row["application_url"])
        with st.expander("Status history"):
            hist = read_sql("""
              SELECT o.title,h.status,h.changed_at,h.note
              FROM application_status_history h JOIN applications a ON a.application_id=h.application_id
              JOIN opportunities o ON o.opp_id=a.opp_id
              WHERE a.student_id=%s ORDER BY h.changed_at DESC
            """, (sid,))
            st.dataframe(hist, use_container_width=True, hide_index=True)

else:
    st.subheader("Analytics")
    c1, c2 = st.columns(2)
    skills = read_sql("""
      SELECT sk.skill_name,COUNT(*) AS opportunities FROM opportunity_skills os
      JOIN skills sk ON sk.skill_id=os.skill_id GROUP BY sk.skill_name
      ORDER BY opportunities DESC LIMIT 10
    """)
    c1.markdown("#### Most requested skills")
    if not skills.empty:
        c1.bar_chart(skills.set_index("skill_name"))
    status = read_sql("SELECT status,COUNT(*) AS applications FROM applications GROUP BY status")
    c2.markdown("#### Applications by status")
    if not status.empty:
        c2.bar_chart(status.set_index("status"))
    domains_df = read_sql("""
      SELECT d.domain_name,COUNT(*) AS opportunities FROM opportunities o
      JOIN domains d ON d.domain_id=o.domain_id GROUP BY d.domain_name
    """)
    c1.markdown("#### Opportunities by domain")
    if not domains_df.empty:
        c1.bar_chart(domains_df.set_index("domain_name"))
    c2.markdown("#### Average monthly reward by organization")
    rewards = read_sql("""
      SELECT g.org_name,ROUND(AVG(o.reward_amount),0) AS avg_per_month
      FROM opportunities o JOIN organizations g ON g.org_id=o.org_id
      WHERE o.reward_unit='Per month' GROUP BY g.org_name ORDER BY avg_per_month DESC
    """)
    c2.dataframe(rewards, use_container_width=True, hide_index=True)
