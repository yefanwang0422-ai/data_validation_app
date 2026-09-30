"use client";

import * as React from "react";
import Box from "@mui/material/Box";
import Drawer from "@mui/material/Drawer";
import AppBar from "@mui/material/AppBar";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import TextField from "@mui/material/TextField";
import Chip from "@mui/material/Chip";
import Divider from "@mui/material/Divider";
import CableIcon from "@mui/icons-material/Cable";
import DashboardIcon from "@mui/icons-material/Dashboard";
import AccountTreeIcon from "@mui/icons-material/AccountTree";
import AssessmentIcon from "@mui/icons-material/Assessment";
import FactCheckIcon from "@mui/icons-material/FactCheck";
import ReportProblemIcon from "@mui/icons-material/ReportProblem";
import CompareArrowsIcon from "@mui/icons-material/CompareArrows";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import TableRowsIcon from "@mui/icons-material/TableRows";
import InsightsIcon from "@mui/icons-material/Insights";
import FilterAltIcon from "@mui/icons-material/FilterAlt";
import FileDownloadIcon from "@mui/icons-material/FileDownload";
import HistoryIcon from "@mui/icons-material/History";
import { usePathname, useRouter } from "next/navigation";
import { useProject } from "./ProjectContext";

const DRAWER_WIDTH = 270;

interface NavItem {
  href: string;
  label: string;
  icon: React.ReactNode;
}

interface NavSegment {
  label: string;
  items: NavItem[];
}

const NAV_SEGMENTS: NavSegment[] = [
  {
    label: "Setup",
    items: [
      { href: "/data-sources", label: "Data Sources", icon: <CableIcon /> },
      { href: "/", label: "Run Pipeline", icon: <DashboardIcon /> },
      { href: "/mappings", label: "Column Mapping", icon: <AccountTreeIcon /> },
      { href: "/data-stages", label: "Data Stage Viewer", icon: <TableRowsIcon /> },
      { href: "/scope-filters", label: "Scope Filters", icon: <FilterAltIcon /> },
    ],
  },
  {
    label: "Data Quality",
    items: [
      { href: "/profiling", label: "Profiling Report", icon: <AssessmentIcon /> },
      { href: "/quality", label: "Dataset Quality", icon: <FactCheckIcon /> },
      { href: "/issues", label: "Issue Explorer", icon: <ReportProblemIcon /> },
      { href: "/cross-reference", label: "Cross-Reference Exceptions", icon: <CompareArrowsIcon /> },
    ],
  },
  {
    label: "Review",
    items: [
      { href: "/review-queue", label: "AI-Fill Review Queue", icon: <SmartToyIcon /> },
      { href: "/records", label: "Record Detail", icon: <TableRowsIcon /> },
    ],
  },
  {
    label: "Analytics",
    items: [
      { href: "/insights", label: "Business Insights", icon: <InsightsIcon /> },
      { href: "/ai-insights", label: "AI Executive Insights", icon: <SmartToyIcon /> },
    ],
  },
  {
    label: "Output",
    items: [{ href: "/export", label: "Export / Download", icon: <FileDownloadIcon /> }],
  },
];

const RUN_HISTORY_ITEM: NavItem = { href: "/runs", label: "Run History", icon: <HistoryIcon /> };

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { projectId, setProjectId, runId, sqlConfigured } = useProject();

  const renderItem = (item: NavItem) => {
    const active = pathname === item.href;
    return (
      <ListItemButton
        key={item.href}
        selected={active}
        onClick={() => router.push(item.href)}
        sx={{
          borderRadius: 2,
          mb: 0.5,
          color: active ? "#fff" : "#C7D6F2",
          bgcolor: active ? "rgba(91,155,213,0.25)" : "transparent",
          "&:hover": { bgcolor: "rgba(91,155,213,0.15)" },
        }}
      >
        <ListItemIcon sx={{ color: active ? "#fff" : "#9FB4E0", minWidth: 36 }}>{item.icon}</ListItemIcon>
        <ListItemText
          primary={item.label}
          primaryTypographyProps={{ fontSize: 14, fontWeight: active ? 600 : 500 }}
        />
      </ListItemButton>
    );
  };

  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <AppBar position="fixed" sx={{ zIndex: (t) => t.zIndex.drawer + 1 }}>
        <Toolbar sx={{ gap: 2 }}>
          <Typography variant="h6" noWrap sx={{ flexGrow: 1, fontWeight: 700 }}>
            Supply Chain Design_Data Validation
          </Typography>
          <Chip
            label={sqlConfigured ? "SQL Server: Connected" : "SQL Server: Not Configured"}
            color={sqlConfigured ? "success" : "warning"}
            size="small"
            sx={{ color: "#fff", bgcolor: sqlConfigured ? "rgba(30,142,99,0.9)" : "rgba(217,130,43,0.9)" }}
          />
          {runId && (
            <Chip
              label={`Run: ${runId.replace("run_", "")}`}
              size="small"
              sx={{ bgcolor: "rgba(255,255,255,0.15)", color: "#fff" }}
            />
          )}
        </Toolbar>
      </AppBar>

      <Drawer
        variant="permanent"
        sx={{
          width: DRAWER_WIDTH,
          flexShrink: 0,
          [`& .MuiDrawer-paper`]: { width: DRAWER_WIDTH, boxSizing: "border-box", display: "flex" },
        }}
      >
        <Toolbar />
        <Box sx={{ p: 2 }}>
          <TextField
            fullWidth
            size="small"
            label="Project ID"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            InputLabelProps={{ style: { color: "#AEC3EA" } }}
            sx={{
              "& .MuiOutlinedInput-root": {
                color: "#fff",
                "& fieldset": { borderColor: "#3A5A9C" },
                "&:hover fieldset": { borderColor: "#5B9BD5" },
              },
            }}
          />
        </Box>
        <Divider sx={{ borderColor: "#243B6E" }} />

        <Box sx={{ flexGrow: 1, overflowY: "auto", px: 1 }}>
          {NAV_SEGMENTS.map((segment) => (
            <Box key={segment.label} sx={{ mb: 1 }}>
              <Typography
                variant="caption"
                sx={{
                  display: "block",
                  px: 2,
                  pt: 2,
                  pb: 0.5,
                  color: "#7C93C4",
                  fontWeight: 700,
                  letterSpacing: 1,
                  textTransform: "uppercase",
                  fontSize: 11,
                }}
              >
                {segment.label}
              </Typography>
              <List sx={{ py: 0 }}>{segment.items.map(renderItem)}</List>
            </Box>
          ))}
        </Box>

        <Divider sx={{ borderColor: "#243B6E" }} />
        <List sx={{ px: 1, py: 1 }}>{renderItem(RUN_HISTORY_ITEM)}</List>
      </Drawer>

      <Box component="main" sx={{ flexGrow: 1, bgcolor: "background.default", minHeight: "100vh" }}>
        <Toolbar />
        <Box sx={{ p: 3 }}>{children}</Box>
      </Box>
    </Box>
  );
}
