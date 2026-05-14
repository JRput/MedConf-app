import { useState } from "react";

const NAVY = "#1B2845";
const TEAL = "#0E7490";
const TEAL_LIGHT = "#CCEAF0";
const ACCENT = "#0EA5E9";
const ACCENT_LIGHT = "#E0F2FE";
const SUCCESS = "#16A34A";
const SUCCESS_LIGHT = "#DCFCE7";
const MUTED = "#6B7280";
const DARK = "#374151";
const BG = "#F0F7FA";
const WHITE = "#FFFFFF";
const PURPLE = "#7C3AED";
const PURPLE_LIGHT = "#EDE9FE";
const AMBER = "#D97706";
const AMBER_LIGHT = "#FEF3C7";

// ─── Arrow ──────────────────────────────────────────────
function Arrow({ label }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", margin: "2px 0" }}>
      {label && (
        <span style={{ fontSize: 10, color: MUTED, fontFamily: "'Inter', sans-serif", marginBottom: 2, fontStyle: "italic" }}>
          {label}
        </span>
      )}
      <svg width="20" height="28" viewBox="0 0 20 28">
        <line x1="10" y1="0" x2="10" y2="20" stroke={TEAL} strokeWidth="2" />
        <polygon points="4,18 10,28 16,18" fill={TEAL} />
      </svg>
    </div>
  );
}

// ─── Flow Node ──────────────────────────────────────────
function Node({ label, sublabel, color, bgColor, icon, width = 240 }) {
  return (
    <div style={{
      width,
      background: bgColor,
      border: `2px solid ${color}`,
      borderRadius: 12,
      padding: "12px 16px",
      textAlign: "center",
      boxShadow: `0 2px 8px ${color}22`,
      position: "relative"
    }}>
      {icon && <div style={{ fontSize: 18, marginBottom: 4 }}>{icon}</div>}
      <div style={{ fontSize: 13, fontWeight: 700, color, fontFamily: "'Inter', sans-serif", lineHeight: 1.3 }}>{label}</div>
      {sublabel && <div style={{ fontSize: 10, color: MUTED, marginTop: 3, fontFamily: "'Inter', sans-serif", lineHeight: 1.4 }}>{sublabel}</div>}
    </div>
  );
}

// ─── Decision Diamond ───────────────────────────────────
function Diamond({ label }) {
  return (
    <div style={{ display: "flex", justifyContent: "center" }}>
      <div style={{
        width: 140, height: 70,
        background: AMBER_LIGHT,
        border: `2px solid ${AMBER}`,
        borderRadius: 8,
        transform: "rotate(0deg)",
        display: "flex", alignItems: "center", justifyContent: "center",
        position: "relative",
        clipPath: "polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)",
        padding: 12
      }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: AMBER, textAlign: "center", fontFamily: "'Inter', sans-serif", lineHeight: 1.3 }}>{label}</span>
      </div>
    </div>
  );
}

// ─── Section Label ──────────────────────────────────────
function SectionLabel({ children }) {
  return (
    <div style={{
      fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 1.5,
      color: WHITE, background: NAVY, borderRadius: 20, padding: "4px 14px",
      fontFamily: "'Inter', sans-serif", marginBottom: 8, display: "inline-block"
    }}>
      {children}
    </div>
  );
}

// ─── USER FLOW ──────────────────────────────────────────
function UserFlow() {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 0 }}>
      <SectionLabel>① Discovery & Registration</SectionLabel>
      <Node label="User Lands on MedConf" sublabel="Homepage or direct link" color={NAVY} bgColor={WHITE} icon="🌐" />
      <Arrow />
      <Node label="Sign Up / Log In" sublabel="Email & password registration" color={NAVY} bgColor={WHITE} icon="📧" />
      <Arrow label="first time only" />
      <Node label="Email Verification" sublabel="Confirm email address" color={NAVY} bgColor={WHITE} icon="✉️" />
      <Arrow label="verified" />
      <Node label="Complete Profile" sublabel="Role, specialty, preferred region" color={NAVY} bgColor={WHITE} icon="👤" />
      <Arrow />

      <SectionLabel>② Browse & Discover</SectionLabel>
      <Node label="Conference Directory" sublabel="Pre-filtered by profile preferences" color={TEAL} bgColor={TEAL_LIGHT} icon="📋" />
      <Arrow label="optional" />
      <Node label="Apply Filters" sublabel="Specialty · Location · Price · Date · CPD" color={TEAL} bgColor={TEAL_LIGHT} icon="🔍" />
      <Arrow />
      <Node label="Search by Keyword" sublabel="Find by name, organiser, or topic" color={TEAL} bgColor={TEAL_LIGHT} icon="🔎" />
      <Arrow />

      <SectionLabel>③ Evaluate & Act</SectionLabel>
      <Node label="View Conference Card" sublabel="Name · Specialty · Dates · Location · Price range · CPD badge" color={ACCENT} bgColor={ACCENT_LIGHT} icon="📌" />
      <Arrow />
      <Node label="Open Detail Page" sublabel="Full info: pricing tiers, CPD points, abstract submissions" color={ACCENT} bgColor={ACCENT_LIGHT} icon="📄" />
      <Arrow />
      <Diamond label="Save or Book?" />
      <div style={{ display: "flex", gap: 40, marginTop: 6 }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          <span style={{ fontSize: 10, color: SUCCESS, fontWeight: 700, fontFamily: "'Inter', sans-serif" }}>Save</span>
          <svg width="16" height="20" viewBox="0 0 16 20"><line x1="8" y1="0" x2="8" y2="12" stroke={SUCCESS} strokeWidth="2"/><polygon points="2,10 8,20 14,10" fill={SUCCESS}/></svg>
          <Node label="Bookmark Conference" sublabel="Added to saved list" color={SUCCESS} bgColor={SUCCESS_LIGHT} icon="🔖" width={180} />
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          <span style={{ fontSize: 10, color: PURPLE, fontWeight: 700, fontFamily: "'Inter', sans-serif" }}>Book</span>
          <svg width="16" height="20" viewBox="0 0 16 20"><line x1="8" y1="0" x2="8" y2="12" stroke={PURPLE} strokeWidth="2"/><polygon points="2,10 8,20 14,10" fill={PURPLE}/></svg>
          <Node label="Redirect to Organiser" sublabel="Official website opens for booking" color={PURPLE} bgColor={PURPLE_LIGHT} icon="🔗" width={180} />
        </div>
      </div>
      <Arrow style={{ marginTop: 8 }} />

      <SectionLabel>④ Ongoing Engagement</SectionLabel>
      <Node label="Receive Notifications" sublabel="New events · Deadline reminders · Digest emails" color={AMBER} bgColor={AMBER_LIGHT} icon="🔔" />
      <Arrow />
      <Node label="Return & Repeat" sublabel="Browse new listings, manage saved conferences" color={NAVY} bgColor={WHITE} icon="🔄" />
    </div>
  );
}

// ─── SYSTEM FLOW ────────────────────────────────────────
function SystemFlow() {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 0 }}>
      <SectionLabel>① Scraper Trigger</SectionLabel>
      <Node label="Job Scheduler Fires" sublabel="Weekly cron / EventBridge trigger" color={NAVY} bgColor={WHITE} icon="⏰" />
      <Arrow />
      <Node label="Query Scraper Sources Table" sublabel="Supabase: retrieve all active source URLs & instructions" color={NAVY} bgColor={WHITE} icon="🗄️" />
      <Arrow />

      <SectionLabel>② Agentic Scraping</SectionLabel>
      <Node label="Spawn Agent Instances" sublabel="One instance per active source, running in parallel" color={TEAL} bgColor={TEAL_LIGHT} icon="⚙️" />
      <Arrow />
      <Node label="Browser Automation (Playwright)" sublabel="Navigate to source URL, read page content" color={TEAL} bgColor={TEAL_LIGHT} icon="🌐" />
      <Arrow />
      <Node label="LLM Reasoning Loop" sublabel="Interpret page · Decide next action · Navigate or extract" color={TEAL} bgColor={TEAL_LIGHT} icon="🧠" />
      <Arrow label="repeats until task complete" />
      <Node label="Extract Structured Data" sublabel="Conference name · Dates · Location · Pricing · CPD · Abstracts" color={TEAL} bgColor={TEAL_LIGHT} icon="📊" />
      <Arrow />

      <SectionLabel>③ Validation & Storage</SectionLabel>
      <Node label="Validate Output" sublabel="Check completeness · Flag missing fields · Log errors" color={ACCENT} bgColor={ACCENT_LIGHT} icon="✅" />
      <Arrow />
      <Diamond label="Already exists?" />
      <div style={{ display: "flex", gap: 40, marginTop: 6 }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          <span style={{ fontSize: 10, color: AMBER, fontWeight: 700, fontFamily: "'Inter', sans-serif" }}>Yes</span>
          <svg width="16" height="20" viewBox="0 0 16 20"><line x1="8" y1="0" x2="8" y2="12" stroke={AMBER} strokeWidth="2"/><polygon points="2,10 8,20 14,10" fill={AMBER}/></svg>
          <Node label="Compare & Update" sublabel="Update only changed fields" color={AMBER} bgColor={AMBER_LIGHT} icon="🔄" width={180} />
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          <span style={{ fontSize: 10, color: SUCCESS, fontWeight: 700, fontFamily: "'Inter', sans-serif" }}>No</span>
          <svg width="16" height="20" viewBox="0 0 16 20"><line x1="8" y1="0" x2="8" y2="12" stroke={SUCCESS} strokeWidth="2"/><polygon points="2,10 8,20 14,10" fill={SUCCESS}/></svg>
          <Node label="Insert New Record" sublabel="Add conference to database" color={SUCCESS} bgColor={SUCCESS_LIGHT} icon="➕" width={180} />
        </div>
      </div>
      <Arrow style={{ marginTop: 8 }} />
      <Node label="Write to Supabase" sublabel="Conferences table updated · Source last_scraped timestamp set" color={ACCENT} bgColor={ACCENT_LIGHT} icon="🗄️" />
      <Arrow />

      <SectionLabel>④ Post-Processing</SectionLabel>
      <Node label="Archive Expired Conferences" sublabel="Flag events whose end date has passed" color={PURPLE} bgColor={PURPLE_LIGHT} icon="📦" />
      <Arrow />
      <Node label="Trigger Notification Pipeline" sublabel="Flag new conferences for user alert matching" color={PURPLE} bgColor={PURPLE_LIGHT} icon="🔔" />
      <Arrow />
      <Node label="Log Scraper Run" sublabel="Sources visited · Inserted · Updated · Failures · Duration" color={NAVY} bgColor={WHITE} icon="📝" />
    </div>
  );
}

// ─── LEGEND ─────────────────────────────────────────────
function Legend() {
  const items = [
    { color: NAVY, bg: WHITE, label: "Entry / Core action" },
    { color: TEAL, bg: TEAL_LIGHT, label: "Browse / Discovery / Scraping" },
    { color: ACCENT, bg: ACCENT_LIGHT, label: "Evaluate / Validate" },
    { color: SUCCESS, bg: SUCCESS_LIGHT, label: "Save / Insert" },
    { color: PURPLE, bg: PURPLE_LIGHT, label: "Redirect / Post-process" },
    { color: AMBER, bg: AMBER_LIGHT, label: "Decision / Update" },
  ];
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "8px 20px", justifyContent: "center", marginTop: 12 }}>
      {items.map(({ color, bg, label }) => (
        <div key={label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <div style={{ width: 14, height: 14, borderRadius: 4, background: bg, border: `2px solid ${color}` }} />
          <span style={{ fontSize: 10, color: MUTED, fontFamily: "'Inter', sans-serif" }}>{label}</span>
        </div>
      ))}
    </div>
  );
}

// ─── APP ────────────────────────────────────────────────
export default function App() {
  const [view, setView] = useState("user");

  return (
    <div style={{
      minHeight: "100vh",
      background: `linear-gradient(135deg, ${BG} 0%, #E8F4F8 100%)`,
      fontFamily: "'Inter', sans-serif",
      padding: "28px 16px"
    }}>
      {/* Header */}
      <div style={{ textAlign: "center", marginBottom: 24 }}>
        <div style={{ fontSize: 26, fontWeight: 800, color: NAVY, letterSpacing: -0.5 }}>
          MedConf
        </div>
        <div style={{ fontSize: 13, color: MUTED, marginTop: 2 }}>Flow Diagrams</div>
      </div>

      {/* Toggle */}
      <div style={{
        display: "flex", justifyContent: "center", gap: 0, marginBottom: 28,
        background: WHITE, borderRadius: 10, padding: 4, boxShadow: "0 2px 10px #00000012", width: "fit-content", margin: "0 auto 28px"
      }}>
        {[
          { key: "user", label: "👤  User Flow", desc: "How a professional uses the app" },
          { key: "system", label: "⚙️  System Flow", desc: "How the backend & scraper operate" }
        ].map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setView(key)}
            style={{
              padding: "10px 22px",
              border: "none",
              borderRadius: 8,
              background: view === key ? NAVY : "transparent",
              color: view === key ? WHITE : MUTED,
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
              fontFamily: "'Inter', sans-serif",
              transition: "all 0.2s ease"
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Subtitle */}
      <div style={{ textAlign: "center", marginBottom: 20 }}>
        <span style={{
          fontSize: 12, color: WHITE, background: TEAL, borderRadius: 20,
          padding: "5px 16px", fontWeight: 600
        }}>
          {view === "user"
            ? "From first visit → discovery → booking → ongoing engagement"
            : "From weekly trigger → scraping → validation → database update → notifications"}
        </span>
      </div>

      {/* Diagram */}
      <div style={{ display: "flex", justifyContent: "center" }}>
        <div style={{
          background: WHITE,
          borderRadius: 16,
          padding: "28px 32px 24px",
          boxShadow: "0 4px 24px #00000010",
          border: `1px solid ${TEAL_LIGHT}`
        }}>
          {view === "user" ? <UserFlow /> : <SystemFlow />}
        </div>
      </div>

      {/* Legend */}
      <Legend />
    </div>
  );
}
