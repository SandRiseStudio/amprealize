# START HERE: Metabase Dashboard Creation

## ✅ Environment Validated & Ready

**Metabase Status:**
- 🟢 Running at http://localhost:3000
- 🟢 Health check: OK
- 🟢 Database connected: `/duckdb/telemetry_sqlite.db`
- 🟢 All 8 tables/views accessible

**Login Credentials:**
- **URL:** http://localhost:3000
- **Email:** `admin@amprealize.local`
- **Password:** `changeme123`

---

## � Choose Your Creation Method

### Option A: **Programmatic Creation (RECOMMENDED)** ⚡
**Time:** 10-15 seconds
**Effort:** One command

```bash
python scripts/create_metabase_dashboards.py
```

**What You Get:**
- ✅ All 4 dashboards created automatically (18 cards total)
- ✅ SQL queries from `CORRECTED_SQL_QUERIES.md`
- ✅ Proper card positioning and sizing
- ✅ Reproducible for future updates

**See:** `docs/analytics/PROGRAMMATIC_DASHBOARD_CREATION.md` for full documentation

---

### Option B: **Manual UI Creation** 🖱️
**Time:** 60-90 minutes
**Effort:** Follow step-by-step guide

If you prefer hands-on learning or need to customize, continue below for manual instructions.

---

## 📋 Manual Creation: 4 Dashboards

### Dashboard 1: **PRD KPI Summary** (Priority 1)
**Time:** ~20 minutes
**Purpose:** Executive overview of PRD success metrics

**Components:**
- ✅ 4 Metric Cards: Behavior Reuse (70%), Token Savings (30%), Completion (80%), Compliance (95%)
- ✅ 30-Day Trend Line Chart (all 4 metrics)
- ✅ Run Volume Bar Chart (by status)

**Guide:** `docs/analytics/METABASE_DASHBOARD_CREATION_GUIDE.md` (lines 50-180)
**Quick SQL:** `docs/analytics/DASHBOARD_QUICK_REFERENCE.md` (lines 12-120)

---

### Dashboard 2: **Behavior Usage Trends** (Priority 2)
**Time:** ~15 minutes
**Purpose:** Behavior citation analytics and patterns

**Components:**
- ✅ Daily Citation Time Series
- ✅ Behavior Leaderboard Table
- ✅ Usage Distribution Histogram

**Guide:** `docs/analytics/METABASE_DASHBOARD_CREATION_GUIDE.md` (lines 220-290)
**Quick SQL:** `docs/analytics/DASHBOARD_QUICK_REFERENCE.md` (lines 122-165)

---

### Dashboard 3: **Token Savings Analysis** (Priority 3)
**Time:** ~20 minutes
**Purpose:** Token efficiency tracking and ROI

**Components:**
- ✅ Baseline vs Output Token Trends
- ✅ Savings Distribution Histogram
- ✅ Savings vs Behaviors Scatter Plot
- ✅ Cumulative Savings Chart
- ✅ Efficiency Leaderboard Table

**Guide:** `docs/analytics/METABASE_DASHBOARD_CREATION_GUIDE.md` (lines 320-410)
**Quick SQL:** `docs/analytics/DASHBOARD_QUICK_REFERENCE.md` (lines 167-240)

---

### Dashboard 4: **Compliance Coverage** (Priority 4)
**Time:** ~15 minutes
**Purpose:** Checklist completion monitoring

**Components:**
- ✅ Coverage Trend (with 95% goal line)
- ✅ Checklist Rankings Bar Chart
- ✅ Step Completion Summary Table
- ✅ Audit Queue (incomplete runs)
- ✅ Coverage Distribution Pie Chart

**Guide:** `docs/analytics/METABASE_DASHBOARD_CREATION_GUIDE.md` (lines 440-550)
**Quick SQL:** `docs/analytics/DASHBOARD_QUICK_REFERENCE.md` (lines 242-320)

---

## 🚀 Getting Started (3 Steps)

### Step 1: Login to Metabase (2 minutes)
```bash
# 1. Open browser
open http://localhost:3000

# 2. Login with credentials above
# 3. Verify database connection in Settings → Admin → Databases
```

### Step 2: Create First Dashboard (20 minutes)
Follow the detailed guide for **PRD KPI Summary**:
- Open: `docs/analytics/METABASE_DASHBOARD_CREATION_GUIDE.md`
- Section: "Dashboard #1: PRD KPI Summary" (starting line 50)
- Copy-paste SQL queries from `DASHBOARD_QUICK_REFERENCE.md`
- Configure visualizations as specified

### Step 3: Repeat for Remaining Dashboards (50 minutes)
Use the same pattern for dashboards 2, 3, 4

---

## 📚 Documentation Quick Links

| Document | Purpose | Key Sections |
|----------|---------|--------------|
| **METABASE_DASHBOARD_CREATION_GUIDE.md** | Comprehensive step-by-step instructions | Pre-flight check, 4 dashboard guides, validation |
| **DASHBOARD_QUICK_REFERENCE.md** | Copy-paste SQL queries | All SQL organized by dashboard |
| **dashboard-exports/README.md** | Dashboard specifications | Data requirements, visualization configs |
| **metabase_setup.md** | Troubleshooting | Connection issues, performance tips |

---

## ⚡ Quick Tips

### Schema Note ⚠️
**Important:** The actual database schema differs from initial design:
- KPI views use column names like `reuse_rate_pct` (not `behavior_reuse_rate`)
- Views don't have `last_updated` timestamp columns
- Percentages are already scaled to 100 (e.g., 100.0 = 100%)
- Fact tables don't have `execution_timestamp` yet

**✅ All SQL queries in the guides have been corrected!**

### For Speed
1. **Use Quick Reference** - Copy SQL directly from `DASHBOARD_QUICK_REFERENCE.md`
2. **Test Queries First** - Run in SQL console before adding to dashboard
3. **Start Simple** - Create basic visualizations, refine later
4. **Save Often** - Click Save after each card/question

### For Quality
1. **Match Specs** - Follow visualization types in dashboard-exports/*.md
2. **Add Filters** - Date range, agent role (if available)
3. **Format Numbers** - Add % suffix, color coding
4. **Set Auto-Refresh** - Every 5-10 minutes for live dashboards

### Troubleshooting
| Issue | Solution |
|-------|----------|
| Empty results | Sample data is minimal; dashboards will work with real data |
| Query error | Check table names: `main.fact_*`, `main.view_*` |
| Can't save | Ensure logged in as admin |
| Slow queries | Add indexes (see Quick Reference) |

---

## 📊 Sample Data Note

⚠️ **Current data volume is minimal** (1-8 rows per table for testing)

**This is NORMAL for initial setup!** Dashboards will:
- ✅ Work correctly with sample data
- ✅ Show proper structure and layout
- ✅ Display real metrics once telemetry flows in

**To generate more data:**
```bash
# Run more behaviors/workflows to generate telemetry
amprealize behaviors list
amprealize workflows list

# Then re-export to SQLite
python scripts/export_duckdb_to_sqlite.py
```

---

## ✅ Completion Checklist

When you finish all 4 dashboards:

- [ ] All 4 dashboards created and accessible
- [ ] SQL queries execute without errors
- [ ] Visualizations render correctly
- [ ] Filters work (if added)
- [ ] Screenshots captured (`docs/analytics/screenshots/`)
- [ ] Test with sample data
- [ ] Document completion in BUILD_TIMELINE.md
- [ ] Update PRD_ALIGNMENT_LOG.md

**Then notify me and I'll help with:**
- Documentation updates
- Screenshot organization
- Next steps (Flink deployment, VS Code integration, export automation)

---

## 🎯 Success Criteria

You'll know you're done when:
1. ✅ Login to Metabase shows 4 dashboards
2. ✅ Each dashboard has all specified cards/charts
3. ✅ PRD metrics display (even if low/zero with sample data)
4. ✅ No SQL errors or missing permissions

---

## 🆘 Need Help?

**During Creation:**
- Check `METABASE_DASHBOARD_CREATION_GUIDE.md` troubleshooting section
- Reference `dashboard-exports/*.md` for exact specifications
- Validate SQL in Metabase SQL console first

**When Done:**
- Let me know and I'll validate completion
- I'll update BUILD_TIMELINE and PRD_ALIGNMENT_LOG
- We'll plan next steps (Flink, VS Code panel, automation)

---

**Ready to start? Open http://localhost:3000 and begin with Dashboard #1!** 🚀
