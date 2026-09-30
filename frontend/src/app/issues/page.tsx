"use client";

import * as React from "react";
import Box from "@mui/material/Box";
import Select from "@mui/material/Select";
import MenuItem from "@mui/material/MenuItem";
import Chip from "@mui/material/Chip";
import { DataGrid, GridColDef } from "@mui/x-data-grid";
import PageHeader from "@/components/PageHeader";
import { useProject } from "@/components/ProjectContext";
import { getIssues, DATASETS } from "@/lib/api";

const SEVERITY_COLOR: Record<string, "error" | "warning" | "info"> = {
  high: "error",
  medium: "warning",
  low: "info",
};

export default function IssueExplorerPage() {
  const { projectId, runId } = useProject();
  const [dataset, setDataset] = React.useState<string>(DATASETS[0]);
  const [rows, setRows] = React.useState<any[]>([]);

  React.useEffect(() => {
    if (runId) {
      getIssues(projectId, runId, dataset)
        .then((res) => {
          // Consolidate: one row per issue type (no repeated rows for the same issue).
          // We keep the first-seen example fields as a representative sample.
          const byType = new Map<string, any>();

          for (const r of res.records || []) {
            const key = String(r.issue_type ?? "unknown");
            const prev = byType.get(key);

            if (!prev) {
              byType.set(key, {
                id: key,
                issue_type: key,
                issue_count: 1,
                severity: r.severity,
                canonical_field: r.canonical_field,
                issue_description: r.issue_description,
                record_id: r.record_id,
                raw_value: r.raw_value,
                manual_review_required: r.manual_review_required,
              });
            } else {
              prev.issue_count += 1;

              // Escalate severity if we see something worse.
              const rank = (s: any) => (s === "high" ? 3 : s === "medium" ? 2 : s === "low" ? 1 : 0);
              if (rank(r.severity) > rank(prev.severity)) prev.severity = r.severity;

              // If any row needs review, mark the consolidated row as needing review.
              if (r.manual_review_required) prev.manual_review_required = true;
            }
          }

          const consolidated = Array.from(byType.values()).sort(
            (a, b) => (b.issue_count || 0) - (a.issue_count || 0)
          );
          setRows(consolidated);
        })
        .catch(() => setRows([]));
    }
  }, [projectId, runId, dataset]);

  const columns: GridColDef[] = [
    { field: "issue_type", headerName: "Issue Type", width: 220 },
    { field: "issue_count", headerName: "Count", width: 110, type: "number" },
    { field: "canonical_field", headerName: "Example Field", width: 160 },
    { field: "record_id", headerName: "Example Record ID", width: 170 },
    { field: "raw_value", headerName: "Example Raw Value", width: 150 },
    { field: "issue_description", headerName: "Example Description", flex: 1, minWidth: 260 },
    {
      field: "severity",
      headerName: "Severity",
      width: 110,
      renderCell: (params) => (
        <Chip label={params.value} size="small" color={SEVERITY_COLOR[params.value] || "default"} />
      ),
    },
    {
      field: "manual_review_required",
      headerName: "Needs Review",
      width: 130,
      renderCell: (params) => (params.value ? <Chip label="Yes" size="small" color="warning" /> : "No"),
    },
  ];

  return (
    <Box>
      <PageHeader
        title="Issue Explorer"
        subtitle="Validation rule failures per dataset"
        actions={
          <Select size="small" value={dataset} onChange={(e) => setDataset(e.target.value)}>
            {DATASETS.map((d) => (
              <MenuItem key={d} value={d}>
                {d.replace(/_/g, " ")}
              </MenuItem>
            ))}
          </Select>
        }
      />
      <Box sx={{ height: 600, bgcolor: "#fff", borderRadius: 2 }}>
        <DataGrid rows={rows} columns={columns} pageSizeOptions={[10, 25, 50]} />
      </Box>
    </Box>
  );
}
